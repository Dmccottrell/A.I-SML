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

Usage:  python coding/collect_runs.py --coder coder-14b --exercises python/exercises/practice --limit 20 --synthetic 40 --out logs/agent_runs.jsonl
        --samples K tries each task K times (more successes per task); --format qwen writes Qwen's own <tool_call> markers instead of ours.
"""
# The next line is a one-line trick: it adds the project's top folder to Python's search path so the sibling code folders can be imported
# (the emvryx_paths import does the rest of that setup). The directive comment after it must stay on the same line.
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
# argparse reads the command-line options (--model, --out ...); hashlib makes fingerprints (hashes) of files; json reads/writes data as text;
# random makes repeatable "random" choices; shutil deletes folders; tempfile makes throwaway folders; Counter is a dict that counts things.
import argparse
import hashlib
import json
import os
import random
import shutil
import sys
import tempfile
from collections import Counter

# Project modules: agent_tasks makes made-up bug-fix tasks; bench_exercises (called X) knows how to read and test Exercism exercises;
# harness is the sandbox and the agent loop; vryxcode (called V) runs one whole VryxCode task.
import agent_tasks
import bench_exercises as X
import harness
import vryxcode as V

# If the model ran a command containing one of these words, we count it as "it ran the tests".
TEST_WORDS = ("unittest", "pytest", "python test", "python3 test")
# Our tool-call markers on the left, and the matching markers Qwen's own chat format uses on the right. to_qwen() swaps left for right,
# so --format qwen writes training text in Qwen's style instead of ours.
QWEN_MARKERS = (("<|tool_call|>", "<tool_call>\n"), ("<|end_tool_call|>", "\n</tool_call>"),
                ("<|tool_result|>", "<tool_response>\n"), ("<|end_tool_result|>", "\n</tool_response>"))


class Task:
    """One practice task: how to make a fresh copy, what to ask, how to check it, and which files the model must not change.

    Fields: id (a name like "exercism:two-fer"), prompt (the text given to the model), prepare() (builds a fresh throwaway copy and returns
    (work folder to delete later, project folder)), check(folder) (runs the tests, returns (passed, output)), protected (test file names it may not edit).
    """

    def __init__(self, task_id, prompt, prepare, check, protected):
        self.id, self.prompt, self.prepare, self.check, self.protected = task_id, prompt, prepare, check, protected


def exercise_tasks(root, limit=None):
    """Yield a Task for each Exercism exercise found in the folder `root` (at most `limit` of them when given)."""
    items = X.find_exercises(root)
    if limit:
        items = items[:limit]
    for path, ex in items:
        # The test file name without ".py" is the module the tests import (e.g. "two_fer_test.py" -> "two_fer_test").
        module = ex["tests"][0][:-3]
        # Fill the shared prompt template with this exercise's file names and instructions.
        prompt = X.PROMPT.format(solution=", ".join(ex["solution"]), tests=", ".join(ex["tests"]), module=module, instructions=ex["instructions"])
        # The lambdas take their values as default arguments (p=path, ...) so each Task keeps ITS OWN exercise, not the last one of the loop.
        yield Task(f"exercism:{ex['slug']}", prompt, (lambda p=path, e=ex: X.stage(p, e)),
                   (lambda folder, m=module: X.run_tests(folder, m)), list(ex["tests"]))


def synthetic_tasks(n, seed=1):
    """Yield `n` made-up bug-fix Tasks. The same `seed` always gives the same tasks, so runs can be repeated."""
    # A Random with a fixed seed makes the same "random" choices every time.
    rng = random.Random(seed)
    for i in range(n):
        t = agent_tasks.make_task(rng)

        # Both helpers below take t as a default argument so they keep this loop round's task, not the final one.
        def prepare(t=t):
            """Make a fresh temp project with the bug planted; returns (work folder to delete later, project folder)."""
            work = tempfile.mkdtemp(prefix="vryxcol_")
            folder = os.path.join(work, "proj")
            os.makedirs(folder)
            with harness.Sandbox(workspace=folder) as sb:
                agent_tasks.setup(sb, t, bug=True)
            return work, folder

        def check(folder, t=t):
            """Run the task's test command in the sandbox; returns (passed, output). "exit code 0" at the start of the output means success."""
            with harness.Sandbox(workspace=folder) as sb:
                out = sb.run(t["command"])
            return out.startswith("exit code 0"), out
        prompt = f"Fix the bug in {t['module']}.py: {t['name']} gives the wrong answer. The tests are in {t['test_file']}."
        task = Task(f"synthetic:{i}:{t['name']}", prompt, prepare, check, [t["test_file"]])
        # Keep the raw task dict on the Task in case other code wants it.
        task.meta = t
        yield task


def file_hashes(folder, names):
    """{file name: SHA-256 fingerprint of its contents, or None if the file does not exist} for each name in `names` inside `folder`.

    Used to prove the model did not change the protected test files: same fingerprint before and after means untouched.
    """
    out = {}
    for n in names:
        p = os.path.join(folder, n)
        out[n] = None
        if os.path.exists(p):
            # "rb" reads raw bytes, so the fingerprint does not depend on text encoding.
            with open(p, "rb") as f:
                out[n] = hashlib.sha256(f.read()).hexdigest()
    return out


def tool_calls(messages):
    """[(name, args)] for every tool call the model wrote, in order."""
    calls = []
    for m in messages:
        # Only the model's own messages ("assistant") can contain tool calls.
        if m["role"] == "assistant":
            try:
                calls.append(harness.parse_tool_call(m["content"]))
            except harness.ToolError:
                # The message had no readable tool call (plain text or broken); keep a placeholder so positions still line up.
                calls.append(("(none)", {}))
    return calls


