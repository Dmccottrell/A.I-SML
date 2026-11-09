"""Proves that a change only added or edited comments (and blank lines), so explaining the code can never change what it does.

    python tools/comments_only.py [BASE] [PATH ...]   # compares every changed code file (or just the PATHs) with BASE (default: origin/main)

For each changed file it takes the old version (from git) and the new one, throws away every comment and all spacing, and checks that what is
left is identical. Python is compared as a syntax tree (docstrings removed); Kotlin, JavaScript, CSS, C++ as text with comments stripped; HTML and XML with <!-- -->
comments (and the comments inside <script> / <style>) stripped; YAML, shell, TOML and the like with whole-line # comments stripped.
Exit code 0: only comments changed. Exit code 1: something besides comments changed (the files are listed).
"""
import ast
import os
import re
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)


def git(*args):
    """Run a git command in the project folder and give back its text output ('' when it fails, for example a file that is new)."""
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def strip_docstrings(tree):
    """Remove the string that starts a module, class or function (its docstring): documentation is allowed to change."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]       # keep the body valid if the docstring was all there was
    return tree


def python_shape(text):
    """A Python file reduced to its syntax tree without docstrings: comments and spacing never reach a syntax tree."""
    return ast.dump(strip_docstrings(ast.parse(text)))


REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^")           # a "/" after one of these starts a JavaScript regular expression, not a division
REGEX_WORDS = ("return", "typeof", "case", "in", "of", "void", "delete", "throw", "new", "else", "do")


def c_like_shape(text, regex=False):
    """A Kotlin / JavaScript file with every comment removed and all spacing squeezed, keeping strings exactly as written.

    Walks the text one character at a time, remembering whether it is inside a string, so that a // inside "http://x" is not mistaken for a comment.
    With regex=True (JavaScript) a regular expression such as /[`'"]/g is copied as it is too: a quote or a backtick inside one is not the start of a string.
    """
    out, i, n = [], 0, len(text)
    last = ""                                            # the last real (not blank) character copied, to tell a regular expression from a division
    while i < n:
        two = text[i:i + 2]
        if regex and text[i] == "/" and two not in ("//", "/*") and (not last or last in REGEX_AFTER or re.search(r"(?:^|[^\w$.])(?:" + "|".join(REGEX_WORDS) + r")$", "".join(out)[-12:].rstrip())):
            j, in_class, ok = i + 1, False, False
            while j < n and text[j] != "\n":
                c = text[j]
                if c == "\\":
                    j += 2; continue
                if c == "[":
                    in_class = True
                elif c == "]":
                    in_class = False
                elif c == "/" and not in_class:
                    ok = True; break
                j += 1
            if ok:
                j += 1
                while j < n and text[j].isalpha():       # the flags: g, i, m...
                    j += 1
                out.append(text[i:j]); last = "x"; i = j
                continue
        if text.startswith('"""', i):                       # Kotlin raw string: copy up to the closing quotes
            j = text.find('"""', i + 3)
            j = n if j < 0 else j + 3
            out.append(text[i:j]); i = j
        elif text[i] in "\"'`":                             # an ordinary string or character: copy up to the matching quote
            q, j = text[i], i + 1
            while j < n and text[j] != q:
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1]); i = j + 1
        elif two == "//":                                   # a line comment: skip to the end of the line
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif two == "/*":                                   # a block comment (also KDoc / JSDoc): skip to the closing */
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(text[i]); i += 1
            if not text[i - 1].isspace():
                last = text[i - 1]
    return re.sub(r"\s+", "", "".join(out))


def squeeze(text):
    """All spacing removed, so that only the real characters are compared."""
    return re.sub(r"\s+", "", text)


def xml_shape(text):
    """An XML file without its <!-- --> comments or spacing."""
    return squeeze(re.sub(r"<!--.*?-->", "", text, flags=re.S))


def html_shape(text):
    """An HTML page without <!-- --> comments; the code inside <script> and <style> is compared with its own comments stripped too."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    parts = re.split(r"(<(?:script|style)\b[^>]*>.*?</(?:script|style)>)", text, flags=re.S | re.I)
    # parts alternates: ordinary html, a script/style block, ordinary html... Blocks are compared as code, the rest as squeezed text
    return "|".join(c_like_shape(p, regex=True) if re.match(r"<(?:script|style)\b", p, re.I) else squeeze(p) for p in parts)


def hash_shape(text):
    """A YAML / shell / TOML-like file without whole-line # comments (a first line #! stays: it is code) or blank lines."""
    keep = [ln.rstrip() for ln in text.splitlines() if ln.strip() and (not ln.lstrip().startswith("#") or ln.startswith("#!"))]
    return "\n".join(keep)


def shape(path, text):
    """The comment-free form of a file, or None for kinds of file this check does not understand."""
    if path.endswith(".py"):
        return python_shape(text)
    if path.endswith((".kt", ".kts", ".js", ".css", ".cc", ".cpp", ".h")):
        return c_like_shape(text, regex=path.endswith(".js"))
    if path.endswith((".html", ".htm")):
        return html_shape(text)
    if path.endswith(".xml"):
        return xml_shape(text)
    if path.endswith((".yml", ".yaml", ".sh", ".toml", ".properties", ".pro", ".txt")) or os.path.basename(path) in ("Dockerfile", ".gitignore"):
        return hash_shape(text)
    return None


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
    only = sys.argv[2:]                                     # when paths are given, check just those
    names = only or git("diff", "--name-only", base).splitlines() + git("ls-files", "--others", "--exclude-standard").splitlines()
    changed = [p for p in names if shape(p, "") is not None]
    bad = []
    for path in sorted(set(changed)):
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            continue
        old = git("show", f"{base}:{path}")
        if not old:                                         # a brand new file: nothing to compare with
            continue
        with open(full, encoding="utf-8") as f:
            new = f.read()
        try:
            same = shape(path, old) == shape(path, new)
        except SyntaxError:
            same = False
        if not same:
            bad.append(path)
    if bad:
        print("more than comments changed in:\n  " + "\n  ".join(bad))
        return 1
    print(f"comments only: {len(set(changed))} changed files checked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
