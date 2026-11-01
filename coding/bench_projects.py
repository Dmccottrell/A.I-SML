"""
bench_projects.py - The multi-step project test for VryxCode: real little programs built from nothing, scored by hidden tests (docs/VRYXCODE.md).

WHAT THIS FILE DOES
    The exercise test (bench_exercises.py) asks for one function in one file. This asks for whole small projects (a to-do app, a bank ledger,
    a Markdown converter, an inventory API, Snake, an expression calculator, tic-tac-toe with an unbeatable computer ...): 3 to 6 files each, in an
    EMPTY folder, from one request written the way a person would ask. It is how we prove VryxCode 3 is a real jump over version 1.
      * Each project is a folder in coding/projects/: task.json (the request, language, level), hidden/ (the tests) and reference/ (a working
        solution, so we know the tests are fair: `--selftest` proves the reference passes and an empty folder fails).
      * The model never sees the hidden tests. After it finishes (or runs out of steps), the hidden tests are copied into a COPY of what it
        built and run there. A project counts as passed only when every hidden test passes; the share of hidden tests passed is reported too
        (partial credit shows progress before whole projects pass).
      * Two loops can be measured: `--loop plain` (version 1: 12 steps, no checks: comparable with the old numbers) and `--loop build`
        (VryxCode 3: the long-build loop with checkpoints, rollback, a step back when stuck, up to 150 steps, the syntax checks on).
      * JavaScript projects need Node (they are skipped, and say so, when it is not installed).

Usage:  python coding/bench_projects.py --selftest                                       (no model: the tests are fair)
        python coding/bench_projects.py --model solstice-2 --loop plain                  (the version 1 baseline)
        python coding/bench_projects.py --model apogee-2 --loop build --only todo_cli,bank_ledger
        python coding/bench_projects.py --coder qwen3.6-27b --loop build                 (an outside model, e.g. the teacher, as the best case)
    Results: logs/projects-<label>-<loop>.json and .md
"""
# This first line puts the project root on Python's search path so "emvryx_paths" can be imported; that module then
# makes the other code folders importable too. (Directive comment on the line is kept.)
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
# argparse reads command-line options; json reads/saves data files; re is for regular expressions (text patterns);
# shutil copies/deletes folders and finds programs; subprocess runs other programs; tempfile makes scratch folders;
# time measures how long a build took.
import argparse
import json
import re
import shutil
import subprocess
import tempfile
import time

# V is the VryxCode agent that does the building (and holds BUILD_STEPS, the step limit of the long-build loop).
import vryxcode as V

# The folder this file lives in, and the folder that holds one sub-folder per project.
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECTS = os.path.join(HERE, "projects")
# The two ways to run the agent: steps = how many turns it gets, build = use the long-build loop (checkpoints,
# rollback), checks = run the syntax checks after edits.
LOOPS = {"plain": {"steps": 12, "build": False, "checks": False}, "build": {"steps": V.BUILD_STEPS, "build": True, "checks": True}}
# The longest one hidden test file may run before we give up on it (seconds).
TEST_SECONDS = 120


def load_projects(root=PROJECTS, only=None):
    """[project dict] sorted by id: task.json plus "id", "dir", "hidden" (file names) and "reference" (folder or None)."""
    out = []
    for pid in sorted(os.listdir(root)):
        folder = os.path.join(root, pid)
        meta = os.path.join(folder, "task.json")
        # Skip things that are not projects (no task.json) and, if --only was given, projects not named in it.
        if not os.path.isfile(meta) or (only and pid not in only):
            continue
        with open(meta, encoding="utf-8") as f:
            p = json.load(f)
        hidden = os.path.join(folder, "hidden")
        # Add the computed fields to the project's dict. A missing folder gives an empty list / None.
        p.update(id=pid, dir=folder, hidden=sorted(os.listdir(hidden)) if os.path.isdir(hidden) else [],
                 reference=os.path.join(folder, "reference") if os.path.isdir(os.path.join(folder, "reference")) else None)
        # "needs" lists programs the project requires (e.g. node); default to none.
        p.setdefault("needs", [])
        out.append(p)
    return out


