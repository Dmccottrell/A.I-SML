"""
vryxcode.py - VryxCode: Emvryx's coding assistant, in the terminal.

WHAT THIS FILE DOES
    You describe a coding task; a model works on it in a loop: it reads your files, writes or edits them, runs the tests, reads the failure and
    tries again, until it says it is done. The tools, the sandbox, the permissions and the loop are `harness.py`; this file connects them to a model
    running in llama-server and gives you the command.

    * Only the higher models: Equinox 2 (small tasks), Solstice 2 and Apogee 2 (`"vryxcode": true` in models.json). Ember and Flare are too small.
    * It works in your project folder, but only inside it ("..", absolute paths and symlinks outside are refused), with a short list of
      allowed programs, a time limit and (on Linux) no network. That protects against a small model's mistakes, not against a hostile program.
    * It asks before it changes anything (shows what), except for running the tests. `--yes` stops the questions for edits and runs;
      git commits and unknown tools always ask.
    * It is a small model: good for a function, a bug fix, a test, a few files. Not for big refactors. If a task is too big it should say so.

Usage:  1. start a model (see open_models.llama_args):  llama-server -m export/open/solstice-2/my-ai-q4_k_m.gguf -c 32768 --port 8080
        2. cd into your project and run:                python vryxcode.py --model solstice-2 "add a function to utils.py that slugifies a title, with tests"
        a coding model from outside Emvryx:             python vryxcode.py --coder qwen2.5-coder-14b "task"
        no task = interactive:                          python vryxcode.py --model solstice-2
        try it without any model:                       python vryxcode.py --demo
"""
import argparse
import json
import os
import re
import sys
import tempfile
import urllib.request

import harness

THINK = re.compile(r"<think>.*?</think>", re.S)
SYSTEM = ("You are VryxCode, Emvryx's coding assistant. You work in the user's project folder using tools. "
          + harness.TOOL_PROMPT +
          " Always write exactly one tool call per reply, and nothing after it. Read before you edit. Keep changes small and match the project's style. "
          "Do not invent files or results: use the tools to look. When the work is done and the tests pass, call finish with a short summary.")
SAFE_RUNS = ("python -m unittest", "python3 -m unittest", "python -m pytest", "pytest")      # tests may run without asking
ELIGIBLE_NOTE = {"equinox-2": "Equinox 2 is a small model: give it small tasks (one function, one file)."}


class LlamaChat:
    """A llama-server (llama.cpp) chat endpoint: the server applies the model's own chat template."""

    def __init__(self, url="http://127.0.0.1:8080", temperature=0.2, max_tokens=1024, timeout=600):
        self.url, self.temperature, self.max_tokens, self.timeout = url.rstrip("/"), temperature, max_tokens, timeout

    def __call__(self, messages):
        body = json.dumps({"model": "local", "messages": messages, "temperature": self.temperature, "max_tokens": self.max_tokens,
                           "stream": False}).encode()
        req = urllib.request.Request(self.url + "/v1/chat/completions", data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.load(r)
        except OSError as e:
            raise SystemExit(f"can't reach the model at {self.url} ({e}). Start llama-server first (see the top of vryxcode.py).")
        return THINK.sub("", data["choices"][0]["message"]["content"]).strip()


class ScriptedChat:
    """A stand-in 'model' that answers from a list: for the demo and the tests (no AI)."""

    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    def __call__(self, messages):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0) if self.replies else harness_call("finish", summary="(no more scripted replies)")


def harness_call(name, **args):
    return f"<|tool_call|>{json.dumps({'name': name, 'args': args})}<|end_tool_call|>"


DEMO = [
    harness_call("write_file", path="slug.py", content='import re\n\n\ndef slugify(title):\n    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")\n'),
    harness_call("write_file", path="test_slug.py", content='import unittest\nfrom slug import slugify\n\n\nclass T(unittest.TestCase):\n'
                 '    def test_basic(self):\n        self.assertEqual(slugify("Hello, World!"), "hello-world")\n\n\nif __name__ == "__main__":\n    unittest.main()\n'),
    harness_call("run", command="python -m unittest"),
    harness_call("finish", summary="Added slugify() in slug.py with a test; the tests pass."),
]


def check_model(model_id):
    """(ok, message). Only models flagged "vryxcode" in models.json may run it."""
    here = os.path.dirname(os.path.abspath(__file__))
    models = json.load(open(os.path.join(here, "models.json"), encoding="utf-8"))["models"]
    by_id = {m["id"]: m for m in models}
    ok_ids = [m["id"] for m in models if m.get("vryxcode")]
    names = ", ".join(f"{by_id[i]['name']} {by_id[i]['version']:g}" for i in ok_ids)
    if model_id not in by_id:
        return False, f"unknown model {model_id!r}. VryxCode runs on: {names}."
    if not by_id[model_id].get("vryxcode"):
        m = by_id[model_id]
        return False, f"VryxCode does not run on {m['name']} {m['version']:g}: it is too small for coding work. It runs on {names}."
    return True, ELIGIBLE_NOTE.get(model_id, "")


