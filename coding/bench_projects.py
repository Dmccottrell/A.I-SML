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
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import argparse
import json
import re
import shutil
import subprocess
import tempfile
import time

import vryxcode as V

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECTS = os.path.join(HERE, "projects")
LOOPS = {"plain": {"steps": 12, "build": False, "checks": False}, "build": {"steps": V.BUILD_STEPS, "build": True, "checks": True}}
TEST_SECONDS = 120


def load_projects(root=PROJECTS, only=None):
    """[project dict] sorted by id: task.json plus "id", "dir", "hidden" (file names) and "reference" (folder or None)."""
    out = []
    for pid in sorted(os.listdir(root)):
        folder = os.path.join(root, pid)
        meta = os.path.join(folder, "task.json")
        if not os.path.isfile(meta) or (only and pid not in only):
            continue
        with open(meta, encoding="utf-8") as f:
            p = json.load(f)
        hidden = os.path.join(folder, "hidden")
        p.update(id=pid, dir=folder, hidden=sorted(os.listdir(hidden)) if os.path.isdir(hidden) else [],
                 reference=os.path.join(folder, "reference") if os.path.isdir(os.path.join(folder, "reference")) else None)
        p.setdefault("needs", [])
        out.append(p)
    return out


def missing_tools(project):
    return [t for t in project.get("needs", []) if not shutil.which(t)]


def count_python(output):
    """(passed, total) from unittest's output."""
    m = re.search(r"Ran (\d+) tests?", output)
    total = int(m.group(1)) if m else 0
    bad = sum(int(x) for x in re.findall(r"(?:failures|errors)=(\d+)", output))
    return max(0, total - bad), total


