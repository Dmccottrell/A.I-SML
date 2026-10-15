"""
factory_checks.py - The lesson factory's checks: things about an answer that can be PROVED, not just judged (docs/LESSONS_4.md).

WHAT THIS FILE DOES
    check(question, answer) -> {"ok": bool, "problems": [...], "checked": [...]}:
      style   the Emvryx hard rules (style_check.py): never another AI's name, no "as an AI language model", no "trained from scratch", no stray tags
      maths   when the question carries its known answer ("answer"), the last number in the reply must match it
      code    every code block in the reply must at least parse (Python here; other languages through VryxCode's checks when that tool is installed);
              when the question carries tests ("tests": Python assert lines or test code), the Python code is RUN with them in a temporary folder,
              with a time limit, and must pass
    "checked" lists what was actually proved (a lesson whose code ran and passed its tests is worth more than one that only parsed).
    Running code: a separate Python process (python -I, no site packages from the project), in an empty temporary folder, killed after a few seconds.
    The teacher is a local open model, but run the factory inside the VryxCode sandbox (Docker) if the questions come from anywhere you do not trust.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import ast
import re
import subprocess
import tempfile

import style_check

CODE_BLOCK = re.compile(r"```([A-Za-z0-9_+#.-]*)[^\n]*\n(.*?)```", re.S)
NUMBER = re.compile(r"-?\$?\d[\d,]*(?:\.\d+)?")
EXT = {"python": ".py", "py": ".py", "javascript": ".js", "js": ".js", "json": ".json", "html": ".html", "java": ".java", "c": ".c", "cpp": ".cpp",
       "c++": ".cpp", "go": ".go", "ruby": ".rb", "php": ".php"}
RUN_SECONDS = 10


def code_blocks(text):
    """[(language, code)] from fenced code blocks; an unlabelled block that parses as Python counts as Python."""
    out = []
    for lang, code in CODE_BLOCK.findall(text or ""):
        lang = lang.lower().strip()
        if not lang:
            try:
                ast.parse(code)
                lang = "python"
            except SyntaxError:
                lang = "text"
        out.append((lang, code))
    return out


def last_number(text):
    found = NUMBER.findall(re.sub(r"```.*?```", " ", text or "", flags=re.S))
    if not found:
        return None
    try:
        return float(found[-1].replace("$", "").replace(",", ""))
    except ValueError:
        return None


def _numbers(text):
    out = []
    for n in NUMBER.findall(text or ""):
        try:
            out.append(float(n.replace("$", "").replace(",", "")))
        except ValueError:
            pass
    return out


def answer_numbers(text):
    """The numbers an answer STATES as its result: the first number of its opening sentence (Emvryx answers first), numbers in bold or after
    "answer:", and the last number (for answers that work it out step by step). Numbers in the middle of the working do not count."""
    plain = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    first = re.split(r"(?<=[.!?])\s|\n", plain.strip(), maxsplit=1)[0] if plain.strip() else ""
    picks = _numbers(first)[:1] + _numbers(" ".join(re.findall(r"\*\*(.+?)\*\*", plain)))
    picks += _numbers(" ".join(re.findall(r"(?i)answer(?: is)?\s*[:=]?\s*([^\n]{0,40})", plain)))[:1]
    last = last_number(plain)
    return picks + ([last] if last is not None else [])


def check_maths(question, answer):
    """None when there is nothing to check, else (ok, problem)."""
    if question.get("answer") in (None, ""):
        return None
    try:
        want = float(str(question["answer"]).replace(",", "").replace("$", ""))
    except ValueError:
        want = None
    if want is None:                                                   # a non-numeric known answer: it must appear in the reply
        ok = str(question["answer"]).strip().lower() in (answer or "").lower()
        return ok, "" if ok else f"does not give the known answer ({question['answer']})"
    tol = max(float(question.get("tol", 0) or 0), 1e-9 * max(1.0, abs(want)))
    stated = answer_numbers(answer)
    ok = any(abs(x - want) <= tol for x in stated)
    return ok, "" if ok else f"the answer it gives is {stated[-1] if stated else 'missing'}, the right answer is {question['answer']}"


def run_python(code, tests="", seconds=RUN_SECONDS):
    """(ok, output) after running the code and then the tests in a fresh, isolated Python process."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "lesson_check.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(code.rstrip() + "\n\n" + (tests or "").strip() + "\n")
        try:
            r = subprocess.run([sys.executable, "-I", path], cwd=d, capture_output=True, text=True, timeout=seconds, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return False, f"did not finish within {seconds} seconds"
    out = (r.stderr or r.stdout or "").strip().splitlines()
    return r.returncode == 0, (out[-1] if out else "")[:300]


def check_code(question, answer):
    """None when there is no code, else (ok, problems, checked)."""
    blocks = code_blocks(answer)
    tests = question.get("tests")
    if isinstance(tests, list):
        tests = "\n".join(tests)
    if not blocks:
        return (False, ["the question has tests but the answer has no code"], []) if tests else None
    problems, checked = [], []
    python = [c for lang, c in blocks if lang in ("python", "py")]
    for lang, code in blocks:
        if lang in ("python", "py"):
            try:
                ast.parse(code)
            except SyntaxError as e:
                problems.append(f"Python code does not parse (line {e.lineno}: {e.msg})")
        elif lang in EXT:
            try:
                import harness                                             # VryxCode's syntax checks (node, javac, gcc... when installed)
                problems += [p.replace("lesson" + EXT[lang], "the code") for p in harness.check_text("lesson" + EXT[lang], code)]
            except ImportError:
                pass
    if not problems:
        checked.append("code parses")
    if tests and python and not problems:
        ok, out = run_python("\n\n".join(python), tests)
        if ok:
            checked.append("code passed its tests")
        else:
            problems.append("the code failed its tests: " + out)
    return not problems, problems, checked


def check(question, answer, thinking=False):
    """Everything that can be proved about one answer."""
    problems, checked = [], []
    row = {"messages": [{"role": "user", "content": question.get("question", "")}, {"role": "assistant", "content": answer or ""}],
           "kind": "thinking" if thinking else question.get("area", "")}
    hard = [rid for rid, sev in style_check.check_lesson(row) if sev == "hard"]
    if hard:
        problems += [style_check.describe(r) for r in hard]
    else:
        checked.append("voice rules")
    if not (answer or "").strip():
        problems.append("the answer is empty")
    m = check_maths(question, answer)
    if m is not None:
        (checked.append("answer matches the known answer") if m[0] else problems.append(m[1]))
    c = check_code(question, answer)
    if c is not None:
        problems += c[1]
        checked += c[2]
    return {"ok": not problems, "problems": problems, "checked": checked}
