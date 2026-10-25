"""
install_hooks.py - Run once in a copy of this project: from then on `git push` first runs the quick checks (lint and the project's guardrails,
tools/guard_repo.py) and stops the push when one fails. The full tests stay in CI (they take a few minutes).

    python scripts/install_hooks.py
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import stat

HOOK = """#!/bin/sh
# Installed by scripts/install_hooks.py: the quick checks before a push (lint, the project's guardrails)
python tools/lint.py || exit 1
python tools/guard_repo.py || exit 1
"""


def main():
    path = os.path.join(emvryx_paths.ROOT, ".git", "hooks", "pre-push")
    if not os.path.isdir(os.path.dirname(path)):
        print("Not a git copy of the project (no .git/hooks).")
        return 1
    with open(path, "w", newline="\n") as f:
        f.write(HOOK)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print("Installed: git push now runs the lint and the guardrails first.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
