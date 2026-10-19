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
        2. cd into your project and run:                python coding/vryxcode.py --model solstice-2 "add a function to utils.py that slugifies a title, with tests"
        a coding model from outside Emvryx:             python coding/vryxcode.py --coder coder-14b "task"
        no task = interactive:                          python coding/vryxcode.py --model solstice-2
        try it without any model:                       python coding/vryxcode.py --demo
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import argparse
import json
import os
import re
import sys
import queue
import socket
import tempfile
import threading
import urllib.error
import urllib.request

import harness

THINK = re.compile(r"<think>.*?</think>", re.S)
SYSTEM = ("You are VryxCode, Emvryx's coding assistant. You work in the user's project folder using tools, and you can talk to them. "
          + harness.TOOL_PROMPT +
          " To use a tool, write exactly one tool call and nothing after it. Read before you edit. Keep changes small and match the project's style. "
          "Do not invent files or results: use the tools to look. If the task is vague or the folder is empty, do not ask questions or wait: choose something small and sensible yourself, "
          "create the files with write_file, and run the tests. "
          "You can also answer in plain words with no tool call: to answer a question, to explain, to say what the user has to do themselves (for example a command to type in "
          "PowerShell, written in a code block), to say what you cannot do from inside the project folder (installing programs, using the internet, anything outside the folder), "
          "or to recommend what to do next. A reply in plain words ends your turn and the user can answer. The user is not an expert: use plain language, short sentences, no jargon. "
          "WHAT TO BUILD WITH: if the user names a language or framework, use it. Otherwise choose what fits what they asked for and say why in one short sentence (they can ask for something else). "
          "A website, landing page, small web app, browser game or tool with buttons: plain HTML, CSS and JavaScript in files, with the page called index.html (no build step; libraries can be loaded from a CDN with a script tag; "
          "the person sees it live in the Preview tab, which also lists the page's errors). A script, automation, data job or file processing: Python. A command-line tool: Python (Go or Rust only if they want one fast program). "
          "A web server or API: Python (Flask or FastAPI) or Node (Express), with SQLite for data. A phone app: a web app that works well on phones first, or React Native or Flutter if they want a store app. "
          "A desktop app: Python or a web page, or Electron or Tauri to package it. A game: JavaScript on a canvas in the browser, or Godot or Unity for a bigger one. Keep the first version small and in one language. "
          "WHAT YOUR SANDBOX CAN DO: there is no internet and you cannot install packages. You have Python (with flask, fastapi, requests, numpy and pytest), and Node.js, a C and C++ compiler and SQLite when they are installed. "
          "You cannot run npm, pip, a phone emulator or a server other people can visit. For anything that needs those, write the code and tell the user the exact commands to run themselves "
          "(for example npm install, then npm run dev) in a code block. "
          "When the work is done and the tests pass, call finish. Its summary says, in a few friendly lines, what you changed, how to run it, and what you recommend next; "
          'its optional next is a list of up to three short follow-up tasks the user could tap, for example ["Add a test for empty input"].')
PLAN_NOTE = (" PLAN MODE: do not change anything in this turn. You may look around with list_files, read_file and diagnostics. Then reply in plain words with a short numbered plan "
             "(3 to 7 steps): what you will build or change, in which files, and how you will check it works. End by asking whether to go ahead. Do not write code in the reply, and do not call finish.")
TODO_NOTE = (" For a job with more than two steps, first call todo with a short checklist, for example {\"name\": \"todo\", \"args\": {\"items\": [{\"text\": \"Write slug.py\", \"done\": false}, "
             "{\"text\": \"Run the tests\", \"done\": false}]}}, and call it again to tick items off as you finish them. Keep each item a few words. Then work on one item at a time: do it, check it, tick it, and only then start the next.")
BUILD_NOTE = (" BUILDING SOMETHING BIGGER (several files or steps): work like a careful engineer. "
              "1) First decide the files and what each one does, and call todo with one item per milestone (a milestone is a piece you can test on its own). "
              "2) For each milestone: write the code, write or extend a unit test for it, run the tests, fix until they pass, then tick the item. "
              "3) Each time the tests pass, VryxCode saves a checkpoint. If a change breaks things and a few tries do not fix it, call rollback (no arguments) "
              "to go back to the last checkpoint, then try a different way. "
              "4) Keep each file focused (under about 300 lines). Read a file again before you edit it if you have not looked at it recently, and copy the old text exactly. "
              "5) Follow every name in the request exactly (files, functions, classes, commands, output text): other code will rely on them. "
              "6) At the end run all the tests once more, then finish.")
