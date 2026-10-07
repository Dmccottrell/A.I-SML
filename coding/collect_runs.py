"""
collect_runs.py - Collect training runs for VryxCode: let a model work on practice tasks, keep only the runs that really succeeded.

WHAT THIS FILE DOES
    A coding agent is trained mostly on its own checked successes. This tool runs a model (an Emvryx model from Equinox 2 up, or an outside coding model with --coder) through
    VryxCode on practice tasks, then keeps a run only if ALL of these are true (we run the tests ourselves; we never trust the model's "done"):
      * it finished and the task's tests pass,
      * it did not touch the test files (no cheating),
      * it changed a file and actually ran the tests before finishing,
      * it did not fall into a spiral of tool errors.
    Rejected runs are counted by reason, never saved. Accepted runs are written as chat examples (JSONL, {"messages": [...]}) that finetune_open.py can train on.
    Tasks: Exercism exercises (--exercises, the same folder bench_exercises.py uses) and fresh made-up bug-fix tasks (--synthetic N, from agent_tasks.py).
    Training on the output: python training/finetune_open.py --model solstice-2 --patch --data logs/agent_runs.jsonl   (a short extra pass on top of the saved adapter).
    Only open-model output is used (policy: never ChatGPT, Claude or Gemini output), and the output keeps the label of the model that wrote it.

Usage:  python coding/collect_runs.py --coder qwen2.5-coder-14b --exercises python/exercises/practice --limit 20 --synthetic 40 --out logs/agent_runs.jsonl
        --samples K tries each task K times (more successes per task); --format qwen writes Qwen's own <tool_call> markers instead of ours.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import argparse
import hashlib
import json
import os
import random
import shutil
import sys
import tempfile
from collections import Counter

import agent_tasks
import bench_exercises as X
import harness
import vryxcode as V

TEST_WORDS = ("unittest", "pytest", "python test", "python3 test")
QWEN_MARKERS = (("<|tool_call|>", "<tool_call>\n"), ("<|end_tool_call|>", "\n</tool_call>"),
                ("<|tool_result|>", "<tool_response>\n"), ("<|end_tool_result|>", "\n</tool_response>"))


class Task:
    """One practice task: how to make a fresh copy, what to ask, how to check it, and which files the model must not change."""

    def __init__(self, task_id, prompt, prepare, check, protected):
        self.id, self.prompt, self.prepare, self.check, self.protected = task_id, prompt, prepare, check, protected


def exercise_tasks(root, limit=None):
    items = X.find_exercises(root)
    if limit:
        items = items[:limit]
    for path, ex in items:
        module = ex["tests"][0][:-3]
        prompt = X.PROMPT.format(solution=", ".join(ex["solution"]), tests=", ".join(ex["tests"]), module=module, instructions=ex["instructions"])
        yield Task(f"exercism:{ex['slug']}", prompt, (lambda p=path, e=ex: X.stage(p, e)),
                   (lambda folder, m=module: X.run_tests(folder, m)), list(ex["tests"]))


def synthetic_tasks(n, seed=1):
    rng = random.Random(seed)
    for i in range(n):
        t = agent_tasks.make_task(rng)

        def prepare(t=t):
            work = tempfile.mkdtemp(prefix="vryxcol_")
            folder = os.path.join(work, "proj")
            os.makedirs(folder)
            with harness.Sandbox(workspace=folder) as sb:
                agent_tasks.setup(sb, t, bug=True)
            return work, folder

        def check(folder, t=t):
            with harness.Sandbox(workspace=folder) as sb:
                out = sb.run(t["command"])
            return out.startswith("exit code 0"), out
        prompt = f"Fix the bug in {t['module']}.py: {t['name']} gives the wrong answer. The tests are in {t['test_file']}."
        task = Task(f"synthetic:{i}:{t['name']}", prompt, prepare, check, [t["test_file"]])
        task.meta = t
        yield task


def file_hashes(folder, names):
    out = {}
    for n in names:
        p = os.path.join(folder, n)
        out[n] = None
        if os.path.exists(p):
            with open(p, "rb") as f:
                out[n] = hashlib.sha256(f.read()).hexdigest()
    return out


def tool_calls(messages):
    """[(name, args)] for every tool call the model wrote, in order."""
    calls = []
    for m in messages:
        if m["role"] == "assistant":
            try:
                calls.append(harness.parse_tool_call(m["content"]))
            except harness.ToolError:
                calls.append(("(none)", {}))
    return calls


def judge(task, result, folder, before):
    """None if the run is good, else the reason it is rejected."""
    if not result["finished"]:
        return "did not finish"
    ok, _ = task.check(folder)
    if not ok:
        return "tests fail"
    if file_hashes(folder, task.protected) != before:
        return "edited the test files"
    calls = tool_calls(result["messages"])
    if not any(n in ("write_file", "edit_file") for n, _ in calls):
        return "changed nothing"
    if not any(n == "run" and any(w in str(a.get("command", "")) for w in TEST_WORDS) for n, a in calls):
        return "never ran the tests"
    errors = sum(1 for m in result["messages"] if m["role"] == "user" and m["content"].startswith("<|tool_result|>error:"))
    if errors > 3:
        return "too many tool errors"
    return None


def to_qwen(messages):
    out = []
    for m in messages:
        text = m["content"]
        for a, b in QWEN_MARKERS:
            text = text.replace(a, b)
        out.append({**m, "content": text})
    return out


def solution_hash(folder, task):
    parts = []
    for root, _, files in sorted(os.walk(folder)):
        for f in sorted(files):
            if f.endswith(".py") and f not in task.protected:
                with open(os.path.join(root, f), "rb") as fh:
                    parts.append(fh.read())
    return hashlib.sha256(b"".join(parts)).hexdigest()


def collect(tasks, generate, label, samples=1, max_turns=12, context_tokens=None, fmt="ours", seen=None, out=print):
    """Run the tasks. Returns (accepted examples, a Counter of how many were tried, accepted and rejected for each reason)."""
    seen = seen if seen is not None else set()
    stats = Counter()
    accepted = []
    for task in tasks:
        for _ in range(samples):
            work, folder = task.prepare()
            try:
                before = file_hashes(folder, task.protected)
                result = V.run_task(task.prompt, generate, folder, V.make_ask(True), max_turns, context_tokens, out=lambda *_: None, checks=False)
                reason = judge(task, result, folder, before)
                key = (task.id, solution_hash(folder, task))
            finally:
                shutil.rmtree(work, ignore_errors=True)
            stats["tried"] += 1
            if reason is None and key in seen:
                reason = "same solution as an earlier run"
            if reason:
                stats["rejected: " + reason] += 1
                continue
            seen.add(key)
            stats["accepted"] += 1
            msgs = result["messages"] if fmt == "ours" else to_qwen(result["messages"])
            accepted.append({"messages": msgs, "kind": "agent_run", "task": task.id, "model": label, "turns": result["turns"], "format": fmt,
                             "solution": key[1]})
        out(f"{task.id}: {stats['accepted']} accepted of {stats['tried']} tries so far")
    return accepted, stats


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default="solstice-2", help="equinox-2, solstice-2 or apogee-2")
    p.add_argument("--coder", default=None, metavar="LABEL", help="use an outside coding model that llama-server is running, under this label")
    p.add_argument("--llama", default="http://127.0.0.1:8080")
    p.add_argument("--exercises", default=None, help="a folder of Exercism practice exercises")
    p.add_argument("--synthetic", type=int, default=0, help="how many made-up bug-fix tasks")
    p.add_argument("--limit", type=int, default=None, help="at most this many exercises")
    p.add_argument("--samples", type=int, default=1, help="tries per task")
    p.add_argument("--max-turns", type=int, default=12)
    p.add_argument("--context", type=int, default=16384)
    p.add_argument("--format", choices=("ours", "qwen"), default="ours")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", default="logs/agent_runs.jsonl")
    a = p.parse_args(argv)
    ok, note = V.gate(a.model, a.coder)
    if not ok:
        raise SystemExit(note)
    if not a.exercises and not a.synthetic:
        raise SystemExit("give me tasks: --exercises FOLDER and/or --synthetic N")
    tasks = []
    if a.exercises:
        tasks += list(exercise_tasks(a.exercises, a.limit))
    if a.synthetic:
        tasks += list(synthetic_tasks(a.synthetic, a.seed))
    seen = set()
    if os.path.exists(a.out):                                    # keep what is already collected: add to it, skip what we have
        with open(a.out, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                seen.add((row["task"], row.get("solution", "")))
    label = a.coder or a.model
    accepted, stats = collect(tasks, V.LlamaChat(a.llama), label, a.samples, a.max_turns, a.context, a.format, seen=seen)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "a", encoding="utf-8") as f:
        for row in accepted:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(dict(stats), indent=2))
    print(f"{len(accepted)} runs added to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