def missing_tools(project):
    """The programs the project needs that are not installed here (empty list = fine to run)."""
    return [t for t in project.get("needs", []) if not shutil.which(t)]


def count_python(output):
    """(passed, total) from unittest's output."""
    # unittest prints a line like "Ran 7 tests in 0.01s". The regex means: the word Ran, digits, then "test" or "tests".
    m = re.search(r"Ran (\d+) tests?", output)
    total = int(m.group(1)) if m else 0
    # On failure it prints e.g. "FAILED (failures=2, errors=1)": add up every such number. max(0, ..) guards against below zero.
    bad = sum(int(x) for x in re.findall(r"(?:failures|errors)=(\d+)", output))
    return max(0, total - bad), total


def count_js(output):
    """(passed, total) from a JavaScript test file's output, which must print a line like "passed 3 of 4"."""
    m = re.search(r"passed (\d+) of (\d+)", output)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def hidden_check(project, built):
    """Run the hidden tests against a COPY of what was built. {"passed": bool, "tests_passed", "tests_total", "output"}."""
    work = tempfile.mkdtemp(prefix="vryxproj_check_")
    copy = os.path.join(work, "p")
    try:
        # Work on a copy so the tests (and the files they create) never touch what the model built.
        shutil.copytree(built, copy, ignore=shutil.ignore_patterns("__pycache__", ".git", "node_modules"))
        # Drop the hidden test files into the copy, now that the model has finished and cannot read them.
        for name in project["hidden"]:
            shutil.copy(os.path.join(project["dir"], "hidden", name), os.path.join(copy, name))
        # Running totals of tests passed and tests found, and the output text from every test file.
        got = total = 0
        outputs = []
        for name in project["hidden"]:
            # Pick the command and the output-counting function by file type; other files are not tests.
            if name.endswith(".py"):
                cmd, counter = [sys.executable, "-B", "-m", "unittest", name[:-3]], count_python
            elif name.endswith(".js"):
                cmd, counter = ["node", name], count_js
            else:
                continue
            # Run the test file inside the copy. PYTHONPATH makes the built code importable; the timeout stops endless loops.
            try:
                r = subprocess.run(cmd, cwd=copy, capture_output=True, text=True, timeout=TEST_SECONDS,
                                   env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": copy})
                text = r.stdout + r.stderr
            except subprocess.TimeoutExpired:
                text = "the hidden tests ran too long (an endless loop?)"
            except OSError as e:
                text = f"could not run the hidden tests: {e}"
            # Count passed and total tests from the printed output.
            p, t = counter(text)
            t = max(t, _declared_tests(os.path.join(project["dir"], "hidden", name)), 1)   # a file that did not even load counts every test in it as failed
            got, total = got + p, total + t
            outputs.append(text[-1200:])
        # A project passes only if at least one test exists and every test passed. Keep the end of each output (the errors).
        return {"passed": total > 0 and got == total, "tests_passed": got, "tests_total": total, "output": "\n".join(outputs)}
    finally:
        # Always delete the temp copy.
        shutil.rmtree(work, ignore_errors=True)


def _declared_tests(path):
    """How many tests a hidden test file declares, found by reading its text: Python "def test_..." methods plus JS
    lines starting "test(". Used when the file crashed before printing a count, so those tests count as failed."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # re.M makes ^ match at the start of every line, not just the start of the text.
    return len(re.findall(r"^\s+def test_", text, re.M)) + len(re.findall(r"^test\(", text, re.M))


def run_project(project, generate, loop="build", context_tokens=None, max_turns=None):
    """Build one project from an empty folder and score it. Returns the result row."""
    cfg = LOOPS[loop]
    work = tempfile.mkdtemp(prefix="vryxproj_")
    # The model starts in a brand-new EMPTY folder named after the project.
    folder = os.path.join(work, project["id"])
    os.makedirs(folder)
    t0 = time.time()
    try:
        # Let the agent build the project from the request text. Questions are auto-approved, printing is dropped.
        result = V.run_task(project["prompt"], generate, folder, V.make_ask(True), max_turns or cfg["steps"], context_tokens, out=lambda *_: None,
                            checks=cfg["checks"], build=cfg["build"])
        # Score it with the hidden tests, then list the files it made (as paths with / even on Windows, skipping caches).
        score = hidden_check(project, folder)
        files = sorted(os.path.relpath(os.path.join(r, f), folder).replace("\\", "/") for r, _, fs in os.walk(folder) for f in fs
                       if "__pycache__" not in r)
    finally:
        # Always delete the scratch folder.
        shutil.rmtree(work, ignore_errors=True)
    # One result row. Only the first 40 file names and the last 600 characters of test output (if it failed) are kept.
    return {"id": project["id"], "lang": project.get("lang"), "level": project.get("level"), "passed": score["passed"],
            "tests_passed": score["tests_passed"], "tests_total": score["tests_total"], "finished": bool(result.get("finished")),
            "stopped": result.get("stopped", ""), "steps": result.get("turns", 0), "seconds": round(time.time() - t0, 1), "files": files[:40],
            "hidden_output": score["output"][-600:] if not score["passed"] else ""}


def summarize(rows):
    """Totals over all result rows: projects passed, share of hidden tests passed, average steps, minutes, by level."""
    n = len(rows)
    if not n:
        return {"projects": 0}
    passed = sum(r["passed"] for r in rows)
    tp, tt = sum(r["tests_passed"] for r in rows), sum(r["tests_total"] for r in rows)
    # by_level maps a level name to [projects passed, projects tried].
    by_level = {}
    for r in rows:
        lv = by_level.setdefault(r.get("level") or "?", [0, 0])
        lv[0] += r["passed"]
        lv[1] += 1
    return {"projects": n, "passed": passed, "pct_passed": round(100 * passed / n, 1), "hidden_tests_pct": round(100 * tp / tt, 1) if tt else 0.0,
            "finished": sum(r["finished"] for r in rows), "avg_steps": round(sum(r["steps"] for r in rows) / n, 1),
            "minutes": round(sum(r["seconds"] for r in rows) / 60, 1), "by_level": by_level}


def report_md(label, loop, s, rows):
    """The same results as a Markdown text report: a headline plus a table with one row per project."""
    lines = [f"# VryxCode project test: {label} ({loop} loop)", "",
             f"**{s['passed']} of {s['projects']} projects passed** ({s['pct_passed']}%), hidden tests passed: {s['hidden_tests_pct']}%, "
             f"finished on its own: {s['finished']}, average steps: {s['avg_steps']}, time: {s['minutes']} min.", "",
             "| Project | Level | Result | Hidden tests | Steps | Stopped |", "|---|---|---|---|---|---|"]
    # The "|" characters make a Markdown table; "-" is shown when the run did not stop early.
    for r in rows:
        lines.append(f"| {r['id']} | {r.get('level')} | {'PASS' if r['passed'] else 'fail'} | {r['tests_passed']}/{r['tests_total']} | {r['steps']} | {r['stopped'] or '-'} |")
    return "\n".join(lines) + "\n"


def selftest(projects, out=print):
    """The tests are fair: every reference solution passes all of its hidden tests, and an empty folder passes none."""
    ok = True
    for p in projects:
        # A project needing a program we do not have (e.g. Node) cannot be checked here.
        if missing_tools(p):
            out(f"{p['id']:20s} skipped (needs {', '.join(missing_tools(p))})")
            continue
        # Check 1: the reference solution must pass all hidden tests (otherwise the tests are unfair).
        ref = hidden_check(p, p["reference"]) if p["reference"] else {"passed": False, "tests_passed": 0, "tests_total": 0, "output": "no reference"}
        # Check 2: an empty folder must pass NO tests (otherwise the tests prove nothing).
        empty = tempfile.mkdtemp(prefix="vryxproj_empty_")
        try:
            blank = hidden_check(p, empty)
        finally:
            shutil.rmtree(empty, ignore_errors=True)
        # Show the outcome; "ok" only when both checks held. ok keeps its False once any project has a problem.
        good = ref["passed"] and blank["tests_passed"] == 0
        ok = ok and good
        out(f"{p['id']:20s} reference {ref['tests_passed']}/{ref['tests_total']}  empty {blank['tests_passed']}/{blank['tests_total']}  {'ok' if good else 'PROBLEM'}")
        # On a problem, show the end of the reference's output to help find why.
        if not good:
            out(ref["output"][-1500:])
    return ok


def main(argv=None):
    """Command-line entry point: self-test, or run the benchmark and save .json and .md reports. Returns the exit code."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default="solstice-2")
    p.add_argument("--coder", default=None, metavar="LABEL", help="score an outside model that llama-server is running, under this label")
    p.add_argument("--llama", default="http://127.0.0.1:8080")
    p.add_argument("--loop", choices=sorted(LOOPS), default="build")
    p.add_argument("--only", default="", help="project ids, comma separated")
    p.add_argument("--max-turns", type=int, default=None)
    p.add_argument("--context", type=int, default=32768)
    p.add_argument("--think", action="store_true", help="let the model think before each step (slower; Qwen3 models)")
    p.add_argument("--selftest", action="store_true", help="check the hidden tests against the reference solutions (no model)")
    a = p.parse_args(argv)
    # --only "a, b" becomes the set {"a", "b"}; an empty set becomes None (meaning "all projects").
    only = {x.strip() for x in a.only.split(",") if x.strip()} or None
    projects = load_projects(only=only)
    if not projects:
        raise SystemExit("no projects found" + (f" matching {a.only}" if only else ""))
    # Self-test needs no model: exit code 0 if all fair, 1 otherwise.
    if a.selftest:
        return 0 if selftest(projects) else 1
    # gate() refuses to score a model that is not allowed or not ready; SystemExit stops the program with the note.
    ok, note = V.gate(a.model, a.coder)
    if not ok:
        raise SystemExit(note)
    # generate(messages) asks the llama-server (the program that runs the model) for the next reply.
    generate = V.LlamaChat(a.llama, thinking=a.think) if a.think else V.LlamaChat(a.llama)
    label = a.coder or a.model
    rows = []
    for proj in projects:
        # Report and skip projects whose tools are missing.
        if missing_tools(proj):
            print(f"{proj['id']:20s} skipped (needs {', '.join(missing_tools(proj))})", flush=True)
            continue
        r = run_project(proj, generate, a.loop, a.context, a.max_turns)
        rows.append(r)
        # :20s pads the id so the columns line up; :.0f shows the seconds as a whole number.
        print(f"{proj['id']:20s} {'PASS' if r['passed'] else 'fail'}  hidden {r['tests_passed']}/{r['tests_total']}  {r['steps']} steps  {r['seconds']:.0f}s", flush=True)
    s = summarize(rows)
    print(json.dumps(s, indent=2))
    os.makedirs("logs", exist_ok=True)
    # File name made safe: the regex replaces anything that is not a letter, digit, _ . or - with an underscore.
    base = os.path.join("logs", f"projects-{re.sub(r'[^A-Za-z0-9_.-]', '_', label)}-{a.loop}")
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump({"model": label, "outside_model": bool(a.coder), "loop": a.loop, "summary": s, "results": rows}, f, indent=2)
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(report_md(label, a.loop, s, rows))
    print(f"saved {base}.json and .md")
    return 0


# Only run main() when the file is started directly, not when another file imports it.
if __name__ == "__main__":
    sys.exit(main())
