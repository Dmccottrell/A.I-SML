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
    write_file(path, content)         create or replace a file
    edit_file(path, old, new)         replace ONE exact piece of text (fails if it isn't found exactly once)
    run(command)                      run a command such as: python -m unittest
    git(args)                         a safe set of git commands: status, diff, log, show, init, add, commit,
                                      branch, switch, checkout, restore, stash, and worktrees ("worktree add NAME")
    diagnostics(path)                 problems in a .py file (syntax errors; more if pyflakes is installed): a
                                      small stand-in for an editor's language server (LSP)
    finish(summary)                   the model says it is done

AROUND THE LOOP (all plain code, nothing the model has to learn except the tool format)
    project notes     YUVRA.md / AGENTS.md / CLAUDE.md in the workspace is shown to the model as "Project notes"
    hooks             .yuvra/hooks.json: commands that run after an edit (e.g. a syntax check), before a command,
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
ALLOWED_PROGRAMS = {"python", "python3", "pytest", "ls", "cat", "head", "tail", "grep", "wc",
                    "echo", "pwd", "sort", "uniq", "diff"}


# git: only these subcommands, and never flags that point outside the workspace or run other programs
GIT_SUBCOMMANDS = {"status", "diff", "log", "show", "init", "add", "commit", "branch", "switch", "checkout",
                   "restore", "stash", "worktree"}
GIT_READ_ONLY = {"status", "diff", "log", "show", "init"}
GIT_BLOCKED_FLAGS = ("-C", "-c", "--git-dir", "--work-tree", "--exec-path", "--upload-pack", "--receive-pack",
                     "--namespace", "--super-prefix", "--config-env", "--output", "--ext-diff", "--textconv")
PROJECT_FILES = ("YUVRA.md", "AGENTS.md", "CLAUDE.md")
HOOKS_FILE = os.path.join(".yuvra", "hooks.json")

# Shown to the model at the start of a coding session (and in every coding lesson), so it knows the tools
TOOL_PROMPT = ("You can use tools. Write one call at a time: <|tool_call|>{\"name\": \"read_file\", \"args\": "
               "{\"path\": \"main.py\"}}<|end_tool_call|> and wait for the result. Tools: list_files(path), "
               "read_file(path, start, end), write_file(path, content), edit_file(path, old, new), run(command), "
               "git(args), diagnostics(path), finish(summary). Small steps; run the tests before you finish; "
               "if a task is too big, say so and suggest a first step.")


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
                 command_prefix=None, allowed_programs=ALLOWED_PROGRAMS):
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

    def write_file(self, path, content):
        full = self.path(path)
        if os.path.isdir(full):
            raise ToolError(f"{path!r} is a folder")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        return f"wrote {self.rel(full)} ({len(content.splitlines())} lines)"

    def edit_file(self, path, old, new):
        full = self.path(path)
        if not os.path.isfile(full):
            raise ToolError(f"{path!r} is not a file")
        with open(full, encoding="utf-8") as f:
            text = f.read()
        if not old:
            raise ToolError("'old' is empty; give the exact text to replace")
        n = text.count(old)
        if n == 0:
            raise ToolError("the text in 'old' was not found. Copy it exactly from read_file (without the line numbers)")
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
        kwargs = {"preexec_fn": _limits} if sys.platform.startswith("linux") else {}
        try:
            r = subprocess.run((self.prefix if wrap else []) + argv, cwd=self.root, env=env, capture_output=True,
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
            raise ToolError(f"{program!r} is not allowed. Allowed: {', '.join(sorted(self.allowed))}")
        if program in ("python", "python3"):
            argv[0] = sys.executable                     # the same Python we are running
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
               "GIT_AUTHOR_NAME": "Yuvra agent", "GIT_AUTHOR_EMAIL": "agent@localhost",
               "GIT_COMMITTER_NAME": "Yuvra agent", "GIT_COMMITTER_EMAIL": "agent@localhost"}
        return self._exec(["git", "-c", f"core.hooksPath={os.devnull}", "-c", "init.defaultBranch=main"] + argv, env)

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


# -------------------------------------------------------------------- the loop
def parse_tool_call(text):
    """The first tool call in the model's text -> (name, args). Raises ToolError if it can't be read."""
    m = TOOL_CALL.search(text)
    if not m:
        raise ToolError('no tool call found. Write: <|tool_call|>{"name": "...", "args": {...}}<|end_tool_call|>')
    try:
        call = json.loads(m.group(1))
        return call["name"], call.get("args", {})
    except (json.JSONDecodeError, KeyError, TypeError):
        raise ToolError('the tool call is not valid JSON with a "name". Example: '
                        '{"name": "read_file", "args": {"path": "main.py"}}')


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
    """Commands from .yuvra/hooks.json that run at set moments, like [{"event": "after_edit", "match": "*.py",
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


def load_project_notes(sandbox, limit=1200):
    """The text of YUVRA.md / AGENTS.md / CLAUDE.md in the workspace (the first found), or ""."""
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


def run_agent(task, generate, sandbox, max_turns=8, system=None, project=True, hooks=None, permissions=None,
              ask=None, context_tokens=None):
    """Let a model work on `task`. `generate(messages)` returns the model's next reply as text.

    project        show the workspace's YUVRA.md / AGENTS.md / CLAUDE.md as "Project notes" before the task
    hooks          a Hooks object (default: .yuvra/hooks.json in the workspace, if any)
    permissions    a Permissions object (default: the defaults; `ask(name, args) -> bool` is used for "ask")
    context_tokens when the conversation gets near this size, old steps are compacted (see `compact`)

    Returns {"finished", "summary", "turns", "messages", "episodes"}. The messages are the whole conversation: exactly
    what a training example for the coding skill pack looks like. `episodes` holds the steps that compaction dropped.
    """
    hooks = hooks if hooks is not None else Hooks.load(sandbox)
    permissions = permissions or Permissions(ask=ask)
    notes = load_project_notes(sandbox) if project else ""
    first = (f"Project notes:\n{notes}\n\nTask: {task}" if notes else task)
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": first}]
    episodes = []
    for turn in range(1, max_turns + 1):
        if context_tokens and estimate_tokens(messages) > context_tokens * 0.7:
            messages, dropped = compact(messages)
            episodes.extend(dropped)
        reply = generate(messages)
        messages.append({"role": "assistant", "content": reply})
        done = False
        try:
            name, args = parse_tool_call(reply)
            refusal = permissions.check(name, args)
            if refusal:
                raise ToolError(refusal)
            if name == "run":
                blocked = hooks.run(sandbox, "before_run")
                if blocked:
                    raise ToolError("; ".join(blocked))
            if name == "finish":
                problems = hooks.run(sandbox, "on_finish")
                if problems:
                    raise ToolError("not finished yet: " + "; ".join(problems))
            result, done = sandbox.call(name, args)
            if name in ("write_file", "edit_file") and not done:
                problems = hooks.run(sandbox, "after_edit", str(args.get("path", "")))
                if problems:
                    result += "\n" + "\n".join(problems)
        except ToolError as e:
            result, done = f"error: {e}", False
        if done:
            return {"finished": True, "summary": result, "turns": turn, "messages": messages, "episodes": episodes}
        messages.append({"role": "user", "content": format_result(result)})
    return {"finished": False, "summary": "", "turns": max_turns, "messages": messages, "episodes": episodes}
