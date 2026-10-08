"""
languages.py - Which programming language fits a task, and what this machine can actually run.

WHAT THIS FILE DOES
    VryxCode used to rely on its instructions alone to pick a language. This adds a small, checkable layer in front of the model:

      * `named(task)`        the languages the person asked for ("in Go", "a Rust program", "with Ruby");
      * `project_language()` the language an existing project already uses (so a Go project is not "improved" into Python);
      * `tools_here(...)`    which language tools can really run on THIS computer, in the Docker sandbox, or are unknown (cloud machine);
      * `recommend(...)`     for a task that names no language: the best fit among what can run, with a plain reason and the other options;
      * `note_for(...)`      the short note given to the model before it plans, and what the page shows ("Suggested: Go, because...").

    The rules are plain keyword rules, not a model: they are predictable and tested. The model still makes the final call and the person can always say
    "use Python instead".
"""
import os
import re
import shutil

# id -> name, file endings, the programs that must exist to RUN it (all of them), how it is run, and whether it is a "can't run here" language
LANGS = {
    "python": {"name": "Python", "ext": (".py",), "needs": ("python3",), "run": "python main.py", "aliases": r"python|py3?"},
    "javascript": {"name": "JavaScript", "ext": (".js", ".mjs"), "needs": ("node",), "run": "node main.js", "aliases": r"javascript|js|node(?:\.?js)?"},
    "typescript": {"name": "TypeScript", "ext": (".ts", ".tsx"), "needs": ("tsc", "node"), "run": "tsc, then node", "aliases": r"typescript|ts"},
    "go": {"name": "Go", "ext": (".go",), "needs": ("go",), "run": "go run main.go", "aliases": r"go|golang"},
    "java": {"name": "Java", "ext": (".java",), "needs": ("javac", "java"), "run": "javac Main.java, then java Main", "aliases": r"java"},
    "c": {"name": "C", "ext": (".c",), "needs": ("gcc",), "run": "gcc -o main main.c", "aliases": r"c"},
    "cpp": {"name": "C++", "ext": (".cpp", ".cc", ".cxx"), "needs": ("g++",), "run": "g++ -o main main.cpp", "aliases": r"c\+\+|cpp"},
    "rust": {"name": "Rust", "ext": (".rs",), "needs": ("rustc",), "run": "rustc main.rs", "aliases": r"rust"},
    "php": {"name": "PHP", "ext": (".php",), "needs": ("php",), "run": "php main.php", "aliases": r"php"},
    "ruby": {"name": "Ruby", "ext": (".rb",), "needs": ("ruby",), "run": "ruby main.rb", "aliases": r"ruby"},
    "sql": {"name": "SQL (SQLite)", "ext": (".sql",), "needs": ("sqlite3",), "run": "sqlite3 db.sqlite < query.sql", "aliases": r"sql|sqlite"},
    "html": {"name": "HTML, CSS and JavaScript", "ext": (".html", ".css"), "needs": (), "run": "open index.html (the Preview tab)", "aliases": r"html|css"},
    "csharp": {"name": "C#", "ext": (".cs",), "needs": ("dotnet",), "run": "dotnet run", "aliases": r"c#|csharp|c sharp"},
    "swift": {"name": "Swift", "ext": (".swift",), "needs": ("swift",), "run": "swift main.swift", "aliases": r"swift"},
    "kotlin": {"name": "Kotlin", "ext": (".kt",), "needs": ("kotlinc",), "run": "kotlinc main.kt", "aliases": r"kotlin"},
}
# a Python-like name for "python" on a machine where only `python` exists (Windows)
EXTRA_NAMES = {"python3": ("python3", "python")}

# what the Docker sandbox image has (docker/code-sandbox/Dockerfile)
SANDBOX_TOOLS = {"python3", "node", "gcc", "g++", "sqlite3"}

# Words that name a language by themselves, and those that only count with "in/using/with/written in" in front (they are also ordinary words or letters).
PLAIN = ("python", "javascript", "typescript", "golang", "rust", "php", "ruby", "swift", "kotlin", "csharp", "c#", "c++", "cpp", "node.js", "nodejs", "html", "sqlite")
NEEDS_CUE = ("go", "c", "java", "js", "ts", "sql", "css", "node", "py")
CUE = r"(?:in|using|with|via|use|written in|rewrite it in|as a|as an)"


def _rx(alias):
    return re.compile(r"(?<![\w+#])(?:%s)(?![\w+#])" % alias, re.I)


