"""
crash_log.py - admin_crashes: the errors in server.log for Admin > Crashes.

WHAT THIS FILE DOES
    `read(path)` reads the end of server.log (the last 2 MB) and finds each Python traceback in it, with the "request failed: GET /api/..." line
    log_crash writes just before it (the time and the address, never a query string). The same error (the same kind of exception at the same
    place in the code) is counted once, with how many times it happened and when last, newest first.
"""
import hashlib
import os
import re

TAIL_BYTES, MAX_TEXT, MAX_GROUPS = 2 * 1024 * 1024, 6000, 100
REQUEST_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) request failed: (\S+ \S+)")
FRAME_RE = re.compile(r'^\s+File "([^"]+)", line (\d+), in (\S+)')


def _tail(path):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            return f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []


def read(path):
    lines, out, order = _tail(path), {}, []
    i = 0
    while i < len(lines):
        if not lines[i].startswith("Traceback (most recent call last):"):
            i += 1
            continue
        when, request = None, None
        m = REQUEST_RE.match(lines[i - 1]) if i else None
        if m:
            when, request = m.group(1), m.group(2)
        j, frame = i + 1, None
        while j < len(lines) and (lines[j].startswith(" ") or lines[j].startswith("\t")):
            f = FRAME_RE.match(lines[j])
            if f:
                frame = (re.split(r"[\\/]", f.group(1))[-1], int(f.group(2)), f.group(3))     # a Windows path too, wherever the log is read
            j += 1
        error = lines[j].strip() if j < len(lines) else "(the error line is missing)"
        kind = error.split(":", 1)[0]
        where = f"{frame[0]}:{frame[1]} in {frame[2]}" if frame else "unknown place"
        key = hashlib.sha1(f"{kind}|{where}".encode()).hexdigest()[:12]
        text = "\n".join(([lines[i - 1]] if m else []) + lines[i:j + 1])[-MAX_TEXT:]
        g = out.get(key)
        if g is None:
            g = out[key] = {"id": key, "kind": kind, "where": where, "count": 0}
        else:
            order.remove(key)
        g.update(count=g["count"] + 1, error=error[:500], text=text, request=request or g.get("request"), last=when or g.get("last"))
        order.append(key)
        i = j + 1
    return [out[k] for k in reversed(order)][:MAX_GROUPS]


def fix_task(crash):
    """The message a VryxCode session gets when the owner presses Fix this."""
    return ("Emvryx crashed with this error (from server.log" + (f", on {crash['request']}" if crash.get("request") else "") + f", {crash['count']} times):\n\n"
            + crash["text"] + "\n\nFind the cause. First write a test that fails because of it, then make the smallest fix that makes the test pass, "
            "and run the tests (python scripts/run_tests.py).")
