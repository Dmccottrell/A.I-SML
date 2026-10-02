"""
make_agent_data.py - Practice runs of the coding helper, as plain text for the final-phase reading -> data/<version>/agent_traces.jsonl

WHAT THIS FILE DOES
    Runs thousands of tiny coding tasks (agent_tasks.py) through the real harness and keeps the ones whose tests pass.
    Each run is written as readable text (Task / Call / Result lines). prepare_web_data.py reads the file as the
    "agent_traces" source of the final phase, so the model has seen the shape "look, change, test, finish" thousands
    of times before the chat lessons teach the exact tool format. (The chat lessons in agent_lessons.py are built from
    the same runs, with the real tool tokens.)

    Everything is made by our own code from templates; no other AI writes any of it.

Usage:  python make_agent_data.py --version v3.5            (about 40,000 runs; shows its progress; roughly 20-60 minutes, using every core)
        python make_agent_data.py --version v3.5 --n 2000
"""
import argparse
import json
import os
import random
import time
from multiprocessing import Pool

import agent_tasks as A
from harness import TOOL_CALL, parse_tool_call, ToolError

KINDS = [("fix", 0.35), ("syntax", 0.12), ("retry", 0.18), ("project", 0.15), ("git", 0.08), ("denied", 0.04),
         ("too_big", 0.08)]


def render(messages):
    """Plain text for pretraining: "Task: ...", "Call: name {args}", "Result: ..." """
    lines = []
    for i, m in enumerate(messages):
        text = m["content"]
        if m["role"] == "user" and i == 0:
            lines.append("Task: " + text)
        elif m["role"] == "user":
            lines.append("Result: " + text.replace("<|tool_result|>", "").replace("<|end_tool_result|>", ""))
        else:
            try:
                name, args = parse_tool_call(text)
            except ToolError:
                lines.append(text)
                continue
            before = TOOL_CALL.sub("", text).strip()
            if before:
                lines.append(before)
            lines.append(f"Call: {name} {json.dumps(args, ensure_ascii=False)}")
    return "\n".join(lines)


def one(seed):
    rng = random.Random(seed)
    kind = rng.choices([k for k, _ in KINDS], [w for _, w in KINDS])[0]
    r = A.make_run(kind, rng)
    return None if r is None else {"kind": kind, "text": render(r["messages"])}


def build(n, seed=1337, workers=None, progress=None):
    """The kept runs for seeds seed .. seed+n. `progress(done, kept)` is called every 500 runs."""
    rows = []
    with Pool(workers) as pool:
        for i, r in enumerate(pool.imap(one, range(seed, seed + n), chunksize=20), 1):
            if r:
                rows.append(r)
            if progress and i % 500 == 0:
                progress(i, len(rows))
    return rows


def main():
    from config import get_version
    p = argparse.ArgumentParser()
    p.add_argument("--version", default="v3.5")
    p.add_argument("--n", type=int, default=40_000, help="runs to try (each takes ~0.3-1 s of one core; Windows is slower)")
    a = p.parse_args()
    V = get_version(a.version)
    out = os.path.join(V.data_dir, "agent_traces.jsonl")
    os.makedirs(V.data_dir, exist_ok=True)
    t0 = time.time()
    rows = build(a.n, progress=lambda done, kept: print(
        f"  {done:,}/{a.n:,} runs, {kept:,} kept, ~{(a.n - done) * (time.time() - t0) / done / 60:.0f} min left", flush=True))
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows):,} runs -> {out}")


if __name__ == "__main__":
    main()
