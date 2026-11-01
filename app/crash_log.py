"""
crash_log.py - admin_crashes: the errors in server.log for Admin > Crashes.

WHAT THIS FILE DOES
    `read(path)` reads the end of server.log (the last 2 MB) and finds each Python traceback in it, with the "request failed: GET /api/..." line
    log_crash writes just before it (the time and the address, never a query string). The same error (the same kind of exception at the same
    place in the code) is counted once, with how many times it happened and when last, newest first.

    Where it fits: the admin routes call read() to fill the Crashes screen, and fix_task() builds the text for the "Fix this" button.
    A "traceback" is the block of text Python prints when a program crashes: it lists the chain of calls ("frames") and ends with the error line.
"""
import hashlib       # makes a short fingerprint (hash) of a piece of text
import os
import re            # regular expressions ("regex"): text patterns

# TAIL_BYTES: how much of the end of the log is read (2 MB). MAX_TEXT: the most characters kept of one traceback. MAX_GROUPS: how many different errors are listed.
TAIL_BYTES, MAX_TEXT, MAX_GROUPS = 2 * 1024 * 1024, 6000, 100
# Matches the line log_crash writes before a traceback, like "2026-10-19 12:34:56 request failed: GET /api/chats".
# Group 1 = the date and time (\d = a digit), group 2 = the method and path (\S+ = a run of non-space characters).
REQUEST_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) request failed: (\S+ \S+)")
# Matches one frame line of a traceback, like '  File "app/x.py", line 42, in my_function'.
# Group 1 = the file path, group 2 = the line number, group 3 = the function name.
FRAME_RE = re.compile(r'^\s+File "([^"]+)", line (\d+), in (\S+)')


def _tail(path):
    """The last TAIL_BYTES of the file at `path` as a list of lines; an empty list if the file cannot be opened."""
    try:
        # "rb" = read raw bytes, so a cut in the middle of a character cannot cause a read error.
        with open(path, "rb") as f:
            # Jump to the end to learn the file size, then back to (size - 2 MB), or the start if the file is smaller.
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            # errors="replace": any broken byte becomes a placeholder character instead of crashing.
            return f.read().decode("utf-8", errors="replace").splitlines()
    # No log file yet (or no permission): there are simply no crashes to show.
    except OSError:
        return []


def read(path):
    """The distinct crashes found in the log at `path`, newest first (at most MAX_GROUPS).

    Each is a dict: id, kind (exception type), where (file:line in function), count, error (the last line), text (the traceback), request, last (time).
    """
    # out: fingerprint -> crash record. order: the fingerprints from oldest to newest occurrence.
    lines, out, order = _tail(path), {}, []
    i = 0
    # Walk down the lines; i is the line being looked at.
    while i < len(lines):
        # Not the start of a traceback: move on to the next line.
        if not lines[i].startswith("Traceback (most recent call last):"):
            i += 1
            continue
        when, request = None, None
        # The line just before the traceback may be the "request failed" line; it gives the time and the request.
        m = REQUEST_RE.match(lines[i - 1]) if i else None
        if m:
            when, request = m.group(1), m.group(2)
        # The traceback's frame lines are indented; read them until a line that is not indented (the error line).
        # `frame` ends up as the LAST frame, i.e. the place where the error actually happened.
        j, frame = i + 1, None
        while j < len(lines) and (lines[j].startswith(" ") or lines[j].startswith("\t")):
            f = FRAME_RE.match(lines[j])
            if f:
                frame = (re.split(r"[\\/]", f.group(1))[-1], int(f.group(2)), f.group(3))     # a Windows path too, wherever the log is read
            j += 1
        error = lines[j].strip() if j < len(lines) else "(the error line is missing)"
        # The exception type is the text before the first colon, e.g. "KeyError" in "KeyError: 'x'".
        kind = error.split(":", 1)[0]
        where = f"{frame[0]}:{frame[1]} in {frame[2]}" if frame else "unknown place"
        # Same kind of error at the same place = same crash. A short fingerprint of that pair is used as its id (not for security).
        key = hashlib.sha1(f"{kind}|{where}".encode()).hexdigest()[:12]
        # The traceback text (with the request line if there was one), keeping only the last MAX_TEXT characters.
        text = "\n".join(([lines[i - 1]] if m else []) + lines[i:j + 1])[-MAX_TEXT:]
        # First time this crash is seen: create its record. Seen before: take it out of `order`, to re-add it at the end (newest).
        g = out.get(key)
        if g is None:
            g = out[key] = {"id": key, "kind": kind, "where": where, "count": 0}
        else:
            order.remove(key)
        # Count one more, and keep the newest details (older request/time are kept if this one has none).
        g.update(count=g["count"] + 1, error=error[:500], text=text, request=request or g.get("request"), last=when or g.get("last"))
        order.append(key)
        # Continue after the error line.
        i = j + 1
    # Newest first, limited to MAX_GROUPS.
    return [out[k] for k in reversed(order)][:MAX_GROUPS]


def fix_task(crash):
    """The message a VryxCode session gets when the owner presses Fix this. `crash` is one record from read()."""
    # The text follows the project's bug rules: first a failing test, then the smallest fix. The quoted pieces side by side are joined.
    return ("Emvryx crashed with this error (from server.log" + (f", on {crash['request']}" if crash.get("request") else "") + f", {crash['count']} times):\n\n"
            + crash["text"] + "\n\nFind the cause. First write a test that fails because of it, then make the smallest fix that makes the test pass, "
            "and run the tests (python scripts/run_tests.py).")