def gate(model_id, coder=None):
    """(ok, message). With `coder` (a label for an outside coding model you started in llama-server, e.g. qwen2.5-coder-14b) the Emvryx model gate is skipped:
    the run is labelled as an outside model, not an Emvryx one. Without it, only Equinox 2 and above may run VryxCode."""
    if coder:
        return True, f"Using the coding model '{coder}' (an outside model, not an Emvryx model). Whatever it scores is its score, not an Emvryx result."
    return check_model(model_id)


def preview(name, args):
    if name == "write_file":
        text = str(args.get("content", ""))
        shown = "\n".join("  + " + l for l in text.splitlines()[:12])
        return f"write {args.get('path')} ({len(text.splitlines())} lines)\n{shown}"
    if name == "edit_file":
        return f"edit {args.get('path')}\n  - {str(args.get('old', ''))[:300]}\n  + {str(args.get('new', ''))[:300]}"
    return f"{name} {json.dumps(args)[:300]}"


def make_ask(auto_yes=False, input_fn=input, out=print):
    """The permission question. y = yes, n = no, a = yes and don't ask again for this kind of action."""
    always = set()

    def ask(name, args):
        if name == "run" and str(args.get("command", "")).strip().startswith(SAFE_RUNS):
            return True
        if auto_yes and name in ("write_file", "edit_file", "run"):
            return True
        if name in always:
            return True
        out(preview(name, args))
        answer = input_fn("Allow? [y/N/a=always] ").strip().lower()
        if answer == "a":
            always.add(name)
        return answer in ("y", "a", "yes")
    return ask


def run_task(task, generate, workspace, ask, max_turns=12, context_tokens=None, extra_programs=(), out=print):
    """Run one task. Returns harness.run_agent's result (finished, summary, turns, messages)."""
    programs = set(harness.ALLOWED_PROGRAMS) | set(extra_programs)
    rules = {"write_file": "ask", "edit_file": "ask", "run": "ask"}
    with harness.Sandbox(workspace=workspace, allowed_programs=programs) as sandbox:
        result = harness.run_agent(task, generate, sandbox, max_turns=max_turns, system=SYSTEM, ask=ask, context_tokens=context_tokens,
                                   permissions=harness.Permissions(rules=rules, ask=ask))
    out(("Done: " if result["finished"] else "Stopped without finishing: ") + (result["summary"] or f"{result['turns']} steps used") )
    return result


def main(argv=None, input_fn=input):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task", nargs="*", help="what to build or fix (no task: interactive)")
    p.add_argument("--model", default="solstice-2", help="equinox-2, solstice-2 or apogee-2 (the models VryxCode runs on)")
    p.add_argument("--llama", default="http://127.0.0.1:8080", help="the llama-server running that model")
    p.add_argument("--workspace", default=".", help="the project folder (default: here)")
    p.add_argument("--yes", action="store_true", help="don't ask before edits and runs (git commits and unknown tools still ask)")
    p.add_argument("--max-turns", type=int, default=12)
    p.add_argument("--context", type=int, default=32768, help="the context the server was started with (old steps are summarised near it)")
    p.add_argument("--allow", default="", help="more programs the model may run, comma separated (e.g. node,npm)")
    p.add_argument("--demo", action="store_true", help="a scripted run in a temporary folder: no model, shows the loop")
    p.add_argument("--coder", default=None, metavar="LABEL", help="use an outside coding model that llama-server is running (e.g. qwen2.5-coder-14b), instead of an Emvryx model")
    a = p.parse_args(argv)

    ok, note = gate(a.model, a.coder)
    if not ok:
        raise SystemExit(note)
    if note:
        print(note)
    extra = [x for x in a.allow.split(",") if x.strip()]
    if a.demo:
        workspace = tempfile.mkdtemp(prefix="vryxcode_demo_")
        print(f"demo: a scripted model builds a tiny project in {workspace}")
        run_task("Write slugify(title) in slug.py with a unit test.", ScriptedChat(DEMO), workspace, make_ask(True, input_fn),
                 a.max_turns)
        return 0
    generate = LlamaChat(a.llama)
    workspace = os.path.abspath(a.workspace)
    ask = make_ask(a.yes, input_fn)
    tasks = [" ".join(a.task)] if a.task else None
    while True:
        if tasks is None:
            try:
                task = input_fn("task> ").strip()
            except EOFError:
                break
            if task in ("", "exit", "quit"):
                break
        else:
            if not tasks:
                break
            task = tasks.pop(0)
        run_task(task, generate, workspace, ask, a.max_turns, a.context, extra)
    return 0


if __name__ == "__main__":
    sys.exit(main())
