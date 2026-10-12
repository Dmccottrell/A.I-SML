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
