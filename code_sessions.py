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
import os
import re
import threading
import time

import harness
import vryxcode

NAME_OK = re.compile(r"[A-Za-z0-9_-]{1,40}")
MAX_FILE_BYTES = 200_000
MAX_EVENT_TEXT = 6000
RESULT_TAGS = re.compile(r"<\|/?(?:end_)?tool_result\|>|<\|end_tool_result\|>")
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".emvryx"}


class CodeError(Exception):
    def __init__(self, message, action=""):
        super().__init__(message)
        self.message, self.action = message, action


class Stopped(Exception):
    pass


def clip(text, limit=MAX_EVENT_TEXT):
    text = str(text)
    return text if len(text) <= limit else text[:limit] + f"\n... ({len(text) - limit} more characters)"


class Session:
    """One task being worked on. `events` only ever grows; the page asks for the ones after the last it saw."""

    def __init__(self, sid, user, project, task, model_id, workspace, auto_edits=False):
        self.id, self.user, self.project, self.task, self.model_id, self.workspace = sid, user, project, task, model_id, workspace
        self.auto_edits = auto_edits
        self.events, self.state = [], "starting"       # starting | working | asking | done | stopped | failed
        self.pending = None                            # the open question, or None
        self.answer = None
        self.stop = threading.Event()
        self.cv = threading.Condition()
        self.started = time.time()

    def emit(self, kind, **data):
        with self.cv:
            self.events.append({"n": len(self.events), "kind": kind, "t": round(time.time() - self.started, 1), **data})
            self.cv.notify_all()

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
        if name in getattr(self, "_always", set()):
            return True
        qid = len(self.events)
        with self.cv:
            self.pending, self.answer, self.state = {"id": qid, "tool": name, "preview": clip(vryxcode.preview(name, args), 2500)}, None, "asking"
        self.emit("ask", id=qid, tool=name, preview=self.pending["preview"])
        with self.cv:
            while self.answer is None and not self.stop.is_set():
                self.cv.wait(0.5)
            answer = self.answer or (False, False)
            self.pending, self.answer = None, None
            if not self.stop.is_set():
                self.state = "working"
        allow, always = answer
        if always:
            self._always = getattr(self, "_always", set()) | {name}
        self.emit("answer", id=qid, allow=allow)
        return allow

    def wrap(self, generate):
        """The model call, with every step reported to the page and a check for Stop."""
        seen = {"n": 0}

        def call(messages):
            if self.stop.is_set():
                raise Stopped()
            if seen["n"] and messages and messages[-1]["role"] == "user":
                self.emit("result", text=clip(RESULT_TAGS.sub("", messages[-1]["content"]).strip()))
            seen["n"] += 1
            reply = generate(messages)
            if self.stop.is_set():
                raise Stopped()
            try:
                name, args = harness.parse_tool_call(reply)
                self.emit("step", tool=name, preview=clip(vryxcode.preview(name, args), 2500), raw=clip(reply, 1500))
            except harness.ToolError:
                self.emit("step", tool="", preview=clip(reply, 1500), raw=clip(reply, 1500))
            return reply
        return call

    def run(self, generate, max_turns, context_tokens, extra_programs=()):
        self.state = "working"
        self.emit("start", task=self.task, model=self.model_id, project=self.project)
        try:
            result = vryxcode.run_task(self.task, self.wrap(generate), self.workspace, self.ask, max_turns, context_tokens, extra_programs,
                                       out=lambda *_: None)
            self.emit("end", finished=result["finished"], summary=clip(result["summary"]), turns=result["turns"])
            self.state = "done" if result["finished"] else "stopped"
        except Stopped:
            self.emit("end", finished=False, summary="Stopped.", turns=0)
            self.state = "stopped"
        except BaseException as e:                     # a model that cannot be reached, a full disk, ...
            msg = getattr(e, "message", None) or str(e) or e.__class__.__name__
            self.emit("end", finished=False, summary="It could not finish: " + clip(msg, 500), turns=0, error=True)
            self.state = "failed"


class CodeManager:
    """All projects and sessions on this server."""

    def __init__(self, root, max_turns=12):
        self.root, self.max_turns = root, max_turns          # root=None keeps projects in a temporary folder (tests)
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

    def start(self, user, project, task, model_id, generate, auto_edits=False, context_tokens=None):
        task = str(task or "").strip()
        if not task:
            raise CodeError("Describe what to build or fix.")
        if len(task) > 8000:
            raise CodeError("That task is too long.", "Keep it under 8,000 characters.")
        ok, note = vryxcode.check_model(model_id)
        if not ok:
            raise CodeError(note)
        with self.lock:
            if self.running(user):
                raise CodeError("You already have a session running.", "Stop it or wait for it to finish.")
            workspace = self.project_path(user, project)
            os.makedirs(workspace, exist_ok=True)
            self._n += 1
            s = Session(f"s{self._n}-{int(time.time())}", user, project, task, model_id, workspace, auto_edits)
            self.sessions[s.id], self.by_user[user] = s, s.id
        threading.Thread(target=s.run, args=(generate, self.max_turns, context_tokens), daemon=True).start()
        return s, note

    def get(self, user, sid):
        s = self.sessions.get(sid)
        if not s or s.user != user:
            raise CodeError("That session isn't here.")
        return s