def judge(task, result, folder, before):
    """None if the run is good, else the reason it is rejected.

    In: the Task, the result dict from V.run_task, the project folder, and `before` (the protected files' fingerprints taken before the run).
    The checks run in order and the first failure wins. We re-run the tests ourselves; the model's own "done" is never trusted.
    """
    # 1. The model must have ended the task on its own (not run out of turns).
    if not result["finished"]:
        return "did not finish"
    # 2. The task's tests must really pass now.
    ok, _ = task.check(folder)
    if not ok:
        return "tests fail"
    # 3. No cheating: the test files must be exactly as they were.
    if file_hashes(folder, task.protected) != before:
        return "edited the test files"
    calls = tool_calls(result["messages"])
    # 4. It must have written or edited at least one file.
    if not any(n in ("write_file", "edit_file") for n, _ in calls):
        return "changed nothing"
    # 5. It must have run a command that looks like running the tests.
    if not any(n == "run" and any(w in str(a.get("command", "")) for w in TEST_WORDS) for n, a in calls):
        return "never ran the tests"
    # 6. Count the tool results that start with "error:"; more than 3 means it flailed.
    errors = sum(1 for m in result["messages"] if m["role"] == "user" and m["content"].startswith("<|tool_result|>error:"))
    if errors > 3:
        return "too many tool errors"
    return None


def to_qwen(messages):
    """Copy of the chat `messages` with our tool-call markers swapped for Qwen's own ones (see QWEN_MARKERS)."""
    out = []
    for m in messages:
        text = m["content"]
        for a, b in QWEN_MARKERS:
            text = text.replace(a, b)
        # {**m, "content": text} = a copy of the message dict with only "content" replaced.
        out.append({**m, "content": text})
    return out


def solution_hash(folder, task):
    """One fingerprint of the model's solution: all .py files except the protected tests, read in a fixed order.

    Two runs that end with the same code give the same hash, which lets collect() skip duplicates.
    """
    parts = []
    # sorted() on both levels makes the order the same every time.
    for root, _, files in sorted(os.walk(folder)):
        for f in sorted(files):
            if f.endswith(".py") and f not in task.protected:
                with open(os.path.join(root, f), "rb") as fh:
                    parts.append(fh.read())
    return hashlib.sha256(b"".join(parts)).hexdigest()


def collect(tasks, generate, label, samples=1, max_turns=12, context_tokens=None, fmt="ours", seen=None, out=print):
    """Run the tasks. Returns (accepted examples, a Counter of how many were tried, accepted and rejected for each reason).

    In: `tasks` (Task objects), `generate` (the function that asks the model for its next message), `label` (the model's name written into each
    example), `samples` (tries per task), `max_turns` and `context_tokens` (limits for one run), `fmt` ("ours" or "qwen"), `seen` (a set of
    (task id, solution hash) already collected, which is added to), `out` (where progress lines go).
    """
    seen = seen if seen is not None else set()
    stats = Counter()
    accepted = []
    for task in tasks:
        # Try each task `samples` times; every try starts from a fresh copy.
        for _ in range(samples):
            work, folder = task.prepare()
            try:
                before = file_hashes(folder, task.protected)
                # Let the model work. make_ask(True) answers "yes" to every permission question (it is a sandbox). out=lambda *_: None silences
                # the run's printing; checks=False skips the agent's own extra checks because judge() does its own.
                result = V.run_task(task.prompt, generate, folder, V.make_ask(True), max_turns, context_tokens, out=lambda *_: None, checks=False)
                reason = judge(task, result, folder, before)
                key = (task.id, solution_hash(folder, task))
            finally:
                # `finally` always runs, even after an error: the throwaway folder is always deleted.
                shutil.rmtree(work, ignore_errors=True)
            stats["tried"] += 1
            # A good run that repeats an earlier solution is dropped too: duplicates add nothing to training.
            if reason is None and key in seen:
                reason = "same solution as an earlier run"
            if reason:
                stats["rejected: " + reason] += 1
                continue
            seen.add(key)
            stats["accepted"] += 1
            # Keep the whole conversation as one training example, with a few labels saying where it came from.
            msgs = result["messages"] if fmt == "ours" else to_qwen(result["messages"])
            accepted.append({"messages": msgs, "kind": "agent_run", "task": task.id, "model": label, "turns": result["turns"], "format": fmt,
                             "solution": key[1]})
        out(f"{task.id}: {stats['accepted']} accepted of {stats['tried']} tries so far")
    return accepted, stats


def main(argv=None):
    """The command-line entry point. Reads the options, collects runs, appends accepted ones to the output file, prints a summary. Returns 0."""
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
    # The gate refuses models that are not allowed to run VryxCode (Emvryx models below Equinox 2); SystemExit(text) quits and prints the text.
    ok, note = V.gate(a.model, a.coder)
    if not ok:
        raise SystemExit(note)
    if not a.exercises and not a.synthetic:
        raise SystemExit("give me tasks: --exercises FOLDER and/or --synthetic N")
    # Build the task list from whichever sources were asked for.
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
    # The label written into every example: the outside coder's name if given, else the Emvryx model's name.
    label = a.coder or a.model
    accepted, stats = collect(tasks, V.LlamaChat(a.llama), label, a.samples, a.max_turns, a.context, a.format, seen=seen)
    # Make the output folder if needed, then append (mode "a") one JSON object per line: this format is called JSONL.
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "a", encoding="utf-8") as f:
        for row in accepted:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(dict(stats), indent=2))
    print(f"{len(accepted)} runs added to {a.out}")
    return 0


# Run main() only when this file is started directly (not when imported by a test); its return value becomes the exit code.
if __name__ == "__main__":
    sys.exit(main())
