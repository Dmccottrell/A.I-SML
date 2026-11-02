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
# This line adds the project's parent folder to Python's search path, then imports emvryx_paths, which makes the other code folders importable.
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

# Short names for the helper modules: BP = the test-project loader/grader, C = helpers that read recorded runs, V = the VryxCode agent itself.
import bench_projects as BP
import collect_runs as C
import vryxcode as V

# Where all output goes (a relative path: data/vryxcode3).
OUT = os.path.join("data", "vryxcode3")
# The name stamped on every kept row so we always know which model wrote it.
TEACHER_LABEL = "qwen3.6-27b"
# A spec needs at least this many hidden tests, or passing them proves little.
MIN_TESTS = 3
TOO_SIMILAR = 0.6              # a new request this close to a test project (difflib ratio) is dropped
ERROR_SHARE = 0.25             # a build where more than this share of steps were tool errors is not a good lesson

# What to build: kinds of small real programs. The teacher picks a concrete project for each seed, in Python or browser JavaScript.
# The list of project ideas the teacher is asked to pick from (one is chosen at random per request).
IDEAS = [
    "a command-line tool that keeps data in a JSON file", "a small library with a few classes and clear errors", "a text parser or formatter",
    "a game's rules and state (no graphics)", "a data report from a CSV file", "a scheduler or calendar helper", "a simple database-backed service with sqlite3",
    "an API handler function that takes (method, path, body) and returns (status, data)", "a state machine", "a recipe, shopping or meal planner",
    "a banking, budgeting or invoicing helper", "a school or grades tool", "an inventory or orders system", "a text-based game engine", "a puzzle solver",
    "a cache or rate limiter", "a search or index over documents", "a templating or report generator", "a unit, currency or date calculator",
    "a browser page with its logic in a separate JavaScript module that also works in Node", "a validation library for forms or records",
    "a command parser with sub-commands", "a log file analyser", "a small interpreter or calculator", "a graph or route finder",
]
# (value, weight) pairs for a weighted random pick: about 75% Python and 25% JavaScript; then the difficulty mix.
LANGS = (("python", 0.75), ("javascript", 0.25))
LEVELS = (("easy", 0.2), ("medium", 0.5), ("hard", 0.3))

# The instructions sent to the teacher to invent one project. {idea}, {lang}, {level}, {files}, {tests}, {avoid} are
# blanks filled in by spec_prompt(). The doubled braces {{ }} are how a literal brace is written inside a .format() template.
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
    """Weighted random choice. `choices` is [(value, weight), ...] with weights adding up to 1; `rng` is a random.Random.

    Draw a number between 0 and 1 and walk along the list adding weights until the running total passes it.
    """
    r, acc = rng.random(), 0.0
    for value, weight in choices:
        acc += weight
        if r <= acc:
            return value
    # Safety net for tiny rounding errors in the weights: fall back to the last choice.
    return choices[-1][0]


def spec_prompt(rng, avoid):
    """Fill in SPEC_PROMPT with a random idea, language and difficulty.

    `avoid` is the list of titles already made (only the last 60 are listed, to keep the prompt short and the projects varied).
    Returns (prompt text, language, level).
    """
    lang, level = pick(rng, LANGS), pick(rng, LEVELS)
    files = {"easy": "2 to 3", "medium": "3 to 4", "hard": "4 to 6"}[level]
    return SPEC_PROMPT.format(idea=rng.choice(IDEAS), lang=lang, level=level, files=files, tests=max(MIN_TESTS, {"easy": 4, "medium": 5, "hard": 7}[level]),
                              avoid="; ".join(avoid[-60:]) or "(nothing yet)"), lang, level


# Matches a marker line like "=== FILE: bank/ledger.py ===" or "=== TEST: hidden_check_x.py ===".
# Group 1 is FILE or TEST, group 2 is the path. re.M makes ^ and $ work per line.
SECTION = re.compile(r"^=== (FILE|TEST): (.+?) ===[ \t]*$", re.M)


