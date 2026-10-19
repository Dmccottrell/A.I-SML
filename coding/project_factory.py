"""
project_factory.py - VryxCode 3's lessons: the teacher (Qwen3.6 27B) builds real projects in VryxCode's own loop; only checked builds are kept (docs/VRYXCODE.md).

WHAT THIS FILE DOES
    VryxCode 3 learns from whole multi-step builds, not tiny template tasks. Three kinds of training task, all checked by hidden tests:
      specs   the teacher invents a project: a request written the way a person asks (with exact file and function names), hidden unit tests and a
              working reference solution. A spec is kept only if the reference passes every hidden test, an empty folder passes none, it has at
              least 3 tests, and it is not a copy of a project in the test (coding/projects): those must stay unseen, or the test means nothing.
      builds  the teacher works on each spec in VryxCode's long-build loop (the same tools, checkpoints and rollback the app uses), from an empty
              folder, never seeing the hidden tests. A build is kept only if every hidden test passes, it ran its own tests, and it did not drown
              in tool errors. Two builds of the same spec, one passing and one failing, make a preference pair (DPO).
      fixes   a passing reference with ONE bug put in (a flipped comparison, a wrong operator, an off-by-one) and its tests visible: "the tests fail,
              find and fix it". Kept when the hidden tests pass again and the test file was not touched.
    Output (data\\vryxcode3\\): specs\\<id>\\ (task.json, hidden\\, reference\\), builds.jsonl (chat lessons in our tool format), pairs.jsonl
    ({"task", "chosen", "rejected"} message lists), rejected.jsonl (why each run was dropped), stats.
    Licence: the teacher must allow training on its output (Qwen3.6 27B: Apache 2.0). Never Claude, ChatGPT or Gemini output.

Usage (the teacher on the 5090; one llama-server, several slots):
    llama-server -m Qwen3.6-27B-Q4_K_M.gguf -ngl 99 -c 131072 --parallel 4 --jinja --port 8099
    python coding/project_factory.py specs  --teacher http://127.0.0.1:8099 --n 400        (new projects with tests and a reference)
    python coding/project_factory.py builds --teacher http://127.0.0.1:8099 --samples 2   (the teacher builds each one; resumes by itself)
    python coding/project_factory.py fixes  --teacher http://127.0.0.1:8099 --per 3       (bug hunts in the references)
    python coding/project_factory.py stats
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import argparse
import difflib
import hashlib
import json
import random
import re
import shutil
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

import bench_projects as BP
import collect_runs as C
import vryxcode as V

OUT = os.path.join("data", "vryxcode3")
TEACHER_LABEL = "qwen3.6-27b"
MIN_TESTS = 3
TOO_SIMILAR = 0.6              # a new request this close to a test project (difflib ratio) is dropped
ERROR_SHARE = 0.25             # a build where more than this share of steps were tool errors is not a good lesson

# What to build: kinds of small real programs. The teacher picks a concrete project for each seed, in Python or browser JavaScript.
IDEAS = [
    "a command-line tool that keeps data in a JSON file", "a small library with a few classes and clear errors", "a text parser or formatter",
    "a game's rules and state (no graphics)", "a data report from a CSV file", "a scheduler or calendar helper", "a simple database-backed service with sqlite3",
    "an API handler function that takes (method, path, body) and returns (status, data)", "a state machine", "a recipe, shopping or meal planner",
    "a banking, budgeting or invoicing helper", "a school or grades tool", "an inventory or orders system", "a text-based game engine", "a puzzle solver",
    "a cache or rate limiter", "a search or index over documents", "a templating or report generator", "a unit, currency or date calculator",
    "a browser page with its logic in a separate JavaScript module that also works in Node", "a validation library for forms or records",
    "a command parser with sub-commands", "a log file analyser", "a small interpreter or calculator", "a graph or route finder",
]
LANGS = (("python", 0.75), ("javascript", 0.25))
LEVELS = (("easy", 0.2), ("medium", 0.5), ("hard", 0.3))

SPEC_PROMPT = """Invent one small but real software project for a coding assistant to build from an empty folder, then write its hidden tests and a working reference solution.
Kind of project: {idea}. Language: {lang}. Difficulty: {level} ({files} files of code).
Rules:
- The REQUEST is what a person would type. It must name every file, function, class, method, argument, return value, error and exact output text the tests check, so a careful builder can pass them without seeing them. No other hidden expectations.
- Python: standard library only; tests use unittest in ONE file named hidden_check_<name>.py that imports the project as a package (and runs any command line with subprocess, sys.executable and cwd set to the test file's folder).
- JavaScript: plain JavaScript; the logic module ends with `if (typeof module !== "undefined") module.exports = {{...}};`; tests are ONE Node file named hidden_check_<name>.js using require("assert") and path.join(__dirname, ...), printing `PASS name` / `FAIL name: message` per test, then `passed X of Y`, and exiting 1 if any failed. Include an index.html that uses the module.
- At least {tests} separate tests, covering normal use, edge cases and errors.
- Do not make any of these: {avoid}.
Reply in exactly this format and nothing else:
TITLE: <a short title>
REQUEST:
<the request>
=== FILE: <path> ===
<file content>
(repeat FILE for every reference file)
=== TEST: <hidden_check_name.py or .js> ===
<test file content>
"""


# ------------------------------------------------------------------ specs
def pick(rng, choices):
    r, acc = rng.random(), 0.0
    for value, weight in choices:
        acc += weight
        if r <= acc:
            return value
    return choices[-1][0]


def spec_prompt(rng, avoid):
    lang, level = pick(rng, LANGS), pick(rng, LEVELS)
    files = {"easy": "2 to 3", "medium": "3 to 4", "hard": "4 to 6"}[level]
    return SPEC_PROMPT.format(idea=rng.choice(IDEAS), lang=lang, level=level, files=files, tests=max(MIN_TESTS, {"easy": 4, "medium": 5, "hard": 7}[level]),
                              avoid="; ".join(avoid[-60:]) or "(nothing yet)"), lang, level


SECTION = re.compile(r"^=== (FILE|TEST): (.+?) ===[ \t]*$", re.M)


def parse_spec(reply):
    """{"title", "prompt", "files": {path: text}, "tests": {name: text}} from the teacher's reply, or None if it is not in the format."""
    text = re.sub(r"<think>.*?</think>", "", reply or "", flags=re.S).strip()
    title = re.search(r"^TITLE:\s*(.+)$", text, re.M)
    req = re.search(r"^REQUEST:\s*\n(.*?)(?=^=== (?:FILE|TEST):)", text, re.M | re.S)
    if not title or not req:
        return None
    files, tests = {}, {}
    marks = list(SECTION.finditer(text))
    for i, m in enumerate(marks):
        body = text[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(text)].strip("\n")
        body = re.sub(r"^```[\w+-]*\n(.*?)\n?```$", r"\1", body.strip(), flags=re.S) + "\n"     # a fenced block inside a section is unwrapped
        path = m.group(2).strip().replace("\\", "/")
        if path.startswith("/") or ".." in path.split("/") or not path:
            return None
        (files if m.group(1) == "FILE" else tests)[path] = body
    if not files or not tests or not all(re.fullmatch(r"hidden_check_\w+\.(py|js)", t) for t in tests):
        return None
    return {"title": title.group(1).strip(), "prompt": req.group(1).strip(), "files": files, "tests": tests}


def too_similar(prompt, others):
    a = " ".join(prompt.lower().split())
    return any(difflib.SequenceMatcher(None, a, " ".join(o.lower().split())).ratio() >= TOO_SIMILAR for o in others)


def spec_id(spec):
    return re.sub(r"[^a-z0-9]+", "_", spec["title"].lower()).strip("_")[:40] + "_" + hashlib.sha1(spec["prompt"].encode("utf-8")).hexdigest()[:6]


def save_spec(root, spec, lang, level):
    """Write a spec in the same layout as the test projects (task.json, hidden/, reference/). Returns its folder."""
    sid = spec_id(spec)
    folder = os.path.join(root, sid)
    if os.path.isdir(folder):
        shutil.rmtree(folder)
    for sub, items in (("reference", spec["files"]), ("hidden", spec["tests"])):
        for path, text in items.items():
            full = os.path.join(folder, sub, *path.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
    with open(os.path.join(folder, "task.json"), "w", encoding="utf-8") as f:
        json.dump({"title": spec["title"], "lang": lang, "level": level, "prompt": spec["prompt"], "needs": ["node"] if lang == "javascript" else [],
                   "source": TEACHER_LABEL}, f, indent=2)
    return folder


def check_spec(folder):
    """None when the spec is fair (reference passes all, empty folder passes none, enough tests), else the reason."""
    p = BP.load_projects(os.path.dirname(folder), only={os.path.basename(folder)})[0]
    if BP.missing_tools(p):
        return "needs " + ", ".join(BP.missing_tools(p))
    ref = BP.hidden_check(p, p["reference"])
    if ref["tests_total"] < MIN_TESTS:
        return f"only {ref['tests_total']} tests"
    if not ref["passed"]:
        return f"the reference fails its own tests ({ref['tests_passed']}/{ref['tests_total']})"
    empty = tempfile.mkdtemp(prefix="vryxspec_empty_")
    try:
        if BP.hidden_check(p, empty)["tests_passed"]:
            return "an empty folder passes some tests (they test nothing)"
    finally:
        shutil.rmtree(empty, ignore_errors=True)
    return None


def make_specs(teacher, n, root, log=print, seed=None, workers=4):
    """Ask the teacher for n projects; keep the fair ones. Returns a Counter-like dict of outcomes."""
    os.makedirs(root, exist_ok=True)
    bench = [p["prompt"] for p in BP.load_projects()]
    titles = [p["title"] for p in BP.load_projects()] + [s["title"] for s in load_specs(root)]
    rng = random.Random(seed)
    lock, stats = threading.Lock(), {"asked": 0, "kept": 0}

    def one(_):
        with lock:
            prompt, lang, level = spec_prompt(rng, titles)
        reply = teacher.chat([{"role": "user", "content": prompt}], temperature=0.8, max_tokens=12000)["answer"]
        spec = parse_spec(reply)
        why = None if spec else "not in the format"
        if spec and too_similar(spec["prompt"], bench):
            why = "too close to a test project"
        with lock:
            stats["asked"] += 1
            if not why and spec["title"] in titles:
                why = "a repeat"
            folder = None if why else save_spec(root, spec, lang, level)
        if folder:
            why = check_spec(folder)
            if why:
                shutil.rmtree(folder, ignore_errors=True)
        with lock:
            if why:
                stats["dropped: " + why.split(" (")[0]] = stats.get("dropped: " + why.split(" (")[0], 0) + 1
            else:
                stats["kept"] += 1
                titles.append(spec["title"])
            log(f"spec {stats['asked']}/{n}: {'kept ' + spec['title'] if not why else 'dropped (' + why + ')'}")
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(one, range(n)))
    return stats


def load_specs(root):
    return BP.load_projects(root) if os.path.isdir(root) else []


# ------------------------------------------------------------------ builds
def judge_build(result, score):
    """None if the build is a good lesson, else why not."""
    if not score["passed"]:
        return f"hidden tests fail ({score['tests_passed']}/{score['tests_total']})"
    if not result.get("finished"):
        return "did not finish"
    calls = C.tool_calls(result["messages"])
    if not any(n in ("write_file", "edit_file") for n, _ in calls):
        return "changed nothing"
    if not any(n == "run" and any(w in str(a.get("command", "")) for w in C.TEST_WORDS + ("node",)) for n, a in calls):
        return "never ran its tests"
    errors = sum(1 for m in result["messages"] if m["role"] == "user" and m["content"].startswith("<|tool_result|>error:"))
    if errors > max(3, ERROR_SHARE * len(calls)):
        return "too many tool errors"
    return None


def lesson(messages, result):
    """The conversation as a lesson: the steps folded away during the build are not part of it (the lesson is what the model saw last)."""
    return [{"role": m["role"], "content": re.sub(r"<think>.*?</think>\s*", "", m["content"], flags=re.S)} for m in messages]


def build_one(project, generate, max_turns=None, context_tokens=None):
    """One build of one spec in the long-build loop: (row, reason or None, score)."""
    work = tempfile.mkdtemp(prefix="vryxbuild_")
    folder = os.path.join(work, "p")
    os.makedirs(folder)
    try:
        result = V.run_task(project["prompt"], generate, folder, V.make_ask(True), max_turns or V.BUILD_STEPS, context_tokens, out=lambda *_: None,
                            checks=True, build=True, full=True)
        score = BP.hidden_check(project, folder)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    why = judge_build(result, score)
    row = {"messages": lesson(result["messages"], result), "kind": "agent_build", "task": project["id"], "model": TEACHER_LABEL,
           "steps": result.get("turns", 0), "level": project.get("level"), "lang": project.get("lang"),
           "hidden": [score["tests_passed"], score["tests_total"]]}
    return row, why, score


class Out:
    """The output folder: append-only JSONL files, safe from several threads; what is done is remembered so a run resumes."""

    def __init__(self, root=OUT):
        self.root = root
        os.makedirs(root, exist_ok=True)
        self.lock = threading.Lock()

    def path(self, name):
        return os.path.join(self.root, name)

    def add(self, name, row):
        with self.lock, open(self.path(name), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def rows(self, name):
        if not os.path.exists(self.path(name)):
            return []
        with open(self.path(name), encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]


def make_builds(projects, generate, out, samples=2, max_turns=None, context_tokens=None, workers=1, log=print):
    """Each spec built `samples` times (skipping specs already done). Keeps passing builds; a pass and a fail of the same spec make a pair."""
    done = {r["task"] for r in out.rows("builds.jsonl")} | {r["task"] for r in out.rows("rejected.jsonl") if r.get("kind") == "build"}
    todo = [p for p in projects if p["id"] not in done and not BP.missing_tools(p)]
    stats = {"specs": len(todo), "builds": 0, "kept": 0, "pairs": 0}
    lock = threading.Lock()

    def one(p):
        runs = [build_one(p, generate, max_turns, context_tokens) for _ in range(samples)]
        good = [r for r, why, _ in runs if not why]
        bad = [(r, s) for r, why, s in runs if why]
        for r in good[:1]:                                    # one lesson per spec (two passing builds of the same project teach the same thing)
            out.add("builds.jsonl", r)
        for r, why, _ in runs:
            if why:
                out.add("rejected.jsonl", {"kind": "build", "task": p["id"], "why": why, "steps": r["steps"]})
        if good and bad:
            worst = min(bad, key=lambda x: x[1]["tests_passed"] / max(1, x[1]["tests_total"]))[0]
            out.add("pairs.jsonl", {"task": p["id"], "prompt": p["prompt"], "chosen": good[0]["messages"], "rejected": worst["messages"],
                                    "chosen_hidden": good[0]["hidden"], "rejected_hidden": worst["hidden"], "model": TEACHER_LABEL})
        with lock:
            stats["builds"] += len(runs)
            stats["kept"] += min(1, len(good))
            stats["pairs"] += 1 if good and bad else 0
            log(f"{p['id']}: {len(good)} of {len(runs)} builds passed")
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(one, todo))
    return stats


# ------------------------------------------------------------------ fixes (one bug put into a working reference)
MUTATIONS = [(r"(?<![<>=!])<=(?!=)", "<"), (r"(?<![<>=!])>=(?!=)", ">"), (r"(?<![<>=!-])<(?![<=])", "<="), (r"(?<![<>=!-])>(?![>=])", ">="),
             (r"==", "!="), (r" \+ 1\b", ""), (r" - 1\b", ""), (r"(?<=\w) \+ (?=\w)", " - "), (r"\bTrue\b", "False"), (r"\band\b", "or"),
             (r"\[1:\]", "[:]"), (r"\.append\(", ".insert(0, ")]


def mutants(text, rng, limit=6):
    """Up to `limit` versions of the code with ONE small bug each: [(new_text, line_number)]."""
    spots = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        code = line.split("#", 1)[0]
        if not code.strip() or code.lstrip().startswith(("import", "from", "def ", "class ", '"""', "'''", "@")) or re.search(r"['\"]", code):
            continue
        for pat, rep in MUTATIONS:
            for m in re.finditer(pat, code):
                spots.append((i, m.start(), m.end(), rep))
    rng.shuffle(spots)
    out = []
    for i, a, b, rep in spots[:limit]:
        new = list(lines)
        new[i] = new[i][:a] + rep + new[i][b:]
        out.append(("\n".join(new), i + 1))
    return out


FIX_PROMPT = ("The tests in {tests} fail. Find the bug in the project and fix it. Do not change {tests}. Run the tests with {command} until they pass, then finish.")


def stage_fix(project, path, text):
    """A copy of the reference with one file changed and the hidden tests visible as ordinary test files. Returns (work, folder)."""
    work = tempfile.mkdtemp(prefix="vryxfix_")
    folder = os.path.join(work, "p")
    shutil.copytree(project["reference"], folder)
    with open(os.path.join(folder, *path.split("/")), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    for name in project["hidden"]:
        shutil.copy(os.path.join(project["dir"], "hidden", name), os.path.join(folder, name.replace("hidden_check_", "test_")))
    return work, folder


def fix_tasks(project, rng, per=3):
    """Bugs that really break a test: [(file path, buggy text, line)]. Python references only."""
    out = []
    files = [os.path.relpath(os.path.join(r, f), project["reference"]).replace("\\", "/") for r, _, fs in os.walk(project["reference"]) for f in fs if f.endswith(".py")]
    rng.shuffle(files)
    for path in files:
        with open(os.path.join(project["reference"], *path.split("/")), encoding="utf-8") as f:
            text = f.read()
        for new, line in mutants(text, rng):
            work, folder = stage_fix(project, path, new)
            try:
                if not BP.hidden_check(project, folder)["passed"]:
                    out.append((path, new, line))
            finally:
                shutil.rmtree(work, ignore_errors=True)
            if len(out) >= per:
                return out
    return out


def make_fixes(projects, generate, out, per=3, max_turns=40, context_tokens=None, seed=7, log=print):
    rng = random.Random(seed)
    done = {r["task"] for r in out.rows("fixes.jsonl")} | {r["task"] for r in out.rows("rejected.jsonl") if r.get("kind") == "fix"}
    stats = {"tried": 0, "kept": 0}
    for p in projects:
        if p.get("lang") != "python" or not p["reference"]:
            continue
        tests = [n.replace("hidden_check_", "test_") for n in p["hidden"]]
        for path, text, line in fix_tasks(p, rng, per):
            tid = f"{p['id']}:fix:{path}:{line}"
            if tid in done:
                continue
            work, folder = stage_fix(p, path, text)
            try:
                before = C.file_hashes(folder, tests)
                prompt = FIX_PROMPT.format(tests=", ".join(tests), command="python -m unittest " + " ".join(t[:-3] for t in tests))
                result = V.run_task(prompt, generate, folder, V.make_ask(True), max_turns, context_tokens, out=lambda *_: None, checks=True, build=True, full=True)
                edited = C.file_hashes(folder, tests) != before or wrote_to(result, tests)
                score = BP.hidden_check(p, folder)               # the hidden copies are what count, not the visible ones it could have changed
            finally:
                shutil.rmtree(work, ignore_errors=True)
            why = "edited the tests" if edited else judge_build(result, score)
            stats["tried"] += 1
            if why:
                out.add("rejected.jsonl", {"kind": "fix", "task": tid, "why": why})
            else:
                stats["kept"] += 1
                out.add("fixes.jsonl", {"messages": lesson(result["messages"], result), "kind": "agent_fix", "task": tid, "model": TEACHER_LABEL,
                                        "steps": result.get("turns", 0)})
            log(f"{tid}: {'kept' if not why else why}")
    return stats


def wrote_to(result, names):
    """True when the model wrote to or edited one of these files (from its tool calls)."""
    for name, args in C.tool_calls(result["messages"]):
        if name in ("write_file", "edit_file") and isinstance(args, dict) and re.sub(r"^(\./)+", "", str(args.get("path", "")).replace("\\", "/")) in names:
            return True
    return False


# ------------------------------------------------------------------ stats and command line
def stats(out, specs_root):
    rows = {n: out.rows(n) for n in ("builds.jsonl", "pairs.jsonl", "fixes.jsonl", "rejected.jsonl")}
    why = {}
    for r in rows["rejected.jsonl"]:
        k = f"{r.get('kind')}: {str(r.get('why', '')).split(' (')[0]}"
        why[k] = why.get(k, 0) + 1
    steps = [r["steps"] for r in rows["builds.jsonl"]]
    return {"specs": len(load_specs(specs_root)), "builds kept": len(rows["builds.jsonl"]), "pairs": len(rows["pairs.jsonl"]),
            "fixes kept": len(rows["fixes.jsonl"]), "average build steps": round(sum(steps) / len(steps), 1) if steps else 0, "rejected": why}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=("specs", "builds", "fixes", "stats"))
    p.add_argument("--teacher", default="http://127.0.0.1:8099", help="the teacher's llama-server (Qwen3.6 27B)")
    p.add_argument("--out", default=OUT)
    p.add_argument("--n", type=int, default=50, help="specs: how many projects to ask for")
    p.add_argument("--samples", type=int, default=2, help="builds: tries per spec (a pass and a fail make a preference pair)")
    p.add_argument("--per", type=int, default=3, help="fixes: bugs per project")
    p.add_argument("--workers", type=int, default=4, help="parallel requests (match llama-server --parallel)")
    p.add_argument("--context", type=int, default=131072)
    p.add_argument("--max-turns", type=int, default=None)
    p.add_argument("--think", action="store_true", help="builds: let the teacher think before each step (better, slower; the thinking is not kept)")
    p.add_argument("--seed", type=int, default=None)
    a = p.parse_args(argv)
    out = Out(a.out)
    specs_root = os.path.join(a.out, "specs")
    if a.command == "stats":
        print(json.dumps(stats(out, specs_root), indent=2))
        return 0
    if a.command == "specs":
        import lesson_factory
        print(json.dumps(make_specs(lesson_factory.Teacher(a.teacher), a.n, specs_root, seed=a.seed, workers=a.workers), indent=2))
        return 0
    generate = V.LlamaChat(a.teacher, thinking=a.think, max_tokens=8192)
    projects = load_specs(specs_root)
    if not projects:
        raise SystemExit(f"no specs in {specs_root}: run `specs` first")
    if a.command == "builds":
        print(json.dumps(make_builds(projects, generate, out, a.samples, a.max_turns, a.context, a.workers), indent=2))
    else:
        print(json.dumps(make_fixes(projects, generate, out, a.per, a.max_turns or 40, a.context), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
