"""
comment_coverage.py - shows how much of the code is explained with comments, file by file, so the "explain every line for a new programmer" work can be finished in order.

WHAT THIS FILE DOES
    For every tracked source file (Python, Kotlin, JavaScript, CSS, HTML, shell, YAML, C++) it counts the lines of code and the lines of comments (a comment line, or a line
    inside a Python docstring or a block comment) and gives the share of comment lines. A file whose share is below the target is "not finished". Run it to see what is left,
    biggest gap first; run tools/comments_only.py after changing a file to prove only comments changed.

Usage:
    python tools/comment_coverage.py                 (the summary and the 40 files with the most uncommented code)
    python tools/comment_coverage.py --all           (every unfinished file)
    python tools/comment_coverage.py --target 0.2    (a different target share, default 0.20)
    python tools/comment_coverage.py --kind py       (only one kind: py kt js css html sh yml cc)
    python tools/comment_coverage.py --skip-tests    (leave out the tests/ folder)
"""
import argparse
import ast
import io
import os
import re
import subprocess
import tokenize

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
KINDS = {".py": "py", ".kt": "kt", ".js": "js", ".css": "css", ".html": "html", ".sh": "sh", ".yml": "yml", ".yaml": "yml", ".cc": "cc", ".cpp": "cc", ".h": "cc"}
SKIP_PARTS = ("node_modules/", "/build/", "site/ad-screens/", "web/vendor/", "android/app/src/main/assets/")


def tracked():
    """The tracked files of the project (git knows which ones are ours, so nothing generated is counted)."""
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
    return [p for p in out if os.path.splitext(p)[1] in KINDS and not any(s in p or p.startswith(s.strip("/")) for s in SKIP_PARTS)]


def count_python(text):
    """(code lines, comment lines) of a Python file: # comments and docstrings count as comments."""
    doc_lines = set()
    try:
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) and isinstance(first.value.value, str):
                    doc_lines.update(range(first.lineno, first.end_lineno + 1))
    except SyntaxError:
        pass
    comment_lines = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                comment_lines.add(tok.start[0])
    except (tokenize.TokenError, IndentationError):
        pass
    code = comments = 0
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s:
            continue
        if n in doc_lines or s.startswith("#"):
            comments += 1
        elif n in comment_lines:
            code += 1; comments += 1                      # a line with code and a trailing comment explains itself: counts as both
        else:
            code += 1
    return code, comments


def count_generic(text, kind):
    """(code lines, comment lines) for the other languages, from whole-line comments and block comments (a trailing comment counts as both)."""
    code = comments = 0
    in_block = False
    line_comment = {"kt": "//", "js": "//", "cc": "//", "css": None, "html": None, "sh": "#", "yml": "#"}[kind]
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if in_block:
            comments += 1
            if "*/" in s or "-->" in s:
                in_block = False
            continue
        if s.startswith("/*") or s.startswith("<!--"):
            comments += 1
            in_block = not ("*/" in s or "-->" in s)
            continue
        if line_comment and s.startswith(line_comment):
            comments += 1
            continue
        code += 1
        if (line_comment and re.search(r"\s" + re.escape(line_comment) + r"\s", s)) or "/*" in s or "<!--" in s:
            comments += 1
    return code, comments


def measure(path):
    """(code lines, comment lines) of one file, or (0, 0) when it cannot be read."""
    try:
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return 0, 0
    kind = KINDS[os.path.splitext(path)[1]]
    return count_python(text) if kind == "py" else count_generic(text, kind)


def main():
    ap = argparse.ArgumentParser(description="How much of the code is explained")
    ap.add_argument("--target", type=float, default=0.20, help="the share of comment lines a finished file has (default 0.20)")
    ap.add_argument("--all", action="store_true", help="list every unfinished file")
    ap.add_argument("--kind", choices=sorted(set(KINDS.values())), help="only this kind of file")
    ap.add_argument("--skip-tests", action="store_true", help="leave out the tests/ folder")
    a = ap.parse_args()
    rows = []
    for p in tracked():
        kind = KINDS[os.path.splitext(p)[1]]
        if (a.kind and kind != a.kind) or (a.skip_tests and (p.startswith("tests/") or "/src/test/" in p or "/src/androidTest/" in p)):
            continue
        code, com = measure(p)
        if code:
            rows.append((p, kind, code, com, com / (code + com) if code + com else 1.0))
    total_code = sum(r[2] for r in rows)
    total_com = sum(r[3] for r in rows)
    todo = [r for r in rows if r[4] < a.target]
    gap = lambda r: max(0, int(a.target * (r[2] + r[3])) - r[3])        # about how many comment lines the file is short of the target
    print(f"{len(rows)} files, {total_code:,} lines of code, {total_com:,} comment lines ({total_com / max(1, total_code + total_com):.0%} of all lines)")
    print(f"finished (at least {a.target:.0%} comments): {len(rows) - len(todo)} files; not finished: {len(todo)} files, {sum(r[2] for r in todo):,} lines of code, about {sum(gap(r) for r in todo):,} comment lines to write")
    by_kind = {}
    for r in todo:
        d = by_kind.setdefault(r[1], [0, 0])
        d[0] += 1; d[1] += r[2]
    print("not finished by kind:", ", ".join(f"{k} {v[0]} files / {v[1]:,} lines" for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1][1])))
    print()
    print("the biggest gaps first (file, code lines, comment share):")
    for r in sorted(todo, key=lambda r: -gap(r))[: (len(todo) if a.all else 40)]:
        print(f"  {r[0]:70s} {r[2]:6d}  {r[4]:4.0%}")


if __name__ == "__main__":
    main()