def parse_spec(reply):
    """{"title", "prompt", "files": {path: text}, "tests": {name: text}} from the teacher's reply, or None if it is not in the format."""
    # Remove any <think>...</think> reasoning the teacher printed; re.S lets "." match across line breaks.
    text = re.sub(r"<think>.*?</think>", "", reply or "", flags=re.S).strip()
    title = re.search(r"^TITLE:\s*(.+)$", text, re.M)
    # The request is everything after "REQUEST:" up to (but not including, the (?=...) look-ahead) the first FILE/TEST marker.
    req = re.search(r"^REQUEST:\s*\n(.*?)(?=^=== (?:FILE|TEST):)", text, re.M | re.S)
    if not title or not req:
        return None
    files, tests = {}, {}
    marks = list(SECTION.finditer(text))
    # Each section's body runs from the end of its marker line to the start of the next marker (or the end of the text).
    for i, m in enumerate(marks):
        body = text[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(text)].strip("\n")
        body = re.sub(r"^```[\w+-]*\n(.*?)\n?```$", r"\1", body.strip(), flags=re.S) + "\n"     # a fenced block inside a section is unwrapped
        path = m.group(2).strip().replace("\\", "/")
        # Safety: refuse absolute paths and ".." parts, so a reply cannot write outside the spec folder.
        if path.startswith("/") or ".." in path.split("/") or not path:
            return None
        # Put the body in `files` or `tests` depending on the marker word.
        (files if m.group(1) == "FILE" else tests)[path] = body
    # Need at least one reference file, one test, and every test file must be named hidden_check_<name>.py or .js.
    if not files or not tests or not all(re.fullmatch(r"hidden_check_\w+\.(py|js)", t) for t in tests):
        return None
    return {"title": title.group(1).strip(), "prompt": req.group(1).strip(), "files": files, "tests": tests}


def too_similar(prompt, others):
    """True if `prompt` reads almost the same as any text in `others` (similarity of TOO_SIMILAR or more).

    Used so the teacher's new requests are not copies of the held-out test projects.
    """
    # Lower-case and collapse all runs of spaces/newlines so only the words are compared.
    a = " ".join(prompt.lower().split())
    return any(difflib.SequenceMatcher(None, a, " ".join(o.lower().split())).ratio() >= TOO_SIMILAR for o in others)


def spec_id(spec):
    """A folder-safe name for a spec: the title in lower-case with "_" between words (max 40 chars) plus 6 hex characters of a hash of the request, so two projects with the same title do not clash."""
    return re.sub(r"[^a-z0-9]+", "_", spec["title"].lower()).strip("_")[:40] + "_" + hashlib.sha1(spec["prompt"].encode("utf-8")).hexdigest()[:6]


