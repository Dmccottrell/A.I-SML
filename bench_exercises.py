"""
bench_exercises.py - An Aider-style coding exercise benchmark for VryxCode: small Exercism exercises, two tries each, no Docker.

WHAT THIS FILE DOES
    For every exercise folder (Exercism layout: `.docs/instructions.md`, a stub file, a `*_test.py`, and `.meta/config.json` naming the files):
      attempt 1: VryxCode gets the instructions and the stub and edits the solution file; we run the tests ourselves.
      attempt 2: if they fail, it gets the failing test output and tries again on the same files.
    The report gives: passed on the first try, passed after the second try, and how many attempts made no change at all (a sign the model could not use the tools).
    This follows the idea of the Aider benchmark (133 Exercism Python exercises, a second try after the failing output). It is NOT the official Aider benchmark, which asks
    for edits in a diff format and runs in Docker, so numbers are not comparable with its published ones. Use it to track our own models over time.

Get exercises:  git clone https://github.com/exercism/python   then   --exercises python/exercises/practice
Usage:  python bench_exercises.py --exercises python/exercises/practice --model solstice-2 --llama http://127.0.0.1:8080 --limit 20 --out logs/exercises.json
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

import vryxcode as V

PROMPT = ("Implement the exercise in {solution}. Read the instructions below and the existing file, then edit {solution} (only that file) so the tests in {tests} pass. "
          "Run the tests with: python -m unittest {module}. When they pass, call finish.\n\nInstructions:\n{instructions}")
RETRY = ("The tests still fail. Here is the output of `python -m unittest {module}`:\n{output}\n\nFix {solution} so they pass (do not edit the tests), run them again, then call finish.")


def load_exercise(path):
    """{"slug", "solution": [files], "tests": [files], "instructions"} for an Exercism practice exercise folder, or None if it is not one."""
    slug = os.path.basename(path.rstrip("/\\"))
    cfg_path = os.path.join(path, ".meta", "config.json")
    solution, tests = [f"{slug.replace('-', '_')}.py"], [f"{slug.replace('-', '_')}_test.py"]
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            files = json.load(f).get("files", {})
        solution, tests = files.get("solution", solution), files.get("test", tests)
    if not all(os.path.exists(os.path.join(path, t)) for t in tests):
        return None
    text = ""
    for name in ("instructions.md", "instructions.append.md"):
        p = os.path.join(path, ".docs", name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                text += f.read().strip() + "\n\n"
    return {"slug": slug, "solution": solution, "tests": tests, "instructions": text.strip() or "(no instructions file)"}


def find_exercises(root):
    out = []
    for name in sorted(os.listdir(root)):
        ex = load_exercise(os.path.join(root, name))
        if ex:
            out.append((os.path.join(root, name), ex))
    return out


def stage(path, ex):
    """A temp copy with only what the model should see: the instructions, the stub and the tests (not .meta, which holds the example solution)."""
    work = tempfile.mkdtemp(prefix="vryxex_")
    dest = os.path.join(work, ex["slug"])
    shutil.copytree(path, dest, ignore=shutil.ignore_patterns(".meta", "__pycache__"))
    return work, dest


def run_tests(folder, module, timeout=60):
    """(passed, output) from running the exercise's tests with python's unittest.

    Cached bytecode is removed first and not written: an edit made in the same second with the same file size would otherwise leave Python running the OLD code."""
    for root, dirs, _ in os.walk(folder):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                dirs.remove(d)
    try:
        r = subprocess.run([sys.executable, "-B", "-m", "unittest", module], cwd=folder, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    except subprocess.TimeoutExpired:
        return False, "the tests ran too long (an endless loop?)"
    return r.returncode == 0, (r.stdout + r.stderr)[-1500:]


def read_files(folder, names):
    out = {}
    for n in names:
        p = os.path.join(folder, n)
        out[n] = open(p, encoding="utf-8").read() if os.path.exists(p) else None
    return out


def run_exercise(path, ex, generate, max_turns=12, context_tokens=None, tries=2):
    """Result for one exercise: {"slug", "passed_first", "passed", "attempts", "unchanged": [bool per attempt]}."""
    work, folder = stage(path, ex)
    module = ex["tests"][0][:-3]
    solution = ", ".join(ex["solution"])
    attempts, unchanged, passed, output = 0, [], False, ""
    try:
        for attempt in range(tries):
            before = read_files(folder, ex["solution"])
            task = (PROMPT.format(solution=solution, tests=", ".join(ex["tests"]), module=module, instructions=ex["instructions"]) if attempt == 0
                    else RETRY.format(module=module, output=output, solution=solution))
            V.run_task(task, generate, folder, V.make_ask(True), max_turns, context_tokens, out=lambda *_: None)
            attempts += 1
            unchanged.append(read_files(folder, ex["solution"]) == before)
            passed, output = run_tests(folder, module)
            if passed:
                break
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"slug": ex["slug"], "passed_first": passed and attempts == 1, "passed": passed, "attempts": attempts, "unchanged": unchanged}


def summarize(results):
    n = len(results)
    if not n:
        return {"exercises": 0}
    first = sum(r["passed_first"] for r in results)
    total = sum(r["passed"] for r in results)
    nochange = sum(1 for r in results for u in r["unchanged"] if u)
    attempts = sum(r["attempts"] for r in results)
    return {"exercises": n, "passed_first_try": first, "passed_after_second_try": total, "pct_first": round(100 * first / n, 1),
            "pct_after_second": round(100 * total / n, 1), "attempts_with_no_change": nochange, "attempts": attempts}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--exercises", required=True, help="a folder of Exercism practice exercises (python/exercises/practice)")
    p.add_argument("--model", default="solstice-2", help="equinox-2, solstice-2 or apogee-2")
    p.add_argument("--llama", default="http://127.0.0.1:8080")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--max-turns", type=int, default=12)
    p.add_argument("--context", type=int, default=32768)
    p.add_argument("--out", default="logs/exercises.json")
    a = p.parse_args(argv)
    ok, note = V.check_model(a.model)
    if not ok:
        raise SystemExit(note)
    items = find_exercises(a.exercises)
    if a.limit:
        items = items[:a.limit]
    if not items:
        raise SystemExit(f"no exercises found in {a.exercises} (each needs a *_test.py and .meta/config.json)")
    generate = V.LlamaChat(a.llama)
    results = []
    for path, ex in items:
        r = run_exercise(path, ex, generate, a.max_turns, a.context)
        results.append(r)
        print(f"{ex['slug']:28s} {'PASS (1st try)' if r['passed_first'] else 'PASS (2nd try)' if r['passed'] else 'fail'}", flush=True)
    s = summarize(results)
    print(json.dumps(s, indent=2))
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"model": a.model, "summary": s, "results": results}, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
