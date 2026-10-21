"""
code_sessions.py - VryxCode inside the Emvryx app: a coding session that runs on the server while the page shows what it does.

WHAT THIS FILE DOES
    The terminal tool (vryxcode.py) and the app's Code screen share one engine: harness.run_agent. Here it runs in a background thread, one
    session per task. The page polls for new events (the model's steps, tool results, questions) and answers the questions ("Allow this edit?").

    * A project is a folder under  <data>/code/<person>/<project>/  on the server. A person can only reach their own folders; names are
      letters, digits, dashes and underscores. The sandbox confines the model to the folder (see harness.py).
    * Only models flagged "vryxcode" in models.json (Equinox 2 and above) can be used. Equinox is marked "small tasks".
    * Edits and runs ask first unless the person chose "auto-approve edits" for the session; running the tests never asks.
    * A person has one running session at a time. "Stop" ends it at the next step.
    * Nothing here sends code anywhere: the model is the llama-server on the same computer.
"""
import base64
import io
import os
import re
import shutil
import sys
import threading
import time
import zipfile

import code_extras
import code_log
import code_report
import code_map
import code_review
import code_sandbox
import harness
import languages
import usage_limits as U
import vryxcode

NAME_OK = re.compile(r"[A-Za-z0-9_-]{1,40}")
MAX_FILE_BYTES = 200_000
MAX_EVENT_TEXT = 6000
RESULT_TAGS = re.compile(r"<\|/?(?:end_)?tool_result\|>|<\|end_tool_result\|>")
MAX_IMPORT_FILES, MAX_IMPORT_BYTES, MAX_ONE_FILE = 1000, 20_000_000, 2_000_000
MAX_QUEUED = 5                                             # sessions that may wait in one person's queue
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".emvryx"}


def remove_tree(path, tries=3):
    """Delete a folder and everything in it. True when it is gone. On Windows, files a git checkout made read-only (.git/objects) stop a plain
    rmtree, so they are made writable and tried again; a file another program has open is retried after a short wait."""
    import stat

    def unlock(func, p, *_):
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            func(p)
        except OSError:
            pass
    for n in range(tries):
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=unlock)
        else:
            shutil.rmtree(path, onerror=unlock)
        if not os.path.exists(path):
            return True
        time.sleep(0.3 * (n + 1))
    return False


WEB_FILES = (".html", ".htm", ".js", ".mjs", ".css", ".jsx")
PAGE_TROUBLE = re.compile(r"loaded, with problems|did not finish loading", re.I)
PAGE_FIX_TRIES = 2


class CodeError(Exception):
    def __init__(self, message, action=""):
        super().__init__(message)
        self.message, self.action = message, action


class Stopped(Exception):
    pass


class QuotaStop(Exception):
    """A coding session ran past one of the person's limits (time, or the project got too big)."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def clip(text, limit=MAX_EVENT_TEXT):
    text = str(text)
    return text if len(text) <= limit else text[:limit] + f"\n... ({len(text) - limit} more characters)"


def context_meter(used, window):
    """How full the model's memory is for the meter by the task box: harness.run_agent folds the older steps at harness.fold_point (75%, at most 96K)."""
    used, window = max(0, int(used)), max(1, int(window))
    return {"used": used, "window": window, "pct": round(min(100.0, 100.0 * used / window), 1), "compact_at": harness.fold_point(window)}


def change_counts(workspace, name, args):
    """{"add", "del"}: the lines a write or an edit adds and takes away (for "+52 -3" in the session list and the file chips), worked out before it runs.
    {} for any other step."""
    if name not in ("write_file", "edit_file") or not isinstance(args, dict):
        return {}
    import difflib
    if name == "edit_file":
        old, new = str(args.get("old", "")).splitlines(), str(args.get("new", "")).splitlines()
    else:
        new, old = str(args.get("content", "")).splitlines(), []
        if not args.get("append"):
            try:
                full = os.path.realpath(os.path.join(workspace, str(args.get("path", ""))))
                if full.startswith(os.path.realpath(workspace) + os.sep) and os.path.isfile(full):
                    with open(full, encoding="utf-8", errors="replace") as f:
                        old = f.read().splitlines()
            except (OSError, ValueError):
                old = []
    add = rem = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            rem += i2 - i1
        if tag in ("replace", "insert"):
            add += j2 - j1
    return {"add": add, "del": rem}


def _folded_steps(messages):
    """How many old steps are listed under "Earlier steps" in the task message (harness.compact puts them there); 0 when nothing was folded."""
    first = next((m for m in messages if m.get("role") == "user"), None)
    if not first or "\n\nEarlier steps:\n" not in str(first.get("content", "")):
        return 0
    return len([l for l in str(first["content"]).split("\n\nEarlier steps:\n", 1)[1].split("\n") if l.strip()])


