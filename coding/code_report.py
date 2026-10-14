"""
code_report.py - The verification report at the end of a VryxCode turn: what it did, how it was checked, and what you should look at.

Built from the session's own events (plain code, no model): every step, the result that came back for it, and the end. Nothing is guessed:
"Verified" means the project's tests ran and passed AFTER the last change; "Checked" means changes were syntax-checked but no tests passed since;
"Not verified" means neither. The report also lists the files touched (lines added and removed as shown in each edit), commands that ran and failed,
errors the model hit, and a short "look at" list.
"""
import re

TEST_RX = re.compile(r"unittest|pytest")
EXIT_RX = re.compile(r"^exit code (\d+)")
WRITE_RX = re.compile(r"^write (\S+) \((\d+) lines\)")
EDIT_RX = re.compile(r"^edit (\S+)")


def _turn_events(events):
    """The events of the latest turn: from the last start/user event to the end."""
    start = 0
    for i, e in enumerate(events):
        if e.get("kind") in ("start", "user"):
            start = i
    return events[start:]


def _count(lines, mark):
    return sum(1 for l in lines if l.startswith(mark))


def _test_line(text):
    """A short human line from a test run's output."""
    m = re.search(r"Ran (\d+) tests?", text)
    ok = bool(re.search(r"^OK\b", text, re.M))
    if m:
        return f"{m.group(1)} tests, " + ("all passed" if ok else "some failed")
    m = re.search(r"(\d+) passed(?:, (\d+) failed)?", text)
    if m:
        return f"{m.group(1)} passed" + (f", {m.group(2)} failed" if m.group(2) else "")
    return "passed" if EXIT_RX.match(text) and EXIT_RX.match(text).group(1) == "0" else "failed"


def build_report(events, end=None):
    """A dict for the page, or None when the turn did no work (a plain answer needs no report). `end` is the turn's end (finished or not) when it is not in `events` yet."""
    ev = _turn_events(events)
    steps = []                                         # [{tool, preview, result}] in order; a result belongs to the step before it
    for e in ev:
        k = e.get("kind")
        if k == "step" and e.get("tool") not in (None, "finish"):
            steps.append({"tool": e["tool"], "preview": str(e.get("preview", "")), "result": ""})
        elif k == "result" and steps and not steps[-1]["result"]:
            steps[-1]["result"] = str(e.get("text", ""))
        elif k == "end":
            end = e
    if not steps:
        return None

    files, other_runs, test_runs, problems = {}, [], [], []
    last_edit = last_pass = -1
    page = None                                        # the last browser check of the page: (step index, it loaded with no errors)
    for i, s in enumerate(steps):
        tool, prev, res = s["tool"], s["preview"], s["result"]
        if res.startswith("error:") or res.startswith("refused"):
            problems.append(f"{tool}: {res.splitlines()[0][:140]}")
        if tool in ("write_file", "edit_file"):
            m = WRITE_RX.match(prev) or EDIT_RX.match(prev)
            if not m:
                continue
            path = m.group(1)
            f = files.setdefault(path, {"path": path, "created": False, "edits": 0, "added": 0, "removed": 0, "checked": False})
            lines = prev.splitlines()[1:]
            if tool == "write_file":
                f["created"] = f["created"] or "created" in res.lower() or not f["edits"]
                f["added"] += int(m.group(2)) if WRITE_RX.match(prev) else 0
            else:
                f["added"] += _count([l.strip() for l in lines], "+")
                f["removed"] += _count([l.strip() for l in lines], "-")
            f["edits"] += 1
            f["checked"] = f["checked"] or "checked" in res
            if not res.startswith("error:") and not res.startswith("refused"):
                last_edit = i
        elif tool == "check_page":
            page = (i, "no errors found" in res)
        elif tool == "run":
            cmd = re.sub(r"^run\s*", "", prev)
            m_cmd = re.search(r'"command"\s*:\s*"([^"]*)', cmd)
            command = m_cmd.group(1) if m_cmd else cmd[:80]
            code = EXIT_RX.match(res)
            passed = bool(code and code.group(1) == "0")
            if TEST_RX.search(command):
                test_runs.append({"command": command[:80], "passed": passed, "line": _test_line(res)})
                if passed:
                    last_pass = i
            elif code and not passed:
                other_runs.append({"command": command[:80], "exit": int(code.group(1))})

    file_list = sorted(files.values(), key=lambda f: f["path"])
    verified = bool(test_runs) and last_pass > last_edit and last_pass >= 0 and test_runs[-1]["passed"]
    checked = any(f["checked"] for f in file_list)
    page_ok = bool(page and page[0] > last_edit and page[1])
    if verified:
        verdict, label = "verified", "Verified: the tests passed after the last change"
    elif page_ok:
        verified, verdict, label = True, "verified", "Verified: the page was opened in a browser after the last change and showed no errors"
    elif file_list and checked:
        verdict, label = "checked", "Checked: changes passed the syntax check, but no passing test run came after them"
    elif file_list:
        verdict, label = "not_verified", "Not verified: nothing was run or checked after the changes"
    else:
        verdict, label = "no_changes", "No files were changed"

    look = []
    if test_runs and not test_runs[-1]["passed"]:
        look.append("The last test run failed. Read its output before trusting the change.")
    if page and page[0] > last_edit and not page[1]:
        look.append("The page check after the last change still found problems: open Preview to see them.")
    if file_list and not test_runs and not page_ok:
        look.append("No tests were run. Ask it to add or run tests, or try the result yourself.")
    elif file_list and test_runs and not verified and test_runs[-1]["passed"]:
        look.append("Code changed after the last passing test run. Ask it to run the tests again.")
    if other_runs:
        look.append(f"{len(other_runs)} command(s) failed along the way (for example: {other_runs[0]['command']}).")
    if problems:
        look.append(f"It hit {len(problems)} error(s) or refusals while working; it may have worked around them.")
    if end and not end.get("finished"):
        look.append("It did not say it was finished: check what is missing.")
    if any(re.search(r"\.(html?|css|js)$", f["path"]) for f in file_list) and not page_ok:
        look.append("A web page was changed: open Preview and try it.")
    return {"verdict": verdict, "label": label, "steps": len(steps), "files": file_list, "tests": test_runs, "failed_commands": other_runs,
            "problems": problems[:5], "look_at": look[:5], "finished": bool(end and end.get("finished"))}
