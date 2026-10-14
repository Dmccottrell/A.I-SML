"""
harness.py - The tools and the loop for the v4 coding helper (no model needed to test it).

WHAT THIS FILE DOES
    An "agent" is a model that works in a loop: it asks for a tool, our code runs the tool and
    hands back the result, and it decides what to do next.

        task -> model: "read main.py" -> our code reads it -> model: "edit line 3" -> our code edits
             -> model: "run the tests" -> our code runs them -> model sees a failure -> tries again

    The model only has to write the request in the right format. EVERYTHING ELSE is this file:
    ordinary code that is safe, testable and knows nothing about AI.

THE FORMAT (uses tokens already reserved in v3's tokenizer)
    The model writes:   <|tool_call|>{"name": "read_file", "args": {"path": "main.py"}}<|end_tool_call|>
    We answer (in the next user message):   <|tool_result|>1: def add(a, b): ...<|end_tool_result|>

THE TOOLS
    list_files(path=".")              what's in a folder
    read_file(path, start=1, end=None)  a file, with line numbers (long files are cut)
    write_file(path, content, append=false)  create or replace a file; append=true adds to the end (write big files in parts)
    edit_file(path, old, new)         replace ONE exact piece of text (fails if it isn't found exactly once)
    run(command)                      run a command such as: python -m unittest
    git(args)                         a safe set of git commands: status, diff, log, show, init, add, commit,
                                      branch, switch, checkout, restore, stash, and worktrees ("worktree add NAME")
    diagnostics(path)                 problems in a .py file (syntax errors; more if pyflakes is installed): a
                                      small stand-in for an editor's language server (LSP)
    finish(summary)                   the model says it is done

AROUND THE LOOP (all plain code, nothing the model has to learn except the tool format)
    project notes     EMVRYX.md / AGENTS.md in the workspace is shown to the model as "Project notes"
    hooks             .emvryx/hooks.json: commands that run after an edit (e.g. a syntax check), before a command,
                      or when the model tries to finish (a "finish gate": the tests must pass first)
    permissions       which tools run freely, which ask first (git commit, ...), which are refused
    compaction        when the conversation gets too long, old steps become a short "Earlier steps" summary
    tool registry     sandbox.register_tool(name, function): the plug-in point for MCP tools (the MCP protocol
                      client itself is not built yet)

THE SANDBOX: what it does and does NOT do
    All file tools are confined to one workspace folder: "..", absolute paths and symlinks that
    lead outside are refused. Commands run with that folder as their working directory, a short
    list of allowed programs, a time limit, an output limit and (on Linux) memory limits and no
    network access (via `unshare`). This protects against a small model's MISTAKES (deleting
    files, endless loops, huge output). It is not a wall against a deliberately hostile program:
    Python can do anything the operating system lets the user do. For real isolation run the whole
    thing inside Docker or WSL (see `command_prefix`). On Windows there are no memory/network limits,
    only the folder confinement, the allowed-programs list and the timeout.

Try it (a scripted "model", no AI needed):    python -m unittest tests.test_harness -v
"""
import ast
import fnmatch
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

TOOL_CALL = re.compile(r"<\|tool_call\|>(.*?)<\|end_tool_call\|>", re.S)
QWEN_TOOL_CALL = re.compile(r"<tool_call>(.*?)</tool_call>", re.S)       # the format Qwen models already know
ALLOWED_PROGRAMS = {"python", "python3", "pytest", "ls", "cat", "head", "tail", "grep", "wc",
                    "echo", "pwd", "sort", "uniq", "diff",
                    # other languages, when they are installed (in the container image: node, gcc, g++, sqlite3). Not package managers (npm, pip, cargo: they download and run other
                    # people's code) and not `make` (a Makefile can run anything); the person is told to run those themselves.
                    "node", "gcc", "g++", "cc", "go", "java", "javac", "php", "ruby", "rustc", "sqlite3"}


# git: only these subcommands, and never flags that point outside the workspace or run other programs.
# (git's own -c / -C options only work BEFORE the subcommand, which is refused above; after it, -c is a subcommand flag such as `switch -c NAME`.)
GIT_SUBCOMMANDS = {"status", "diff", "log", "show", "init", "add", "commit", "branch", "switch", "checkout",
                   "restore", "stash", "worktree"}
GIT_READ_ONLY = {"status", "diff", "log", "show", "init"}
GIT_BLOCKED_FLAGS = ("--git-dir", "--work-tree", "--exec-path", "--upload-pack", "--receive-pack",
                     "--namespace", "--super-prefix", "--config-env", "--output", "--ext-diff", "--textconv")
PROJECT_FILES = ("VRYX.md", "EMVRYX.md", "AGENTS.md")
HOOKS_FILE = os.path.join(".emvryx", "hooks.json")

# Shown to the model at the start of a coding session (and in every coding lesson), so it knows the tools
TOOL_PROMPT = ("You can use tools. Write one call at a time: <|tool_call|>{\"name\": \"read_file\", \"args\": "
               "{\"path\": \"main.py\"}}<|end_tool_call|> and wait for the result. Tools: list_files(path), "
               "read_file(path, start, end), write_file(path, content), edit_file(path, old, new), run(command), "
               "git(args), diagnostics(path), finish(summary, next). Small steps; run the tests before you finish; "
               "if a task is too big, say so and suggest a first step. Write a big file in parts of about 60 lines: write_file(path, content) "
               "for the first part, then write_file(path, content, append=true) for each next part. In the JSON, write line breaks as \\n and quotes as \\\".")


class ToolError(Exception):
    """A tool couldn't do what was asked. The message goes back to the model so it can correct itself."""


def cut(text, limit):
    """Keep the start and the end of long text (errors are usually at the end)."""
    if len(text) <= limit:
        return text
    head, tail = limit * 2 // 3, limit // 3
    return f"{text[:head]}\n... [{len(text) - head - tail} characters cut] ...\n{text[-tail:]}"


def _limits():
    """Linux only: runs in the child process before the command starts."""
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))       # 2 GB of memory
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))                        # 30 s of CPU time
    resource.setrlimit(resource.RLIMIT_FSIZE, (50 * 1024**2, 50 * 1024**2))  # files up to 50 MB