def named(task):
    """The languages a message asks for, in the order they appear: ["go"], ["python", "sql"]... An empty list means none was named."""
    text = str(task or "")
    found = []
    for lid, info in LANGS.items():
        for alias in info["aliases"].split("|"):
            alias = alias.strip()
            if alias in PLAIN or alias.replace("\\", "") in PLAIN:
                m = _rx(alias).search(text)
            elif alias in NEEDS_CUE or alias.replace("\\", "") in NEEDS_CUE:
                alias = "(?-i:C)" if alias == "c" else alias                     # the letter C only counts as a capital
                # "in Go", "using C", "a Java program", "Go version": a bare "go" or "c" in a sentence is not a language
                m = re.search(r"(?<![\w+#])%s\s+(?:%s)(?![\w+#])(?!\s*(?:to|on|and then|ahead|home|back|through|over))" % (CUE, alias), text, re.I) \
                    or re.search(r"(?<![\w+#])(?:%s)\s+(?:program|script|code|version|app|function|class|module|library|snippet|file)s?\b" % alias, text, re.I)
            else:
                m = None
            if m:
                found.append((m.start(), lid))
                break
    # "javascript" contains "java": the plain-word check above already refuses a match inside a longer word, so no extra rule is needed
    return [lid for _, lid in sorted(found)]


def project_language(folder, limit=2000):
    """The language an existing project mostly uses, from its file endings (None for an empty folder or a tie of nothing)."""
    counts = {}
    seen = 0
    for dirpath, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", "venv", ".venv", "target", "build", "dist")]
        for f in files:
            seen += 1
            if seen > limit:
                break
            ext = os.path.splitext(f)[1].lower()
            for lid, info in LANGS.items():
                if ext in info["ext"] and lid not in ("html",):
                    counts[lid] = counts.get(lid, 0) + 1
            if ext in (".html", ".css"):
                counts["html"] = counts.get("html", 0) + 1
    if not counts:
        return None
    best = max(counts, key=counts.get)
    return best if counts[best] >= 1 else None


def tools_here(env="local", which=shutil.which):
    """The set of programs VryxCode can use for this environment: what is installed (local), the sandbox image's, or None (cloud machine: not checked from here)."""
    if env == "sandbox":
        return set(SANDBOX_TOOLS)
    if env == "cloud":
        return None
    have = {n for n in {t for i in LANGS.values() for t in i["needs"]} | {"python3"} if which(n)}
    if "python3" not in have and which("python"):
        have.add("python3")
    return have


def can_run(lid, tools):
    """True/False, or None when it cannot be known (cloud machine)."""
    if tools is None:
        return None
    return all(n in tools for n in LANGS[lid]["needs"])


# kind -> (keyword pattern, [(language, reason)...] best first)
KINDS = [
    ("sql", r"\b(sql|sqlite|query|queries|database schema|tables? and joins?)\b", [("sql", "SQLite runs SQL queries directly"), ("python", "Python can drive SQLite")]),
    ("phone", r"\b(ios app|android app|iphone app|phone app|mobile app|app for (?:my |a )?(?:phone|ios|android))\b",
     [("html", "a web app that works well on phones needs no store account or emulator, and you can preview it here"), ("javascript", "React Native uses JavaScript for a store app")]),
    ("web", r"\b(web ?site|web ?page|landing page|html|css|front-?end|portfolio|web app|button|browser|in the browser|calculator app|quiz app|to-?do app|timer|clock|dashboard|form|animation|canvas)\b",
     [("html", "plain HTML, CSS and JavaScript needs no build step, so you see it live in the Preview tab"), ("javascript", "JavaScript runs in every browser")]),
    ("game", r"\b(game|snake|tetris|pong|platformer|2d game|arcade)\b",
     [("html", "a browser game on a canvas runs anywhere and previews instantly"), ("python", "Python is fine for a simple text game")]),
    ("speed", r"\b(fast|faster|performance|high[- ]performance|low[- ]level|systems?|embedded|memory[- ]safe|single binary|compiled|benchmark|number crunching|simulation|compiler|interpreter)\b",
     [("go", "Go is fast, simple, and makes one small program"), ("rust", "Rust is fast and memory safe"), ("cpp", "C++ is fast and everywhere"), ("c", "C is small and fast")]),
    ("server", r"\b(api|rest|server|backend|back-?end|endpoint|webhook|microservice|http service|rest api|crud)\b",
     [("python", "Python with Flask or FastAPI is quick to write and easy to read"), ("javascript", "Node with Express is a common choice for APIs"), ("go", "Go makes a fast, single-file server")]),
    ("cli", r"\b(command[- ]line|cli|terminal (?:tool|app|program)|takes arguments|shell script|utility)\b",
     [("python", "Python is the quickest way to a clear command-line tool"), ("go", "Go makes a single fast program"), ("rust", "Rust makes a single fast program")]),
    ("data", r"\b(csv|excel|spreadsheet|data|dataset|scrape|scraping|parse|parsing|pandas|plot|chart|statistics|machine learning|report|rename (?:my )?files|automate|automation|script|convert files?|batch)\b",
     [("python", "Python is the best fit for scripts, files and data")]),
    ("desktop", r"\b(desktop app|desktop application|gui|window app|tkinter|windows app)\b",
     [("python", "Python with tkinter makes a small desktop window with no installs"), ("html", "a web page can act as a desktop app")]),
    ("teach", r"\b(algorithm|leetcode|homework|exercise|function that|write a function|class that|unit tests?|kata|puzzle|fizzbuzz|prime|sort(?:ing)?|fibonacci|palindrome)\b",
     [("python", "Python is the clearest language for a small function or exercise")]),
]
DEFAULT = ("python", "Python is the safest default: clear to read, and it runs everywhere")


