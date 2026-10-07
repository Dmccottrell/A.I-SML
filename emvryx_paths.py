"""
emvryx_paths.py - Makes the code folders importable, so every file can still say `import chat` or `import app_engine`.

WHAT THIS FILE DOES
    The code lives in folders by job (app/, coding/, core/, training/, data_prep/, evaluation/, tools/). Importing this file adds those folders to
    Python's search path, so a script in any folder (or a test) can import any module by its plain name. Scripts start with one line that imports it.
    `script("train.py")` gives the full path of a script by its file name (for programs that start other programs). `ROOT` is the project folder.
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
FOLDERS = ("app", "coding", "core", "training", "data_prep", "evaluation", "tools")

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
for _folder in FOLDERS:
    _path = os.path.join(ROOT, _folder)
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.append(_path)


def script(name):
    """The full path of a script (or .sh file) by its file name."""
    for folder in ("",) + FOLDERS + ("scripts",):
        path = os.path.join(ROOT, folder, name)
        if os.path.exists(path):
            return path
    raise FileNotFoundError(name)
