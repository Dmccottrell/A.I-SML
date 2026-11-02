"""
code_map.py - search a project, and draw its map.

    search(folder, query)    -> [{"path", "line", "text"}]  every line that contains the words (and files whose NAME does), text files only
    project_map(folder)      -> {"files", "languages", "entry", "readme", "outline": [{"path", "kind", "items": [...]}]}  what is where, from the files alone
    explain_prompt(map)      -> the request the model gets for "Explain this project" (read-only: it can look but not change)

No model is used for the map: the outline comes from reading the files (Python with `ast`, JavaScript and others with simple patterns), so it is instant and cannot
be wrong about what is in a file. The model only gets involved to put it in plain words.
"""
# ast reads Python source into a tree (a "syntax tree") without running it; os handles paths and folders;
# re = regular expressions (text patterns).
import ast
import os
import re

# Folders never searched or listed: version history, caches, installed libraries, VryxCode's own data.
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".emvryx", ".venv", "venv", ".worktrees"}
# Limits: most files listed in the map, biggest file (bytes) that is read as text, most search results.
MAX_FILES = 400
MAX_BYTES = 200_000
MAX_HITS = 80
# File ending -> language name shown in the map. Only these endings are read and outlined.
LANGS = {".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".json": "JSON", ".md": "Markdown", ".go": "Go", ".rs": "Rust",
         ".java": "Java", ".c": "C", ".cpp": "C++", ".sh": "Shell", ".sql": "SQL", ".txt": "Text", ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML"}
# File names that usually are where a program starts. Earlier in the list = more likely the main entry point.
ENTRY_NAMES = ("index.html", "main.py", "app.py", "server.py", "manage.py", "main.js", "index.js", "server.js", "app.js", "main.go", "main.rs", "Main.java", "main.c", "main.cpp")


def _walk(folder):
    """Yield (full path, path relative to the folder with "/" separators) for every file, in a stable sorted order.
    Skipped folders and all links are left out (a link could lead outside the project)."""
    for dirpath, dirs, names in os.walk(folder):
        # Editing dirs in place tells os.walk which sub-folders to enter, and sorting makes the order repeatable.
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d)))
        for n in sorted(names):
            full = os.path.join(dirpath, n)
            if not os.path.islink(full):
                yield full, os.path.relpath(full, folder).replace(os.sep, "/")


def _text(full):
    """The file's text, or None if it is not a normal text file (too big, binary, not UTF-8, or unreadable)."""
    try:
        # Read one byte more than the limit so we can tell "too big" from "exactly at the limit".
        with open(full, "rb") as f:
            data = f.read(MAX_BYTES + 1)
    except OSError:
        return None
    # A zero byte in the first 4000 bytes is the usual sign of a binary file (picture, program...).
    if len(data) > MAX_BYTES or b"\0" in data[:4000]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def search(folder, query, limit=MAX_HITS):
    """Find a piece of text (ignoring upper/lower case) in the project. Returns up to `limit` hits, each
    {"path", "line", "text"}. A match on a file NAME has line 0. Needs at least 2 characters to search."""
    q = str(query or "").strip().lower()
    if len(q) < 2 or not os.path.isdir(folder):
        return []
    hits, seen = [], 0
    for full, rel in _walk(folder):
        # Safety stops: look at no more than 2000 files, and stop once enough hits are found.
        seen += 1
        if seen > 2000 or len(hits) >= limit:
            break
        # A file whose NAME contains the query counts as a hit too.
        if q in os.path.basename(rel).lower():
            hits.append({"path": rel, "line": 0, "text": "(file name)"})
        text = _text(full)
        if text is None:
            continue
        # Check each line; enumerate(..., 1) numbers the lines from 1. Long lines are cut to 160 characters.
        for i, line in enumerate(text.splitlines(), 1):
            if q in line.lower():
                hits.append({"path": rel, "line": i, "text": line.strip()[:160]})
                if len(hits) >= limit:
                    break
    return hits[:limit]


# Finds JavaScript/TypeScript definitions, one per line start (re.M = "^" matches at every line start). Three kinds,
# each captured in its own group: "function name(...)", "const/let/var name = (...) =>" or "name = x =>" (arrow
# functions), and "class Name". Optional "export" and "async" words are allowed before them.
JS_DEF = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[\w$]+)\s*=>|^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)", re.M)
# Finds definitions in Go, Rust, Java, C and C++ by their keyword (fn, func, def, class, struct, interface, type) and
# captures the name that follows. Simple and approximate, but fast.
GENERIC_DEF = re.compile(r"^\s*(?:pub\s+)?(?:fn|func|def|class|struct|interface|type)\s+([A-Za-z_]\w*)", re.M)


