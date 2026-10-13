"""
code_map.py - search a project, and draw its map.

    search(folder, query)    -> [{"path", "line", "text"}]  every line that contains the words (and files whose NAME does), text files only
    project_map(folder)      -> {"files", "languages", "entry", "readme", "outline": [{"path", "kind", "items": [...]}]}  what is where, from the files alone
    explain_prompt(map)      -> the request the model gets for "Explain this project" (read-only: it can look but not change)

No model is used for the map: the outline comes from reading the files (Python with `ast`, JavaScript and others with simple patterns), so it is instant and cannot
be wrong about what is in a file. The model only gets involved to put it in plain words.
"""
import ast
import os
import re

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".emvryx", ".venv", "venv", ".worktrees"}
MAX_FILES = 400
MAX_BYTES = 200_000
MAX_HITS = 80
LANGS = {".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".json": "JSON", ".md": "Markdown", ".go": "Go", ".rs": "Rust",
         ".java": "Java", ".c": "C", ".cpp": "C++", ".sh": "Shell", ".sql": "SQL", ".txt": "Text", ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML"}
ENTRY_NAMES = ("index.html", "main.py", "app.py", "server.py", "manage.py", "main.js", "index.js", "server.js", "app.js", "main.go", "main.rs", "Main.java", "main.c", "main.cpp")


def _walk(folder):
    for dirpath, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d)))
        for n in sorted(names):
            full = os.path.join(dirpath, n)
            if not os.path.islink(full):
                yield full, os.path.relpath(full, folder).replace(os.sep, "/")


def _text(full):
    try:
        with open(full, "rb") as f:
            data = f.read(MAX_BYTES + 1)
    except OSError:
        return None
    if len(data) > MAX_BYTES or b"\0" in data[:4000]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def search(folder, query, limit=MAX_HITS):
    q = str(query or "").strip().lower()
    if len(q) < 2 or not os.path.isdir(folder):
        return []
    hits, seen = [], 0
    for full, rel in _walk(folder):
        seen += 1
        if seen > 2000 or len(hits) >= limit:
            break
        if q in os.path.basename(rel).lower():
            hits.append({"path": rel, "line": 0, "text": "(file name)"})
        text = _text(full)
        if text is None:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if q in line.lower():
                hits.append({"path": rel, "line": i, "text": line.strip()[:160]})
                if len(hits) >= limit:
                    break
    return hits[:limit]


JS_DEF = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[\w$]+)\s*=>|^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)", re.M)
GENERIC_DEF = re.compile(r"^\s*(?:pub\s+)?(?:fn|func|def|class|struct|interface|type)\s+([A-Za-z_]\w*)", re.M)


def _outline(rel, text):
    ext = os.path.splitext(rel)[1].lower()
    if ext == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return ["(could not be read: a syntax error)"]
        out = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append(node.name + "()")
            elif isinstance(node, ast.ClassDef):
                methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                out.append(f"class {node.name}" + (f" ({', '.join(methods[:6])}{', ...' if len(methods) > 6 else ''})" if methods else ""))
        return out[:20]
    if ext in (".js", ".ts"):
        return [next(g for g in m.groups() if g) for m in JS_DEF.finditer(text)][:20]
    if ext in (".html", ".htm"):
        title = re.search(r"<title>(.*?)</title>", text, re.S | re.I)
        scripts = re.findall(r'<script[^>]+src="([^"]+)"', text, re.I)
        sheets = re.findall(r'<link[^>]+href="([^"]+\.css)"', text, re.I)
        return ([f'title: {title.group(1).strip()[:60]}'] if title else []) + [f"loads {s}" for s in scripts + sheets][:8]
    if ext in (".go", ".rs", ".java", ".c", ".cpp"):
        return [m.group(1) for m in GENERIC_DEF.finditer(text)][:20]
    return []


def project_map(folder):
    files, langs, outline, entry, readme = [], {}, [], None, ""
    if not os.path.isdir(folder):
        return {"files": 0, "languages": {}, "entry": None, "readme": "", "outline": []}
    for full, rel in _walk(folder):
        if len(files) >= MAX_FILES:
            break
        files.append(rel)
        ext = os.path.splitext(rel)[1].lower()
        if ext in LANGS:
            langs[LANGS[ext]] = langs.get(LANGS[ext], 0) + 1
        if os.path.basename(rel) in ENTRY_NAMES and rel.count("/") <= 1 and (entry is None or ENTRY_NAMES.index(os.path.basename(rel)) < ENTRY_NAMES.index(os.path.basename(entry))):
            entry = rel
        text = _text(full) if ext in LANGS else None
        if text is None:
            continue
        if os.path.basename(rel).lower() in ("readme.md", "readme.txt") and not readme:
            readme = text.strip()[:600]
        items = _outline(rel, text)
        if items:
            outline.append({"path": rel, "kind": LANGS.get(ext, ""), "items": items})
    return {"files": len(files), "languages": dict(sorted(langs.items(), key=lambda kv: -kv[1])), "entry": entry, "readme": readme, "outline": outline[:60]}


def explain_prompt(m):
    if not m["files"]:
        return "Explain this project. It has no files yet: say so in one sentence and suggest a first thing to build."
    lines = [f"- {o['path']}: " + "; ".join(o["items"][:10]) for o in m["outline"][:40]]
    langs = ", ".join(f"{k} ({v})" for k, v in m["languages"].items()) or "no code files"
    return ("Explain this project to someone who did not write it, in plain words and short sentences. Say what it is for, how to run or open it, and what each important file does. "
            "You may read files with list_files and read_file to be sure, but do not change anything and do not run anything. Finish with one sentence on what you would do next.\n\n"
            f"Here is its map, made by reading the files ({m['files']} files; {langs}). Entry point: {m['entry'] or 'not obvious'}.\n"
            + (f"\nFrom the README:\n{m['readme']}\n" if m["readme"] else "") + "\nFiles and what is in them:\n" + "\n".join(lines))
