"""insert_comments.py SPEC - a helper for the comment-writing work (docs/COMMENTING.md): insert comment lines before given line numbers of the ORIGINAL file, then prove only comments changed.
SPEC format (stdin or file): a line "@path" starts a file; then lines "N: comment text" mean: put this comment on its own line before original line N,
matching that line's indentation. Several lines with the same N go in order. Lines starting with "#" in the spec are ignored.
"""
import os, re, subprocess, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
spec = open(sys.argv[1]).read() if len(sys.argv) > 1 else sys.stdin.read()
files, cur = {}, None
for raw in spec.splitlines():
    if raw.startswith("@"):
        cur = raw[1:].strip(); files[cur] = []
    elif cur and re.match(r"^\d+:", raw):
        n, t = raw.split(":", 1); files[cur].append((int(n), t.strip()))
bad = []
for path, items in files.items():
    full = os.path.join(ROOT, path)
    lines = open(full, encoding="utf-8").read().split("\n")
    ext = os.path.splitext(path)[1]
    # for html: which language is each line in (script / style / plain)
    lang = [None] * (len(lines) + 2)
    if ext == ".html":
        mode = None
        for i, l in enumerate(lines, 1):
            low = l.lower()
            if mode is None and re.search(r"<script\b(?![^>]*\bsrc=)[^>]*>", low) and "</script>" not in low: mode = "js"; lang[i] = None; continue
            if mode is None and re.search(r"<style\b[^>]*>", low) and "</style>" not in low: mode = "css"; lang[i] = None; continue
            if mode and re.search(r"</(script|style)>", low): mode = None; continue
            lang[i] = mode
    def fmt(n, text, indent):
        if ext in (".py", ".sh", ".yml", ".yaml"): return f"{indent}# {text}"
        if ext in (".kt", ".js", ".cc", ".cpp", ".h"): return f"{indent}// {text}"
        if ext == ".css": return f"{indent}/* {text} */"
        if ext == ".html":
            m = lang[n]
            return f"{indent}// {text}" if m == "js" else f"{indent}/* {text} */" if m == "css" else f"{indent}<!-- {text} -->"
        raise SystemExit("unknown type " + path)
    by = {}
    for n, t in items: by.setdefault(n, []).append(t)
    out = []
    for i, l in enumerate(lines, 1):
        for t in by.get(i, []):
            indent = re.match(r"\s*", l).group(0)
            out.append(fmt(i, t, indent))
        out.append(l)
    open(full, "w", encoding="utf-8").write("\n".join(out))
    print(f"{path}: +{sum(len(v) for v in by.values())} comment lines")
r = subprocess.run([sys.executable, os.path.join("tools", "comments_only.py"), "HEAD", *files], cwd=ROOT, capture_output=True, text=True)
print(r.stdout.strip() or "(no output)", r.stderr.strip()[:300])
sys.exit(r.returncode)