class Meter:
    """Counts a coding session against the person's plan, step by step, exactly like chat messages (same tank, same week, same model weight).
    Before each model call the likely cost is held; afterwards the real counts (from llama-server when it reports them) replace the hold.
    Steps count at limits.json code_rate, and the hold counts what the last step already sent as cached: each step resends the same project,
    so counting it all as new text again emptied a Mega tank in a handful of Apogee steps."""

    def __init__(self, limiter, user, model_key, clock=time.time, max_new=1024, effort="balanced"):
        self.limiter, self.user, self.key, self.clock, self.max_new, self.effort = limiter, user, model_key, clock, max_new, effort
        self.counted = 0.0
        self.steps = 0
        self.seen = 0                                      # tokens the last step sent and got back (llama-server keeps them cached)

    @staticmethod
    def tokens(messages):
        return sum(len(str(m.get("content", ""))) for m in messages) // 4 + 4 * len(messages)

    def reserve(self, messages):
        total = self.tokens(messages)
        cached = min(total, self.seen)
        held = total - cached + cached * self.limiter.cfg["multipliers"]["cached_in"] + self.max_new
        est = held * self.limiter.weight(self.key) * self.limiter.cfg["effort"][self.effort] * self.limiter.code_rate()
        return self.limiter.reserve(self.user, self.key, self.effort, est, self.clock())

    def cancel(self, res):
        self.limiter.cancel(res, self.clock())

    def settle(self, res, generate, messages, reply):
        u = getattr(generate, "usage", None) or {}
        fresh = u.get("fresh_in", self.tokens(messages))
        out = u.get("out", len(reply) // 4)
        self.counted += self.limiter.settle(res, fresh, u.get("cached_in", 0), out, self.effort, self.clock(), rate=self.limiter.code_rate())
        self.steps += 1
        self.seen = self.tokens(messages) + len(reply) // 4


class Session:
    """One task being worked on. `events` only ever grows; the page asks for the ones after the last it saw."""

    def __init__(self, sid, user, project, task, model_id, workspace, auto_edits=False, meter=None, tools=None, identity=None, prefix=None, quotas=None, base=None,
                 env="local", log=None, snapshot=None, plan=False, expand=None, remote=False):
        self.meter, self.tools, self.identity = meter, tools, identity
        self.remote = bool(remote)                                       # the cloud machine: the prefix runs commands on another computer over SSH
        self.plan_first, self.expand = plan, expand or (lambda t: t)       # the first turn only looks and plans; @file mentions are expanded for the model
        self.env, self.log, self.snapshot_fn = env, log, snapshot       # where it runs (local | sandbox), the history on disk, and a function that zips the project
        self.checkpoints, self.updated, self._saved_at = [], time.time(), 0.0
        self.prefix, self.quotas, self.base = prefix, quotas, base         # the container prefix (or None), the quota checker and the person's projects folder
        self.deadline = quotas.session_deadline() if quotas else None
        self.id, self.user, self.project, self.task, self.model_id, self.workspace = sid, user, project, task, model_id, workspace
        self.auto_edits = auto_edits
        self.events, self.state = [], "starting"       # starting | working | asking | done | stopped | failed
        self.pending = None                            # the open question, or None
        self.answer = None
        self.stop = threading.Event()
        self.cv = threading.Condition()
        self.started = time.time()
        self.live = None                               # what the model is doing right now (not part of `events`, which only record finished steps)
        self.history = None                            # the whole conversation so far, so a follow-up message continues it
        self.live_messages = None                      # the conversation as it grows during a turn (kept if the turn is stopped)
        self.want_compact = False                      # "Compact now" pressed while a turn runs: fold before the next step
        self.generate, self.max_turns, self.context_tokens, self.extra_programs = None, 12, None, ()
        self.turns_run = 0
        self.build = False                              # the long-build loop (a VryxCode 3 model): set by CodeManager.start / revive / switch_model
        self._auto_tries = 0                            # automatic second tries after an unexpected failure, this message
        self._page_tries = 0                            # automatic fixes after the app's own page check found problems, this message
        self.notify, self.on_notify = False, None       # tell the owner's phone when a turn ends or it needs an answer (set by the server)

    def emit(self, kind, **data):
        with self.cv:
            self.events.append({"n": len(self.events), "kind": kind, "t": round(time.time() - self.started, 1), **data})
            self.updated = time.time()
            self.cv.notify_all()
        self.persist(force=kind in ("start", "user", "end", "rewind"))

    # ---- the history on disk (the Sessions list)
    def meta(self):
        steps, files, snippet, added, removed, pending = 0, set(), "", 0, 0, None
        for e in self.events:
            if e["kind"] == "step" and e.get("tool") and e.get("tool") != "finish":
                steps += 1
                m = re.match(r"(?:write|edit) (\S+)", str(e.get("preview", "")))
                if m:
                    files.add(m.group(1))
                pending = (e.get("add", 0), e.get("del", 0)) if "add" in e else None
            elif e["kind"] == "result" and pending:                   # counted once the change really went in
                if not str(e.get("text", "")).startswith("error"):
                    added, removed = added + pending[0], removed + pending[1]
                pending = None
            if e["kind"] == "end" and e.get("summary"):
                snippet = e["summary"]
        title = " ".join(str(self.task).split())[:70]
        return {"id": self.id, "title": title, "project": self.project, "model": self.model_id, "env": self.env, "state": self.state, "started": self.started,
                "updated": self.updated, "snippet": clip(snippet, 220), "steps": steps, "files": len(files), "checkpoints": list(self.checkpoints),
                "added": added, "removed": removed}

    def persist(self, force=False):
        if not self.log:
            return
        now = time.time()
        if not force and now - self._saved_at < 2.0:
            return
        self._saved_at = now
        try:
            with self.cv:
                events = list(self.events)
            self.log.save(self.meta(), events)
        except (OSError, ValueError):
            pass                                          # the history is a convenience: never stop the work for it

    def _checkpoint(self, label):
        """The project as it is before this message, so Rewind can bring it back."""
        if not (self.log and self.snapshot_fn):
            return
        try:
            data = self.snapshot_fn()
            if data and self.log.save_checkpoint(self.id, self.turns_run, data):
                self.checkpoints.append({"turn": self.turns_run, "t": round(time.time(), 1), "label": " ".join(str(label).split())[:60]})
                self.checkpoints = self.checkpoints[-code_log.MAX_CHECKPOINTS:]
        except (CodeError, OSError):
            pass

    def _on_delta(self, info):
        live = self.live
        if live is not None and live.get("phase") != "running":
            live.update(text=info.get("text", ""), chunks=info.get("chunks", 0), thinking=info.get("thinking_chars", 0))

    def live_view(self):
        """For the page's spinner: {"phase": thinking|writing|calling|running, "secs", "tokens", "text", "tool"} or None. Never the raw tool-call JSON."""
        live = self.live
        if not live:
            return None
        secs = round(time.time() - live["since"], 1)
        if live["phase"] == "running":
            return {"phase": "running", "secs": secs, "tokens": 0, "text": "", "tool": live.get("tool", ""), "target": live.get("target", "")}
        text = live.get("text", "")
        cut = min([i for i in (text.find("<|tool_call|>"), text.find("<tool_call>")) if i >= 0], default=-1)
        prose = (text if cut < 0 else text[:cut]).strip()
        tool = target = ""
        if cut >= 0:
            m = re.search(r'"name"\s*:\s*"(\w+)"', text[cut:])
            tool = m.group(1) if m else ""
            t = re.search(r'"(?:path|command)"\s*:\s*"([^"]{1,120})', text[cut:])      # the file or command, as soon as it has been written
            target = t.group(1) if t else ""
        phase = "calling" if cut >= 0 else ("writing" if prose else "thinking")
        return {"phase": phase, "secs": secs, "tokens": live.get("chunks", 0), "text": clip(prose, 400), "tool": tool, "target": target}

    def since(self, after):
        with self.cv:
            return list(self.events[after:]), self.state, self.pending

    def respond(self, qid, allow, always=False, choice=None):
        with self.cv:
            if not self.pending or self.pending["id"] != qid:
                return False
            if self.pending.get("tool") == "ask_user":           # a multiple-choice question: the answer is the option picked (or the person's own words)
                text = clip(str(choice or "").strip(), 500)
                if not text:
                    return False
                self.answer = ("choice", text)
            else:
                self.answer = (bool(allow), bool(always))
            self.cv.notify_all()
            return True

    def ask_choice(self, question=None, options=None):
        """The ask_user tool (the full agent): the person picks one of 2 to 4 options, or writes their own answer."""
        question = clip(str(question or "").strip(), 400)
        opts = [clip(str(o).strip(), 120) for o in (options if isinstance(options, list) else []) if str(o).strip()][:4]
        if not question or len(opts) < 2:
            raise harness.ToolError('ask_user needs a question and 2 to 4 options, like {"question": "Which database?", "options": ["SQLite", "PostgreSQL"]}')
        qid = len(self.events)
        with self.cv:
            self.pending, self.answer, self.state = {"id": qid, "tool": "ask_user", "question": question, "options": opts}, None, "asking"
        self.emit("choose", id=qid, question=question, options=opts)
        self._tell("asking")
        with self.cv:
            while self.answer is None and not self.stop.is_set():
                self.cv.wait(0.5)
            answer = self.answer
            self.pending, self.answer = None, None
            if not self.stop.is_set():
                self.state = "working"
        if not answer or answer[0] != "choice":
            raise harness.ToolError("the person stopped before answering")
        self.emit("answer", id=qid, allow=True, choice=answer[1])
        return f"The person chose: {answer[1]}"

    def _tools_now(self):
        """The extra tools this turn: the full agent adds the multiple-choice question and its memory."""
        if not getattr(self, "full", False):
            return self.tools
        extra = {"ask_user": self.ask_choice}
        if self.base:
            extra["remember"] = lambda note=None: code_extras.remember(self.base, note)
        return dict(self.tools or {}, **extra)

    def _memory_note(self):
        if not getattr(self, "full", False) or not self.base:
            return ""
        return code_extras.MEMORY_TOOL_NOTE + code_extras.memory_note(self.base)

    PICTURE_MARK = "[The person attached {n} picture(s) to this message: look at them.]"

    def attach_pictures(self, urls):
        """Screenshots sent with the next message (the full agent): data: URLs of PNG, JPEG, WebP or GIF, up to 3, 5 MB each. Returns the line added to the message."""
        good = [u for u in (urls or []) if isinstance(u, str) and re.match(r"^data:image/(png|jpe?g|webp|gif);base64,[A-Za-z0-9+/=]+$", u) and len(u) <= 7_000_000][:3]
        if not good:
            self._pictures = None
            return ""
        mark = self.PICTURE_MARK.format(n=len(good))
        self._pictures = (mark, good)
        return mark

    STEER = "While you were working, the person added: "

    def steer(self, text):
        """A message typed while it works (the full agent): the model reads it before its next step, without stopping."""
        text = str(text or "").strip()
        if not text:
            raise CodeError("Write a message first.")
        if len(text) > 4000:
            raise CodeError("That message is too long.", "Keep it under 4,000 characters.")
        with self.cv:
            if self.state not in ("starting", "working", "asking"):
                raise CodeError("It is not working right now.", "Send it as a normal message.")
            self._steers = getattr(self, "_steers", []) + [text]
        self.emit("user", text=text, steer=True)

    def compact_now(self):
        """The "Compact now" button. While it works, the fold happens before the next step ("next_step"); between messages the remembered conversation is
        folded at once (the number of steps folded, 0 when there is nothing old enough)."""
        if self.state in ("starting", "working", "asking"):
            self.want_compact = True
            return {"when": "next_step"}
        if not self.history:
            return {"when": "now", "folded": 0}
        new = harness.fold_now(self.history)
        if len(new) >= len(self.history):
            return {"when": "now", "folded": 0}
        self.history = new
        steps = _folded_steps(new)
        self.emit("compacted", steps=steps, manual=True)
        if self.context_tokens:
            self.emit("context", **context_meter(harness.estimate_tokens(new), self.context_tokens))
        return {"when": "now", "folded": steps}

    def request_stop(self):
        if self.state == "queued":                       # never started: take it out of the queue
            self.state = "stopped"
            self.emit("end", finished=False, summary="Removed from the queue.", turns=0)
            self.persist(force=True)
            return
        self.stop.set()
        with self.cv:
            self.cv.notify_all()

    # ---- what the engine calls
    def rules_path(self):
        """This project's saved permission rules (the full agent), kept in the person's folder: None in a session without one (tests)."""
        return code_extras.rules_path(self.base, self.project) if self.base else None

    def ask(self, name, args):
        full = getattr(self, "full", False)            # the Claude Code-style agent: its permission rules too
        command = str(args.get("command", "")).strip() if name == "run" and isinstance(args, dict) else ""
        if full and self.rules_path() and name != "github":
            verdict = code_extras.decide(self.rules_path(), name, harness.command_keys(command) if name == "run" else [])
            if verdict == "deny":
                self.emit("note", text="Not allowed by this project's rules: " + clip(command or name, 120))
                return False
            if verdict == "allow":
                return True
        if name == "run":
            if full:
                # only looks (ls, cat, git status, the tests), or only makes, moves or copies files in "Edit without asking", or "always allow" was said for this command
                if (harness.read_only_command(command) or (self.auto_edits and harness.file_command(command))
                        or "run:" + harness.command_key(command) in getattr(self, "_always", set())):
                    return True
            elif command.startswith(vryxcode.SAFE_RUNS):
                return True
        if self.auto_edits and name in (("write_file", "edit_file", "rollback") if full else ("write_file", "edit_file", "run", "rollback")):
            return True
        if name == "github" and str(args.get("action", "status")) == "status":
            return True                                  # only looking at the link
        if name == "check_page":
            return True                                  # the browser check only looks (and cannot reach the internet): no question
        if name in getattr(self, "_always", set()) and name != "github":       # pulling and pushing always ask, every time
            return True
        qid = len(self.events)
        shown = vryxcode.preview(name, args)
        if harness.preview_check(self.workspace, name, args) == "":
            shown += "\n\u2713 Checked: no problems found in this change"          # a change with a problem never gets this far: the model is told to fix it first
        with self.cv:
            self.pending, self.answer, self.state = {"id": qid, "tool": name, "preview": clip(shown, 2500)}, None, "asking"
        self.emit("ask", id=qid, tool=name, preview=self.pending["preview"])
        self._tell("asking")
        with self.cv:
            while self.answer is None and not self.stop.is_set():
                self.cv.wait(0.5)
            answer = self.answer or (False, False)
            self.pending, self.answer = None, None
            if not self.stop.is_set():
                self.state = "working"
        allow, always = answer
        if always and name != "github":                  # the full agent remembers the command (npm test), not every command
            self._always = getattr(self, "_always", set()) | {"run:" + harness.command_key(command) if full and name == "run" else name}
            if full and allow and self.rules_path():        # ...and saves it for this project, like Claude Code's settings (Settings > the project's rules to undo)
                for key in (harness.command_keys(command) if name == "run" else [name]):
                    try:
                        code_extras.add_rule(self.rules_path(), "allow", key)
                    except (ValueError, OSError):
                        pass
        self.emit("answer", id=qid, allow=allow)
        return allow

    def check_limits(self):
        if self.deadline and time.time() > self.deadline:
            raise QuotaStop(f"This session ran for the longest time allowed ({self.quotas.q['code_session_minutes']} minutes).")
        if self.quotas and self.base:
            try:
                self.quotas.room(self.base, self.workspace)
            except code_sandbox.QuotaError as e:
                raise QuotaStop(e.message + " " + e.action)

    def wrap(self, generate):
        """The model call, with every step reported to the page and a check for Stop."""
        seen = {"n": 0}

        def call(messages):
            manual = False
            if self.want_compact:                                                     # "Compact now" was pressed while it worked: fold before this step
                self.want_compact = False
                new = harness.fold_now(messages)
                manual = len(new) < len(messages)
                messages[:] = new                                                     # the same list the loop keeps using
            folded = _folded_steps(messages)
            if (seen.get("folded") == 0 and folded > 0) or manual:                   # the first time this turn that old steps were folded into the "Earlier steps" list to save room
                self.emit("compacted", steps=folded, **({"manual": True} if manual else {}))
            seen["folded"] = folded
            if self.context_tokens:                                                    # the memory meter on the page (feature flag context_meter)
                self.emit("context", **context_meter(harness.estimate_tokens(messages), self.context_tokens))
            self.live_messages = messages
            if self.stop.is_set():
                raise Stopped()
            if seen["n"] and messages and messages[-1]["role"] == "user":
                self.emit("result", text=clip(RESULT_TAGS.sub("", messages[-1]["content"]).strip()))
                self.check_limits()                                          # a step may have grown the project: check before going on
            with self.cv:
                steers, self._steers = getattr(self, "_steers", []), []
            if steers:                                                       # typed while it worked: the model reads it now, after the last result
                note = "\n\n".join(self.STEER + t for t in steers)
                if messages and messages[-1]["role"] == "user":
                    messages[-1] = dict(messages[-1], content=messages[-1]["content"] + "\n\n" + note)
                else:
                    messages.append({"role": "user", "content": note})
            seen["n"] += 1
            res = self.meter.reserve(messages) if self.meter else None       # raises U.LimitError when the plan has run out
            self.live = {"phase": "thinking", "since": time.time(), "text": "", "chunks": 0, "thinking": 0}
            try:
                generate.pictures = getattr(self, "_pictures", None)     # screenshots sent with the message: the model sees them on every step of this turn
                generate.on_delta = self._on_delta         # the model call reports its progress here (a plain function accepts the attribute too)
                generate.should_stop = self.stop.is_set    # ...and asks here whether Stop was pressed
            except AttributeError:
                pass
            try:
                reply = generate(messages)
            except BaseException as e:
                self.live = None
                if self.meter:
                    self.meter.cancel(res)
                if isinstance(e, vryxcode.Interrupted):
                    raise Stopped()
                raise
            if self.meter:
                self.meter.settle(res, generate, messages, reply)
            if self.stop.is_set():
                raise Stopped()
            took = {"secs": round(time.time() - self.live["since"], 1), "words": self.live.get("chunks", 0)} if self.live else {}      # what the live line showed: kept on the step
            self.live = None
            try:
                name, args = harness.parse_tool_call(reply)
                self.emit("step", tool=name, preview=clip(vryxcode.preview(name, args), 2500), raw=clip(reply, 1500), **took, **change_counts(self.workspace, name, args))
                if name == "finish" and isinstance(args, dict):
                    nxt = args.get("next")
                    self.next_steps = [clip(str(x), 120) for x in nxt[:3]] if isinstance(nxt, list) else []
                if name != "finish":
                    target = str(args.get("path") or args.get("command") or args.get("args") or args.get("action") or "") if isinstance(args, dict) else ""
                    self.live = {"phase": "running", "since": time.time(), "tool": name, "target": target[:120]}      # the tool runs next; cleared when the next model call starts
            except harness.ToolError as e:
                if not str(e).startswith("no tool call found"):     # a tool call that could not be read: it is sent back to the model to try again, so say so and keep what it wrote
                    prose = RESULT_TAGS.sub("", re.split(r"<\|tool_call\|>|<tool_call>", reply)[0]).strip()
                    self.emit("retry", text=clip(prose, 400), why=clip(str(e), 200), limit=bool(getattr(generate, "cut_off", False)), **took)
                # words with no tool call: if the turn ends on them they arrive as the "end" message, so no step is shown
            return reply
        call.fixes = getattr(generate, "fixes", False)          # vryxcode_fixes reaches the agent loop (harness.run_agent reads it from the model call)
        return call

    def run(self, generate, max_turns, context_tokens, extra_programs=()):
        """The first turn of the conversation (the task the person typed)."""
        self.generate, self.max_turns, self.context_tokens, self.extra_programs = generate, max_turns, context_tokens, tuple(extra_programs)
        self._turn(self.task, first=True, plan=self.plan_first)

    def send(self, text, plan=False, model_text=None):
        """The person's next message: another turn of the same conversation (the model sees everything said and done so far)."""
        text = str(text or "").strip()
        if not text:
            raise CodeError("Write a message first.")
        if len(text) > 8000:
            raise CodeError("That message is too long.", "Keep it under 8,000 characters.")
        with self.cv:
            if self.state in ("starting", "working", "asking"):
                raise CodeError("It is still working.", "Wait for it to finish, or press Stop.")
            if self.generate is None:
                raise CodeError("This session cannot continue.", "Start a new one.")
            self.state = "working"
            self.stop.clear()
        self._auto_tries = self._page_tries = 0
        self._model_text = model_text                       # what the model gets instead of the line the person sees (a code review's diff)
        threading.Thread(target=self._turn, args=(text, False, bool(plan)), daemon=True).start()

    def _turn(self, text, first, plan=False, auto=False):
        retried, again = False, None
        self.state = "working"
        self.next_steps = []
        self.turns_run += 1
        if self.quotas:
            self.deadline = self.quotas.session_deadline()          # each message gets its own time allowance
        self._checkpoint(text)
        if first:
            self.emit("start", task=text, model=self.model_id, project=self.project, plan=plan)
        else:
            self.emit("user", text=text, plan=plan, **({"auto": True} if auto else {}))
        self.live_messages = None
        lang = languages.decide(text, self.env, self.workspace)                  # which language fits, and what can run here: told to the person and to the model
        line = languages.page_line(lang)
        if line:
            self.emit("language", text=line, language=lang["name"], mode=lang["mode"])
        try:
            model_text, self._model_text = getattr(self, "_model_text", None), None
            result = vryxcode.run_task(model_text or self.expand(text), self.wrap(self.generate), self.workspace, self.ask, self.max_turns, self.context_tokens, self.extra_programs, lang_note=languages.note_for(lang) + self._memory_note(),
                                       out=lambda *_: None, tools=self._tools_now(),
                                       git_identity=self.identity,
                                       command_prefix=self.prefix, container=bool(self.prefix) and not self.remote, history=self.history, chat_mode=True, plan=plan, todo=True, remote=self.remote,
                                       build=getattr(self, "build", False), full=getattr(self, "full", False))
            self.history = result["messages"]
            report = None if self.stop.is_set() else self._page_proof()
            if report and PAGE_TROUBLE.search(report) and self._page_tries < PAGE_FIX_TRIES:
                # the app opened the page itself and it is broken: like a person would, it goes back and fixes it before saying it is done
                self._page_tries += 1
                again = ("I opened the page in a browser and it does not work yet:\n" + clip(report, 1500) +
                         "\nFix these problems, then open it again with check_page and finish only when it loads with no errors.")
                return
            self._end( finished=result["finished"], said=bool(result.get("said")), summary=clip(result["summary"], 4000), turns=result["turns"],
                      next=self.next_steps if result["finished"] else [], plan=bool(plan) and bool(result["finished"] or result.get("said")))
            self.state = "done" if (result["finished"] or result.get("said")) else "stopped"
        except U.LimitError as e:
            self._keep_history()
            when = f" Try again in about {max(1, int((e.retry_after or 0) // 60))} minutes." if e.retry_after else ""
            self._end( finished=False, summary=f"Your usage ran out: {e.message}{when} Your files so far are kept.", turns=0, limited=True)
            self.state = "limited"
        except QuotaStop as e:
            self._keep_history()
            self._end( finished=False, summary="Stopped: " + e.message + " Your files so far are kept.", turns=0, limited=True)
            self.state = "limited"
        except Stopped:
            self._keep_history()
            self._end( finished=False, summary="Stopped.", turns=0)
            self.state = "stopped"
        except BaseException as e:                     # a model that cannot be reached, a full disk, ...
            self._keep_history()
            msg = getattr(e, "message", None) or str(e) or e.__class__.__name__
            if not isinstance(e, (CodeError, SystemExit, KeyboardInterrupt)) and not self.stop.is_set() and self._auto_tries < 1 and self.generate is not None:
                # something unexpected broke the step: like a person would, look at what went wrong and carry on once, before giving up
                self._auto_tries += 1
                retried = True
                self.emit("note", text="Something went wrong (" + clip(msg, 160) + "). Trying again by itself.")
            else:
                self._end( finished=False, summary="It could not finish: " + clip(msg, 500), turns=0, error=True)
                self.state = "failed"
        finally:
            if again:
                return self._turn(again, False, auto=True)
            if retried:
                return self._turn("The last step failed with this error: " + clip(msg, 400) + ". Look at what went wrong, then carry on from where you stopped and finish the task.", False, auto=True)
            self.live = None
            self.persist(force=True)
            if self.state not in ("starting", "working", "asking"):
                self._tell(self.state)
            idle = getattr(self, "on_idle", None)
            if idle and self.state not in ("starting", "working", "asking"):
                try:
                    idle(self)                            # the next queued session may start
                except Exception:
                    pass

    def _page_proof(self):
        """Proof before "done": when this turn changed the web page and nothing opened it since, the app opens it itself (the model is not trusted to
        remember) and the result goes in the feed. The report, or None when there was nothing to check."""
        tool = (self.tools or {}).get("check_page")
        if not tool:
            return None
        last_web, last_check, page = -1, -1, ""
        for i, e in enumerate(code_report._turn_events(self.events)):
            if e.get("kind") != "step":
                continue
            m = re.match(r"(?:write|edit) (\S+)", str(e.get("preview", "")))
            if e.get("tool") in ("write_file", "edit_file") and m and m.group(1).lower().endswith(WEB_FILES):
                last_web, page = i, (m.group(1) if m.group(1).lower().endswith((".html", ".htm")) else page)
            elif e.get("tool") == "check_page":
                last_check = i
        if last_web < 0 or last_check > last_web:
            return None
        self.emit("step", tool="check_page", preview=f"check_page {page or 'the main page'} (the app opens the page itself before it says it is done)", auto=True)
        try:
            report = tool(page) if page else tool()
        except Exception as e:                            # noqa: BLE001  (a missing browser is not a broken page)
            report = "Browser check could not run: " + (getattr(e, "message", None) or str(e))
        self.emit("result", text=clip(report))
        return report

    def switch_model(self, model_id, generate, context_tokens, meter, build_steps=None, default_turns=12):
        """Another model takes over this conversation (the same session, the same history): the next message runs on it."""
        with self.cv:
            if self.state in ("starting", "working", "asking"):
                raise CodeError("It is still working.", "Wait for it to finish, or press Stop, then pick the other model.")
        old, self.model_id, self.generate, self.context_tokens, self.meter = self.model_id, model_id, generate, context_tokens, meter
        self.build, self.max_turns = bool(build_steps), int(build_steps or default_turns)
        self.emit("model", model=model_id, previous=old)

    def set_effort(self, generate, turns):
        """Another effort for the next message (feature flag vryxcode_effort): its step budget and its model call (Deep thinks before each step)."""
        with self.cv:
            if self.state in ("starting", "working", "asking"):
                raise CodeError("It is still working.", "Wait for it to finish, or press Stop, then change the effort.")
        self.generate, self.max_turns = generate, int(turns)

    def catch_up(self, text):
        """For a session brought back from the history (the model's own memory of it is gone): what happened so far, then the new message."""
        lines = []
        for e in self.events:
            if e["kind"] in ("start", "user") and (e.get("task") or e.get("text")):
                lines.append("The user asked: " + clip(str(e.get("task") or e.get("text")), 600))
            elif e["kind"] == "end" and e.get("summary"):
                lines.append("Result: " + clip(str(e["summary"]), 600))
        recap = "\n".join(lines[-8:])
        return (("This continues an earlier session in this project. What happened so far:\n" + recap + "\n\nThe files are as that work left them: read them before changing anything.\n\n")
                if recap else "") + "Now: " + self.expand(str(text or ""))

    def _tell(self, kind):
        """The phone notification (when it was asked for): the state and the project, never code or file contents. Never raises."""
        cb = self.on_notify
        if self.notify and cb:
            try:
                cb(self, kind)
            except Exception:
                pass

    def _end(self, **data):
        """The end of a turn. When it did any work the end carries its verification report (so it is in the history on disk too)."""
        try:
            report = code_report.build_report(self.events, end=data)
        except Exception:                                 # the report is a convenience: never fail a turn over it
            report = None
        self._pictures = None                              # the screenshots belong to the message that brought them
        self.emit("end", **data, **({"report": report} if report else {}))

    def _keep_history(self):
        """A stopped or failed turn still happened: the next message continues from where it got to."""
        if self.live_messages:
            self.history = list(self.live_messages)


class CodeManager:
    """All projects and sessions on this server."""

    def __init__(self, root, max_turns=12, quotas=None):
        self.root, self.max_turns = root, max_turns          # root=None keeps projects in a temporary folder (tests)
        self.quotas = quotas or code_sandbox.Quotas()
        self.cloud = None                                    # the cloud machine: {"host", "port", "user", "key", "known_hosts", "for_others"} set by the server (None = not set up)
        self.sandbox = {"mode": "none"}                      # set from the command line: {"mode": "docker", "image", "runtime", "cpus", "memory", "pids"}
        self._avail = (0, None)
        self.sessions, self.by_user = {}, {}
        self._run_locks = {}
        self.lock = threading.Lock()
        self._tmp = None
        self._n = 0

    # ---- projects
    def base(self, user):
        if self.root:
            path = os.path.join(self.root, "code", re.sub(r"[^A-Za-z0-9_-]", "_", user))
        else:
            import tempfile
            self._tmp = self._tmp or tempfile.mkdtemp(prefix="vryx_code_")
            path = os.path.join(self._tmp, re.sub(r"[^A-Za-z0-9_-]", "_", user))
        os.makedirs(path, exist_ok=True)
        return path

    def check_name(self, project):
        if not NAME_OK.fullmatch(str(project or "")):
            raise CodeError("That project name isn't allowed.", "Use letters, numbers, dashes and underscores (up to 40).")
        return project

    def projects(self, user):
        base = self.base(user)
        return sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)) and NAME_OK.fullmatch(d))

    def project_path(self, user, project):
        return os.path.join(self.base(user), self.check_name(project))

    def files(self, user, project):
        path, out = self.project_path(user, project), []
        if not os.path.isdir(path):
            return out
        for dirpath, dirs, names in os.walk(path):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d)))
            for n in sorted(names):
                full = os.path.join(dirpath, n)
                if not os.path.islink(full):
                    out.append(os.path.relpath(full, path).replace(os.sep, "/"))
            if len(out) > 500:
                break
        return out[:500]

    def search(self, user, project, query):
        return code_map.search(self.project_path(user, project), query)

    def project_map(self, user, project):
        return code_map.project_map(self.project_path(user, project))

    def read(self, user, project, rel):
        root = os.path.realpath(self.project_path(user, project))
        full = os.path.realpath(os.path.join(root, rel))
        if not (full == root or full.startswith(root + os.sep)) or not os.path.isfile(full):
            raise CodeError("That file isn't in the project.")
        with open(full, "rb") as f:
            data = f.read(MAX_FILE_BYTES + 1)
        if b"\0" in data[:2000]:
            return {"path": rel, "text": "(a binary file)", "truncated": False}
        return {"path": rel, "text": data[:MAX_FILE_BYTES].decode("utf-8", "replace"), "truncated": len(data) > MAX_FILE_BYTES}

    def run_command(self, user, project, command, owner=False, env="local"):
        """The editor's output panel: run one command in the project the way a session would (the same allowed programs, the same sandbox or cloud choice, no network where
        it can be cut), for the person, with no model involved. Refused while VryxCode is working in the same project. Returns {"command", "exit", "output", "secs", "env"}."""
        project = self.check_name(project)
        command = str(command or "").strip()
        if not command or len(command) > 500:
            raise CodeError("Type a command to run.", "For example: python -m unittest")
        for x in self.sessions.values():
            if x.user == user and x.project == project and x.state in ("starting", "working", "asking"):
                raise CodeError("VryxCode is working in this project right now.", "Wait for it to finish, or press Stop, then run it.")
        ok, why = self.sandbox_ready()
        if not ok:
            raise CodeError("The code sandbox isn't available, so nothing was run. " + why, "The owner needs to start Docker or build the sandbox image.")
        env = self.resolve_env(env, owner)
        workspace = self.project_path(user, project)
        os.makedirs(workspace, exist_ok=True)
        prefix = self.cloud_prefix(user, project) if env == "cloud" else self.prefix_for(workspace, force=(env == "sandbox"))
        kw = {}
        if prefix:
            kw.update(command_prefix=prefix, container=not env == "cloud", remote=(env == "cloud"))
        lock = self._run_locks.setdefault(user, threading.Lock())
        if not lock.acquire(blocking=False):
            raise CodeError("A command is already running for you.", "Wait for it to finish.")
        started = time.time()
        try:
            with harness.Sandbox(workspace=workspace, allowed_programs=set(harness.ALLOWED_PROGRAMS), command_timeout=120 if env == "cloud" else 60, output_limit=12000, **kw) as sb:
                try:
                    result = sb.run(command)
                except harness.ToolError as e:
                    result = f"exit code 126\n{e}"
        finally:
            lock.release()
        first, _, rest = result.partition("\n")
        m = re.match(r"exit code (-?\d+)", first)
        return {"command": command, "exit": int(m.group(1)) if m else 0, "output": rest if m else result, "secs": round(time.time() - started, 1), "env": env}

    def save_file(self, user, project, rel, text):
        """The editor's Save: write one text file of the project (a new file too). Refused while VryxCode is working in the same project (the two would overwrite each
        other), for paths outside the project or in hidden folders, for binary files, and past the file-size and project quotas. Returns {"path", "size", "created"}."""
        project = self.check_name(project)
        for x in self.sessions.values():
            if x.user == user and x.project == project and x.state in ("starting", "working", "asking"):
                raise CodeError("VryxCode is working in this project right now.", "Wait for it to finish, or press Stop, then save again.")
        if not isinstance(text, str):
            raise CodeError("There is nothing to save.")
        data = text.replace("\r\n", "\n").encode("utf-8")
        if len(data) > MAX_FILE_BYTES:
            raise CodeError("That file is too big to edit here.", f"The editor handles files up to {MAX_FILE_BYTES // 1000} KB.")
        name = self._safe_rel(rel)
        if not name or any(p in SKIP_DIRS for p in name.split("/")) or len(name) > 200:
            raise CodeError("That file name isn't allowed.", "Use a name inside the project, not in .git or .emvryx.")
        workspace = self.project_path(user, project)
        root = os.path.realpath(workspace)
        full = os.path.realpath(os.path.join(root, name))
        if not full.startswith(root + os.sep):
            raise CodeError("That file isn't in the project.")
        exists = os.path.isfile(full)
        if os.path.islink(os.path.join(root, name)):
            raise CodeError("That is a link, not a file.")
        if os.path.isdir(full):
            raise CodeError("That name is a folder.")
        if exists:
            with open(full, "rb") as f:
                if b"\0" in f.read(2000):
                    raise CodeError("That is a binary file; it can't be edited here.")
        try:
            os.makedirs(root, exist_ok=True)
            self.quotas.room(self.base(user), workspace, extra_bytes=len(data), extra_files=0 if exists else 1)
        except code_sandbox.QuotaError as e:
            raise CodeError(e.message, e.action)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        tmp = full + ".saving"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, full)
        return {"path": name, "size": len(data), "created": not exists}

    def export_zip(self, user, project):
        """The whole project as zip bytes (without .git, caches and node_modules)."""
        path = self.project_path(user, project)
        if not os.path.isdir(path):
            raise CodeError("That project isn't here.")
        buf, total = io.BytesIO(), 0
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for dirpath, dirs, names in os.walk(path):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d)))
                for n in sorted(names):
                    full = os.path.join(dirpath, n)
                    if os.path.islink(full):
                        continue
                    total += os.path.getsize(full)
                    if total > 50_000_000:
                        raise CodeError("That project is too big to download as one zip.")
                    z.write(full, os.path.relpath(full, path))
        return buf.getvalue()

    @staticmethod
    def _safe_rel(name):
        """A path from an upload, made safe: None to skip it, CodeError if it tries to escape."""
        name = str(name).replace("\\", "/").lstrip("/")
        parts = [p for p in name.split("/") if p not in ("", ".")]
        if not parts:
            return None
        if ".." in parts or re.match(r"^[A-Za-z]:", parts[0]):
            raise CodeError("That upload has a path that leaves the project.", "Nothing was imported.")
        if any(p in SKIP_DIRS for p in parts[:-1]):
            return None
        return "/".join(parts)

    def import_files(self, user, project, entries):
        """entries: [(path, bytes)]. Writes them into the project (overwriting). Returns how many were written."""
        if self.running(user):
            raise CodeError("A session is running.", "Stop it first.")
        root = os.path.realpath(self.project_path(user, project))
        clean, total = [], 0
        for name, data in entries:
            rel = self._safe_rel(name)
            if rel is None:
                continue
            if len(data) > MAX_ONE_FILE:
                raise CodeError(f"{rel} is too big to import (over 2 MB).", "Nothing was imported.")
            total += len(data)
            clean.append((rel, data))
            if len(clean) > MAX_IMPORT_FILES or total > MAX_IMPORT_BYTES:
                raise CodeError("That is too much to import (up to 1,000 files and 20 MB).", "Nothing was imported.")
        if not clean:
            raise CodeError("No files to import.")
        for rel, data in clean:
            full = os.path.realpath(os.path.join(root, rel))
            if not full.startswith(root + os.sep):
                raise CodeError("That upload has a path that leaves the project.", "Nothing was imported.")
        os.makedirs(root, exist_ok=True)
        try:
            self.quotas.room(self.base(user), root, extra_bytes=total, extra_files=len(clean))
        except code_sandbox.QuotaError as e:
            raise CodeError(e.message, e.action)
        for rel, data in clean:
            full = os.path.join(root, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as f:
                f.write(data)
        return len(clean)

    def import_zip(self, user, project, data):
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise CodeError("That isn't a zip file.")
        entries, total = [], 0
        with z:
            for info in z.infolist():
                if info.is_dir() or (info.external_attr >> 16) & 0o170000 == 0o120000:     # folders and symlinks are skipped
                    continue
                total += info.file_size
                if info.file_size > MAX_ONE_FILE or total > MAX_IMPORT_BYTES or len(entries) >= MAX_IMPORT_FILES:
                    raise CodeError("That zip is too big to import (up to 1,000 files, 20 MB, 2 MB each).", "Nothing was imported.")
                entries.append((info.filename, z.read(info)))
        return self.import_files(user, project, entries)

    def import_b64(self, user, project, body):
        """Either {"zip_b64": ...} or {"files": [{"path", "b64"}]}."""
        try:
            if body.get("zip_b64"):
                return self.import_zip(user, project, base64.b64decode(body["zip_b64"], validate=True))
            files = body.get("files")
            if not isinstance(files, list):
                raise CodeError("Choose a zip file or a folder.")
            return self.import_files(user, project, [(f["path"], base64.b64decode(f["b64"], validate=True)) for f in files])
        except (ValueError, KeyError, TypeError):
            raise CodeError("That upload could not be read.")

    def read_bytes(self, user, project, rel, limit=None):
        """A project file's raw bytes (for the data export), only from inside the project; None if it is missing, a link or over `limit`."""
        root = os.path.realpath(self.project_path(user, project))
        full = os.path.realpath(os.path.join(root, rel))
        if not full.startswith(root + os.sep) or not os.path.isfile(full) or os.path.islink(os.path.join(root, rel)):
            return None
        if limit is not None and os.path.getsize(full) > limit:
            return None
        with open(full, "rb") as f:
            return f.read()

    def fork_project(self, user, project):
        """A separate copy of a project to try an idea in (the original is not touched). Returns the copy's name: "shop" -> "shop-try", "shop-try-2", ..."""
        src = self.project_path(user, project)
        if not os.path.isdir(src):
            raise CodeError("That project isn't here.")
        if self.running(user) and any(x.project == project and x.state in ("starting", "working", "asking") for x in self.sessions.values() if x.user == user):
            raise CodeError("A session is working in that project.", "Wait for it to finish, then make the copy.")
        base = re.sub(r"-try(-\d+)?$", "", project)[:34]
        name, n = base + "-try", 2
        while os.path.exists(self.project_path(user, name)):
            name = f"{base}-try-{n}"
            n += 1
        try:
            self.quotas.new_project(self.base(user), name)
            self.quotas.room(self.base(user), src, extra_bytes=0)
        except code_sandbox.QuotaError as e:
            raise CodeError(e.message, e.action)
        dst = self.project_path(user, name)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__", ".emvryx"), symlinks=False)
        return name

    def adopt_project(self, user, copy, into):
        """Use a copy's files in the original: the original is first saved as "<into>-before" (so nothing is lost), then its files are replaced by the copy's."""
        a, b = self.project_path(user, copy), self.project_path(user, into)
        if copy == into or not os.path.isdir(a) or not os.path.isdir(b):
            raise CodeError("Pick a copy and the project it came from.")
        if any(x.user == user and x.project in (copy, into) and x.state in ("starting", "working", "asking") for x in self.sessions.values()):
            raise CodeError("A session is working in one of them.", "Wait for it to finish.")
        backup, n = into + "-before", 2
        while os.path.exists(self.project_path(user, backup)):
            backup = f"{into}-before-{n}"
            n += 1
        try:
            self.quotas.new_project(self.base(user), backup)
        except code_sandbox.QuotaError as e:
            raise CodeError(e.message, e.action)
        os.rename(b, self.project_path(user, backup))
        shutil.copytree(a, b, ignore=shutil.ignore_patterns(".emvryx"), symlinks=False)
        git = os.path.join(self.project_path(user, backup), ".git")
        if os.path.isdir(git):                                    # the history stays with the original
            shutil.copytree(git, os.path.join(b, ".git"))
        return {"project": into, "backup": backup}

    def delete_project(self, user, project):
        busy = self.running(user)
        if busy and busy.project == project:
            raise CodeError("A session is working in this project.", "Stop it first, then delete the project.")
        path = self.project_path(user, project)
        if os.path.isdir(path) and not remove_tree(path):
            raise CodeError("Some files in this project could not be deleted because something is still using them.",
                            "Close anything that has the project open (an editor, a terminal or the preview) and try again.")

    # ---- sessions
    def running(self, user):
        """The user's session that is working now (queued ones are waiting, not running), or None."""
        for s in list(self.sessions.values()):
            if s.user == user and s.state in ("starting", "working", "asking"):
                return s
        return None

    def any_running(self):
        return any(x.state in ("starting", "working", "asking") for x in list(self.sessions.values()))

    def sandbox_ready(self):
        """(ok, message). In container mode Docker must answer (checked at most every 30 s); there is no quiet fallback to the host."""
        if self.sandbox.get("mode") != "docker":
            return True, "folder sandbox only"
        now = time.time()
        if now - self._avail[0] > 30 or self._avail[1] is None:
            self._avail = (now, code_sandbox.available(self.sandbox.get("image", code_sandbox.DEFAULT_IMAGE)))
        return self._avail[1]

    def prefix_for(self, workspace, force=False):
        if self.sandbox.get("mode") != "docker" and not force:
            return None
        sb = self.sandbox
        return code_sandbox.docker_prefix(sb.get("image", code_sandbox.DEFAULT_IMAGE), workspace, cpus=sb.get("cpus", "1"), memory=sb.get("memory", "768m"),
                                          pids=sb.get("pids", 128), runtime=sb.get("runtime"))

    def start(self, user, project, task, model_id, generate, auto_edits=False, context_tokens=None, meter=None, outside=False, tools=None, identity=None, env="local", plan=False, owner=False, queue=False, model_text=None,
              build_steps=None, turns=None, full=False, pictures=None):
        task = str(task or "").strip()
        if not task:
            raise CodeError("Describe what to build or fix.")
        if len(task) > 8000:
            raise CodeError("That task is too long.", "Keep it under 8,000 characters.")
        if outside:                                    # an outside coding model: labelled as such, never presented as an Emvryx result
            note = "An outside coding model, not an Emvryx model."
        else:
            ok, note = vryxcode.check_model(model_id)
            if not ok:
                raise CodeError(note)
        with self.lock:
            busy = self.running(user)
            if busy and not queue:
                raise CodeError("You already have a session running.", "Stop it or wait for it to finish.")
            if busy and sum(1 for x in self.sessions.values() if x.user == user and x.state == "queued") >= MAX_QUEUED:
                raise CodeError(f"{MAX_QUEUED} sessions are already waiting in your queue.", "Wait for some to finish, or stop one.")
            ok, why = self.sandbox_ready()
            if not ok:
                raise CodeError("The code sandbox isn't available, so nothing was run. " + why, "The owner needs to start Docker or build the sandbox image.")
            env = self.resolve_env(env, owner)
            workspace = self.project_path(user, project)
            try:
                self.quotas.new_project(self.base(user), project)
                os.makedirs(workspace, exist_ok=True)
                self.quotas.room(self.base(user), workspace)
                self.quotas.start_session(user)
            except code_sandbox.QuotaError as e:
                raise CodeError(e.message, e.action)
            self._n += 1
            s = Session(f"s{self._n}-{int(time.time())}", user, project, task, model_id, workspace, auto_edits, meter, tools, identity,
                        prefix=(self.cloud_prefix(user, project) if env == "cloud" else self.prefix_for(workspace, force=(env == "sandbox"))), quotas=self.quotas, base=self.base(user),
                        env=env, remote=(env == "cloud"), log=code_log.SessionLog(self.base(user)), snapshot=lambda u=user, p=project: self._snapshot(u, p), plan=bool(plan),
                        expand=lambda t, u=user, p=project: self.expand_mentions(u, p, t))
            self.sessions[s.id], self.by_user[user] = s, s.id
            s._model_text = model_text                          # what the model gets instead of the line the person sees (a second opinion's diff)
            s.build = bool(build_steps)                         # a model made for long builds (VryxCode 3): the long-build loop and its own step budget
            s.full = bool(full)                                 # the Claude Code-style agent (VryxCode 3, feature flag vryxcode_full_agent)
            mark = s.attach_pictures(pictures) if full and pictures else ""
            if mark:                                            # screenshots sent with the task: the model is told, and sees them
                s.task = task + "\n\n" + mark
            turns = int(build_steps or turns or self.max_turns)      # turns: the step budget of the effort picked (feature flag vryxcode_effort)
            s.on_idle = self._session_idle
            if busy:                                           # one model on one card: sessions wait their turn, so they never work on the same files at once
                s.state, s.run_args = "queued", (generate, turns, context_tokens)
                s.emit("queued", task=task, project=project, position=self.queue_position(user, s.id))
                s.persist(force=True)
                return s, note
        threading.Thread(target=s.run, args=(generate, turns, context_tokens), daemon=True).start()
        return s, note

    def revive(self, user, sid, model_id, generate, context_tokens, meter, tools=None, identity=None, owner=False, auto_edits=False, build_steps=None, turns=None, full=False):
        """Bring a session from the history back to life, so a new message carries on in it (same id, same feed, same Rewind points)."""
        with self.lock:
            if self.running(user):
                raise CodeError("You already have a session running.", "Stop it or wait for it to finish.")
            d = self.saved(user, sid)
            meta = d["meta"]
            project = meta["project"]
            env = self.resolve_env(meta.get("env") or "local", owner)
            workspace = self.project_path(user, project)
            os.makedirs(workspace, exist_ok=True)
            s = Session(sid, user, project, meta.get("title") or "", model_id, workspace, auto_edits, meter, tools, identity,
                        prefix=(self.cloud_prefix(user, project) if env == "cloud" else self.prefix_for(workspace, force=(env == "sandbox"))), quotas=self.quotas, base=self.base(user),
                        env=env, remote=(env == "cloud"), log=code_log.SessionLog(self.base(user)), snapshot=lambda u=user, p=project: self._snapshot(u, p),
                        expand=lambda t, u=user, p=project: self.expand_mentions(u, p, t))
            s.events = list(d["events"])
            s.checkpoints = list(meta.get("checkpoints") or [])
            s.started = meta.get("started") or s.started
            s.turns_run = max([c.get("turn", 0) for c in s.checkpoints] + [sum(1 for e in s.events if e["kind"] in ("start", "user"))])
            s.generate, s.max_turns, s.context_tokens = generate, int(build_steps or turns or self.max_turns), context_tokens
            s.build, s.full = bool(build_steps), bool(full)
            s.state = "done"
            s.on_idle = self._session_idle
            if meta.get("model") and meta["model"] != model_id:
                s.emit("model", model=model_id, previous=meta["model"])
            self.sessions[sid], self.by_user[user] = s, sid
        return s

    def queue_position(self, user, sid):
        """1 = next to start, or 0 when the session is not waiting."""
        waiting = sorted((x for x in self.sessions.values() if x.user == user and x.state == "queued"), key=lambda x: x.started)
        return next((i + 1 for i, x in enumerate(waiting) if x.id == sid), 0)

    def _session_idle(self, finished):
        """A session finished a turn: start the user's next queued session, if nothing of theirs is working."""
        with self.lock:
            if self.running(finished.user):
                return
            waiting = sorted((x for x in self.sessions.values() if x.user == finished.user and x.state == "queued"), key=lambda x: x.started)
            if not waiting:
                return
            nxt = waiting[0]
            nxt.state = "starting"
            args = nxt.run_args
        threading.Thread(target=nxt.run, args=args, daemon=True).start()

    # ---- @file mentions and the project instructions file
    MENTION = re.compile(r"(?<![\w@])@([\w][\w./-]{0,119})")

    def expand_mentions(self, user, project, text):
        """The message for the model: a /command of the project's own (.vryx/commands/<name>.md) becomes its text, and each @path that is a file in the
        project gets its contents added (up to 5 files, 6 KB each), so the person can point at a file."""
        text = code_extras.expand_command(self.project_path(user, project), text)
        out, seen = str(text), []
        for m in self.MENTION.finditer(str(text)):
            rel = m.group(1).rstrip(".,;:)")
            if rel in seen or len(seen) >= 5:
                continue
            try:
                f = self.read(user, project, rel)
            except CodeError:
                continue
            seen.append(rel)
            body = f["text"][:6000] + ("\n... (shortened)" if f["truncated"] or len(f["text"]) > 6000 else "")
            out += f"\n\nContents of {rel}:\n```\n{body}\n```"
        return out

    INSTRUCTIONS_TEMPLATE = ("# Project instructions for VryxCode\n\nVryxCode reads this file at the start of every session in this project.\n\n"
                             "## What this project is\n(one or two sentences)\n\n## How to run it and test it\n(for example: python -m unittest)\n\n"
                             "## Style rules\n- (for example: keep functions short, add a test for every change)\n\n## Do not\n- (things VryxCode should leave alone)\n")

    def init_instructions(self, user, project):
        """Create VRYX.md with a starter template (never overwrites): {"created", "path"}."""
        root = self.project_path(user, project)
        os.makedirs(root, exist_ok=True)
        path = os.path.join(root, "VRYX.md")
        if os.path.exists(path):
            return {"created": False, "path": "VRYX.md"}
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.INSTRUCTIONS_TEMPLATE)
        return {"created": True, "path": "VRYX.md"}

    # ---- where a session runs
    def _docker_ok(self):
        now = time.time()
        if now - getattr(self, "_docker_at", 0) > 30 or getattr(self, "_docker", None) is None:
            self._docker_at = now
            self._docker = code_sandbox.available(self.sandbox.get("image", code_sandbox.DEFAULT_IMAGE))
        return self._docker

    # ---- the cloud machine: another computer (for example a rented GPU box) reached over SSH; see cloud_run.py
    def cloud_ready(self, owner=False):
        """(ok, why not)."""
        c = self.cloud
        if not c or not c.get("host"):
            return False, "Not set up. The owner adds it in Settings > Owner > Cloud machine."
        if not shutil.which("ssh"):
            return False, "This computer has no SSH program (ssh)."
        if not os.path.exists(c.get("key", "")):
            return False, "No SSH key yet. The owner makes one in Settings > Owner > Cloud machine."
        if not owner and not c.get("for_others"):
            return False, "Only the owner can use the cloud machine."
        return True, "ready"

    def cloud_prefix(self, user, project):
        c = self.cloud
        work = "emvryx-work/" + re.sub(r"[^A-Za-z0-9_-]", "_", f"{user}-{project}")[:80]
        return [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloud_run.py"), "--host", c["host"], "--port", str(c.get("port", 22)), "--user", c.get("user", "root"),
                "--key", c["key"], "--known-hosts", c["known_hosts"], "--workdir", work, "--timeout", str(c.get("timeout", 90)), "--"]

    def environments(self, owner=False):
        """The places a session can run, for the page: [{"id", "name", "available", "note"}]."""
        forced = self.sandbox.get("mode") == "docker"
        d_ok, d_why = (True, "ready") if forced else self._docker_ok()
        return [
            {"id": "local", "name": "This computer", "available": not forced,
             "note": "The owner runs every session in the sandbox." if forced else "Works in the project folder on the computer that runs Emvryx. Only a short list of programs may run."},
            {"id": "sandbox", "name": "Isolated sandbox", "available": bool(d_ok),
             "note": "Runs inside a locked container: no internet, limited memory and time." if d_ok else d_why},
            {"id": "cloud", "name": "Cloud machine", "available": self.cloud_ready(owner)[0],
             "note": (f"Runs on {self.cloud['host']}: your project is copied there for each command and the changes are copied back." if self.cloud_ready(owner)[0] else self.cloud_ready(owner)[1])}]

    def resolve_env(self, env, owner=False):
        """The environment a session will really use, or a CodeError the person can act on."""
        env = str(env or "local")
        if self.sandbox.get("mode") == "docker":
            return "sandbox"                                   # the owner forces the container for everyone
        if env == "cloud":
            ok, why = self.cloud_ready(owner)
            if not ok:
                raise CodeError("The cloud machine isn't available. " + why, "Choose This computer or the isolated sandbox.")
            return "cloud"
        if env == "sandbox":
            ok, why = self._docker_ok()
            if not ok:
                raise CodeError("The isolated sandbox isn't available. " + why, "Choose This computer, or ask the owner to set up Docker.")
            return "sandbox"
        if env != "local":
            raise CodeError("That environment isn't known.")
        return "local"

    # ---- the history (the Sessions list) and Rewind
    def log(self, user):
        return code_log.SessionLog(self.base(user))

    def _snapshot(self, user, project):
        try:
            return self.export_zip(user, project)
        except CodeError:
            return None

    def list_sessions(self, user):
        """Newest first: the running ones from memory, the rest from the history on disk."""
        now, out = time.time(), {}
        for m in self.log(user).metas():
            if m.get("state") in ("starting", "working", "asking", "queued") and m["id"] not in self.sessions:
                m["state"] = "interrupted"                     # the server was restarted while it was working (or waiting)
            out[m["id"]] = m
        for sid, s in self.sessions.items():
            if s.user == user:
                out[sid] = s.meta()
                if s.state == "queued":
                    out[sid]["position"] = self.queue_position(user, sid)
        rows = sorted(out.values(), key=lambda m: m.get("updated", 0), reverse=True)[:code_log.MAX_SESSIONS]
        for m in rows:
            m["age"] = code_log.age_words(now, m.get("updated", now))
        return rows

    def saved(self, user, sid):
        """A session from the history: {"meta", "events"} (read-only), or a CodeError."""
        d = self.log(user).load(sid)
        if not d:
            raise CodeError("That session isn't here.")
        if d["meta"].get("state") in ("starting", "working", "asking", "queued"):
            d["meta"]["state"] = "interrupted"
        return d

    def delete_session(self, user, sid):
        live = self.sessions.get(sid)
        if live and live.user == user and live.state in ("starting", "working", "asking"):
            raise CodeError("That session is running.", "Stop it first.")
        self.sessions.pop(sid, None)
        self.log(user).delete(sid)

    def _before_and_after(self, user, sid):
        """(workspace, the zip of the project before the session's first message, {path: text} then, {path: text} now)."""
        log = self.log(user)
        d = self.saved(user, sid) if sid not in self.sessions else {"meta": self.sessions[sid].meta()}
        turns = sorted(log.checkpoint_numbers(sid))
        data = log.load_checkpoint(sid, turns[0]) if turns else None
        if not data:
            raise CodeError("The starting point of this session is no longer kept.", "Ask VryxCode to review with git instead: \"run git diff and review it\".")
        workspace = self.project_path(user, d["meta"]["project"])
        after = {}
        for dirpath, dirs, names in os.walk(workspace):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, x))]
            for n in names:
                full = os.path.join(dirpath, n)
                if os.path.islink(full):
                    continue
                try:
                    with open(full, "rb") as f:
                        text = code_review._text_of(f.read(code_review.MAX_FILE_BYTES + 1))
                except OSError:
                    continue
                if text is not None:
                    after[os.path.relpath(full, workspace).replace(os.sep, "/")] = text
        return workspace, data, code_review.snapshot_files(data), after

    def review_session(self, user, sid):
        """The review request for what a session changed: the project before its first message (a saved snapshot) against the files now."""
        _, _, before, after = self._before_and_after(user, sid)
        diff, changed, cut = code_review.diff_files(before, after)
        return {"prompt": code_review.review_prompt(diff, changed, cut, "the changes this session made"), "files": changed}

    def changes(self, user, sid):
        """What the session changed, file by file: [{path, status: new|changed|removed, add, del, diff}], so each can be kept or undone."""
        _, _, before, after = self._before_and_after(user, sid)
        out = []
        for p in sorted(set(before) | set(after)):
            a, b = before.get(p), after.get(p)
            if a == b:
                continue
            diff, _, _ = code_review.diff_files({p: a} if a is not None else {}, {p: b} if b is not None else {}, limit=6000)
            lines = diff.splitlines()
            out.append({"path": p, "status": "new" if a is None else "removed" if b is None else "changed",
                        "add": sum(1 for x in lines if x.startswith("+") and not x.startswith("+++")), "del": sum(1 for x in lines if x.startswith("-") and not x.startswith("---")),
                        "diff": diff})
        return out

    def reject_file(self, user, sid, path):
        """Undo one file of a session: put it back as it was before the session's first message (a file the session made is removed)."""
        if self.running(user):
            raise CodeError("A session is running.", "Stop it first.")
        workspace, data, before, after = self._before_and_after(user, sid)
        rel = self._safe_rel(str(path or ""))
        if rel is None:
            raise CodeError("That is not a file in this project.")
        root = os.path.realpath(workspace)
        full = os.path.realpath(os.path.join(root, rel))
        if not full.startswith(root + os.sep):
            raise CodeError("That is not a file in this project.")
        if before.get(rel) == after.get(rel):
            raise CodeError("That file has not changed in this session.")
        if rel in before:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "wb") as f:
                    f.write(z.read(rel))
        else:
            os.remove(full)
        live = self.sessions.get(sid)
        if live:
            live.history = None                                # what the model remembers no longer matches the files
            live.emit("undo", path=rel)
        return {"path": rel, "restored": rel in before}

    def rewind(self, user, sid, turn):
        """Put the project back as it was before message `turn` of this session (files made since are removed; .git is left alone)."""
        if self.running(user):
            raise CodeError("A session is running.", "Stop it first.")
        log = self.log(user)
        d = self.saved(user, sid) if sid not in self.sessions else {"meta": self.sessions[sid].meta()}
        data = log.load_checkpoint(sid, turn)
        if not data:
            raise CodeError("That point is no longer kept.", "Only the last few messages of a session can be rewound to.")
        workspace = self.project_path(user, d["meta"]["project"])
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise CodeError("That saved point is damaged.")
        root = os.path.realpath(workspace)
        with z:
            names = [i for i in z.infolist() if not i.is_dir()]
            for dirpath, dirs, files in os.walk(root):
                dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
                for n in files:
                    full = os.path.join(dirpath, n)
                    if not os.path.islink(full):
                        os.remove(full)
            for info in names:
                rel = self._safe_rel(info.filename)
                if rel is None:
                    continue
                full = os.path.realpath(os.path.join(root, rel))
                if not full.startswith(root + os.sep):
                    continue
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "wb") as f:
                    f.write(z.read(info))
        live = self.sessions.get(sid)
        label = next((c["label"] for c in d["meta"].get("checkpoints", []) if c["turn"] == int(turn)), "")
        if live:
            live.history = None                                # what the model remembers no longer matches the files
            live.emit("rewind", turn=int(turn), label=label)
        else:
            d = self.saved(user, sid)
            d["events"].append({"n": len(d["events"]) + d.get("offset", 0), "kind": "rewind", "t": 0, "turn": int(turn), "label": label})
            d["meta"]["updated"] = time.time()
            log.save(d["meta"], d["events"])
        return {"project": d["meta"]["project"], "label": label}

    def get(self, user, sid):
        s = self.sessions.get(sid)
        if not s or s.user != user:
            raise CodeError("That session isn't here.")
        return s