BUILD_STEPS = 150                  # steps per message in the long-build loop (a model's "vryxcode_steps" in models.json can set its own)
# VryxCode's effort (feature flag vryxcode_effort: no model picker, only this): how many steps a message may take, and whether the model thinks first.
EFFORTS = {"quick": {"steps": 0.5, "think": False, "note": "Small fixes and questions. Fewest steps, fastest."},
           "balanced": {"steps": 1.0, "think": False, "note": "Most tasks. The usual number of steps."},
           "deep": {"steps": 1.5, "think": True, "note": "Bigger builds and hard bugs. More steps, and it thinks before each one."}}


FULL_STEPS, FULL_STEPS_CAP = 500, 1000     # the full agent (Claude Code-style): it keeps going until the task is done, so the budget is only a safety net


def effort_steps(turns, effort, cap=400):
    """The step budget for a message at this effort (Quick about half, Deep half again more), between 6 and cap."""
    return max(6, min(cap, round(int(turns) * EFFORTS.get(effort, EFFORTS["balanced"])["steps"])))


def pick_auto(models):
    """The model VryxCode uses by itself (no picker): a model made for long builds (VryxCode 3) first, then Apogee 3; until one of them is ready,
    the newest, biggest ready model (generation first, so Solstice 3 comes before Apogee 2). `models` is code_models(); outside models are never picked."""
    ready = [m for m in models if not m.get("outside") and m.get("state") == "ready"]
    family = lambda m: next((i for i, f in enumerate(("apogee", "solstice", "equinox")) if m["id"].startswith(f)), 9)
    try_float = lambda v: float(v) if isinstance(v, (int, float)) or str(v).replace(".", "", 1).isdigit() else 0.0
    return min(ready, key=lambda m: (not m.get("build"), m["id"] != "apogee-3", -try_float(m.get("version")), family(m)))["id"] if ready else None
SAFE_RUNS = ("python -m unittest", "python3 -m unittest", "python -m pytest", "pytest")      # tests may run without asking
ELIGIBLE_NOTE = {"equinox-2": "Equinox 2 is a small model: give it small tasks (one function, one file)."}


def _hang_up(response):
    """Cut the connection right now, even while another thread is blocked reading it (closing the response would wait for that read).
    llama-server stops generating when its client leaves, so the graphics card is free again at once."""
    sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
    try:
        if sock is not None:
            sock.shutdown(socket.SHUT_RDWR)
        else:
            response.close()
    except (OSError, ValueError):
        pass


class Interrupted(Exception):
    """The person pressed Stop while the model was loading or writing."""


class NoInfill(Exception):
    """This model's llama-server cannot fill in the middle (the model has no fill-in-the-middle tokens)."""