def save_spec(root, spec, lang, level):
    """Write a spec in the same layout as the test projects (task.json, hidden/, reference/). Returns its folder."""
    sid = spec_id(spec)
    folder = os.path.join(root, sid)
    # Start clean if the folder is left over from an earlier try.
    if os.path.isdir(folder):
        shutil.rmtree(folder)
    # Files go under reference/ (the working solution) and hidden/ (the tests the builder must never see).
    for sub, items in (("reference", spec["files"]), ("hidden", spec["tests"])):
        for path, text in items.items():
            full = os.path.join(folder, sub, *path.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            # newline="\n" keeps Unix line endings even on Windows so file contents are identical everywhere.
            with open(full, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
    # task.json describes the spec; JavaScript specs need the "node" program installed to be graded.
    with open(os.path.join(folder, "task.json"), "w", encoding="utf-8") as f:
        json.dump({"title": spec["title"], "lang": lang, "level": level, "prompt": spec["prompt"], "needs": ["node"] if lang == "javascript" else [],
                   "source": TEACHER_LABEL}, f, indent=2)
    return folder


def check_spec(folder):
    """None when the spec is fair (reference passes all, empty folder passes none, enough tests), else the reason."""
    # Load just this one spec as a project, then run the hidden tests against the teacher's own reference solution.
    p = BP.load_projects(os.path.dirname(folder), only={os.path.basename(folder)})[0]
    if BP.missing_tools(p):
        return "needs " + ", ".join(BP.missing_tools(p))
    ref = BP.hidden_check(p, p["reference"])
    if ref["tests_total"] < MIN_TESTS:
        return f"only {ref['tests_total']} tests"
    if not ref["passed"]:
        return f"the reference fails its own tests ({ref['tests_passed']}/{ref['tests_total']})"
    # Now run the same tests against an EMPTY folder. If any pass, the tests do not really test anything.
    empty = tempfile.mkdtemp(prefix="vryxspec_empty_")
    try:
        if BP.hidden_check(p, empty)["tests_passed"]:
            return "an empty folder passes some tests (they test nothing)"
    finally:
        # Always delete the temp folder, even if grading crashed.
        shutil.rmtree(empty, ignore_errors=True)
    return None


def make_specs(teacher, n, root, log=print, seed=None, workers=4):
    """Ask the teacher for n projects; keep the fair ones. Returns a Counter-like dict of outcomes.

    `teacher` is the model client (has .chat), `root` the folder where specs are saved, `workers` how many requests run at once.
    """
    os.makedirs(root, exist_ok=True)
    # `bench` = the test projects' requests (specs must not copy these); `titles` = all titles so far (to avoid repeats).
    bench = [p["prompt"] for p in BP.load_projects()]
    titles = [p["title"] for p in BP.load_projects()] + [s["title"] for s in load_specs(root)]
    rng = random.Random(seed)
    # Several threads share `rng`, `titles` and `stats`, so a lock makes them take turns changing them.
    lock, stats = threading.Lock(), {"asked": 0, "kept": 0}

    def one(_):
        """Ask for, check and save (or drop) one spec. The argument is just the job number and is unused."""
        with lock:
            prompt, lang, level = spec_prompt(rng, titles)
        # The slow network call runs OUTSIDE the lock so the other threads can work meanwhile.
        reply = teacher.chat([{"role": "user", "content": prompt}], temperature=0.8, max_tokens=12000)["answer"]
        spec = parse_spec(reply)
        # `why` is the reason for dropping the spec; None means it is still OK so far.
        why = None if spec else "not in the format"
        if spec and too_similar(spec["prompt"], bench):
            why = "too close to a test project"
        with lock:
            stats["asked"] += 1
            if not why and spec["title"] in titles:
                why = "a repeat"
            folder = None if why else save_spec(root, spec, lang, level)
        # The slow check (it runs the tests) is also outside the lock. A spec that fails it is deleted again.
        if folder:
            why = check_spec(folder)
            if why:
                shutil.rmtree(folder, ignore_errors=True)
        with lock:
            if why:
                # Count drops by reason (text before any " (" detail).
                stats["dropped: " + why.split(" (")[0]] = stats.get("dropped: " + why.split(" (")[0], 0) + 1
            else:
                stats["kept"] += 1
                titles.append(spec["title"])
            log(f"spec {stats['asked']}/{n}: {'kept ' + spec['title'] if not why else 'dropped (' + why + ')'}")
    # A thread pool runs up to `workers` jobs at the same time. list(...) waits for all n jobs to finish.
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(one, range(n)))
    return stats


def load_specs(root):
    """All specs saved under `root` as project dicts (an empty list if the folder does not exist yet)."""
    return BP.load_projects(root) if os.path.isdir(root) else []


# ------------------------------------------------------------------ builds
def judge_build(result, score):
    """None if the build is a good lesson, else why not.

    `result` is what the agent run returned (messages, finished flag...); `score` is the hidden-test result.
    """
    # Test in order: hidden tests pass, the agent said it was finished, it changed files, it ran its own tests, few tool errors.
    if not score["passed"]:
        return f"hidden tests fail ({score['tests_passed']}/{score['tests_total']})"
    if not result.get("finished"):
        return "did not finish"
    # calls = list of (tool name, arguments) the agent made.
    calls = C.tool_calls(result["messages"])
    if not any(n in ("write_file", "edit_file") for n, _ in calls):
        return "changed nothing"
    # "Ran its tests" = some `run` call whose command contains a test word (or "node" for JavaScript).
    if not any(n == "run" and any(w in str(a.get("command", "")) for w in C.TEST_WORDS + ("node",)) for n, a in calls):
        return "never ran its tests"
    # Tool errors come back to the model as user messages starting with this marker; too many means a messy, poor lesson.
    errors = sum(1 for m in result["messages"] if m["role"] == "user" and m["content"].startswith("<|tool_result|>error:"))
    if errors > max(3, ERROR_SHARE * len(calls)):
        return "too many tool errors"
    return None


def lesson(messages, result):
    """The conversation as a lesson: the steps folded away during the build are not part of it (the lesson is what the model saw last)."""
    # Strip the model's <think>...</think> reasoning from every message before keeping it as training text.
    return [{"role": m["role"], "content": re.sub(r"<think>.*?</think>\s*", "", m["content"], flags=re.S)} for m in messages]


def build_one(project, generate, max_turns=None, context_tokens=None):
    """One build of one spec in the long-build loop: (row, reason or None, score)."""
    # Build in a throwaway temp folder that starts empty.
    work = tempfile.mkdtemp(prefix="vryxbuild_")
    folder = os.path.join(work, "p")
    os.makedirs(folder)
    try:
        # Run the real VryxCode loop: `generate` is the model, out=lambda *_: None throws away the progress printing.
        result = V.run_task(project["prompt"], generate, folder, V.make_ask(True), max_turns or V.BUILD_STEPS, context_tokens, out=lambda *_: None,
                            checks=True, build=True, full=True)
        # Grade the finished folder with the hidden tests.
        score = BP.hidden_check(project, folder)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    why = judge_build(result, score)
    # One training row: the chat, plus labels about where it came from and how well it did.
    row = {"messages": lesson(result["messages"], result), "kind": "agent_build", "task": project["id"], "model": TEACHER_LABEL,
           "steps": result.get("turns", 0), "level": project.get("level"), "lang": project.get("lang"),
           "hidden": [score["tests_passed"], score["tests_total"]]}
    return row, why, score


class Out:
    """The output folder: append-only JSONL files, safe from several threads; what is done is remembered so a run resumes."""

    def __init__(self, root=OUT):
        """Remember the folder (creating it if needed) and make a lock so threads do not write at the same moment."""
        self.root = root
        os.makedirs(root, exist_ok=True)
        self.lock = threading.Lock()

    def path(self, name):
        """Full path of the file `name` inside the output folder."""
        return os.path.join(self.root, name)

    def add(self, name, row):
        """Append `row` (a dict) as one JSON line to the file `name`."""
        with self.lock, open(self.path(name), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def rows(self, name):
        """All rows of the JSONL file `name` as dicts ([] if it does not exist yet); blank lines are skipped."""
        if not os.path.exists(self.path(name)):
            return []
        with open(self.path(name), encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]


def make_builds(projects, generate, out, samples=2, max_turns=None, context_tokens=None, workers=1, log=print):
    """Each spec built `samples` times (skipping specs already done). Keeps passing builds; a pass and a fail of the same spec make a pair."""
    # `done` = specs already built (kept or rejected), so rerunning the command resumes where it stopped.
    done = {r["task"] for r in out.rows("builds.jsonl")} | {r["task"] for r in out.rows("rejected.jsonl") if r.get("kind") == "build"}
    todo = [p for p in projects if p["id"] not in done and not BP.missing_tools(p)]
    stats = {"specs": len(todo), "builds": 0, "kept": 0, "pairs": 0}
    lock = threading.Lock()

    def one(p):
        """Build spec `p` `samples` times and record the results."""
        runs = [build_one(p, generate, max_turns, context_tokens) for _ in range(samples)]
        # good = rows with no problem; bad = (row, score) for the failures.
        good = [r for r, why, _ in runs if not why]
        bad = [(r, s) for r, why, s in runs if why]
        for r in good[:1]:                                    # one lesson per spec (two passing builds of the same project teach the same thing)
            out.add("builds.jsonl", r)
        # Every failed build is logged with its reason.
        for r, why, _ in runs:
            if why:
                out.add("rejected.jsonl", {"kind": "build", "task": p["id"], "why": why, "steps": r["steps"]})
        # A preference pair needs both a pass (chosen) and a fail (rejected); use the failure with the lowest share of tests passed.
        if good and bad:
            worst = min(bad, key=lambda x: x[1]["tests_passed"] / max(1, x[1]["tests_total"]))[0]
            out.add("pairs.jsonl", {"task": p["id"], "prompt": p["prompt"], "chosen": good[0]["messages"], "rejected": worst["messages"],
                                    "chosen_hidden": good[0]["hidden"], "rejected_hidden": worst["hidden"], "model": TEACHER_LABEL})
        # Update the shared counters one thread at a time.
        with lock:
            stats["builds"] += len(runs)
            stats["kept"] += min(1, len(good))
            stats["pairs"] += 1 if good and bad else 0
            log(f"{p['id']}: {len(good)} of {len(runs)} builds passed")
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(one, todo))
    return stats


# ------------------------------------------------------------------ fixes (one bug put into a working reference)
# Each entry is (regex, replacement): a small edit that usually breaks working code.
# Examples: "<=" becomes "<", "==" becomes "!=", "+ 1" is dropped, "True" becomes "False", "and" becomes "or".
# The (?<!...) and (?!...) parts stop it matching inside longer operators such as "<=" or "->".
MUTATIONS = [(r"(?<![<>=!])<=(?!=)", "<"), (r"(?<![<>=!])>=(?!=)", ">"), (r"(?<![<>=!-])<(?![<=])", "<="), (r"(?<![<>=!-])>(?![>=])", ">="),
             (r"==", "!="), (r" \+ 1\b", ""), (r" - 1\b", ""), (r"(?<=\w) \+ (?=\w)", " - "), (r"\bTrue\b", "False"), (r"\band\b", "or"),
             (r"\[1:\]", "[:]"), (r"\.append\(", ".insert(0, ")]


def mutants(text, rng, limit=6):
    """Up to `limit` versions of the code with ONE small bug each: [(new_text, line_number)]."""
    # `spots` collects every place a mutation could go: (line index, start, end, replacement).
    spots = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        # Ignore anything after a "#" (a comment).
        code = line.split("#", 1)[0]
        # Skip blank lines, imports, definitions, decorators, docstring lines and any line with a quote character
        # (so text inside strings is never changed).
        if not code.strip() or code.lstrip().startswith(("import", "from", "def ", "class ", '"""', "'''", "@")) or re.search(r"['\"]", code):
            continue
        for pat, rep in MUTATIONS:
            for m in re.finditer(pat, code):
                spots.append((i, m.start(), m.end(), rep))
    rng.shuffle(spots)
    out = []
    # Take a random few; each one edits a copy of the lines, so every result has exactly one change.
    for i, a, b, rep in spots[:limit]:
        new = list(lines)
        new[i] = new[i][:a] + rep + new[i][b:]
        out.append(("\n".join(new), i + 1))
    return out


# The request given to the agent for a bug hunt. {tests} and {command} are filled in by make_fixes().
FIX_PROMPT = ("The tests in {tests} fail. Find the bug in the project and fix it. Do not change {tests}. Run the tests with {command} until they pass, then finish.")


def stage_fix(project, path, text):
    """A copy of the reference with one file changed and the hidden tests visible as ordinary test files. Returns (work, folder)."""
    work = tempfile.mkdtemp(prefix="vryxfix_")
    folder = os.path.join(work, "p")
    shutil.copytree(project["reference"], folder)
    # Overwrite one file with the buggy version.
    with open(os.path.join(folder, *path.split("/")), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    # Copy each hidden test next to the code under a visible name: hidden_check_x.py becomes test_x.py.
    for name in project["hidden"]:
        shutil.copy(os.path.join(project["dir"], "hidden", name), os.path.join(folder, name.replace("hidden_check_", "test_")))
    return work, folder


def fix_tasks(project, rng, per=3):
    """Bugs that really break a test: [(file path, buggy text, line)]. Python references only."""
    out = []
    # Every .py file under the reference folder, as paths with "/" separators, in random order.
    files = [os.path.relpath(os.path.join(r, f), project["reference"]).replace("\\", "/") for r, _, fs in os.walk(project["reference"]) for f in fs if f.endswith(".py")]
    rng.shuffle(files)
    for path in files:
        with open(os.path.join(project["reference"], *path.split("/")), encoding="utf-8") as f:
            text = f.read()
        for new, line in mutants(text, rng):
            work, folder = stage_fix(project, path, new)
            try:
                # Keep the mutation only if it really makes the hidden tests fail (many changes are harmless).
                if not BP.hidden_check(project, folder)["passed"]:
                    out.append((path, new, line))
            finally:
                shutil.rmtree(work, ignore_errors=True)
            if len(out) >= per:
                return out
    return out


def make_fixes(projects, generate, out, per=3, max_turns=40, context_tokens=None, seed=7, log=print):
    """Run the bug-hunt lessons: for each Python spec, plant up to `per` bugs and let the agent fix them. Returns counts.

    A run is kept when the hidden tests pass again, the agent did not edit the test files, and judge_build() is happy.
    """
    rng = random.Random(seed)
    # Skip bugs already tried (kept or rejected) so the command can be restarted.
    done = {r["task"] for r in out.rows("fixes.jsonl")} | {r["task"] for r in out.rows("rejected.jsonl") if r.get("kind") == "fix"}
    stats = {"tried": 0, "kept": 0}
    for p in projects:
        # Bug planting only works on Python references.
        if p.get("lang") != "python" or not p["reference"]:
            continue
        # The visible names of the test files, as stage_fix() copies them.
        tests = [n.replace("hidden_check_", "test_") for n in p["hidden"]]
        for path, text, line in fix_tasks(p, rng, per):
            # A unique id for this exact bug: spec, file and line.
            tid = f"{p['id']}:fix:{path}:{line}"
            if tid in done:
                continue
            work, folder = stage_fix(p, path, text)
            try:
                # Fingerprint the visible test files now so we can tell later whether the agent changed them (cheating).
                before = C.file_hashes(folder, tests)
                prompt = FIX_PROMPT.format(tests=", ".join(tests), command="python -m unittest " + " ".join(t[:-3] for t in tests))
                result = V.run_task(prompt, generate, folder, V.make_ask(True), max_turns, context_tokens, out=lambda *_: None, checks=True, build=True, full=True)
                # Edited if the fingerprints changed or the agent's tool calls wrote to a test file.
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
    # Look at each tool call; clean the path (backslashes to "/", leading "./" removed) before comparing with `names`.
    for name, args in C.tool_calls(result["messages"]):
        if name in ("write_file", "edit_file") and isinstance(args, dict) and re.sub(r"^(\./)+", "", str(args.get("path", "")).replace("\\", "/")) in names:
            return True
    return False


# ------------------------------------------------------------------ stats and command line
def stats(out, specs_root):
    """Summary numbers for the `stats` command: how many specs, kept builds, pairs, kept fixes, average build length, and why runs were rejected."""
    rows = {n: out.rows(n) for n in ("builds.jsonl", "pairs.jsonl", "fixes.jsonl", "rejected.jsonl")}
    # Count rejections by "kind: short reason" (the text before any " (" detail).
    why = {}
    for r in rows["rejected.jsonl"]:
        k = f"{r.get('kind')}: {str(r.get('why', '')).split(' (')[0]}"
        why[k] = why.get(k, 0) + 1
    steps = [r["steps"] for r in rows["builds.jsonl"]]
    return {"specs": len(load_specs(specs_root)), "builds kept": len(rows["builds.jsonl"]), "pairs": len(rows["pairs.jsonl"]),
            "fixes kept": len(rows["fixes.jsonl"]), "average build steps": round(sum(steps) / len(steps), 1) if steps else 0, "rejected": why}


def main(argv=None):
    """Command-line entry point. `argv` is the argument list (None means use the real command line). Returns the exit code."""
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
    # `stats` and `specs` need no local model, so they are handled before the model client is built.
    specs_root = os.path.join(a.out, "specs")
    if a.command == "stats":
        print(json.dumps(stats(out, specs_root), indent=2))
        return 0
    if a.command == "specs":
        # Imported only when needed (it is a heavy module the other commands do not use).
        import lesson_factory
        print(json.dumps(make_specs(lesson_factory.Teacher(a.teacher), a.n, specs_root, seed=a.seed, workers=a.workers), indent=2))
        return 0
    # `builds` and `fixes` drive the VryxCode loop with the teacher served by llama-server.
    generate = V.LlamaChat(a.teacher, thinking=a.think, max_tokens=8192)
    projects = load_specs(specs_root)
    # Nothing to build or fix from: stop with a message telling the person what to run first.
    if not projects:
        raise SystemExit(f"no specs in {specs_root}: run `specs` first")
    if a.command == "builds":
        print(json.dumps(make_builds(projects, generate, out, a.samples, a.max_turns, a.context, a.workers), indent=2))
    else:
        print(json.dumps(make_fixes(projects, generate, out, a.per, a.max_turns or 40, a.context), indent=2))
    return 0


# Run only when started directly; the return value of main() becomes the program's exit code (0 = success).
if __name__ == "__main__":
    sys.exit(main())
