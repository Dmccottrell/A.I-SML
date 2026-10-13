"""
lint.py - Finds real mistakes in the code (an undefined name, an unused import or variable) with pyflakes. Exits 1 if it finds anything new.

    python tools/lint.py

`import emvryx_paths` appears at the top of many files only for its side effect (it makes the code folders importable), so those are ignored.
KNOWN lists the few older findings that were looked at and left on purpose; anything else fails, so the list only ever shrinks.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import re
import subprocess

KNOWN = (
    "app/live_data.py:'web_search' imported but unused",
    "app/app_engine.py:local variable 'started' is assigned to but never used",
    "app_server.py:local variable 'migrated' is assigned to but never used",
    "tools/generate.py:redefinition of unused 'web_notes'",
    "training/finetune_open.py:'bitsandbytes' imported but unused",
    "data_prep/format_lessons_3x.py:f-string is missing placeholders",
    "coding/vryxcode.py:redefinition of unused 'emvryx_paths'",
)


def files():
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=emvryx_paths.ROOT, capture_output=True, text=True).stdout.split()
    return [f for f in out if not f.startswith("tests/")]


def main():
    p = subprocess.run([sys.executable, "-m", "pyflakes", *files()], cwd=emvryx_paths.ROOT, capture_output=True, text=True)
    bad = []
    for line in (p.stdout or "").splitlines():
        m = re.match(r"(.+?):\d+:\d+:? (.*)", line)
        if not m:
            bad.append(line)
            continue
        path, msg = m.group(1), m.group(2)
        if "emvryx_paths" in msg and "imported but unused" in msg:
            continue
        if any(k.split(":", 1)[0] == path and k.split(":", 1)[1] in msg for k in KNOWN):
            continue
        bad.append(line)
    for b in bad:
        print(b)
    print(f"lint: {len(bad)} new finding(s)" if bad else "lint: clean")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