def recommend(task, tools, project=None):
    """{"language", "name", "why", "alternatives": [names], "kind", "runnable"}: the best language that can run here (or the best language, with the missing tool named)."""
    task = str(task or "")
    kind, options = "general", [DEFAULT]
    low = task.lower()
    for k, pat, opts in KINDS:
        if re.search(pat, low):
            kind, options = k, opts
            break
    if project and project in LANGS and kind in ("general", "data", "teach", "cli", "server", "speed"):
        options = [(project, "this project already uses it")] + [o for o in options if o[0] != project]
    pick = next((o for o in options if can_run(o[0], tools) is not False), None)
    first = options[0]
    chosen = pick or first
    lid, why = chosen
    if pick is not first and pick is not None:
        why += f" ({LANGS[first[0]]['name']} would fit better, but it is not installed here)"
    return {"language": lid, "name": LANGS[lid]["name"], "why": why, "kind": kind, "runnable": can_run(lid, tools),
            "alternatives": [LANGS[o[0]]["name"] for o in options if o[0] != lid][:3]}


def tool_summary(tools):
    if tools is None:
        return "The cloud machine's tools are not checked from here, so assume Python and Node.js and check with a quick command (for example `go version`) before relying on another language."
    runnable = [LANGS[l]["name"] for l in LANGS if l not in ("html",) and can_run(l, tools)]
    missing = [LANGS[l]["name"] for l in ("python", "javascript", "go", "java", "cpp", "rust", "php", "ruby") if not can_run(l, tools)]
    return "Languages that can run here: " + (", ".join(runnable) or "none") + (". Not installed here: " + ", ".join(missing) + " (you can still write them, then tell the user the commands to run)" if missing else "") + "."


def decide(task, env="local", folder=None, tools=None, which=shutil.which):
    """Everything the page and the model need about the language for this message:
    {"mode": "named" | "project" | "suggested", "language", "name", "why", "runnable", "alternatives", "named": [...], "tools": ...}."""
    tools = tools if tools is not None or env == "cloud" else tools_here(env, which)
    asked = named(task)
    project = project_language(folder) if folder and os.path.isdir(folder) else None
    out = {"named": asked, "tools_known": tools is not None}
    if asked:
        lid = asked[0]
        out.update(mode="named", language=lid, name=LANGS[lid]["name"], why="you asked for it", runnable=can_run(lid, tools), alternatives=[])
    elif project and len(str(task)) < 1200 and not re.search(r"\b(new project|from scratch|rewrite|port|convert|migrate)\b", str(task), re.I):
        out.update(mode="project", language=project, name=LANGS[project]["name"], why="this project already uses it", runnable=can_run(project, tools), alternatives=[])
    else:
        rec = recommend(task, tools, project)
        out.update(mode="suggested", language=rec["language"], name=rec["name"], why=rec["why"], runnable=rec["runnable"], alternatives=rec["alternatives"], kind=rec["kind"])
    out["tools"] = tool_summary(tools)
    return out


def note_for(decision):
    """The few lines that go to the model after its instructions (never shown as the person's words)."""
    d = decision
    if d["mode"] == "named":
        line = f"LANGUAGE: the user asked for {d['name']}. Use {d['name']}."
    elif d["mode"] == "project":
        line = f"LANGUAGE: this project already uses {d['name']}. Keep using {d['name']} unless the user asks for another."
    else:
        line = f"LANGUAGE: the user did not name one. Best fit: {d['name']}, because {d['why']}." + (f" Other options: {', '.join(d['alternatives'])}." if d["alternatives"] else "") + \
               " Say in one short sentence which language you chose and why."
    if d.get("runnable") is False:
        line += f" {d['name']} cannot be run here, so write the code and give the user the exact command to run it themselves."
    return " " + line + " " + d["tools"]


def page_line(decision):
    """What the page shows under the task: '' when there is nothing to say."""
    d = decision
    if d["mode"] == "suggested":
        return f"Suggested language: {d['name']}, because {d['why']}." + ("" if d.get("runnable") is not False else f" ({d['name']} cannot run on this machine: VryxCode will write it and tell you how to run it.)")
    if d["mode"] == "named" and d.get("runnable") is False:
        return f"{d['name']} isn't installed on this machine, so VryxCode can write it but not run it here."
    return ""