def _no_network_prefix():
    """['unshare', '-rn'] if this Linux machine lets us cut off the network, else []."""
    if sys.platform.startswith("linux") and shutil.which("unshare"):
        try:
            if subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=5).returncode == 0:
                return ["unshare", "-rn"]
        except (OSError, subprocess.SubprocessError):
            pass
    return []


class Sandbox:
    """One workspace folder plus the tools that work inside it."""

    def __init__(self, workspace=None, command_timeout=20, output_limit=1500, max_read_lines=80,
                 command_prefix=None, allowed_programs=ALLOWED_PROGRAMS, git_identity=("Emvryx agent", "agent@localhost"), container=False, remote=False):
        self.git_identity = tuple(git_identity)
        self.container = bool(container)         # True when command_prefix is a `docker run ...` (code_sandbox.docker_prefix): commands run inside it
        self.remote = bool(remote)               # True when command_prefix runs the command on another machine (cloud_run.py): its Python is not ours, and git stays here
        self.own_dir = workspace is None
        self.root = os.path.realpath(workspace or tempfile.mkdtemp(prefix="agent_"))
        os.makedirs(self.root, exist_ok=True)
        self.command_timeout, self.output_limit, self.max_read_lines = command_timeout, output_limit, max_read_lines
        self.allowed = set(allowed_programs)
        self.prefix = _no_network_prefix() if command_prefix is None else list(command_prefix)
        self.extra_tools = {}

    def close(self):
        if self.own_dir:
            shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---------------------------------------------------------------- paths
    def path(self, name):
        """Turn a path the model gave into a real path INSIDE the workspace, or refuse."""
        if not isinstance(name, str) or not name.strip() or "\x00" in name:
            raise ToolError("path must be a non-empty string")
        name = name.strip().replace("\\", "/")                   # a Windows-style path from the model
        if re.match(r"^[A-Za-z]:/", name):
            name = name[3:]
        if name.startswith("/"):                                  # "/index.html" means the project's root, unless it already is a real path inside it
            inside = os.path.realpath(name)
            name = inside if inside == self.root or inside.startswith(self.root + os.sep) else name.lstrip("/") or "."
        full = os.path.realpath(os.path.join(self.root, name))    # resolves .. and symlinks
        if full != self.root and not full.startswith(self.root + os.sep):
            raise ToolError(f"{name!r} is outside the workspace; only files inside it can be used")
        return full

    def rel(self, full):
        return os.path.relpath(full, self.root).replace("\\", "/")

    # ---------------------------------------------------------------- tools
    def list_files(self, path="."):
        full = self.path(path)
        if not os.path.isdir(full):
            raise ToolError(f"{path!r} is not a folder")
        names = sorted(n + ("/" if os.path.isdir(os.path.join(full, n)) else "") for n in os.listdir(full))
        return "\n".join(names[:100]) or "(empty)"

    def read_file(self, path, start=1, end=None):
        full = self.path(path)
        if not os.path.isfile(full):
            raise ToolError(f"{path!r} is not a file (try list_files)")
        with open(full, encoding="utf-8", errors="replace") as f:
            lines = f.read().split("\n")
        if len(lines) > 1 and lines[-1] == "":
            lines.pop()                                  # the empty piece after the final newline
        start = max(1, int(start))
        end = min(len(lines), int(end) if end else start + self.max_read_lines - 1, start + self.max_read_lines - 1)
        if start > len(lines):
            raise ToolError(f"{path!r} has only {len(lines)} lines")
        out = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))
        more = f"\n[showing lines {start}-{end} of {len(lines)}]" if end < len(lines) or start > 1 else ""
        return cut(out, self.output_limit * 2) + more

    def _not_git_folder(self, full):
        """The .git folder holds the project's git settings (including where it pushes): only git itself may change it."""
        if ".git" in self.rel(full).split("/"):
            raise ToolError("the .git folder is managed by git: use the git tool instead of editing it")

    def write_file(self, path, content, append=False):
        """Create or replace a file; with append=true the text is added to the end instead (big files are written in parts, so no single call has to be long)."""
        full = self.path(path)
        self._not_git_folder(full)
        if os.path.isdir(full):
            raise ToolError(f"{path!r} is a folder")
        content = _unescape_if_flattened(path, content)
        if append and not os.path.isfile(full):
            raise ToolError(f"{path!r} does not exist yet: write the first part without append, then add the rest with append=true")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "a" if append else "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        return f"{'added to' if append else 'wrote'} {self.rel(full)} ({len(content.splitlines())} lines)"

    def edit_file(self, path, old, new):
        full = self.path(path)
        self._not_git_folder(full)
        if not os.path.isfile(full):
            raise ToolError(f"{path!r} is not a file")
        with open(full, encoding="utf-8") as f:
            text = f.read()
        if not old:
            raise ToolError("'old' is empty; give the exact text to replace")
        n = text.count(old)
        if n == 0:
            raise ToolError(_not_found_hint(text, old, path))
        if n > 1:
            raise ToolError(f"the text in 'old' appears {n} times; include more surrounding lines so it matches once")
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            f.write(text.replace(old, new, 1))
        return f"edited {self.rel(full)}"

    def _exec(self, argv, extra_env=None, wrap=True):
        """Run argv in the workspace with the limits (time, output, memory, no network on Linux)."""
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
        if os.name == "nt":
            env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")
        env.update(extra_env or {})
        kwargs = {"preexec_fn": _limits} if sys.platform.startswith("linux") and not self.container and not self.remote else {}
        if self.container and wrap:
            # the container is a separate world: environment variables must be passed in with -e (before the image name, the last word of the prefix)
            inside = dict(extra_env or {})
            if "HOME" in inside:
                inside["HOME"] = "/tmp"
            command = self.prefix[:-1] + [x for k, v in inside.items() for x in ("-e", f"{k}={v}")] + [self.prefix[-1]] + argv
        else:
            command = (self.prefix if wrap else []) + argv
        try:
            r = subprocess.run(command, cwd=self.root, env=env, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=self.command_timeout,
                               stdin=subprocess.DEVNULL, **kwargs)
        except subprocess.TimeoutExpired:
            raise ToolError(f"the command took longer than {self.command_timeout} s and was stopped")
        except OSError as e:
            raise ToolError(f"could not run it: {e}")
        out = (r.stdout + ("\n" + r.stderr if r.stderr else "")).strip()
        return cut(f"exit code {r.returncode}\n{out}" if out else f"exit code {r.returncode}", self.output_limit)

    def run(self, command):
        try:
            argv = shlex.split(command)
        except ValueError as e:
            raise ToolError(f"can't read that command: {e}")
        if not argv:
            raise ToolError("empty command")
        program = os.path.basename(argv[0])
        if program not in self.allowed:
            extra = " Run one program at a time (no cd, &&, |, ; or >): the project folder is already the current folder." if program in ("cd", "sh", "bash", "cmd", "powershell") or any(t in argv for t in ("&&", "||", "|", ";", ">", ">>")) else ""
            raise ToolError(f"{program!r} is not allowed. Allowed: {', '.join(sorted(self.allowed))}.{extra}")
        if any(t in argv for t in ("&&", "||", "|", ";", ">", ">>")):
            raise ToolError("run one program at a time: no &&, ||, |, ; or > (they are not understood here). The project folder is already the current folder.")
        if program in ("python", "python3") and not self.container and not self.remote:
            argv[0] = sys.executable                     # the same Python we are running (inside a container, or on a remote machine, that one's own python is used)
        return self._exec(argv)

    # ---------------------------------------------------------------- git (a safe subset)
    def git(self, args):
        if not shutil.which("git"):
            raise ToolError("git is not installed on this machine")
        try:
            argv = shlex.split(args) if isinstance(args, str) else [str(a) for a in args]
        except ValueError as e:
            raise ToolError(f"can't read that git command: {e}")
        if not argv:
            raise ToolError("empty git command")
        sub = argv[0]
        if sub not in GIT_SUBCOMMANDS:
            raise ToolError(f"git {sub!r} is not allowed. Allowed: {', '.join(sorted(GIT_SUBCOMMANDS))}")
        for a in argv[1:]:
            if any(a == f or a.startswith(f + "=") for f in GIT_BLOCKED_FLAGS):
                raise ToolError(f"the git option {a!r} is not allowed")
            if os.path.isabs(a) or ".." in re.split(r"[\\/]", a):
                raise ToolError(f"{a!r} points outside the workspace")
        if sub == "worktree":
            return self._worktree(argv[1:])
        return self._git(argv)

    def _git(self, argv):
        env = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_TERMINAL_PROMPT": "0", "GIT_EDITOR": "true", "GIT_PAGER": "cat", "HOME": self.root,
               "GIT_AUTHOR_NAME": self.git_identity[0], "GIT_AUTHOR_EMAIL": self.git_identity[1],
               "GIT_COMMITTER_NAME": self.git_identity[0], "GIT_COMMITTER_EMAIL": self.git_identity[1]}
        return self._exec(["git", "-c", f"core.hooksPath={os.devnull}", "-c", "init.defaultBranch=main"] + argv, env, wrap=not self.remote)

    def _worktree(self, args):
        """worktree list | add NAME [BRANCH] | remove NAME: always under .worktrees/ inside the workspace."""
        if not args:
            raise ToolError("use: worktree list, worktree add NAME [BRANCH], or worktree remove NAME")
        name_ok = lambda n: bool(re.fullmatch(r"[A-Za-z0-9_.-]+", n)) and n not in (".", "..")
        if args[0] == "list":
            return self._git(["worktree", "list"])
        if args[0] == "add" and len(args) in (2, 3) and name_ok(args[1]) and (len(args) == 2 or name_ok(args[2])):
            os.makedirs(os.path.join(self.root, ".worktrees"), exist_ok=True)
            return self._git(["worktree", "add", "-b", args[2] if len(args) == 3 else args[1],
                              f".worktrees/{args[1]}"])
        if args[0] == "remove" and len(args) == 2 and name_ok(args[1]):
            return self._git(["worktree", "remove", f".worktrees/{args[1]}"])
        raise ToolError("use: worktree list, worktree add NAME [BRANCH], or worktree remove NAME")

    # ---------------------------------------------------------------- diagnostics (a small stand-in for LSP)
    def diagnostics(self, path):
        full = self.path(path)
        if not os.path.isfile(full):
            raise ToolError(f"{path!r} is not a file")
        if not full.endswith(".py"):
            raise ToolError("diagnostics only checks .py files for now")
        with open(full, encoding="utf-8", errors="replace") as f:
            src = f.read()
        rel = self.rel(full)
        try:
            ast.parse(src, filename=rel)
        except SyntaxError as e:
            return f"{rel}:{e.lineno}: syntax error: {e.msg}"
        try:                                              # a fuller check when pyflakes is installed
            from pyflakes import api, reporter
            import io
            out = io.StringIO()
            api.check(src, rel, reporter.Reporter(out, out))
            text = out.getvalue().strip()
            return text or "no problems found"
        except ImportError:
            return "no syntax errors found (install pyflakes for undefined-name and unused-import checks)"

    # ---------------------------------------------------------------- plug-in tools (MCP-style registry)
    def register_tool(self, name, function):
        """Add a tool: function(**args) -> text. This is where tools from an MCP server plug in."""
        if name in self.builtin_names() or not callable(function):
            raise ValueError(f"can't register {name!r}")
        self.extra_tools[name] = function

    def builtin_names(self):
        return ["list_files", "read_file", "write_file", "edit_file", "run", "git", "diagnostics", "finish"]

    def call(self, name, args):
        """Run one tool. Returns (text for the model, whether the model said it is finished)."""
        if name == "finish":
            return str(args.get("summary", "")), True
        tools = {"list_files": self.list_files, "read_file": self.read_file, "write_file": self.write_file,
                 "edit_file": self.edit_file, "run": self.run, "git": self.git, "diagnostics": self.diagnostics,
                 **self.extra_tools}
        if name not in tools:
            raise ToolError(f"unknown tool {name!r}. Tools: {', '.join(list(tools) + ['finish'])}")
        if not isinstance(args, dict):
            raise ToolError("'args' must be an object like {\"path\": \"main.py\"}")
        try:
            return tools[name](**args), False
        except TypeError as e:
            raise ToolError(f"wrong arguments for {name}: {e}")
        except (ValueError, OSError) as e:                       # a bad number, a name the system refuses, a file that cannot be written: tell the model, do not crash the session
            raise ToolError(f"{name} could not do that: {e}")


