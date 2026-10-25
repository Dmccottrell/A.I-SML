"""
code_review.py - Code review mode for VryxCode: turn a change into a review request the model can answer, worst problems first.

Two sources of a change, both read-only:
  * a session's changes: the project as it was before the session (a saved Rewind snapshot) against the files now, as a plain unified diff;
  * a GitHub pull request: its diff, fetched with the person's connected token (GET only; nothing is posted back).
The page sends the prompt in Plan-first mode, where VryxCode may only look (writing, editing, running and git are refused), so a review can never change anything.
"""
import difflib
import io
import re
import zipfile

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".emvryx"}
MAX_FILE_BYTES = 200_000
DEFAULT_LIMIT = 20_000                      # characters of diff sent to the model (its memory is small); the rest is listed by name
PR_RX = re.compile(r"(?:https?://github\.com/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(?:/pull/|#)(\d+)")


def parse_pr_ref(text):
    """'https://github.com/o/r/pull/12', 'o/r/pull/12' or 'o/r#12' -> (owner, repo, number), or None."""
    m = PR_RX.search(str(text or "").strip())
    return (m.group(1), m.group(2), int(m.group(3))) if m else None


def _text_of(data):
    if b"\0" in data[:4000] or len(data) > MAX_FILE_BYTES:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def snapshot_files(zip_bytes):
    """{path: text} for the text files in a Rewind snapshot."""
    out = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for info in z.infolist():
            if info.is_dir() or any(part in SKIP_DIRS for part in info.filename.split("/")):
                continue
            text = _text_of(z.read(info))
            if text is not None:
                out[info.filename] = text
    return out


def diff_files(before, after, limit=DEFAULT_LIMIT):
    """(unified diff text, [changed paths], how many characters were left out). `before` and `after` are {path: text}."""
    paths = sorted(set(before) | set(after))
    parts, changed, used, cut = [], [], 0, 0
    for p in paths:
        a, b = before.get(p), after.get(p)
        if a == b:
            continue
        changed.append(p)
        d = "".join(difflib.unified_diff((a or "").splitlines(True), (b or "").splitlines(True),
                                         fromfile="/dev/null" if a is None else "a/" + p, tofile="/dev/null" if b is None else "b/" + p, n=3))
        if used + len(d) > limit:
            cut += len(d)
            continue
        parts.append(d if d.endswith("\n") else d + "\n")
        used += len(d)
    return "".join(parts), changed, cut


RULES = """You are reviewing a code change. Read it carefully and look for real problems. You may only read: do not change any file and do not run anything.

List the problems WORST FIRST. For each one write:
- the severity: BUG (it will fail or give wrong results), RISK (it could break or be unsafe in some cases) or NIT (style or small cleanup)
- the file and line or function
- what is wrong, in one or two plain sentences
- how to fix it, in one line

Rules: only report what you can point to in the change; do not invent problems to look thorough; if you find nothing serious, say "I found no serious problems" and then list any small nits. Check for: wrong logic, missing error handling, security problems (secrets, injection, unsafe file or network use), tests that are missing or no longer match, and anything the change breaks elsewhere. Finish with one sentence: would you merge this as it is?"""


def review_prompt(diff, changed, cut=0, source="these changes"):
    names = ", ".join(changed[:30]) + (f" and {len(changed) - 30} more" if len(changed) > 30 else "")
    note = f"\n\n(The diff was too long: {cut:,} characters of it were left out. Say which files you could not see.)" if cut else ""
    if not diff.strip():
        return f"Review {source}. There are no changes to look at yet: say so in one sentence."
    return f"{RULES}\n\nReview {source}. Files changed: {names}.{note}\n\n```diff\n{diff}\n```"


# vryxcode_guardrails: a review that can end. A reviewer asked to "review this" thinks its job is to find fault, so it is given the request as a checklist,
# three severities, and told that approving is the best answer when the change does what was asked. Only CRITICAL and MAJOR count; NITPICKs are listed
# and never worked on by themselves. Every CRITICAL or MAJOR must say which test would fail because of it (the fix starts by writing that test).
RULES_STRICT = """You are reviewing a code change against the request it was made for. You may only read: do not change any file and do not run anything.

Judge it against this checklist only:
- it does what the request asked (each part of it)
- it does not crash or lose data on ordinary input
- it has no security problem (secrets in code, injection, unsafe file or network use)
- it does not break something that worked before

Classify every problem you can point to in the change:
- CRITICAL: a crash, a security hole or lost data
- MAJOR: part of the request does not work
- NITPICK: naming, style, small cleanups, micro-speedups (these never block)
For CRITICAL and MAJOR also name the test that would fail because of it (what it does, what it expects). If you cannot describe such a test, it is
not a CRITICAL or MAJOR problem. Do not invent problems or edge cases to look thorough: approving is the best outcome when the checklist is met.

Write your findings in plain words, worst first, then end with exactly one JSON block:
```json
{"status": "APPROVED", "defects": []}
```
or, when something CRITICAL or MAJOR is wrong:
```json
{"status": "CHANGES_NEEDED", "defects": [{"severity": "MAJOR", "file": "app.py", "line": 12, "problem": "...", "fix": "...", "test": "..."}]}
```
NITPICK items may be listed in "defects" too; with only NITPICKs the status is still APPROVED."""

FIX_GATE = """Fix only these problems from the review, one at a time. For each one, first write a small test that shows the problem and run it:
if the test passes on the first run, the problem is not real, so drop it and say so; if it fails, fix the code until it passes, with the other tests
still passing. Do not change or delete the existing tests. Leave NITPICK items alone. Problems:
{items}"""


def strict(prompt, task=""):
    """The review request with the checklist rules instead of the open ones, and the request the change was made for (the reviewer sees only the
    request, the change and its files: never the conversation that produced it)."""
    body = prompt.replace(RULES, RULES_STRICT) if RULES in prompt else RULES_STRICT + "\n\n" + prompt
    return body + (f"\n\nThe request this change was made for:\n{str(task)[:2000]}" if task else "")


def verdict(text):
    """The JSON block at the end of a strict review -> {"status", "defects", "blocking"} (blocking = CRITICAL and MAJOR only), or None."""
    import json
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", str(text or ""), re.S)
    for b in reversed(blocks):
        try:
            v = json.loads(b)
        except ValueError:
            continue
        if not isinstance(v, dict) or "status" not in v:
            continue
        defects = [d for d in v.get("defects") or [] if isinstance(d, dict)]
        blocking = [d for d in defects if str(d.get("severity", "")).upper() in ("CRITICAL", "MAJOR")]
        status = "CHANGES_NEEDED" if blocking else "APPROVED"            # the router decides from the severities, not from the word the reviewer chose
        return {"status": status, "defects": defects, "blocking": blocking}
    return None


def fix_request(blocking):
    """The message that sends the CRITICAL and MAJOR problems back to be fixed, test first (FIX_GATE)."""
    items = "\n".join(f"- {str(d.get('severity', '')).upper()} in {d.get('file', '?')}"
                       + (f" line {d.get('line')}" if d.get("line") else "") + f": {d.get('problem', '')}"
                       + (f" (test: {d.get('test')})" if d.get("test") else "") for d in blocking)
    return FIX_GATE.format(items=items)