def count_js(output):
    m = re.search(r"passed (\d+) of (\d+)", output)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def hidden_check(project, built):
    """Run the hidden tests against a COPY of what was built. {"passed": bool, "tests_passed", "tests_total", "output"}."""
    work = tempfile.mkdtemp(prefix="vryxproj_check_")
    copy = os.path.join(work, "p")
    try:
        shutil.copytree(built, copy, ignore=shutil.ignore_patterns("__pycache__", ".git", "node_modules"))
        for name in project["hidden"]:
            shutil.copy(os.path.join(project["dir"], "hidden", name), os.path.join(copy, name))
        got = total = 0
        outputs = []
        for name in project["hidden"]:
            if name.endswith(".py"):
                cmd, counter = [sys.executable, "-B", "-m", "unittest", name[:-3]], count_python
            elif name.endswith(".js"):
                cmd, counter = ["node", name], count_js
            else:
                continue
            try:
                r = subprocess.run(cmd, cwd=copy, capture_output=True, text=True, timeout=TEST_SECONDS,
                                   env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": copy})
                text = r.stdout + r.stderr
            except subprocess.TimeoutExpired:
                text = "the hidden tests ran too long (an endless loop?)"
            except OSError as e:
                text = f"could not run the hidden tests: {e}"
            p, t = counter(text)
            t = max(t, _declared_tests(os.path.join(project["dir"], "hidden", name)), 1)   # a file that did not even load counts every test in it as failed
            got, total = got + p, total + t
            outputs.append(text[-1200:])
        return {"passed": total > 0 and got == total, "tests_passed": got, "tests_total": total, "output": "\n".join(outputs)}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _declared_tests(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return len(re.findall(r"^\s+def test_", text, re.M)) + len(re.findall(r"^test\(", text, re.M))


def run_project(project, generate, loop="build", context_tokens=None, max_turns=None):
    """Build one project from an empty folder and score it. Returns the result row."""
    cfg = LOOPS[loop]
    work = tempfile.mkdtemp(prefix="vryxproj_")
    folder = os.path.join(work, project["id"])
    os.makedirs(folder)
    t0 = time.time()
    try:
        result = V.run_task(project["prompt"], generate, folder, V.make_ask(True), max_turns or cfg["steps"], context_tokens, out=lambda *_: None,
                            checks=cfg["checks"], build=cfg["build"])
        score = hidden_check(project, folder)
        files = sorted(os.path.relpath(os.path.join(r, f), folder).replace("\\", "/") for r, _, fs in os.walk(folder) for f in fs
                       if "__pycache__" not in r)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"id": project["id"], "lang": project.get("lang"), "level": project.get("level"), "passed": score["passed"],
            "tests_passed": score["tests_passed"], "tests_total": score["tests_total"], "finished": bool(result.get("finished")),
            "stopped": result.get("stopped", ""), "steps": result.get("turns", 0), "seconds": round(time.time() - t0, 1), "files": files[:40],
            "hidden_output": score["output"][-600:] if not score["passed"] else ""}


def summarize(rows):
    n = len(rows)
    if not n:
        return {"projects": 0}
    passed = sum(r["passed"] for r in rows)
    tp, tt = sum(r["tests_passed"] for r in rows), sum(r["tests_total"] for r in rows)
    by_level = {}
    for r in rows:
        lv = by_level.setdefault(r.get("level") or "?", [0, 0])
        lv[0] += r["passed"]
        lv[1] += 1
    return {"projects": n, "passed": passed, "pct_passed": round(100 * passed / n, 1), "hidden_tests_pct": round(100 * tp / tt, 1) if tt else 0.0,
            "finished": sum(r["finished"] for r in rows), "avg_steps": round(sum(r["steps"] for r in rows) / n, 1),
            "minutes": round(sum(r["seconds"] for r in rows) / 60, 1), "by_level": by_level}


def report_md(label, loop, s, rows):
    lines = [f"# VryxCode project test: {label} ({loop} loop)", "",
             f"**{s['passed']} of {s['projects']} projects passed** ({s['pct_passed']}%), hidden tests passed: {s['hidden_tests_pct']}%, "
             f"finished on its own: {s['finished']}, average steps: {s['avg_steps']}, time: {s['minutes']} min.", "",
             "| Project | Level | Result | Hidden tests | Steps | Stopped |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['id']} | {r.get('level')} | {'PASS' if r['passed'] else 'fail'} | {r['tests_passed']}/{r['tests_total']} | {r['steps']} | {r['stopped'] or '-'} |")
    return "\n".join(lines) + "\n"


def selftest(projects, out=print):
    """The tests are fair: every reference solution passes all of its hidden tests, and an empty folder passes none."""
    ok = True
    for p in projects:
        if missing_tools(p):
            out(f"{p['id']:20s} skipped (needs {', '.join(missing_tools(p))})")
            continue
        ref = hidden_check(p, p["reference"]) if p["reference"] else {"passed": False, "tests_passed": 0, "tests_total": 0, "output": "no reference"}
        empty = tempfile.mkdtemp(prefix="vryxproj_empty_")
        try:
            blank = hidden_check(p, empty)
        finally:
            shutil.rmtree(empty, ignore_errors=True)
        good = ref["passed"] and blank["tests_passed"] == 0
        ok = ok and good
        out(f"{p['id']:20s} reference {ref['tests_passed']}/{ref['tests_total']}  empty {blank['tests_passed']}/{blank['tests_total']}  {'ok' if good else 'PROBLEM'}")
        if not good:
            out(ref["output"][-1500:])
    return ok


def main(argv=None):
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
    only = {x.strip() for x in a.only.split(",") if x.strip()} or None
    projects = load_projects(only=only)
    if not projects:
        raise SystemExit("no projects found" + (f" matching {a.only}" if only else ""))
    if a.selftest:
        return 0 if selftest(projects) else 1
    ok, note = V.gate(a.model, a.coder)
    if not ok:
        raise SystemExit(note)
    generate = V.LlamaChat(a.llama, thinking=a.think) if a.think else V.LlamaChat(a.llama)
    label = a.coder or a.model
    rows = []
    for proj in projects:
        if missing_tools(proj):
            print(f"{proj['id']:20s} skipped (needs {', '.join(missing_tools(proj))})", flush=True)
            continue
        r = run_project(proj, generate, a.loop, a.context, a.max_turns)
        rows.append(r)
        print(f"{proj['id']:20s} {'PASS' if r['passed'] else 'fail'}  hidden {r['tests_passed']}/{r['tests_total']}  {r['steps']} steps  {r['seconds']:.0f}s", flush=True)
    s = summarize(rows)
    print(json.dumps(s, indent=2))
    os.makedirs("logs", exist_ok=True)
    base = os.path.join("logs", f"projects-{re.sub(r'[^A-Za-z0-9_.-]', '_', label)}-{a.loop}")
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump({"model": label, "outside_model": bool(a.coder), "loop": a.loop, "summary": s, "results": rows}, f, indent=2)
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(report_md(label, a.loop, s, rows))
    print(f"saved {base}.json and .md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