def _outline(rel, text):
    """A short list of what a file contains (function and class names, page title...), at most 20 items. [] if unknown."""
    ext = os.path.splitext(rel)[1].lower()
    # Python: parse the file into a tree and look at its top level only (no need to run it).
    if ext == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return ["(could not be read: a syntax error)"]
        out = []
        for node in tree.body:
            # A top-level function.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append(node.name + "()")
            # A class: list up to 6 of its method names after it.
            elif isinstance(node, ast.ClassDef):
                methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                out.append(f"class {node.name}" + (f" ({', '.join(methods[:6])}{', ...' if len(methods) > 6 else ''})" if methods else ""))
        return out[:20]
    # JavaScript/TypeScript: JS_DEF has three alternatives, each with its own group; next() takes the one that matched.
    if ext in (".js", ".ts"):
        return [next(g for g in m.groups() if g) for m in JS_DEF.finditer(text)][:20]
    # HTML: the page title, then the script files and style sheets it loads (regex patterns that read the tags).
    if ext in (".html", ".htm"):
        title = re.search(r"<title>(.*?)</title>", text, re.S | re.I)
        scripts = re.findall(r'<script[^>]+src="([^"]+)"', text, re.I)
        sheets = re.findall(r'<link[^>]+href="([^"]+\.css)"', text, re.I)
        return ([f'title: {title.group(1).strip()[:60]}'] if title else []) + [f"loads {s}" for s in scripts + sheets][:8]
    # Other compiled languages: use the simple keyword pattern.
    if ext in (".go", ".rs", ".java", ".c", ".cpp"):
        return [m.group(1) for m in GENERIC_DEF.finditer(text)][:20]
    return []


def project_map(folder):
    """Look through the project and return its map (see the top of the file for the shape of the result)."""
    # files = relative paths, langs = language -> number of files, outline = per-file contents,
    # entry = the likely start file, readme = the start of the README.
    files, langs, outline, entry, readme = [], {}, [], None, ""
    if not os.path.isdir(folder):
        return {"files": 0, "languages": {}, "entry": None, "readme": "", "outline": []}
    for full, rel in _walk(folder):
        if len(files) >= MAX_FILES:
            break
        files.append(rel)
        ext = os.path.splitext(rel)[1].lower()
        # Count files per language.
        if ext in LANGS:
            langs[LANGS[ext]] = langs.get(LANGS[ext], 0) + 1
        # Entry point: a known start file in the top folder or one level down; if several, keep the one that is
        # earliest in ENTRY_NAMES.
        if os.path.basename(rel) in ENTRY_NAMES and rel.count("/") <= 1 and (entry is None or ENTRY_NAMES.index(os.path.basename(rel)) < ENTRY_NAMES.index(os.path.basename(entry))):
            entry = rel
        # Only known file types are read.
        text = _text(full) if ext in LANGS else None
        if text is None:
            continue
        # The first README found gives the project description (first 600 characters).
        if os.path.basename(rel).lower() in ("readme.md", "readme.txt") and not readme:
            readme = text.strip()[:600]
        items = _outline(rel, text)
        if items:
            outline.append({"path": rel, "kind": LANGS.get(ext, ""), "items": items})
    # Languages are listed most-used first (the "-kv[1]" sorts by count, biggest first). At most 60 outlined files.
    return {"files": len(files), "languages": dict(sorted(langs.items(), key=lambda kv: -kv[1])), "entry": entry, "readme": readme, "outline": outline[:60]}


def explain_prompt(m):
    """The request text sent to the model for "Explain this project", built from the map m (see project_map)."""
    # Empty project: nothing to explain.
    if not m["files"]:
        return "Explain this project. It has no files yet: say so in one sentence and suggest a first thing to build."
    # One line per file ("- path: item; item; ..."), for at most 40 files and 10 items each.
    lines = [f"- {o['path']}: " + "; ".join(o["items"][:10]) for o in m["outline"][:40]]
    # e.g. "Python (3), HTML (1)".
    langs = ", ".join(f"{k} ({v})" for k, v in m["languages"].items()) or "no code files"
    return ("Explain this project to someone who did not write it, in plain words and short sentences. Say what it is for, how to run or open it, and what each important file does. "
            "You may read files with list_files and read_file to be sure, but do not change anything and do not run anything. Finish with one sentence on what you would do next.\n\n"
            f"Here is its map, made by reading the files ({m['files']} files; {langs}). Entry point: {m['entry'] or 'not obvious'}.\n"
            + (f"\nFrom the README:\n{m['readme']}\n" if m["readme"] else "") + "\nFiles and what is in them:\n" + "\n".join(lines))
