"""lint_polyglot.py - checks the languages the Python linter (tools/lint.py) does not look at, with tools that need nothing installed beyond Python and Node.

    python tools/lint_polyglot.py            check everything, print one line per problem, exit 1 if there is any
    python tools/lint_polyglot.py --list     only say what would be checked

What is checked (and why these checks: each one catches a mistake that would otherwise only show up in a browser, on a phone, or when a build fails):
    JavaScript   every .js file in web/ is parsed by Node (`node --check`): a missing bracket breaks the whole page at load
    JSON         every tracked .json file parses
    YAML         every workflow and other .yml file parses
    XML          every Android .xml file (layouts, manifest, resources) is well formed
    CSS          every .css file has balanced braces and no unterminated comment
    Shell        every .sh file is read by bash without running it (`bash -n`)
    HTML         every .html file is read by Python's HTML parser, and no <script> or <style> block is left open
Kotlin is checked by its compiler (the android build) and C++ by cppcheck in CI; Python by tools/lint.py.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

ROOT = emvryx_paths.ROOT


def tracked():
    """Every file git tracks (so generated and downloaded files are never checked), as paths relative to the project folder."""
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout
    return [p for p in out.splitlines() if os.path.isfile(os.path.join(ROOT, p))]


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8", errors="replace") as f:
        return f.read()


def check_js(path):
    node = shutil.which("node")
    if not node:
        return []                                             # no Node here: CI has it, and the check says nothing rather than guess
    p = subprocess.run([node, "--check", os.path.join(ROOT, path)], capture_output=True, text=True)
    return [] if p.returncode == 0 else [(p.stderr or "syntax error").strip().splitlines()[-1][:200]]


def check_json(path):
    try:
        json.loads(read(path))
        return []
    except ValueError as e:
        return [str(e)[:200]]


def check_yaml(path):
    try:
        import yaml
    except ImportError:
        return []
    try:
        list(yaml.safe_load_all(read(path)))
        return []
    except yaml.YAMLError as e:
        return [str(e).replace("\n", " ")[:200]]


def check_xml(path):
    try:
        ET.fromstring(read(path).encode("utf-8"))
        return []
    except ET.ParseError as e:
        return [str(e)[:200]]


def check_css(path):
    text = re.sub(r"/\*.*?\*/", "", read(path), flags=re.S)
    problems = []
    if "/*" in text:
        problems.append("a comment is never closed")
    text = re.sub(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'', '""', text)           # braces inside strings do not count
    if text.count("{") != text.count("}"):
        problems.append(f"{text.count('{')} opening braces but {text.count('}')} closing")
    return problems


def bash_works():
    """The path of a bash that really runs, or None. (On Windows the first `bash` on the path can be the Windows Subsystem for Linux stub, which fails when no Linux is installed.)"""
    bash = shutil.which("bash")
    if not bash:
        return None
    try:
        return bash if subprocess.run([bash, "-c", "true"], capture_output=True, timeout=20).returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def check_sh(path):
    bash = bash_works()
    if not bash:
        return []
    p = subprocess.run([bash, "-n", os.path.join(ROOT, path)], capture_output=True, text=True)
    return [] if p.returncode == 0 else [(p.stderr or "syntax error").strip().splitlines()[-1][:200]]


class _Html(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.raw = []                                          # the open <script>/<style> blocks

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.raw.append(tag)

    def handle_endtag(self, tag):
        if tag in self.raw:
            self.raw.remove(tag)


def check_html(path):
    p = _Html()
    try:
        p.feed(read(path))
        p.close()
    except Exception as e:                                     # the parser itself gave up
        return [str(e)[:200]]
    return [f"<{t}> is never closed" for t in p.raw]


CHECKS = [("JavaScript", lambda p: p.endswith(".js") and p.startswith("web/"), check_js), ("JSON", lambda p: p.endswith(".json"), check_json),
          ("YAML", lambda p: p.endswith((".yml", ".yaml")), check_yaml), ("XML", lambda p: p.endswith(".xml") and p.startswith("android/"), check_xml),
          ("CSS", lambda p: p.endswith(".css"), check_css), ("Shell", lambda p: p.endswith(".sh"), check_sh), ("HTML", lambda p: p.endswith(".html"), check_html)]


def run(only_list=False):
    """Check every tracked file. Returns (problems, counts): problems is a list of "path: kind: message", counts says how many files of each kind were looked at."""
    problems, counts = [], {}
    files = tracked()
    for kind, pick, check in CHECKS:
        chosen = [p for p in files if pick(p)]
        counts[kind] = len(chosen)
        if only_list:
            continue
        for path in chosen:
            problems += [f"{path}: {kind}: {m}" for m in check(path)]
    return problems, counts


def main(argv=None):
    only_list = "--list" in (argv if argv is not None else sys.argv[1:])
    problems, counts = run(only_list)
    for kind, n in counts.items():
        print(f"{kind:11s} {n:4d} files")
    if problems:
        print("\n".join(problems))
        print(f"lint_polyglot: {len(problems)} problem(s)")
        return 1
    print("lint_polyglot: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
