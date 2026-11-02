"""
make_agent_data.py - Practice runs of the coding helper, as plain text for the final-phase reading -> data/<version>/agent_traces.jsonl

WHAT THIS FILE DOES
    Runs thousands of tiny coding tasks (agent_tasks.py) through the real harness and keeps the ones whose tests pass.
    Each run is written as readable text (Task / Call / Result lines). prepare_web_data.py reads the file as the
    "agent_traces" source of the final phase, so the model has seen the shape "look, change, test, finish" thousands
    of times before the chat lessons teach the exact tool format. (The chat lessons in agent_lessons.py are built from
    the same runs, with the real tool tokens.)

    Everything is made by our own code from templates; no other AI writes any of it.

Usage:  python coding/make_agent_data.py --version v3.5            (about 40,000 runs; shows its progress; roughly 20-60 minutes, using every core)
        python coding/make_agent_data.py --version v3.5 --n 2000
"""
# This line adds the project's parent folder to Python's search path, then imports emvryx_paths, which makes the other code folders importable.
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import argparse
import json
import os
import random
import time
from multiprocessing import Pool

import agent_tasks as A
from harness import TOOL_CALL, parse_tool_call, ToolError

# The kinds of practice run, each with how often it is picked (the weights add up to 1.0): fixing a bug, a syntax error,
# retrying after a failure, building a project, using git, being refused a bad action, and a file that is too big.
KINDS = [("fix", 0.35), ("syntax", 0.12), ("retry", 0.18), ("project", 0.15), ("git", 0.08), ("denied", 0.04),
         ("too_big", 0.08)]


def render(messages):
    """Plain text for pretraining: "Task: ...", "Call: name {args}", "Result: ..."

    `messages` is the chat of one run: a list of {"role": "user"|"assistant", "content": text}.
    Returns one string with a line per step. The special tool tokens are removed so only readable words remain.
    """
    lines = []
    for i, m in enumerate(messages):
        text = m["content"]
        # The first user message is the task; later user messages are tool results fed back to the model.
        if m["role"] == "user" and i == 0:
            lines.append("Task: " + text)
        elif m["role"] == "user":
            # Drop the marker tokens that wrap a tool result in the chat format.
            lines.append("Result: " + text.replace("<|tool_result|>", "").replace("<|end_tool_result|>", ""))
        else:
            # Assistant message: it may contain a tool call. If it has none, keep the text as it is.
            try:
                name, args = parse_tool_call(text)
            except ToolError:
                lines.append(text)
                continue
            # Any words the assistant wrote around the tool call (TOOL_CALL is the regex that matches the call itself).
            before = TOOL_CALL.sub("", text).strip()
            if before:
                lines.append(before)
            # ensure_ascii=False keeps non-English characters readable instead of \uXXXX escapes.
            lines.append(f"Call: {name} {json.dumps(args, ensure_ascii=False)}")
    return "\n".join(lines)


def one(seed):
    """Make one practice run from a random-number `seed`. Returns {"kind", "text"}, or None if the run failed its tests and is dropped.

    The same seed always gives the same run, so the whole data set can be rebuilt exactly.
    """
    rng = random.Random(seed)
    # Pick a kind of run using the weights in KINDS.
    kind = rng.choices([k for k, _ in KINDS], [w for _, w in KINDS])[0]
    r = A.make_run(kind, rng)
    return None if r is None else {"kind": kind, "text": render(r["messages"])}


def build(n, seed=1337, workers=None, progress=None):
    """The kept runs for seeds seed .. seed+n. `progress(done, kept)` is called every 500 runs."""
    rows = []
    # A Pool is a group of worker processes (one per CPU core by default) that run `one` on many seeds at the same time.
    with Pool(workers) as pool:
        # imap hands out seeds in chunks of 20 and gives results back in order; i counts runs finished, starting at 1.
        for i, r in enumerate(pool.imap(one, range(seed, seed + n), chunksize=20), 1):
            if r:
                rows.append(r)
            # Report progress every 500 runs.
            if progress and i % 500 == 0:
                progress(i, len(rows))
    return rows


def main():
    """Command-line entry: build the runs and write them as one JSON object per line (JSON Lines) into the version's data folder."""
    # Imported here, not at the top, so the file can be imported without loading the config.
    from config import get_version
    # argparse reads the options typed after the file name (--version, --workers, --n).
    p = argparse.ArgumentParser()
    p.add_argument("--version", default="v3.5")
    p.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1),
                   help="parallel processes (default 4: more can overload a Windows PC, since every run starts programs)")
    p.add_argument("--n", type=int, default=40_000, help="runs to try (each takes ~0.3-1 s of one core; Windows is slower)")
    a = p.parse_args()
    V = get_version(a.version)
    out = os.path.join(V.data_dir, "agent_traces.jsonl")
    os.makedirs(V.data_dir, exist_ok=True)
    t0 = time.time()
    # The lambda prints a progress line: elapsed time so far / runs done gives time per run, times runs left = time remaining (shown in minutes).
    rows = build(a.n, workers=a.workers, progress=lambda done, kept: print(
        f"  {done:,}/{a.n:,} runs, {kept:,} kept, ~{(a.n - done) * (time.time() - t0) / done / 60:.0f} min left", flush=True))
    # One JSON object per line.
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows):,} runs -> {out}")


# Run main() only when this file is started directly, not when another file imports it.
if __name__ == "__main__":
    main()
