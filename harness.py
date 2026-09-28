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
    finish(summary)                   the model says it is done

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
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
        if os.name == "nt":
            env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")
        kwargs = {"preexec_fn": _limits} if sys.platform.startswith("linux") else {}
        try:
            r = subprocess.run(self.prefix + argv, cwd=self.root, env=env, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=self.command_timeout,
                               stdin=subprocess.DEVNULL, **kwargs)
        except subprocess.TimeoutExpired:
            raise ToolError(f"the command took longer than {self.command_timeout} s and was stopped")
        except OSError as e:
            raise ToolError(f"could not run it: {e}")
        out = (r.stdout + ("\n" + r.stderr if r.stderr else "")).strip()
        return cut(f"exit code {r.returncode}\n{out}" if out else f"exit code {r.returncode}", self.output_limit)

    def call(self, name, args):
        """Run one tool. Returns (text for the model, whether the model said it is finished)."""
        if name == "finish":
            return str(args.get("summary", "")), True
        tools = {"list_files": self.list_files, "read_file": self.read_file, "write_file": self.write_file,
                 "edit_file": self.edit_file, "run": self.run}
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


def run_agent(task, generate, sandbox, max_turns=8, system=None):
    """Let a model work on `task`. `generate(messages)` returns the model's next reply as text.

    Returns {"finished": bool, "summary": str, "turns": int, "messages": [...]}. The messages
    are the whole conversation: exactly what a training example for the coding skill pack looks like.
    """
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": task}]
    for turn in range(1, max_turns + 1):
        reply = generate(messages)
        messages.append({"role": "assistant", "content": reply})
        try:
            name, args = parse_tool_call(reply)
            result, done = sandbox.call(name, args)
        except ToolError as e:
            result, done = f"error: {e}", False
        if done:
            return {"finished": True, "summary": result, "turns": turn, "messages": messages}
        messages.append({"role": "user", "content": format_result(result)})
    return {"finished": False, "summary": "", "turns": max_turns, "messages": messages}
