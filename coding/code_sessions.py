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
import threading
import time
import zipfile

import code_sandbox
import harness
import usage_limits as U
import vryxcode

NAME_OK = re.compile(r"[A-Za-z0-9_-]{1,40}")
MAX_FILE_BYTES = 200_000
MAX_EVENT_TEXT = 6000
RESULT_TAGS = re.compile(r"<\|/?(?:end_)?tool_result\|>|<\|end_tool_result\|>")
MAX_IMPORT_FILES, MAX_IMPORT_BYTES, MAX_ONE_FILE = 1000, 20_000_000, 2_000_000
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".emvryx"}


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


class Meter:
    """Counts a coding session against the person's plan, step by step, exactly like chat messages (same tank, same week, same model weight).
    Before each model call the likely cost is held; afterwards the real counts (from llama-server when it reports them) replace the hold."""

    def __init__(self, limiter, user, model_key, clock=time.time, max_new=1024, effort="balanced"):
        self.limiter, self.user, self.key, self.clock, self.max_new, self.effort = limiter, user, model_key, clock, max_new, effort
        self.counted = 0.0
        self.steps = 0

    @staticmethod
    def tokens(messages):
        return sum(len(str(m.get("content", ""))) for m in messages) // 4 + 4 * len(messages)

    def reserve(self, messages):
        est = (self.tokens(messages) + self.max_new) * self.limiter.weight(self.key) * self.limiter.cfg["effort"][self.effort]
        return self.limiter.reserve(self.user, self.key, self.effort, est, self.clock())

    def cancel(self, res):
        self.limiter.cancel(res, self.clock())

    def settle(self, res, generate, messages, reply):
        u = getattr(generate, "usage", None) or {}
        fresh = u.get("fresh_in", self.tokens(messages))
        out = u.get("out", len(reply) // 4)
        self.counted += self.limiter.settle(res, fresh, u.get("cached_in", 0), out, self.effort, self.clock())
        self.steps += 1


class Session:
    """One task being worked on. `events` only ever grows; the page asks for the ones after the last it saw."""

    def __init__(self, sid, user, project, task, model_id, workspace, auto_edits=False, meter=None, tools=None, identity=None, prefix=None, quotas=None, base=None):
        self.meter, self.tools, self.identity = meter, tools, identity
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
        self.generate, self.max_turns, self.context_tokens, self.extra_programs = None, 12, None, ()
        self.turns_run = 0

    def emit(self, kind, **data):
        with self.cv:
            self.events.append({"n": len(self.events), "kind": kind, "t": round(time.time() - self.started, 1), **data})
            self.cv.notify_all()

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

    def respond(self, qid, allow, always=False):
        with self.cv:
            if not self.pending or self.pending["id"] != qid:
                return False
            self.answer = (bool(allow), bool(always))
            self.cv.notify_all()
            return True

    def request_stop(self):
        self.stop.set()
        with self.cv:
            self.cv.notify_all()

    # ---- what the engine calls
    def ask(self, name, args):
        if name == "run" and str(args.get("command", "")).strip().startswith(vryxcode.SAFE_RUNS):
            return True
        if self.auto_edits and name in ("write_file", "edit_file", "run"):
            return True
        if name == "github" and str(args.get("action", "status")) == "status":
            return True                                  # only looking at the link
        if name in getattr(self, "_always", set()) and name != "github":       # pulling and pushing always ask, every time
            return True
        qid = len(self.events)
        shown = vryxcode.preview(name, args)
        if harness.preview_check(self.workspace, name, args) == "":
            shown += "\n\u2713 Checked: no problems found in this change"          # a change with a problem never gets this far: the model is told to fix it first
        with self.cv:
            self.pending, self.answer, self.state = {"id": qid, "tool": name, "preview": clip(shown, 2500)}, None, "asking"
        self.emit("ask", id=qid, tool=name, preview=self.pending["preview"])
        with self.cv:
            while self.answer is None and not self.stop.is_set():
                self.cv.wait(0.5)
            answer = self.answer or (False, False)
            self.pending, self.answer = None, None
            if not self.stop.is_set():
                self.state = "working"
        allow, always = answer
        if always and name != "github":
            self._always = getattr(self, "_always", set()) | {name}
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
            self.live_messages = messages
            if self.stop.is_set():
                raise Stopped()
            if seen["n"] and messages and messages[-1]["role"] == "user":
                self.emit("result", text=clip(RESULT_TAGS.sub("", messages[-1]["content"]).strip()))
                self.check_limits()                                          # a step may have grown the project: check before going on
            seen["n"] += 1
            res = self.meter.reserve(messages) if self.meter else None       # raises U.LimitError when the plan has run out
            self.live = {"phase": "thinking", "since": time.time(), "text": "", "chunks": 0, "thinking": 0}
            try:
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
            self.live = None
            try:
                name, args = harness.parse_tool_call(reply)
                self.emit("step", tool=name, preview=clip(vryxcode.preview(name, args), 2500), raw=clip(reply, 1500))
                if name == "finish" and isinstance(args, dict):
                    nxt = args.get("next")
                    self.next_steps = [clip(str(x), 120) for x in nxt[:3]] if isinstance(nxt, list) else []
                if name != "finish":
                    target = str(args.get("path") or args.get("command") or args.get("args") or args.get("action") or "") if isinstance(args, dict) else ""
                    self.live = {"phase": "running", "since": time.time(), "tool": name, "target": target[:120]}      # the tool runs next; cleared when the next model call starts
            except harness.ToolError:
                pass                                       # words with no tool call: if the turn ends on them they arrive as the "end" message, so no step is shown
            return reply
        return call

    def run(self, generate, max_turns, context_tokens, extra_programs=()):
        """The first turn of the conversation (the task the person typed)."""
        self.generate, self.max_turns, self.context_tokens, self.extra_programs = generate, max_turns, context_tokens, tuple(extra_programs)
        self._turn(self.task, first=True)

    def send(self, text):
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
        threading.Thread(target=self._turn, args=(text, False), daemon=True).start()

    def _turn(self, text, first):
        self.state = "working"
        self.next_steps = []
        self.turns_run += 1
        if self.quotas:
            self.deadline = self.quotas.session_deadline()          # each message gets its own time allowance
        if first:
            self.emit("start", task=text, model=self.model_id, project=self.project)
        else:
            self.emit("user", text=text)
        self.live_messages = None
        try:
            result = vryxcode.run_task(text, self.wrap(self.generate), self.workspace, self.ask, self.max_turns, self.context_tokens, self.extra_programs,
                                       out=lambda *_: None, tools=self.tools, git_identity=self.identity,
                                       command_prefix=self.prefix, container=bool(self.prefix), history=self.history, chat_mode=True)
            self.history = result["messages"]
            self.emit("end", finished=result["finished"], said=bool(result.get("said")), summary=clip(result["summary"], 4000), turns=result["turns"],
                      next=self.next_steps if result["finished"] else [])
            self.state = "done" if (result["finished"] or result.get("said")) else "stopped"
        except U.LimitError as e:
            self._keep_history()
            when = f" Try again in about {max(1, int((e.retry_after or 0) // 60))} minutes." if e.retry_after else ""
            self.emit("end", finished=False, summary=f"Your usage ran out: {e.message}{when} Your files so far are kept.", turns=0, limited=True)
            self.state = "limited"
        except QuotaStop as e:
            self._keep_history()
            self.emit("end", finished=False, summary="Stopped: " + e.message + " Your files so far are kept.", turns=0, limited=True)
            self.state = "limited"
        except Stopped:
            self._keep_history()
            self.emit("end", finished=False, summary="Stopped.", turns=0)
            self.state = "stopped"
        except BaseException as e:                     # a model that cannot be reached, a full disk, ...
            self._keep_history()
            msg = getattr(e, "message", None) or str(e) or e.__class__.__name__
            self.emit("end", finished=False, summary="It could not finish: " + clip(msg, 500), turns=0, error=True)
            self.state = "failed"
        finally:
            self.live = None

    def _keep_history(self):
        """A stopped or failed turn still happened: the next message continues from where it got to."""
        if self.live_messages:
            self.history = list(self.live_messages)


class CodeManager:
    """All projects and sessions on this server."""

    def __init__(self, root, max_turns=12, quotas=None):
        self.root, self.max_turns = root, max_turns          # root=None keeps projects in a temporary folder (tests)
        self.quotas = quotas or code_sandbox.Quotas()
        self.sandbox = {"mode": "none"}                      # set from the command line: {"mode": "docker", "image", "runtime", "cpus", "memory", "pids"}
        self._avail = (0, None)
        self.sessions, self.by_user = {}, {}
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
        return sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)))

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

    def delete_project(self, user, project):
        import shutil
        if self.running(user):
            raise CodeError("A session is running.", "Stop it first.")
        path = self.project_path(user, project)
        if os.path.isdir(path):
            shutil.rmtree(path)

    # ---- sessions
    def running(self, user):
        s = self.sessions.get(self.by_user.get(user))
        return s if s and s.state in ("starting", "working", "asking") else None

    def sandbox_ready(self):
        """(ok, message). In container mode Docker must answer (checked at most every 30 s); there is no quiet fallback to the host."""
        if self.sandbox.get("mode") != "docker":
            return True, "folder sandbox only"
        now = time.time()
        if now - self._avail[0] > 30 or self._avail[1] is None:
            self._avail = (now, code_sandbox.available(self.sandbox.get("image", code_sandbox.DEFAULT_IMAGE)))
        return self._avail[1]

    def prefix_for(self, workspace):
        if self.sandbox.get("mode") != "docker":
            return None
        sb = self.sandbox
        return code_sandbox.docker_prefix(sb.get("image", code_sandbox.DEFAULT_IMAGE), workspace, cpus=sb.get("cpus", "1"), memory=sb.get("memory", "768m"),
                                          pids=sb.get("pids", 128), runtime=sb.get("runtime"))

    def start(self, user, project, task, model_id, generate, auto_edits=False, context_tokens=None, meter=None, outside=False, tools=None, identity=None):
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
            if self.running(user):
                raise CodeError("You already have a session running.", "Stop it or wait for it to finish.")
            ok, why = self.sandbox_ready()
            if not ok:
                raise CodeError("The code sandbox isn't available, so nothing was run. " + why, "The owner needs to start Docker or build the sandbox image.")
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
                        prefix=self.prefix_for(workspace), quotas=self.quotas, base=self.base(user))
            self.sessions[s.id], self.by_user[user] = s, s.id
        threading.Thread(target=s.run, args=(generate, self.max_turns, context_tokens), daemon=True).start()
        return s, note

    def get(self, user, sid):
        s = self.sessions.get(sid)
        if not s or s.user != user:
            raise CodeError("That session isn't here.")
        return s