# -------------------------------------------------------------------- checks before and after a change
def check_text(path, text):
    """Problems found in the text a file would hold: a Python syntax error, an undefined name (when pyflakes is installed), or invalid JSON. [] = fine or not checked."""
    low = path.lower()
    if low.endswith(".py"):
        try:
            ast.parse(text, filename=path)
        except SyntaxError as e:
            return [f"{path}:{e.lineno}: syntax error: {e.msg}"]
        try:
            from pyflakes import api, reporter
            import io
            out = io.StringIO()
            api.check(text, path, reporter.Reporter(out, out))
            return [l for l in out.getvalue().splitlines() if "undefined name" in l][:5]       # not unused imports: they are noise that sends a small model in circles
        except ImportError:
            return []
    if low.endswith(".json"):
        try:
            json.loads(text)
        except ValueError as e:
            return [f"{path}: not valid JSON: {e}"]
    if low.endswith((".js", ".mjs")):
        return _check_js(path, text)
    if low.endswith((".html", ".htm")):
        return _check_html(path, text)
    other = _check_other(path, text)
    return other


def checkable(path):
    return str(path).lower().endswith((".py", ".json", ".js", ".mjs", ".html", ".htm") + tuple(OTHER_CHECKS))


SCRIPT_RX = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.I | re.S)
_STRINGS = re.compile(r"`(?:\\.|[^`\\])*`|'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"|//[^\n]*|/\*.*?\*/", re.S)
_JSX = re.compile(r"(?:\breturn|[=(,?:]|&&|\|\||=>)\s*<(?:[A-Za-z][\w.]*|>)(?:[\s/>])")
JSX_FIX = ('this <script> uses JSX (tags like <div> written inside JavaScript), which a browser cannot run in a plain <script> ("Unexpected token \'<\'"). '
           'Either add <script src="https://unpkg.com/@babel/standalone@7.26.4/babel.min.js"></script> before it and change it to <script type="text/babel">, '
           'or write React.createElement(...) instead of tags')


def _check_html(path, text):
    """The JavaScript inside a web page: JSX in a plain <script> (the most common reason a React page shows nothing), then a syntax check of each inline script."""
    out = []
    for m in SCRIPT_RX.finditer(text):
        attrs, body = m.group(1), m.group(2)
        if re.search(r"\bsrc\s*=", attrs, re.I) or not body.strip():
            continue
        kind = (re.search(r"\btype\s*=\s*[\"']?([\w/+.-]+)", attrs, re.I) or [None, ""])[1].lower()
        if kind not in ("", "text/javascript", "application/javascript", "module"):
            continue                                              # text/babel, JSON, templates: not plain JavaScript
        line = text.count("\n", 0, m.start(2)) + 1
        bare = _STRINGS.sub(lambda x: "\n" * x.group(0).count("\n"), body)
        jsx = _JSX.search(bare)
        if jsx:
            out.append(f"{path}:{line + bare.count(chr(10), 0, jsx.start() + jsx.group(0).index('<'))}: syntax error: {JSX_FIX}")    # the line of the tag itself
            continue
        for err in _check_js(path + (".mjs" if kind == "module" else ""), body):
            mm = re.match(r".*?:(\d+): (.*)", err)
            out.append(f"{path}:{line + int(mm.group(1)) - 1}: {mm.group(2)}" if mm else err)
        if len(out) >= 3:
            break
    return out


# Other languages: only a SYNTAX check, and only when that language's tool is installed on this machine (nothing is reported otherwise).
# Each entry: file ending -> (program, a function that makes the command from a temp file path, a pattern a real syntax error line matches).
# Errors about things in OTHER files of the project (a missing import, an unknown name) are left out on purpose: the text is checked alone.
_SYNTAX_WORDS = re.compile(r"expected|unexpected|syntax error|stray|unterminated|missing terminating|unbalanced|extra tokens|illegal start|reached end of file|unclosed|parse error|invalid token|before .* token", re.I)
OTHER_CHECKS = {
    ".go": ("gofmt", lambda f, d: ["gofmt", "-e", f], re.compile(r"")),
    ".php": ("php", lambda f, d: ["php", "-l", f], re.compile(r"Parse error|syntax error", re.I)),
    ".rb": ("ruby", lambda f, d: ["ruby", "-c", f], re.compile(r"syntax error|unexpected|expecting", re.I)),
    ".c": ("gcc", lambda f, d: ["gcc", "-fsyntax-only", "-x", "c", f], _SYNTAX_WORDS),
    ".h": ("gcc", lambda f, d: ["gcc", "-fsyntax-only", "-x", "c", f], _SYNTAX_WORDS),
    ".cpp": ("g++", lambda f, d: ["g++", "-fsyntax-only", "-x", "c++", f], _SYNTAX_WORDS),
    ".cc": ("g++", lambda f, d: ["g++", "-fsyntax-only", "-x", "c++", f], _SYNTAX_WORDS),
    ".java": ("javac", lambda f, d: ["javac", "-proc:none", "-d", d, f], _SYNTAX_WORDS),
}


def _check_other(path, text):
    ext = os.path.splitext(str(path).lower())[1]
    spec = OTHER_CHECKS.get(ext)
    if not spec or not shutil.which(spec[0]):
        return []
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        name = os.path.basename(str(path)) if ext == ".java" else "check" + ext         # a Java file must be named after its public class
        f = os.path.join(d, name)
        with open(f, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        try:
            r = subprocess.run(spec[1](f, d), capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL, cwd=d)
        except (OSError, subprocess.SubprocessError):
            return []
    if r.returncode == 0:
        return []
    out = []
    for line in (r.stderr + "\n" + r.stdout).splitlines():
        if not line.strip() or not spec[2].search(line):
            continue
        if ext == ".java" and re.search(r"cannot find symbol|does not exist|should be declared in a file|incompatible types|cannot be applied", line):
            continue
        clean = line.replace(f, str(path)).replace(d + os.sep, "").strip()
        m = re.search(r":(\d+)(?::\d+)?:?\s*(.*)", clean)
        out.append(f"{path}:{m.group(1)}: syntax error: {m.group(2).strip()}" if m else f"{path}: syntax error: {clean}")
        if len(out) >= 3:
            break
    return out


def _check_js(path, text):
    """A JavaScript syntax check with `node --check`, when Node is installed on this machine (otherwise not checked)."""
    node = shutil.which("node")
    if not node:
        return []
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "check" + (".mjs" if path.lower().endswith(".mjs") else ".js"))
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(text)
        try:
            r = subprocess.run([node, "--check", f], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return []
    if r.returncode == 0:
        return []
    lines = [l for l in r.stderr.splitlines() if l.strip()]
    where = next((l for l in lines if l.startswith(f + ":")), "")
    line_no = where.split(":")[-1] if where else "?"
    msg = next((l for l in lines if "Error" in l), "invalid JavaScript")
    return [f"{path}:{line_no}: syntax error: {msg.strip()}"]


def proposed_text(root, name, args):
    """(path, the text the file would hold after this write_file/edit_file), or None when that cannot be worked out (the tool then reports its own error)."""
    if name not in ("write_file", "edit_file") or not isinstance(args, dict) or not isinstance(args.get("path"), str) or not checkable(args["path"]):
        return None
    full = os.path.realpath(os.path.join(root, args["path"]))
    if full != root and not full.startswith(root + os.sep):
        return None
    if name == "write_file":
        if args.get("append"):
            return None                                           # one part of a bigger file: a half-written file is expected to be incomplete
        return args["path"], str(args.get("content", ""))
    try:
        with open(full, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    old, new = str(args.get("old", "")), str(args.get("new", ""))
    return (args["path"], text.replace(old, new, 1)) if old and text.count(old) == 1 else None


def preview_check(root, name, args):
    """Look at a change BEFORE it is made. None = nothing to check, "" = it looks fine, else the problem(s) it would cause."""
    got = proposed_text(os.path.realpath(root), name, args)
    if got is None:
        return None
    return "; ".join(check_text(*got))


def has_tests(root):
    for dirpath, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv", "venv")]
        if dirpath[len(root):].count(os.sep) > 2:
            dirs[:] = []
        if any((n.startswith("test_") or n.endswith("_test.py")) and n.endswith(".py") for n in names):
            return True
    return False


TEST_COMMAND = re.compile(r"unittest|pytest")


# -------------------------------------------------------------------- the loop
def _unescape_if_flattened(path, text):
    """A model sometimes writes a whole file as one line with the two letters \\n where the line breaks belong (it escaped twice). Turn those back into line breaks,
    but never in JSON (where \\n inside a string is correct) and never when the text already has real line breaks."""
    if not isinstance(text, str) or "\n" in text or str(path).lower().endswith(".json") or len(text) < 60:
        return text
    if text.count("\\n") < 3:
        return text
    return text.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')


def _not_found_hint(text, old, path):
    """Why edit_file could not find 'old', and what to do: the commonest cause is spaces or line endings that differ; the next is that the text is not in this file at all."""
    squash = lambda t: re.sub(r"\s+", " ", t).strip()
    want = squash(old)
    if want:
        lines = text.split("\n")
        for i in range(len(lines)):
            window = ""
            for j in range(i, min(len(lines), i + max(1, old.count("\n") + 3))):
                window = squash(window + " " + lines[j])
                if window == want:
                    return (f"the text in 'old' was not found exactly, but the same words are at lines {i + 1}-{j + 1} with different spaces or line breaks. "
                            f"Use read_file {path} (start {i + 1}) and copy that text exactly, without the line numbers.")
        first = squash(old.split("\n")[0])
        if first and first in squash(text):
            return ("the first line of 'old' is in the file but the rest does not match. Use read_file to see the exact text, and replace a smaller piece "
                    "(one or two lines) so it matches once.")
    return (f"the text in 'old' is not in {path} at all. It may be in another file, or may not be in the project (a page can show scripts that "
            "the hosting adds, which are not in your files). Use read_file to look at the file; do not try the same edit again.")


TOOL_ALIASES = {"create_file": "write_file", "write": "write_file", "create": "write_file", "save_file": "write_file", "new_file": "write_file",
                "edit": "edit_file", "replace": "edit_file", "str_replace": "edit_file", "str_replace_editor": "edit_file", "update_file": "edit_file", "modify_file": "edit_file",
                "read": "read_file", "view": "read_file", "cat": "read_file", "open_file": "read_file",
                "ls": "list_files", "list": "list_files", "list_dir": "list_files", "list_directory": "list_files",
                "bash": "run", "shell": "run", "execute": "run", "execute_command": "run", "run_command": "run", "terminal": "run", "exec": "run", "command": "run",
                "done": "finish", "complete": "finish", "final_answer": "finish", "task_complete": "finish"}
_PATH_KEYS = ("file_path", "filepath", "filename", "file_name", "file", "fname", "name", "target_file", "filePath")
ARG_ALIASES = {
    "write_file": {"path": _PATH_KEYS, "content": ("contents", "text", "code", "body", "data", "file_content", "file_text", "source")},
    "edit_file": {"path": _PATH_KEYS, "old": ("old_string", "old_str", "old_text", "search", "find", "original", "oldText", "old_content"),
                  "new": ("new_string", "new_str", "new_text", "replace", "replacement", "replace_with", "newText", "new_content")},
    "read_file": {"path": _PATH_KEYS, "start": ("start_line", "from_line", "offset"), "end": ("end_line", "to_line")},
    "list_files": {"path": ("dir", "directory", "folder", "dir_path", "directory_path") + _PATH_KEYS},
    "run": {"command": ("cmd", "commandline", "command_line", "script", "shell_command", "code")},
    "finish": {"summary": ("message", "result", "text", "answer", "output", "final_answer", "response")},
}


def normalize_call(name, args):
    """What the model meant: another name for a tool (create_file, bash...) or another word for an argument (file_path, old_string, cmd...) is accepted,
    and arguments sent as a JSON string are opened. The real names always win."""
    name = TOOL_ALIASES.get(name, name) if isinstance(name, str) else name
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {"command": args} if name == "run" else args
    if isinstance(args, dict) and name in ARG_ALIASES:
        args = dict(args)
        for real, others in ARG_ALIASES[name].items():
            if real not in args:
                for o in others:
                    if o in args:
                        args[real] = args.pop(o)
                        break
    return name, args


def parse_tool_call(text):
    """The first tool call in the model's text -> (name, args). Raises ToolError if it can't be read."""
    m = TOOL_CALL.search(text) or QWEN_TOOL_CALL.search(text)
    if not m and ("<|tool_call|>" in text or "<tool_call>" in text):
        raise ToolError("the tool call was cut off before its end (it was too long). Send it again in smaller parts: write_file for the first part, "
                        "then write_file with append=true for each next part, about 60 lines at a time.")
    if not m:
        raise ToolError('no tool call found. Write: <|tool_call|>{"name": "...", "args": {...}}<|end_tool_call|>')
    body = m.group(1)
    for strict in (True, False):                                  # models often put raw line breaks inside the file text; strict=False accepts those
        try:
            call = json.loads(body, strict=strict)
            return normalize_call(call["name"], call.get("args", {}))
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            continue
    salvaged = _salvage_write(body)
    if salvaged:
        return normalize_call(*salvaged)
    raise ToolError('the tool call is not valid JSON with a "name". Example: {"name": "read_file", "args": {"path": "main.py"}}. '
                    'Inside "content", write line breaks as \\n and quotes as \\", or keep each call small: write_file for the first part, then write_file with append=true for the rest.')


_WRITE_NAME = re.compile(r'"name"\s*:\s*"write_file"')
_WRITE_PATH = re.compile(r'"path"\s*:\s*"([^"\n]{1,200})"')
_WRITE_CONTENT = re.compile(r'"content"\s*:\s*"', re.S)


def _salvage_write(body):
    """A write_file call whose JSON is broken (usually a quote or line break inside the file that was not escaped): the path and the text between
    "content": " and the closing "}} are still plain to see. (name, args) or None."""
    if not _WRITE_NAME.search(body):
        return None
    p, c = _WRITE_PATH.search(body), _WRITE_CONTENT.search(body)
    if not p or not c:
        return None
    text = body[c.end():]
    end = re.search(r'"\s*\}\s*\}?\s*$', text)
    if not end:
        return None                                               # cut off before the end: do not save half a file
    text = text[:end.start()]
    text = re.sub(r"\\(n|t|r|\"|\\)", lambda k: {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}[k.group(1)], text)
    args = {"path": p.group(1), "content": text}
    if re.search(r'"append"\s*:\s*true', body[:c.start()] + body[c.end() + len(text):]):
        args["append"] = True                                     # a part of a bigger file must not replace what is already there
    return "write_file", args


def format_result(text):
    return f"<|tool_result|>{text}<|end_tool_result|>"


class Permissions:
    """Which tools run freely, which ask first, which are refused: "allow", "ask" or "deny".

    Defaults: reading, editing, running allowed (the sandbox confines them); git commands that only look are
    allowed, git commands that change things ask first; unknown (plug-in) tools ask. `rules` overrides by tool name
    ("run": "ask") or by "git:commit". With no `ask` function, "ask" means refused.
    """

    def __init__(self, rules=None, ask=None):
        self.rules, self.ask = dict(rules or {}), ask

    def level(self, name, args):
        if name == "git" and isinstance(args, dict):
            words = str(args.get("args", "")).split()
            sub = words[0] if words else ""
            if f"git:{sub}" in self.rules:
                return self.rules[f"git:{sub}"]
            if name in self.rules:
                return self.rules[name]
            return "allow" if sub in GIT_READ_ONLY else "ask"
        if name in self.rules:
            return self.rules[name]
        return "allow" if name in ("list_files", "read_file", "write_file", "edit_file", "run", "diagnostics",
                                   "finish") else "ask"

    def check(self, name, args):
        """None if it may run, else the reason it may not (as the model sees it)."""
        level = self.level(name, args)
        if level == "allow":
            return None
        if level == "ask" and self.ask and self.ask(name, args):
            return None
        return f"{name} was not allowed here" + (" (the user said no)" if level == "ask" and self.ask else "")


class Hooks:
    """Commands from .emvryx/hooks.json that run at set moments, like [{"event": "after_edit", "match": "*.py",
    "run": "python -m py_compile {path}"}]. Events: after_edit (a file was written), before_run (a command is
    about to run; a failure stops it) and on_finish (the model wants to stop; a failure means "not yet")."""

    EVENTS = ("after_edit", "before_run", "on_finish")

    def __init__(self, rules=()):
        self.rules = [r for r in rules if isinstance(r, dict) and r.get("event") in self.EVENTS and r.get("run")]

    @classmethod
    def load(cls, sandbox):
        try:
            with open(os.path.join(sandbox.root, HOOKS_FILE), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return cls()
        return cls(data if isinstance(data, list) else [])

    def run(self, sandbox, event, path=None):
        """Run the matching hooks. Returns the problems found (a list of short texts; empty means all fine)."""
        problems = []
        for r in self.rules:
            if r["event"] != event:
                continue
            if event == "after_edit" and not (path and fnmatch.fnmatch(path, r.get("match", "*"))):
                continue
            command = r["run"].replace("{path}", shlex.quote(path or ""))
            try:
                out = sandbox.run(command)
            except ToolError as e:
                out = f"exit code 1\n{e}"
            if not out.startswith("exit code 0"):
                problems.append(f"hook `{command}` failed: {out}")
        return problems


def load_project_notes(sandbox, limit=3000):
    """The text of VRYX.md / EMVRYX.md / AGENTS.md in the workspace (the first found), or ""."""
    for name in PROJECT_FILES:
        try:
            with open(os.path.join(sandbox.root, name), encoding="utf-8", errors="replace") as f:
                return cut(f.read().strip(), limit)
        except OSError:
            continue
    return ""


# -------------------------------------------------------------------- keeping the conversation short
def estimate_tokens(messages):
    return int(sum(len(m["content"]) for m in messages) / 3.3)


def describe_step(call_text, result):
    """One line for the summary: what was asked and how it went."""
    try:
        name, args = parse_tool_call(call_text)
    except ToolError:
        return "a reply that was not a tool call"
    what = args.get("path") or args.get("command") or args.get("args") or "" if isinstance(args, dict) else ""
    first = (result or "").split("\n", 1)[0].replace("<|tool_result|>", "").replace("<|end_tool_result|>", "")
    return f"{name} {what}".strip() + (f" -> {cut(first, 80)}" if name in ("run", "git", "diagnostics") or
                                        first.startswith("error") else "")


def compact(messages, keep=4):
    """Shorten a long conversation: the system message and the task stay, the last `keep` messages stay, and
    everything between becomes an "Earlier steps" list inside the task message. Returns (messages, dropped)."""
    system = [m for m in messages[:1] if m["role"] == "system"]
    rest = messages[len(system):]
    if len(rest) <= keep + 1:
        return messages, []
    tail = rest[-keep:]
    middle = rest[1:len(rest) - keep]
    steps = []
    for i in range(0, len(middle) - 1, 2):
        steps.append("- " + describe_step(middle[i]["content"], middle[i + 1]["content"]))
    task = rest[0]["content"].split("\n\nEarlier steps", 1)[0]
    old = rest[0]["content"].split("\n\nEarlier steps:\n", 1)
    if len(old) == 2:
        steps = old[1].split("\n") + steps
    steps = steps[-30:]
    head = {"role": "user", "content": task + "\n\nEarlier steps:\n" + "\n".join(steps)}
    return system + [head] + tail, middle


THINK_TAGS = re.compile(r"<think>.*?</think>", re.S)
NO_CALL_LIMIT = 3          # stop after this many replies in a row without a tool call, instead of using every step on the same answer
BAD_CALL_LIMIT = 3         # ...and this many replies in a row whose tool call could not be read (a file too big to write in one go, say)
NO_CALL_TOTAL = 5          # ...or this many in one run (a model that alternates "I can't" with the same tool call is stuck too)
REPEAT_HINT_AT = 3         # the same step with the same result this many times: tell the model to try something else
REPEAT_STOP_AT = 5         # ...and stop the run at this many


SHELL_FENCES = {"powershell", "ps1", "pwsh", "bash", "sh", "shell", "zsh", "cmd", "bat", "console", "terminal", "text", "txt", ""}


def pasted_code(words):
    """True when a reply in words contains a block of program code (not just a command to type): a fenced block in a programming language, or a long one."""
    for m in re.finditer(r"```([A-Za-z0-9_+-]*)[^\n]*\n(.*?)```", words, re.S):
        lang, body = m.group(1).lower(), m.group(2).strip("\n")
        if lang in SHELL_FENCES and len(body.splitlines()) < 4:
            continue
        return True
    return False


CODE_NUDGE = ("Do not paste code into the chat. Save it in the project with write_file (one file per call), then run it or its tests. "
              "If you really cannot do this, say so in a sentence and say what the user could do.")


def steady_note(items, failures=0):
    """One short line that keeps a small model on ONE step of its checklist: which item is next, and (after two failed tries in a row) to make the retry smaller."""
    todo = [it for it in (items or []) if isinstance(it, dict) and str(it.get("text", "")).strip()]
    if not todo:
        return ""
    left = [it for it in todo if not it.get("done")]
    if not left:
        return "Every checklist item is ticked. Check the result once (run it or its tests), then call finish."
    n = len(todo) - len(left) + 1
    line = f'Now do only step {n} of {len(todo)}: "{str(left[0]["text"]).strip()}". Check it worked, then tick it with todo before the next step.'
    if failures >= 2:
        line += " That step has failed twice: try a smaller change, one thing only, and read the file again first."
    return line


def run_agent(task, generate, sandbox, max_turns=8, system=None, project=True, hooks=None, permissions=None,
              ask=None, context_tokens=None, history=None, chat_mode=False, checks=False, steady=False):
    """Let a model work on `task`. `generate(messages)` returns the model's next reply as text.

    project        show the workspace's EMVRYX.md / AGENTS.md as "Project notes" before the task
    hooks          a Hooks object (default: .emvryx/hooks.json in the workspace, if any)
    permissions    a Permissions object (default: the defaults; `ask(name, args) -> bool` is used for "ask")
    context_tokens when the conversation gets near this size, old steps are compacted (see `compact`)

    history        the conversation so far (the `messages` an earlier call returned): `task` is then the person's next message, not a new task
    chat_mode      a reply in plain words (no tool call) is a message to the person, not a mistake: it ends the turn and `said` is True, so the person can
                   answer. (Once, if the model pastes code into the chat before doing any work, it is told to save the code in the project instead.)

    steady         keep the model on one checklist (todo) item at a time: after each step it is told which item is next, and after two failures in a row to retry smaller

    checks         look at a Python or JSON change before it is made and refuse it if it would not even parse (nothing is saved and the model is told what is wrong, so
                   the person is not asked to approve broken code); say "checked" after a good change; and, once, ask for the tests to be run before finishing if code
                   changed since they last passed and the project has tests.

    Returns {"finished", "summary", "turns", "messages", "episodes"}. The messages are the whole conversation: exactly
    what a training example for the coding skill pack looks like. `episodes` holds the steps that compaction dropped.
    """
    hooks = hooks if hooks is not None else Hooks.load(sandbox)
    permissions = permissions or Permissions(ask=ask)
    notes = load_project_notes(sandbox) if project else ""
    first = (f"Project notes:\n{notes}\n\nTask: {task}" if notes else task)
    if history:
        messages = list(history) + [{"role": "user", "content": task}]
    else:
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": first}]
    episodes = []
    used_tools, nudged = 0, False
    edited_since_test, test_nudged = False, False
    web_unchecked, page_nudges = False, 0                            # a web file changed since the page was last checked (proof before "done")
    plan_items, step_fails = None, 0                                 # the model's todo list (steady mode) and failures in a row
    no_call, no_call_total, bad_calls, repeats = 0, 0, 0, {}        # replies with no tool call at all (the model is chatting, not working); steps repeated
    for turn in range(1, max_turns + 1):
        if context_tokens and estimate_tokens(messages) > context_tokens * 0.7:
            messages, dropped = compact(messages)
            episodes.extend(dropped)
        reply = generate(messages)
        messages.append({"role": "assistant", "content": reply})
        done = False
        try:
            name, args = parse_tool_call(reply)
            if checks and name in ("write_file", "edit_file"):
                problem = preview_check(sandbox.root, name, args)
                if problem:
                    raise ToolError("preview check: this change would break the file, so nothing was saved. " + problem + ". Fix it and send it again.")
            refusal = permissions.check(name, args)
            if refusal:
                raise ToolError(refusal)
            if name == "run":
                blocked = hooks.run(sandbox, "before_run")
                if blocked:
                    raise ToolError("; ".join(blocked))
            if name == "finish":
                if checks and edited_since_test and not test_nudged and has_tests(sandbox.root):
                    test_nudged = True
                    raise ToolError("not finished yet: code changed since the tests last passed. Run them first (python -m unittest), then finish.")
                if checks and web_unchecked and page_nudges < 2 and "check_page" in sandbox.extra_tools:
                    page_nudges += 1
                    raise ToolError("not finished yet: you changed the web page since it was last checked. Open it with check_page first, fix anything it reports, then finish.")
                problems = hooks.run(sandbox, "on_finish")
                if problems:
                    raise ToolError("not finished yet: " + "; ".join(problems))
            result, done = sandbox.call(name, args)
            if name in ("write_file", "edit_file") and isinstance(args, dict) and str(args.get("path", "")).lower().endswith((".html", ".htm", ".css", ".js")):
                web_unchecked = True
            elif name == "check_page":
                web_unchecked = False
            if checks and name in ("write_file", "edit_file") and isinstance(args, dict) and checkable(args.get("path", "")):
                result += " \u00b7 checked \u2713"
                edited_since_test = edited_since_test or str(args.get("path", "")).endswith(".py")
            if checks and name == "run" and isinstance(args, dict) and TEST_COMMAND.search(str(args.get("command", ""))) and str(result).startswith("exit code 0"):
                edited_since_test = False
            if name in ("write_file", "edit_file") and not done:
                problems = hooks.run(sandbox, "after_edit", str(args.get("path", "")))
                if problems:
                    result += "\n" + "\n".join(problems)
        except ToolError as e:
            if chat_mode and str(e).startswith("no tool call found"):
                words = THINK_TAGS.sub("", reply).strip()
                if pasted_code(words) and used_tools == 0 and not nudged:           # code pasted into the chat instead of saved: once, tell it to use the tools
                    nudged = True
                    messages.append({"role": "user", "content": CODE_NUDGE})
                    continue
                return {"finished": False, "said": True, "summary": words, "turns": turn, "messages": messages, "episodes": episodes}
            result, done = f"error: {e}", False
            step_fails += 1
            if steady and plan_items and step_fails >= 2:
                result += "\n" + steady_note(plan_items, step_fails)
            bad_calls = bad_calls + 1 if str(e).startswith(("the tool call is not valid JSON", "the tool call was cut off")) else 0
            if bad_calls >= BAD_CALL_LIMIT:
                return {"finished": False, "turns": turn, "messages": messages, "episodes": episodes, "stopped": "bad_call",
                        "summary": "The model kept sending a tool call that could not be read, so it was stopped instead of looping. This usually means the file was too big "
                                   "to write in one go. Ask for it in smaller parts (for example the page first, then the styles, then the script), or pick Solstice or the Qwen coder."}
            no_call = no_call + 1 if str(e).startswith("no tool call found") else 0
            no_call_total += 1 if str(e).startswith("no tool call found") else 0
            if no_call >= NO_CALL_LIMIT or no_call_total >= NO_CALL_TOTAL:
                said = " ".join(reply.split())[:300]
                return {"finished": False, "turns": turn, "messages": messages, "episodes": episodes, "stopped": "no_tool",
                        "summary": f'The model kept answering in words instead of using its tools, so nothing was done. It said: "{said}" '
                                   "Try a specific task (for example: create hello.py that prints a greeting, with a test), or pick Solstice or the Qwen coder."}
        else:
            no_call = 0
            bad_calls = 0
            step_fails = 0
            used_tools += 1
            if steady:
                if name == "todo" and isinstance(args, dict) and isinstance(args.get("items"), list):
                    plan_items = [it if isinstance(it, dict) else {"text": str(it)} for it in args["items"]]
                if plan_items and not done:
                    result = str(result) + "\n" + steady_note(plan_items)
            if not done:
                key = (name, json.dumps(args, sort_keys=True, default=str), str(result)[:300])     # the same step with the same result again
                repeats[key] = repeats.get(key, 0) + 1
                if repeats[key] >= REPEAT_STOP_AT:
                    return {"finished": False, "turns": turn, "messages": messages, "episodes": episodes, "stopped": "stuck",
                            "summary": f"The model kept repeating the same step ({name}) without making progress, so it was stopped. "
                                       "Try a more specific task, or pick Solstice or the Qwen coder."}
                if repeats[key] >= REPEAT_HINT_AT:
                    result = str(result) + ("\nNote: you already did exactly this and got the same result. Do something different now. "
                                           "If the folder is empty, create the file you need with write_file and test it; do not ask the user anything.")
        if done:
            return {"finished": True, "summary": result, "turns": turn, "messages": messages, "episodes": episodes}
        messages.append({"role": "user", "content": format_result(result)})
    return {"finished": False, "summary": "", "turns": max_turns, "messages": messages, "episodes": episodes}