class LlamaChat:
    """A llama-server (llama.cpp) chat endpoint: the server applies the model's own chat template.

    The reply is STREAMED: while it is being written `on_delta(info)` is called with what is known so far, so the page can show that the model is working
    (see Session.wrap). Qwen3 models "think" before every answer by default, which can take most of a step's time and tokens; for coding steps that is
    switched off (`thinking=False`, sent as chat_template_kwargs) because the steps are short and the thinking is thrown away anyway.
    `should_stop()` is asked every fifth of a second, also while the model is still reading the prompt and nothing has come back yet: when it says yes
    the connection is closed (llama-server stops writing when the client leaves) and Interrupted is raised, so Stop works at once."""

    def __init__(self, url="http://127.0.0.1:8080", temperature=0.2, max_tokens=4096, timeout=600, thinking=False):
        self.url, self.temperature, self.max_tokens, self.timeout, self.thinking = url.rstrip("/"), temperature, max_tokens, timeout, thinking
        self.cut_off = False                               # True when the last reply stopped because it reached max_tokens (a long file does that)
        self.usage = None                                  # {"fresh_in", "cached_in", "out"} of the last call (the app counts it)
        self.on_delta = None                               # function(info) or None; info = {"text", "thinking_chars", "chunks"}
        self.should_stop = None                            # function() -> bool, or None

    def __call__(self, messages):
        self.cut_off = False
        body = json.dumps({"model": "local", "messages": messages, "temperature": self.temperature, "max_tokens": self.max_tokens,
                           "stream": True, "stream_options": {"include_usage": True}, "cache_prompt": True,
                           "chat_template_kwargs": {"enable_thinking": bool(self.thinking)}}).encode()
        box, out = {}, queue.Queue()

        def work():
            req = urllib.request.Request(self.url + "/v1/chat/completions", data=body, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    box["r"] = r
                    if box.get("stopped"):                 # Stop was pressed before the first byte came back
                        _hang_up(r)
                        return
                    if "text/event-stream" in (r.headers.get("Content-Type") or ""):
                        out.put(("done", self._read_stream(r)))
                    else:                                  # a server that answered in one piece
                        data = json.load(r)
                        out.put(("done", (data["choices"][0]["message"]["content"], data.get("usage") or {}, data.get("timings") or {})))
            except BaseException as e:                     # noqa: BLE001 - handed to the caller's thread
                out.put(("error", e))
        threading.Thread(target=work, daemon=True).start()
        while True:
            try:
                kind, val = out.get(timeout=0.2)
                break
            except queue.Empty:
                if self.should_stop and self.should_stop():
                    box["stopped"] = True
                    if box.get("r") is not None:
                        _hang_up(box["r"])
                    raise Interrupted()
        if kind == "error":
            if isinstance(val, OSError):
                raise SystemExit(f"can't reach the model at {self.url} ({val}). Start llama-server first (see the top of vryxcode.py).")
            raise val
        text, usage, timings = val
        cached = int(timings.get("cache_n") or 0)
        if "prompt_tokens" in usage:
            prompt = int(usage["prompt_tokens"])
            self.usage = {"fresh_in": max(0, prompt - cached), "cached_in": min(cached, prompt), "out": int(usage.get("completion_tokens", 0))}
        return THINK.sub("", text).strip()

    def infill(self, prefix, suffix, n_predict=64, timeout=30):
        """Fill-in-the-middle through llama-server's /infill (for inline autocomplete): the text that belongs between `prefix` and `suffix`, or NoInfill when this model
        has no fill-in-the-middle tokens. Fast and small: no chat template, no thinking."""
        body = json.dumps({"input_prefix": prefix, "input_suffix": suffix, "n_predict": int(n_predict), "temperature": 0.1, "top_k": 40, "cache_prompt": True,
                           "stop": ["\n\n\n"]}).encode()
        req = urllib.request.Request(self.url + "/infill", data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (400, 404, 405, 500, 501):                 # llama-server answers an error when the model has no FIM tokens
                raise NoInfill() from e
            raise
        timings = data.get("timings") or {}
        cached = int(timings.get("cache_n") or data.get("tokens_cached") or 0)
        prompt = int(data.get("tokens_evaluated") or 0)
        self.usage = {"fresh_in": max(0, prompt - cached), "cached_in": min(cached, prompt), "out": int(data.get("tokens_predicted") or 0)}
        return str(data.get("content") or "")

    def _read_stream(self, r):
        text, thought, chunks, usage, timings = "", 0, 0, {}, {}
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except ValueError:
                continue
            usage = chunk.get("usage") or usage
            timings = chunk.get("timings") or timings
            if ((chunk.get("choices") or [{}])[0].get("finish_reason")) == "length":
                self.cut_off = True
            delta = ((chunk.get("choices") or [{}])[0].get("delta")) or {}
            piece, reasoning = delta.get("content") or "", delta.get("reasoning_content") or ""
            if not piece and not reasoning:
                continue
            chunks += 1
            text += piece
            thought += len(reasoning)
            if self.on_delta:
                try:
                    self.on_delta({"text": text, "thinking_chars": thought, "chunks": chunks})
                except Exception:                          # a display problem must never break the model call
                    pass
        return text, usage, timings


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
    import emvryx_paths
    with open(os.path.join(emvryx_paths.ROOT, "models.json"), encoding="utf-8") as f:
        models = json.load(f)["models"]
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
    """(ok, message). With `coder` (a label for an outside coding model you started in llama-server, e.g. coder-14b) the Emvryx model gate is skipped:
    the run is labelled as an outside model, not an Emvryx one. Without it, only Equinox 2 and above may run VryxCode."""
    if coder:
        return True, f"Using the coding model '{coder}' (an outside model, not an Emvryx model). Whatever it scores is its score, not an Emvryx result."
    return check_model(model_id)


def preview(name, args):
    if name == "write_file":
        text = str(args.get("content", ""))
        shown = "\n".join("  + " + l for l in text.splitlines()[:12])
        more = " \u00b7 added to the end" if args.get("append") else ""
        return f"write {args.get('path')} ({len(text.splitlines())} lines){more}\n{shown}"
    if name == "edit_file":
        return f"edit {args.get('path')}\n  - {str(args.get('old', ''))[:300]}\n  + {str(args.get('new', ''))[:300]}"
    if name == "todo":
        return "todo " + json.dumps(args)[:1500]
    if name == "rollback":
        return "rollback: put the project back as it was at the last checkpoint (the last time the tests passed); files made since are removed"
    if name == "github":
        return {"pull": "github pull: fetch new work from the linked GitHub repository (fast-forward only)",
                "push": "github push: send this project's current branch to the linked GitHub repository"}.get(str(args.get("action")), f"github {args.get('action')}")
    return f"{name} {json.dumps(args)[:300]}"


def make_ask(auto_yes=False, input_fn=input, out=print):
    """The permission question. y = yes, n = no, a = yes and don't ask again for this kind of action."""
    always = set()

    def ask(name, args):
        if name == "run" and str(args.get("command", "")).strip().startswith(SAFE_RUNS):
            return True
        if auto_yes and name in ("write_file", "edit_file", "run", "rollback"):
            return True
        if name in always:
            return True
        out(preview(name, args))
        answer = input_fn("Allow? [y/N/a=always] ").strip().lower()
        if answer == "a":
            always.add(name)
        return answer in ("y", "a", "yes")
    return ask


GITHUB_TOOL_NOTE = (" github(action) with action status, pull or push works with the GitHub repository this project is linked to: commit with git first; "
                    "the user is asked before anything is pulled or pushed.")


CHECK_PAGE_NOTE = (" check_page(path, width, height) opens a web page of this project in a hidden browser (phone size by default), clicks around, and tells you the errors and "
                   "layout problems it finds (sideways scrolling, tiny buttons, broken pictures, no labels) with a screenshot for the person. Use it after you build or change a page, "
                   "fix what it reports, and check again. It cannot reach the internet except a few common CDNs. "
                   "React from a CDN in one HTML file: load react, react-dom AND @babel/standalone (unpkg.com), and put the app in <script type=\"text/babel\">: "
                   "a plain <script> cannot run JSX tags like <div>.")


HELPER_STEPS = 25
HELPER_SYSTEM = ("You are a helper for VryxCode. Another agent gave you one question about the project in this folder. Look with your tools (list_files, read_file, "
                 "glob, grep, and commands that only look), then answer in a few short lines: the files, functions and line numbers that matter, and what you found. "
                 "You cannot change anything. " + harness.TOOL_PROMPT)


def make_helper(generate, sandbox, context_tokens=None):
    """The helper tool (a subagent, like Claude Code's): a question goes to a fresh conversation that can only look, and its short answer comes back, so a big
    search does not fill the main conversation's memory."""
    def helper(task=None, question=None):
        task = str(task or question or "").strip()
        if not task:
            raise harness.ToolError("helper needs a task, like: find where the login form is handled")
        perms = harness.Permissions(rules={"write_file": "deny", "edit_file": "deny", "git": "deny", "run": "ask"},
                                    ask=lambda name, args: name == "run" and harness.read_only_command((args or {}).get("command", "")))
        r = harness.run_agent(task, generate, sandbox, max_turns=HELPER_STEPS, system=HELPER_SYSTEM, project=False, permissions=perms,
                              context_tokens=context_tokens, chat_mode=True, hooks=harness.Hooks())
        answer = (r.get("summary") or "").strip()
        return "Helper's answer: " + (harness.cut(answer, 3000) if answer else f"none (it used its {r.get('turns', 0)} steps without answering; ask a narrower question)")
    return helper


def make_todo():
    """The checklist tool: todo(items=[{"text", "done"}]). It only records the list (the page shows it); it changes nothing in the project."""
    def todo(items=None):
        if not isinstance(items, list) or not items:
            raise harness.ToolError('todo needs items: a list like [{"text": "Write slug.py", "done": false}]')
        clean = []
        for it in items[:12]:
            if isinstance(it, dict):
                clean.append({"text": str(it.get("text", "")).strip()[:100], "done": bool(it.get("done"))})
            else:
                clean.append({"text": str(it).strip()[:100], "done": False})
        clean = [c for c in clean if c["text"]]
        if not clean:
            raise harness.ToolError("todo items need some text")
        return f"todo list saved: {sum(c['done'] for c in clean)} of {len(clean)} done. Carry on with the next item."
    return todo


def run_task(task, generate, workspace, ask, max_turns=12, context_tokens=None, extra_programs=(), out=print, tools=None, git_identity=None, command_prefix=None, container=False,
             history=None, chat_mode=False, checks=True, plan=False, todo=False, remote=False, lang_note="", build=False, full=False):
    """Run one task. Returns harness.run_agent's result (finished, summary, turns, messages).
    `tools` is {name: function(**args) -> text} of extra tools (the GitHub tool, run by the server, never by the sandbox).
    `plan` looks only (no edits, runs or git changes) and answers with a plan; `todo` adds the checklist tool the page shows as a to-do list.
    `build` is the long-build loop (VryxCode 3, harness.run_agent's build mode): checkpoints when the tests pass, the rollback tool, a step back after the
    same failure, the checklist kept through folds. It implies `todo`.
    `full` is the Claude Code-style agent (harness.FULL_TOOL_NOTE): glob, grep, 2,000-line reads, replace_all, commands up to 10 minutes, the long-build loop,
    and a real terminal when the commands run in the container or on the cloud machine."""
    build = (bool(build) or bool(full)) and not plan
    todo = todo or build
    programs = set(harness.ALLOWED_PROGRAMS) | set(extra_programs)
    rules = {"write_file": "ask", "edit_file": "ask", "run": "ask", "helper": "allow", "ask_user": "allow"}
    if plan:
        rules = {"write_file": "deny", "edit_file": "deny", "run": "deny", "git": "deny", "github": "deny", "helper": "allow", "ask_user": "allow"}
        if full:                                                  # as in Claude Code's plan mode: commands that only look may still run
            rules["run"] = "ask"
            ask = lambda name, args: name == "run" and harness.read_only_command((args or {}).get("command", ""))
    tools = dict(tools or {})
    if todo:
        tools["todo"] = make_todo()
        rules["todo"] = "allow"
    if build:
        rules["rollback"] = "ask"                                 # it rewrites files, so it asks like an edit (--yes / Edit without asking: it just runs)
    kw = {"git_identity": git_identity} if git_identity else {}
    if full:
        kw["full"] = True
    if command_prefix:
        kw.update(command_prefix=command_prefix, container=container, remote=remote)
        if remote:
            kw["command_timeout"] = 120                       # copying the project over and back takes a while
    with harness.Sandbox(workspace=workspace, allowed_programs=programs, **kw) as sandbox:
        for name, fn in (tools or {}).items():
            if full or name != "ask_user":
                sandbox.register_tool(name, fn)
        if sandbox.full:                                          # the helper only looks, so Plan first may use it too
            sandbox.register_tool("helper", make_helper(generate, sandbox, context_tokens))
        system = SYSTEM + (harness.FULL_TOOL_NOTE if sandbox.full else "") + (harness.SHELL_NOTE if sandbox.shell else "") + (GITHUB_TOOL_NOTE if "github" in (tools or {}) else "") + (CHECK_PAGE_NOTE if "check_page" in (tools or {}) else "") + (TODO_NOTE if todo else "") + (BUILD_NOTE if build else "") + (PLAN_NOTE if plan else "") + (lang_note or "")
        result = harness.run_agent(task, generate, sandbox, max_turns=max_turns, system=system, ask=ask, context_tokens=context_tokens,
                                   permissions=harness.Permissions(rules=rules, ask=ask), history=history, chat_mode=chat_mode, checks=checks, steady=todo, build=build)
    out(("Done: " if result["finished"] else "Stopped without finishing: ") + (result["summary"] or f"{result['turns']} steps used") )
    return result


def main(argv=None, input_fn=input):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task", nargs="*", help="what to build or fix (no task: interactive)")
    p.add_argument("--model", default="solstice-2", help="equinox-2, solstice-2 or apogee-2 (the models VryxCode runs on)")
    p.add_argument("--llama", default="http://127.0.0.1:8080", help="the llama-server running that model")
    p.add_argument("--workspace", default=".", help="the project folder (default: here)")
    p.add_argument("--yes", action="store_true", help="don't ask before edits and runs (git commits and unknown tools still ask)")
    p.add_argument("--max-turns", type=int, default=None, help="steps per task (default 12, or 150 with --build)")
    p.add_argument("--build", action="store_true", help="the long-build loop for multi-step projects: checkpoints, rollback, a step back when stuck (VryxCode 3)")
    p.add_argument("--context", type=int, default=32768, help="the context the server was started with (old steps are summarised near it)")
    p.add_argument("--allow", default="", help="more programs the model may run, comma separated (e.g. node,npm)")
    p.add_argument("--demo", action="store_true", help="a scripted run in a temporary folder: no model, shows the loop")
    p.add_argument("--coder", default=None, metavar="LABEL", help="use an outside coding model that llama-server is running (e.g. coder-14b), instead of an Emvryx model")
    a = p.parse_args(argv)

    ok, note = gate(a.model, a.coder)
    if not ok:
        raise SystemExit(note)
    if note:
        print(note)
    extra = [x for x in a.allow.split(",") if x.strip()]
    if a.max_turns is None:
        a.max_turns = BUILD_STEPS if a.build else 12
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
        run_task(task, generate, workspace, ask, a.max_turns, a.context, extra, build=a.build)
    return 0


if __name__ == "__main__":
    sys.exit(main())
