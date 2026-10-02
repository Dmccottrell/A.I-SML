"""
stretch_ladder.py - Stretch v3's memory step by step and stop at the first step that doesn't hold up.

WHAT THIS FILE DOES
    Runs the long-context ladder (docs/LONG_CONTEXT.md) hands-off:

        v3-long-8k -> 16k -> 32k -> 64k -> 128k -> 256k

    For each step: train it (run_training.py, which restarts after a crash), then run the gate (eval_long.py: needle,
    multi-fact, code and loss-by-position tests; it exits with an error when a test fails). A step that passes becomes
    the new starting point. The ladder STOPS at the first step that fails its tests or can't run (for example it runs
    out of GPU memory), and tells you the last length that passed: that is how far v3 can go. Nothing after the failed step
    is trained, so nothing is wasted. Progress is saved in data/v3-long/ladder.json, so run it again to carry on.

    "Nothing got worse" (HellaSwag, the chat sheet) is a separate check: after each passing step it prints the
    command (python exam.py --version <step>); compare it with v3's baseline yourself.

Usage:  python stretch_ladder.py --dry_run                  (shows the plan and the commands)
        python stretch_ladder.py                            (runs the whole ladder, from the next unfinished step)
        python stretch_ladder.py --stop_after v3-long-64k   (don't go past 64K)
        python stretch_ladder.py --from_step v3-long-32k    (start at a later step)
"""
import argparse
import json
import os
import subprocess
import sys

LADDER = ["v3-long-8k", "v3-long-16k", "v3-long-32k", "v3-long-64k", "v3-long-128k", "v3-long-256k"]
STATE_PATH = os.path.join("data", "v3-long", "ladder.json")


def load_state(path=STATE_PATH):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"passed": [], "failed": None}


def save_state(state, path=STATE_PATH):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    os.replace(path + ".tmp", path)


def commands(step):
    py = sys.executable
    return {"train": [py, "run_training.py", "--version", step],
            "gate": [py, "eval_long.py", "--version", step, "--out", os.path.join("data", "v3-long", f"eval_{step}.json")]}


def run(cmd):
    return subprocess.call(cmd)


def run_ladder(steps=LADDER, runner=run, state_path=STATE_PATH, stop_after=None, from_step=None,
               say=print, final_exists=None):
    """Go up the ladder. Returns the state dict ({"passed": [...], "failed": None or {"step", "why"}}).

    runner(cmd) -> exit code (0 = fine). final_exists(step) -> True if that step already has its final.pt (training is skipped).
    """
    state = load_state(state_path)
    if from_step:
        steps = steps[steps.index(from_step):]
    for step in steps:
        if step in state["passed"]:
            say(f"{step}: already passed, skipping")
            continue
        state["failed"] = None
        cmds = commands(step)
        if final_exists is None or not final_exists(step):
            say(f"\n=== training {step} ===")
            if runner(cmds["train"]) != 0:
                state["failed"] = {"step": step, "why": "training stopped with an error (out of GPU memory? see its output)"}
                save_state(state, state_path)
                break
        say(f"\n=== gate for {step} (needle, multi-fact, code, loss by position) ===")
        code = runner(cmds["gate"])
        if code != 0:
            why = "failed its long-context tests" if code == 1 else f"the test run crashed (exit code {code})"
            state["failed"] = {"step": step, "why": why}
            save_state(state, state_path)
            break
        state["passed"].append(step)
        save_state(state, state_path)
        say(f"{step}: PASSED. Check nothing got worse:  python exam.py --version {step}")
        if stop_after == step:
            break
    return state


def summary(state, steps=LADDER):
    lengths = {s: int(s.split("-")[-1][:-1]) * 1024 for s in steps}
    last = state["passed"][-1] if state["passed"] else None
    lines = []
    if last:
        lines.append(f"Last step that passed: {last} ({lengths[last]:,} tokens). That is how far v3 can go so far.")
    else:
        lines.append("No step has passed yet (v3 stays a 2,048-token model).")
    if state["failed"]:
        f = state["failed"]
        lines.append(f"Stopped at {f['step']} ({lengths[f['step']]:,} tokens): {f['why']}.")
        lines.append(f"Keep {last or 'v3'} as the long-memory model; nothing past {f['step']} was trained.")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="Stretch v3's memory up the ladder and stop at the first failure")
    p.add_argument("--dry_run", action="store_true")
    p.add_argument("--stop_after", default=None, choices=LADDER)
    p.add_argument("--from_step", default=None, choices=LADDER)
    a = p.parse_args()
    if a.dry_run:
        for step in LADDER:
            c = commands(step)
            print(f"{step}\n  train: {' '.join(c['train'])}\n  gate:  {' '.join(c['gate'])}")
        return
    from config import get_version
    from exam import final_weights            # where a finished step's weights are

    def finished(step):
        try:
            return os.path.exists(final_weights(get_version(step)))
        except Exception:
            return False
    state = run_ladder(stop_after=a.stop_after, from_step=a.from_step, final_exists=finished)
    print("\n" + summary(state))
    raise SystemExit(1 if state["failed"] else 0)


if __name__ == "__main__":
    main()
