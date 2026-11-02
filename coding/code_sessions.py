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

    Main parts, top to bottom: small helpers (built_kind, remove_tree, clip...), Meter (counts usage against the plan), Session (one running task:
    its events, questions and background thread), and CodeManager (starts, finds, stops and lists sessions and projects).
"""
# What the standard-library imports are for: base64 = turns binary data into text and back; io = in-memory files; os = files and folders;
# re = regular expressions (text patterns); shutil = copy/delete whole folders; sys = Python version info; threading = background threads and locks;
# time = clock and sleeping; zipfile = make and read .zip files.
import base64
import io
import os
import re
import shutil
import sys
import threading
import time
import zipfile

# The project's own modules (all in the coding/ folder or on its path): code_extras = memory notes and extra tools; code_log = the session history
# kept on disk; code_report = the written summary of a session; code_map = a map of the project's files; code_options = per-person settings;
# code_review = the automatic review of a finished change; code_sandbox = the Docker container the commands run in; guardrails = the brakes against
# going in circles; harness = the agent loop and its tools; languages = which programming languages are known; usage_limits (U) = the plan limits;
# vryxcode = the terminal version of the agent, sharing the same engine.
import code_extras
import code_log
import code_report
import code_map
import code_options
import code_review
import code_sandbox
import guardrails
import harness
import languages
import usage_limits as U
import vryxcode

# A project or session name: 1 to 40 letters, digits, dashes or underscores. (Used with fullmatch, so nothing else may appear; this also blocks
# "../" tricks that would escape the person's folder.)
NAME_OK = re.compile(r"[A-Za-z0-9_-]{1,40}")
# The largest file (200,000 bytes) the page may open in its file viewer.
MAX_FILE_BYTES = 200_000
# The longest text kept in one event shown on the page (6000 characters); longer text is cut by clip().
MAX_EVENT_TEXT = 6000
# Finds the special marker words the model's chat format puts around tool results (<|tool_result|>, <|end_tool_result|> ...), so they can be
# removed from text before showing it. `(?:...)` is a group that is not remembered; `/?` and `end_` are optional parts.
RESULT_TAGS = re.compile(r"<\|/?(?:end_)?tool_result\|>|<\|end_tool_result\|>")
# Limits when a person imports a project: at most 1000 files, 20 MB in all, and 2 MB for any one file.
MAX_IMPORT_FILES, MAX_IMPORT_BYTES, MAX_ONE_FILE = 1000, 20_000_000, 2_000_000
MAX_QUEUED = 5                                             # sessions that may wait in one person's queue
# Folders left out of file lists, zips and imports: version history, caches, installed packages, Emvryx's own bookkeeping.
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".emvryx"}
# Text added to the model's instructions so it knows built programs are offered for download and it should say where the file is.
DOWNLOAD_NOTE = ("\n\nWhen you build a program (a Windows .exe, an Android .apk, a Linux or Mac program, a .jar), it is offered to the person with a Download "
                 "button under your Done message, and a website or the whole project as a zip. Say where the built file is. Never say you cannot give them "
                 "the file.")
MAX_BUILT = 300_000_000                    # a built program bigger than this is not offered for download
# vryxcode_downloads: what a built program is, by its name and the first bytes inside it (so a text file called .exe is not offered as a program)
# Each file ending maps to (the bytes the file must start with, a plain-words name). "MZ" starts every Windows program, "PK" starts every zip-based
# file (.apk and .jar are zips), \x7fELF starts Linux programs, "!<arch>" starts .deb files. b"" (nothing) accepts any .dmg.
BUILT_EXT = {".exe": (b"MZ", "Windows program"), ".msi": (b"\xd0\xcf\x11\xe0", "Windows installer"), ".apk": (b"PK", "Android app"),
             ".aab": (b"PK", "Android app bundle"), ".jar": (b"PK", "Java program"), ".appimage": (b"\x7fELF", "Linux program"),
             ".deb": (b"!<arch>", "Linux installer"), ".dmg": (b"", "Mac app")}
# The first 4 bytes ("magic number") of a Mac executable in its different forms (32-bit/64-bit, either byte order). Used to spot Mac programs.
MACHO = (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf")


def built_kind(path):
    """"Windows program", "Android app" ... for a program VryxCode built, or None for anything else (source code, text, pictures).

    In: the path of a file. The decision uses both the file ending and the first bytes, so a text file renamed to .exe is not offered.
    """
    try:
        size = os.path.getsize(path)
        # Read only the first 8 bytes: enough to tell the file type.
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return None
    # An empty file, or one over the download limit, is not offered.
    if not size or size > MAX_BUILT:
        return None
    ext = os.path.splitext(path)[1].lower()
    if ext in BUILT_EXT:
        magic, kind = BUILT_EXT[ext]
        return kind if head.startswith(magic) else None
    # os.access(path, os.X_OK) asks "is this file marked executable?"; Linux and Mac programs have no ending but are marked that way.
    if not ext and os.access(path, os.X_OK):                # a program with no extension, as Linux and Mac compilers make them
        if head.startswith(b"\x7fELF"):
            return "Linux program"
        if head[:4] in MACHO:
            return "Mac program"
    return None


def remove_tree(path, tries=3):
    """Delete a folder and everything in it. True when it is gone. On Windows, files a git checkout made read-only (.git/objects) stop a plain
    rmtree, so they are made writable and tried again; a file another program has open is retried after a short wait.

    In: the folder path and how many times to try (default 3). Out: True if the folder no longer exists, False if it could not be removed.
    """
    import stat

    def unlock(func, p, *_):
        """Called by rmtree for each thing it could not delete: make it writable, then try deleting it once more (`func` is the failed delete)."""
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            func(p)
        except OSError:
            pass
    for n in range(tries):
        # Python 3.12 renamed rmtree's error-handler option from onerror to onexc, so pick the right name for this version.
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=unlock)
        else:
            shutil.rmtree(path, onerror=unlock)
        if not os.path.exists(path):
            return True
        # Wait a little longer each time (0.3s, 0.6s, 0.9s) before trying again.
        time.sleep(0.3 * (n + 1))
    return False


# File endings that count as web pages and their scripts/styles; changing one of these triggers the page check and refreshes the Preview.
WEB_FILES = (".html", ".htm", ".js", ".mjs", ".css", ".jsx")
# Matches the wording of the page check's report when it found problems (case ignored). `a|b` means "a or b".
PAGE_TROUBLE = re.compile(r"loaded, with problems|did not finish loading", re.I)
# How many times VryxCode is asked to fix a page automatically after the page check reports trouble.
PAGE_FIX_TRIES = 2
AUTO_ROUNDS = 5                                            # vryxcode_autocontinue: at most this many extra rounds of steps per message
# The message sent to the model on its automatic extra round when it ran out of steps before finishing.
CONTINUE_TEXT = ("You used all your steps for this round and the task is not finished. Carry on from exactly where you stopped (do not start over), "
                 "and finish the task. When it is really done and checked, call finish with what you did.")


class CodeError(Exception):
    """An error with words for the person: `message` says what went wrong, `action` (optional) says what they can do about it."""

    def __init__(self, message, action=""):
        super().__init__(message)
        self.message, self.action = message, action


class Stopped(Exception):
    """Raised inside a session when the person pressed Stop, to jump out of the work at once."""
    pass


class QuotaStop(Exception):
    """A coding session ran past one of the person's limits (time, or the project got too big)."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def clip(text, limit=MAX_EVENT_TEXT):
    """`text` cut to at most `limit` characters, with a note of how many were left out. Keeps events and page data from growing huge."""
    text = str(text)
    return text if len(text) <= limit else text[:limit] + f"\n... ({len(text) - limit} more characters)"


def context_meter(used, window):
    """How full the model's memory is for the meter by the task box: harness.run_agent folds the older steps at harness.fold_point (75%, at most 96K)."""
    # `used` = tokens now in the conversation, `window` = the model's memory size in tokens. Keep used >= 0 and window >= 1 (so no divide by zero).
    used, window = max(0, int(used)), max(1, int(window))
    # pct is the percent full (at most 100, one decimal); compact_at is the size at which older steps get folded into a short summary.
    return {"used": used, "window": window, "pct": round(min(100.0, 100.0 * used / window), 1), "compact_at": harness.fold_point(window)}


def change_counts(workspace, name, args):
    """{"add", "del"}: the lines a write or an edit adds and takes away (for "+52 -3" in the session list and the file chips), worked out before it runs.
    {} for any other step.

    In: the project folder, the tool's name and its arguments dict. Out: {"add": n, "del": n} or {}.
    """
    if name not in ("write_file", "edit_file") or not isinstance(args, dict):
        return {}
    import difflib
    if name == "edit_file":
        # edit_file swaps the text `old` for `new`: compare those two.
        old, new = str(args.get("old", "")).splitlines(), str(args.get("new", "")).splitlines()
    else:
        new, old = str(args.get("content", "")).splitlines(), []
        # A write that is not an "append" replaces the whole file, so the old lines are what the file holds now (none if it is new).
        if not args.get("append"):
            try:
                # realpath resolves symlinks and "..", and the startswith check makes sure the file is really inside the project folder.
                full = os.path.realpath(os.path.join(workspace, str(args.get("path", ""))))
                if full.startswith(os.path.realpath(workspace) + os.sep) and os.path.isfile(full):
                    with open(full, encoding="utf-8", errors="replace") as f:
                        old = f.read().splitlines()
            except (OSError, ValueError):
                old = []
    add = rem = 0
    # get_opcodes() lists the differences: each has a kind (tag) and the range of old lines (i1..i2) and new lines (j1..j2) it covers.
    # Lines in the old range are removed; lines in the new range are added.
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            rem += i2 - i1
        if tag in ("replace", "insert"):
            add += j2 - j1
    return {"add": add, "del": rem}


def _folded_steps(messages):
    """How many old steps are listed under "Earlier steps" in the task message (harness.compact puts them there); 0 when nothing was folded."""
    # The task message is the first "user" message; next(..., None) takes the first match or None.
    first = next((m for m in messages if m.get("role") == "user"), None)
    if not first or "\n\nEarlier steps:\n" not in str(first.get("content", "")):
        return 0
    # Count the non-empty lines after the "Earlier steps:" heading.
    return len([l for l in str(first["content"]).split("\n\nEarlier steps:\n", 1)[1].split("\n") if l.strip()])


class Meter:
    """Counts a coding session against the person's plan, step by step, exactly like chat messages (same tank, same week, same model weight).
    Before each model call the likely cost is held; afterwards the real counts (from llama-server when it reports them) replace the hold.
    Steps count at limits.json code_rate, and the hold counts what the last step already sent as cached: each step resends the same project,
    so counting it all as new text again emptied a Mega tank in a handful of Apogee steps.

    `limiter` is the shared usage limiter (the plan rules), `user` the person, `model_key` the model, `clock` a time function (replaced in tests),
    `max_new` the most new tokens one step may write, `effort` the effort level (it scales the cost). A token is a small piece of text (about 4 characters).
    """

    def __init__(self, limiter, user, model_key, clock=time.time, max_new=1024, effort="balanced"):
        self.limiter, self.user, self.key, self.clock, self.max_new, self.effort = limiter, user, model_key, clock, max_new, effort
        self.counted = 0.0                                 # total usage charged to the plan so far in this session
        self.steps = 0                                     # model calls settled so far
        self.seen = 0                                      # tokens the last step sent and got back (llama-server keeps them cached)

    @staticmethod
    def tokens(messages):
        """A rough token count of a list of chat messages: about 1 token per 4 characters, plus 4 per message for the chat format's own markers."""
        return sum(len(str(m.get("content", ""))) for m in messages) // 4 + 4 * len(messages)

    def reserve(self, messages):
        """Before a model call: hold the likely cost against the plan. Returns the limiter's reservation (to settle or cancel later).

        The model server remembers text it saw last step ("cached"), and cached text is charged at a cheaper rate (the "cached_in" multiplier).
        """
        total = self.tokens(messages)
        cached = min(total, self.seen)
        # held = new text at full price + cached text at the cheaper price + the most the reply could add.
        held = total - cached + cached * self.limiter.cfg["multipliers"]["cached_in"] + self.max_new
        # Scale by the model's weight, the effort level and the code rate (limits.json) to get the cost in plan units.
        est = held * self.limiter.weight(self.key) * self.limiter.cfg["effort"][self.effort] * self.limiter.code_rate()
        return self.limiter.reserve(self.user, self.key, self.effort, est, self.clock())

    def cancel(self, res):
        """Give the held amount back (the model call did not happen or failed)."""
        self.limiter.cancel(res, self.clock())

    def settle(self, res, generate, messages, reply):
        """After a model call: replace the hold with the real cost.

        `generate` may carry a `usage` dict with the true counts from llama-server (fresh input, cached input, output tokens); when it does not,
        the counts are estimated from the text length.
        """
        u = getattr(generate, "usage", None) or {}
        fresh = u.get("fresh_in", self.tokens(messages))
        out = u.get("out", len(reply) // 4)
        self.counted += self.limiter.settle(res, fresh, u.get("cached_in", 0), out, self.effort, self.clock(), rate=self.limiter.code_rate())
        self.steps += 1
        # Remember how much text this step sent plus its reply: llama-server will have cached it, so the next step's hold counts it as cached.
        self.seen = self.tokens(messages) + len(reply) // 4


# vryxcode_preview: the model knew nothing of the app's live preview, so asked for a link it said it "cannot generate links or host files" and told
# the person to find the file themselves
PREVIEW_NOTE = ("\nThe person sees a live Preview of this project's web pages in the app, next to this chat: it opens the page you changed last and "
                "refreshes by itself after every change. When they ask for a link, or how to see or run what you built, tell them to press Preview "
                "(top right), or the Preview button under your last message. Never say you cannot make links or host files, and never tell them to "
                "find the file on their computer. Web pages (HTML, CSS, JavaScript) show there; a Python or Node server cannot, so for those build the "
                "page in HTML and JavaScript where you can.")


class Session:
    """One task being worked on. `events` only ever grows; the page asks for the ones after the last it saw.

    A Session holds everything about one coding task: the events the page shows, the open question (if any), the stop flag, the conversation so far,
    and the settings it runs with. The work itself runs on a background thread (a thread is a second line of execution running at the same time as
    the web server); the web requests only read events and answer questions. A `threading.Condition` (self.cv) lets the two sides wait for each other.
    Argument meanings: sid = session id, user/project = whose and which folder, task = the person's request, model_id = which model,
    workspace = the project's folder path, auto_edits = approve edits without asking, meter = usage counting, tools = extra tools,
    identity = git author for commits, prefix = docker words for commands (None = run locally), quotas = limits checker, base = the person's
    projects folder, env = "local" or "sandbox", log = history on disk, snapshot = function that zips the project, plan = plan-only first turn,
    expand = function that expands @file mentions, remote = commands run on the cloud machine over SSH.
    """

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
        self._auto_rounds = 0                           # vryxcode_autocontinue: times it carried on by itself after using all its steps, this message
        self._page_tries = 0                            # automatic fixes after the app's own page check found problems, this message
        self.archived = False                           # vryxcode_archive: tucked away in the Archived list (kept, not shown in the normal list)
        self.notify, self.on_notify = False, None       # tell the owner's phone when a turn ends or it needs an answer (set by the server)

    def emit(self, kind, **data):
        """Add an event (a step, a result, a question, "end"...) for the page to show. Numbered in order; wakes anyone waiting; saves history."""
        # `with self.cv` takes the lock so another thread cannot change events at the same moment.
        with self.cv:
            # n = position in the list, t = seconds since the session started; **data adds the event's own fields.
            self.events.append({"n": len(self.events), "kind": kind, "t": round(time.time() - self.started, 1), **data})
            self.updated = time.time()
            # Wake up any thread waiting on this condition (for example one waiting for an answer) so it checks again.
            self.cv.notify_all()
        # Important moments are saved to disk at once; others at most every 2 seconds (see persist).
        self.persist(force=kind in ("start", "user", "end", "rewind"))

    # ---- the history on disk (the Sessions list)
    def meta(self):
        """The summary row of this session for the Sessions list: title, state, step count, files touched, lines added/removed, checkpoints."""
        steps, files, snippet, added, removed, pending = 0, set(), "", 0, 0, None
        for e in self.events:
            # A real step is one that used a tool (the closing "finish" does not count).
            if e["kind"] == "step" and e.get("tool") and e.get("tool") != "finish":
                steps += 1
                # The preview text starts "write <file>" or "edit <file>"; capture the file name to count distinct files.
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
        # The title is the task with all runs of whitespace squeezed to single spaces, cut to 70 characters.
        title = " ".join(str(self.task).split())[:70]
        row = {"id": self.id, "title": title, "project": self.project, "model": self.model_id, "env": self.env, "state": self.state, "started": self.started,
               "updated": self.updated, "snippet": clip(snippet, 220), "steps": steps, "files": len(files), "checkpoints": list(self.checkpoints),
               "added": added, "removed": removed}
        if self.archived:
            row["archived"] = True                       # only present when on: a session that was never archived has the same summary as always
        return row

    _save_lock = threading.Lock()                         # one save or delete of a session's history at a time (shared: saves are short)

    def persist(self, force=False):
        """Save this session's history to disk (if a log is set). Unless `force`, at most once every 2 seconds, so a busy session is not slowed down."""
        if not self.log:
            return
        now = time.time()
        if not force and now - self._saved_at < 2.0:
            return
        self._saved_at = now
        try:
            # Copy the events while holding the lock, then write the copy without holding it.
            with self.cv:
                events = list(self.events)
            with Session._save_lock:
                if getattr(self, "deleted", False):
                    return                                # deleted while it was finishing: its last save must not bring it back
                self.log.save(self.meta(), events)
                if getattr(self, "replay", None):
                    self.log.save_replay(self.id, {"task": self.task, "model": self.model_id, "project": self.project, "env": self.env,
                                                   "full": bool(getattr(self, "full", False)), "steps": list(self.replay)})
        except (OSError, ValueError):
            pass                                          # the history is a convenience: never stop the work for it

    def _checkpoint(self, label):
        """The project as it is before this message, so Rewind can bring it back.

        `label` is the message text, shortened to 60 characters for the list. Needs a history log and a snapshot function; otherwise does nothing.
        """
        if not (self.log and self.snapshot_fn):
            return
        try:
            # snapshot_fn() returns the project zipped into bytes; save_checkpoint stores it on disk and says whether it worked.
            data = self.snapshot_fn()
            if data and self.log.save_checkpoint(self.id, self.turns_run, data):
                self.checkpoints.append({"turn": self.turns_run, "t": round(time.time(), 1), "label": " ".join(str(label).split())[:60]})
                # Keep only the newest few checkpoints (a negative slice takes the last N).
                self.checkpoints = self.checkpoints[-code_log.MAX_CHECKPOINTS:]
        except (CodeError, OSError):
            pass

    def _on_delta(self, info):
        """Called as the model writes its reply, piece by piece ("delta" = a new piece). Stores the latest text so the page's spinner can show it."""
        live = self.live
        if live is not None and live.get("phase") != "running":
            live.update(text=info.get("text", ""), chunks=info.get("chunks", 0), thinking=info.get("thinking_chars", 0))

    def live_view(self):
        """For the page's spinner: {"phase": thinking|writing|calling|running, "secs", "tokens", "text", "tool"} or None. Never the raw tool-call JSON."""
        live = self.live
        if not live:
            return None
        secs = round(time.time() - live["since"], 1)
        # A tool (a command or edit) is running: nothing to stream, just say which one.
        if live["phase"] == "running":
            return {"phase": "running", "secs": secs, "tokens": 0, "text": "", "tool": live.get("tool", ""), "target": live.get("target", "")}
        text = live.get("text", "")
        # The model writes plain words first, then a tool call after a marker. Find where the marker starts (-1 = no tool call yet);
        # `if i >= 0` drops the "not found" results and default=-1 covers the case where both were dropped.
        cut = min([i for i in (text.find("<|tool_call|>"), text.find("<tool_call>")) if i >= 0], default=-1)
        # Only the words before the marker are shown, never the raw tool-call JSON.
        prose = (text if cut < 0 else text[:cut]).strip()
        tool = target = ""
        if cut >= 0:
            # Pull the tool's name out of the partly written JSON with a regex: "name" : "word".
            m = re.search(r'"name"\s*:\s*"(\w+)"', text[cut:])
            tool = m.group(1) if m else ""
            t = re.search(r'"(?:path|command)"\s*:\s*"([^"]{1,120})', text[cut:])      # the file or command, as soon as it has been written
            target = t.group(1) if t else ""
        # calling = writing a tool call; writing = writing words; thinking = nothing written yet.
        phase = "calling" if cut >= 0 else ("writing" if prose else "thinking")
        return {"phase": phase, "secs": secs, "tokens": live.get("chunks", 0), "text": clip(prose, 400), "tool": tool, "target": target}

    def since(self, after):
        """For the page's polling: (events after position `after`, the session state, the open question or None)."""
        with self.cv:
            return list(self.events[after:]), self.state, self.pending

    def respond(self, qid, allow, always=False, choice=None):
        """The person's answer to the open question `qid`. Returns False if that question is not open (already answered or stale), else True.

        Yes/no questions use `allow` (and `always` = "do not ask again for this kind"); a multiple-choice question uses `choice` (the option text).
        """
        with self.cv:
            # Ignore an answer that is for an old question.
            if not self.pending or self.pending["id"] != qid:
                return False
            if self.pending.get("tool") == "ask_user":           # a multiple-choice question: the answer is the option picked (or the person's own words)
                text = clip(str(choice or "").strip(), 500)
                if not text:
                    return False
                self.answer = ("choice", text)
            else:
                self.answer = (bool(allow), bool(always))
            # Wake the work thread, which is waiting for this answer.
            self.cv.notify_all()
            return True

    def ask_choice(self, question=None, options=None):
        """The ask_user tool (the full agent): the person picks one of 2 to 4 options, or writes their own answer."""
        # Clean the inputs: the question is cut to 400 characters; options must be a list, each cut to 120, empty ones dropped, at most 4 kept.
        question = clip(str(question or "").strip(), 400)
        opts = [clip(str(o).strip(), 120) for o in (options if isinstance(options, list) else []) if str(o).strip()][:4]
        if not question or len(opts) < 2:
            raise harness.ToolError('ask_user needs a question and 2 to 4 options, like {"question": "Which database?", "options": ["SQLite", "PostgreSQL"]}')
        # The question's id is the current number of events, which is unique because events only grow.
        qid = len(self.events)
        with self.cv:
            self.pending, self.answer, self.state = {"id": qid, "tool": "ask_user", "question": question, "options": opts}, None, "asking"
        self.emit("choose", id=qid, question=question, options=opts)
        self._tell("asking")
        # Wait here (this is the work thread) until respond() sets an answer or Stop is pressed. wait(0.5) sleeps up to half a second or until woken,
        # then the loop checks again.
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
        # getattr(self, "full", False): `full` is only set on the full-agent sessions, so default to False when it was never set.
        if not getattr(self, "full", False):
            return self.tools
        extra = {"ask_user": self.ask_choice}
        # The memory tool needs the person's projects folder to store notes in.
        if self.base:
            extra["remember"] = lambda note=None: code_extras.remember(self.base, note)
        # dict(a, **b) = a copy of a with b's entries added (an empty dict if there were no tools).
        return dict(self.tools or {}, **extra)

    def _memory_note(self):
        """Text added to the model's instructions in the full agent: how to use its memory tool plus what it remembered earlier. "" otherwise."""
        if not getattr(self, "full", False) or not self.base:
            return ""
        return code_extras.MEMORY_TOOL_NOTE + code_extras.memory_note(self.base)

    # The line added to the message when pictures are attached; {n} is replaced by how many.
    PICTURE_MARK = "[The person attached {n} picture(s) to this message: look at them.]"

    def attach_pictures(self, urls):
        """Screenshots sent with the next message (the full agent): data: URLs of PNG, JPEG, WebP or GIF, up to 3, 5 MB each. Returns the line added to the message."""
        # Keep a URL only if it is text, looks like data:image/<png|jpg|jpeg|webp|gif>;base64,<base64 characters> (the regex), and is under about
        # 7 million characters (a 5 MB picture grows by about a third in base64); then keep at most 3.
        good = [u for u in (urls or []) if isinstance(u, str) and re.match(r"^data:image/(png|jpe?g|webp|gif);base64,[A-Za-z0-9+/=]+$", u) and len(u) <= 7_000_000][:3]
        if not good:
            self._pictures = None
            return ""
        mark = self.PICTURE_MARK.format(n=len(good))
        self._pictures = (mark, good)
        return mark

    # The words placed in front of a message the person typed while the model was already working.
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
            # Queue it; the work loop picks the queued messages up before the next step. getattr gives [] the first time.
            self._steers = getattr(self, "_steers", []) + [text]
        self.emit("user", text=text, steer=True)

    def compact_now(self):
        """The "Compact now" button. While it works, the fold happens before the next step ("next_step"); between messages the remembered conversation is
        folded at once (the number of steps folded, 0 when there is nothing old enough).

        "Folding" = replacing old steps in the conversation with a short list, so the model's limited memory has room. Returns a small dict for the page.
        """
        # Busy: just set a flag; wrap()'s call() checks it before the next model call.
        if self.state in ("starting", "working", "asking"):
            self.want_compact = True
            return {"when": "next_step"}
        if not self.history:
            return {"when": "now", "folded": 0}
        new = harness.fold_now(self.history)
        # If the folded version is not shorter, nothing was old enough to fold.
        if len(new) >= len(self.history):
            return {"when": "now", "folded": 0}
        self.history = new
        steps = _folded_steps(new)
        self.emit("compacted", steps=steps, manual=True)
        # Tell the page the new size of the memory meter.
        if self.context_tokens:
            self.emit("context", **context_meter(harness.estimate_tokens(new), self.context_tokens))
        return {"when": "now", "folded": steps}

    def request_stop(self):
        """The Stop button. A queued session is simply removed; a running one gets its stop flag set and ends at its next step."""
        if self.state == "queued":                       # never started: take it out of the queue
            self.state = "stopped"
            self.emit("end", finished=False, summary="Removed from the queue.", turns=0)
            self.persist(force=True)
            return
        # threading.Event.set() raises the flag the work thread checks; notify_all wakes it if it is waiting for an answer to a question.
        self.stop.set()
        with self.cv:
            self.cv.notify_all()

    # ---- what the engine calls
    def rules_path(self):
        """This project's saved permission rules (the full agent), kept in the person's folder: None in a session without one (tests)."""
        return code_extras.rules_path(self.base, self.project) if self.base else None

    def ask(self, name, args):
        """The engine's permission question: may the model use tool `name` with `args`? Returns True (go ahead) or False (refused).

        Safe or already-approved actions return True straight away. Otherwise the work thread posts a question on the page ("ask" event) and
        waits until the person answers via respond() or presses Stop. "Always" answers are remembered for the rest of the session.
        """
        full = getattr(self, "full", False)            # the Claude Code-style agent: its permission rules too
        command = str(args.get("command", "")).strip() if name == "run" and isinstance(args, dict) else ""
        # The project's saved rules come first: "deny" refuses without asking, "allow" approves without asking, anything else falls through.
        if full and self.rules_path() and name != "github":
            verdict = code_extras.decide(self.rules_path(), name, harness.command_keys(command) if name == "run" else [])
            if verdict == "deny":
                self.emit("note", text="Not allowed by this project's rules: " + clip(command or name, 120))
                return False
            if verdict == "allow":
                return True
        # Commands that only look are allowed without asking. The old agent has a fixed safe list (the tests); the full agent checks the command.
        if name == "run":
            if full:
                # only looks (ls, cat, git status, the tests), or only makes, moves or copies files in "Edit without asking", or "always allow" was said for this command
                if (harness.read_only_command(command) or (self.auto_edits and harness.file_command(command))
                        or "run:" + harness.command_key(command) in getattr(self, "_always", set())):
                    return True
            elif command.startswith(vryxcode.SAFE_RUNS):
                return True
        # "Auto-approve edits": file changes (and, for the old agent, every command) go ahead without a question.
        if self.auto_edits and name in (("write_file", "edit_file", "rollback") if full else ("write_file", "edit_file", "run", "rollback")):
            return True
        if name == "github" and str(args.get("action", "status")) == "status":
            return True                                  # only looking at the link
        if name == "check_page":
            return True                                  # the browser check only looks (and cannot reach the internet): no question
        if name in ("stop_app", "app_logs") or (name == "start_app" and self.auto_edits):
            return True                                  # stopping or reading the app changes nothing; starting it asks like a command unless edits run without asking
        if name in getattr(self, "_always", set()) and name != "github":       # pulling and pushing always ask, every time
            return True
        # None of the shortcuts applied, so ask the person. The question id is the event count, which is unique.
        qid = len(self.events)
        # `shown` is the readable description of the action (a diff, a command...) that the page puts in the question box.
        shown = vryxcode.preview(name, args)
        if harness.preview_check(self.workspace, name, args) == "":
            shown += "\n\u2713 Checked: no problems found in this change"          # a change with a problem never gets this far: the model is told to fix it first
        with self.cv:
            self.pending, self.answer, self.state = {"id": qid, "tool": name, "preview": clip(shown, 2500)}, None, "asking"
        self.emit("ask", id=qid, tool=name, preview=self.pending["preview"])
        self._tell("asking")
        # Wait for respond() to fill in self.answer (or Stop). wait(0.5) sleeps up to half a second or until notified, then the loop re-checks.
        with self.cv:
            while self.answer is None and not self.stop.is_set():
                self.cv.wait(0.5)
            # No answer (because of Stop) counts as "no".
            answer = self.answer or (False, False)
            self.pending, self.answer = None, None
            if not self.stop.is_set():
                self.state = "working"
        # answer is (allow?, always?)
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
        """Raise QuotaStop if this message has run past its time allowance or the person's storage is full. Called between steps."""
        if self.deadline and time.time() > self.deadline:
            raise QuotaStop(f"This session ran for the longest time allowed ({self.quotas.q['code_session_minutes']} minutes).")
        if self.quotas and self.base:
            try:
                self.quotas.room(self.base, self.workspace)
            except code_sandbox.QuotaError as e:
                raise QuotaStop(e.message + " " + e.action)

    def wrap(self, generate):
        """The model call, with every step reported to the page and a check for Stop.

        In: `generate`, the function that asks the model for its next reply given the chat messages. Out: `call`, a function with the same shape
        that the agent loop uses instead. Before and after each model call it updates the page (results, memory meter, steps), applies messages the
        person typed meanwhile, counts usage and stops when asked. Settings flags on `generate` are copied onto `call` at the end.
        """
        # `seen` is a small dict shared by every call of this turn: "n" counts model calls; "folded" remembers how many steps were folded.
        seen = {"n": 0}

        def call(messages):
            manual = False
            if self.want_compact:                                                     # "Compact now" was pressed while it worked: fold before this step
                self.want_compact = False
                new = harness.fold_now(messages)
                manual = len(new) < len(messages)
                # messages[:] = new replaces the list's contents in place (the loop holds this same list, so rebinding the name would not reach it)
                messages[:] = new                                                     # the same list the loop keeps using
            folded = _folded_steps(messages)
            if (seen.get("folded") == 0 and folded > 0) or manual:                   # the first time this turn that old steps were folded into the "Earlier steps" list to save room
                self.emit("compacted", steps=folded, **({"manual": True} if manual else {}))
            seen["folded"] = folded
            if self.context_tokens:                                                    # the memory meter on the page (feature flag context_meter)
                self.emit("context", **context_meter(harness.estimate_tokens(messages), self.context_tokens))
            self.live_messages = messages
            # Pressed Stop: jump out before spending another model call.
            if self.stop.is_set():
                raise Stopped()
            # After the first call, the last message is the previous tool's result (sent as a "user" message): show it on the page, minus the
            # chat-format marker tags.
            if seen["n"] and messages and messages[-1]["role"] == "user":
                self.emit("result", text=clip(RESULT_TAGS.sub("", messages[-1]["content"]).strip()))
                self.check_limits()                                          # a step may have grown the project: check before going on
            # Take the queued steering messages and empty the queue in one step, under the lock.
            with self.cv:
                steers, self._steers = getattr(self, "_steers", []), []
            if steers:                                                       # typed while it worked: the model reads it now, after the last result
                note = "\n\n".join(self.STEER + t for t in steers)
                # Add the note to the last user message if there is one (two user messages in a row confuse the chat format), else add a new one.
                if messages and messages[-1]["role"] == "user":
                    messages[-1] = dict(messages[-1], content=messages[-1]["content"] + "\n\n" + note)
                else:
                    messages.append({"role": "user", "content": note})
            seen["n"] += 1
            # Hold the cost against the plan before calling the model.
            res = self.meter.reserve(messages) if self.meter else None       # raises U.LimitError when the plan has run out
            self.live = {"phase": "thinking", "since": time.time(), "text": "", "chunks": 0, "thinking": 0}
            # Hook the model call up to this session. Plain functions accept new attributes, but some callables do not, hence the try.
            try:
                generate.pictures = getattr(self, "_pictures", None)     # screenshots sent with the message: the model sees them on every step of this turn
                generate.on_delta = self._on_delta         # the model call reports its progress here (a plain function accepts the attribute too)
                generate.should_stop = self.stop.is_set    # ...and asks here whether Stop was pressed
            except AttributeError:
                pass
            # The actual model call. If it fails (or is interrupted), give the held usage back first; an interruption becomes Stopped, anything
            # else is raised again unchanged (a bare `raise` re-raises the same error).
            try:
                reply = generate(messages)
            except BaseException as e:
                self.live = None
                if self.meter:
                    self.meter.cancel(res)
                if isinstance(e, vryxcode.Interrupted):
                    raise Stopped()
                raise
            if getattr(generate, "record", False):        # vryxcode_record: the model's whole reply, for replaying the session later (tools/replay_vryx.py)
                self._record({"model": reply})
            # Replace the hold with the real usage now that the reply is in.
            if self.meter:
                self.meter.settle(res, generate, messages, reply)
            if self.stop.is_set():
                raise Stopped()
            took = {"secs": round(time.time() - self.live["since"], 1), "words": self.live.get("chunks", 0)} if self.live else {}      # what the live line showed: kept on the step
            self.live = None
            # Read the tool call out of the reply and report it to the page as a "step". A reply with no readable tool call raises ToolError.
            try:
                name, args = harness.parse_tool_call(reply)
                self.emit("step", tool=name, preview=clip(vryxcode.preview(name, args), 2500), raw=clip(reply, 1500), **took, **change_counts(self.workspace, name, args))
                # The finish tool may list up to 3 suggested next steps for the page to show as buttons.
                if name == "finish" and isinstance(args, dict):
                    nxt = args.get("next")
                    self.next_steps = [clip(str(x), 120) for x in nxt[:3]] if isinstance(nxt, list) else []
                if name != "finish":
                    target = str(args.get("path") or args.get("command") or args.get("args") or args.get("action") or "") if isinstance(args, dict) else ""
                    self.live = {"phase": "running", "since": time.time(), "tool": name, "target": target[:120]}      # the tool runs next; cleared when the next model call starts
            except harness.ToolError as e:
                # "no tool call found" is normal (the model just wrote words); any other error means a broken call:
                if not str(e).startswith("no tool call found"):     # a tool call that could not be read: it is sent back to the model to try again, so say so and keep what it wrote
                    # prose = the words the model wrote before the tool-call marker, with chat-format tags removed.
                    prose = RESULT_TAGS.sub("", re.split(r"<\|tool_call\|>|<tool_call>", reply)[0]).strip()
                    self.emit("retry", text=clip(prose, 400), why=clip(str(e), 200), limit=bool(getattr(generate, "cut_off", False)), **took)
                # words with no tool call: if the turn ends on them they arrive as the "end" message, so no step is shown
            return reply
        # Copy the feature switches that the agent loop reads from the model call onto the wrapper (the loop only sees `call`).
        call.fixes = getattr(generate, "fixes", False)          # vryxcode_fixes reaches the agent loop (harness.run_agent reads it from the model call)
        call.guardrails = getattr(generate, "guardrails", False)     # ...and so does vryxcode_guardrails
        call.autocheck = getattr(generate, "autocheck", False)       # ...and vryxcode_autocheck
        call.record = getattr(generate, "record", False)             # ...and vryxcode_record
        call.secrets = getattr(generate, "secrets", None)           # ...and vryxcode_secrets (the values go to the sandbox, never to the model)
        return call

    def run(self, generate, max_turns, context_tokens, extra_programs=()):
        """The first turn of the conversation (the task the person typed). Runs on the thread that calls it (the manager's background thread).

        Saves the model call and limits for later follow-up messages, then runs one turn.
        """
        self.generate, self.max_turns, self.context_tokens, self.extra_programs = generate, max_turns, context_tokens, tuple(extra_programs)
        self._turn(self.task, first=True, plan=self.plan_first)

    def send(self, text, plan=False, model_text=None):
        """The person's next message: another turn of the same conversation (the model sees everything said and done so far)."""
        # Check the message: not empty, at most 8000 characters.
        text = str(text or "").strip()
        if not text:
            raise CodeError("Write a message first.")
        if len(text) > 8000:
            raise CodeError("That message is too long.", "Keep it under 8,000 characters.")
        # Only one turn may run at a time, and a session that was never given a model call (for example one restored from disk) cannot continue.
        with self.cv:
            if self.state in ("starting", "working", "asking"):
                raise CodeError("It is still working.", "Wait for it to finish, or press Stop.")
            if self.generate is None:
                raise CodeError("This session cannot continue.", "Start a new one.")
            self.state = "working"
            self.stop.clear()
        # A new message resets the automatic-retry counters.
        self._auto_tries = self._page_tries = self._auto_rounds = 0
        self._model_text = model_text                       # what the model gets instead of the line the person sees (a code review's diff)
        # Run the turn on its own background thread so this web request can return at once. daemon=True means the thread will not keep the
        # program alive when the server shuts down.
        threading.Thread(target=self._turn, args=(text, False, bool(plan)), daemon=True).start()

    def _turn(self, text, first, plan=False, auto=False):
        """Run one turn: one message from the person (or an automatic follow-up) until the model finishes, stops, or fails.

        In: `text` = the message, `first` = True for the very first message, `plan` = look and plan only, `auto` = this is an automatic follow-up
        (a retry, a page fix or a "carry on"), not something the person typed. Always ends by leaving a final state ("done", "stopped", "limited",
        "failed") and an "end" event, unless it starts an automatic follow-up turn from the `finally` block (`again` / `retried`).
        """
        retried, again = False, None
        self.state = "working"
        self.next_steps = []
        self.turns_run += 1
        if self.quotas:
            self.deadline = self.quotas.session_deadline()          # each message gets its own time allowance
        # Save the project as it is now so Rewind can come back to this point; then announce the turn on the page.
        self._checkpoint(text)
        if first:
            self.emit("start", task=text, model=self.model_id, project=self.project, plan=plan, turn=self.turns_run)
        else:
            self.emit("user", text=text, plan=plan, turn=self.turns_run, **({"auto": True} if auto else {}))
        # vryxcode_record: write the turn into the replay file.
        if getattr(self.generate, "record", False):
            self._record({"user": text, "plan": bool(plan), "first": bool(first), "model_text": bool(getattr(self, "_model_text", None))})
        self.live_messages = None
        # Everything below is inside try/except so every way of ending (finish, limit, Stop, crash) is turned into a clear final state.
        try:
            # model_text = the text the model gets when it differs from what the person typed (for example a code review's diff). Used once.
            model_text, self._model_text = getattr(self, "_model_text", None), None
            if not auto and not model_text and getattr(self.generate, "options", False) and code_options.vague(text):
                # vryxcode_options: an open-ended message ("let's build something"): talk first and offer choices, instead of guessing
                question, choices = code_options.options_for(text, self._top_files())
                try:
                    picked = self.ask_choice(question, choices)
                except harness.ToolError:
                    # ask_choice raises this when the person stopped before answering.
                    raise Stopped()
                model_text = code_options.with_choice(text, picked.split("The person chose: ", 1)[-1])
            # Work out which programming language fits the request and what can run here; the person and the model are both told.
            lang = languages.decide(model_text or text, self.env, self.workspace)      # which language fits, and what can run here: told to the person and to the model
            line = languages.page_line(lang)
            if line:
                self.emit("language", text=line, language=lang["name"], mode=lang["mode"])
            # The main call: run the agent on the task. The long lang_note string is the extra instructions: language advice + memory + (when the
            # matching feature flags are on) notes about the Preview, downloads and guardrails. out=lambda *_: None throws away terminal printing
            # (the page shows events instead). command_prefix/container say where commands run; history lets a follow-up continue the conversation.
            result = vryxcode.run_task(model_text or self.expand(text), self.wrap(self.generate), self.workspace, self.ask, self.max_turns, self.context_tokens, self.extra_programs, lang_note=languages.note_for(lang) + self._memory_note() + (PREVIEW_NOTE if getattr(self.generate, "preview", False) else "") + (DOWNLOAD_NOTE if getattr(self.generate, "downloads", False) else "") + (guardrails.PROMPT_NOTE if getattr(self.generate, "guardrails", False) else ""),
                                       out=lambda *_: None, tools=self._tools_now(),
                                       git_identity=self.identity,
                                       command_prefix=self.prefix, container=bool(self.prefix) and not self.remote, history=self.history, chat_mode=True, plan=plan, todo=True, remote=self.remote,
                                       build=getattr(self, "build", False), full=getattr(self, "full", False),
                                       open_host=bool(getattr(self.generate, "open_pc", False)) and self.prefix is None and not self.remote and self.env == "local")
            # Keep the whole conversation so the next message continues it. Then, unless stopped, let the app open the web page itself as proof.
            self.history = result["messages"]
            report = None if self.stop.is_set() else self._page_proof()
            if report and PAGE_TROUBLE.search(report) and self._page_tries < PAGE_FIX_TRIES:
                # the app opened the page itself and it is broken: like a person would, it goes back and fixes it before saying it is done
                self._page_tries += 1
                # `again` is the text of an automatic follow-up turn; the `finally` block below starts it after this turn is wrapped up.
                again = ("I opened the page in a browser and it does not work yet:\n" + clip(report, 1500) +
                         "\nFix these problems, then open it again with check_page and finish only when it loads with no errors.")
                return
            # (the plain `return` above still runs the `finally` block, which is where the follow-up turn is started)
            # used every step without finishing (not stopped by a guardrail, by the person, or because it got stuck)
            out_of_steps = not result["finished"] and not result.get("said") and not result.get("stopped") and not self.stop.is_set()
            if out_of_steps and getattr(self.generate, "autocontinue", False) and self._auto_rounds < AUTO_ROUNDS:
                self._auto_rounds += 1                  # vryxcode_autocontinue: carry on by itself (usage limits still stop it)
                self.emit("note", text=f"Used all {result['turns']} steps and it is not finished yet: carrying on by itself ({self._auto_rounds} of {AUTO_ROUNDS}).")
                again = CONTINUE_TEXT
                return
            # Normal ending: record the result. "said" = the model answered in words without calling finish (a question or a plan).
            self._end( finished=result["finished"], said=bool(result.get("said")), summary=clip(result["summary"], 4000), turns=result["turns"],
                      next=self.next_steps if result["finished"] else [], plan=bool(plan) and bool(result["finished"] or result.get("said")),
                      **({"reason": "steps", "rounds": self._auto_rounds} if out_of_steps else {}))
            self.state = "done" if (result["finished"] or result.get("said")) else "stopped"
        # The person's plan ran out of usage: say when to come back. The files already written are kept.
        except U.LimitError as e:
            self._keep_history()
            when = f" Try again in about {max(1, int((e.retry_after or 0) // 60))} minutes." if e.retry_after else ""
            self._end( finished=False, summary=f"Your usage ran out: {e.message}{when} Your files so far are kept.", turns=0, limited=True)
            self.state = "limited"
        # The session's own limits (time or storage) were reached.
        except QuotaStop as e:
            self._keep_history()
            self._end( finished=False, summary="Stopped: " + e.message + " Your files so far are kept.", turns=0, limited=True)
            self.state = "limited"
        # The person pressed Stop.
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
        # `finally` runs whichever way the try ended. First it starts any automatic follow-up turn (a page fix, "carry on", or one retry after
        # an unexpected error); only when there is none does it do the normal tidy-up.
        finally:
            if again:
                return self._turn(again, False, auto=True)
            if retried:
                return self._turn("The last step failed with this error: " + clip(msg, 400) + ". Look at what went wrong, then carry on from where you stopped and finish the task.", False, auto=True)
            self.live = None
            self.persist(force=True)
            # Tell the owner's phone (if enabled) that the turn ended.
            if self.state not in ("starting", "working", "asking"):
                self._tell(self.state)
            idle = getattr(self, "on_idle", None)
            if idle and self.state not in ("starting", "working", "asking"):
                try:
                    idle(self)                            # the next queued session may start
                except Exception:
                    pass

    def _top_files(self):
        """The files and folders at the top of the project (empty for a new project)."""
        try:
            return [n for n in os.listdir(self.workspace) if not n.startswith(".")]
        except OSError:
            return []

    def _page_proof(self):
        """Proof before "done": when this turn changed the web page and nothing opened it since, the app opens it itself (the model is not trusted to
        remember) and the result goes in the feed. The report, or None when there was nothing to check."""
        tool = (self.tools or {}).get("check_page")
        if not tool:
            return None
        # Walk this turn's events in order, remembering the position of the last web-file edit and of the last page check, and the page's name.
        last_web, last_check, page = -1, -1, ""
        for i, e in enumerate(code_report._turn_events(self.events)):
            if e.get("kind") != "step":
                continue
            m = re.match(r"(?:write|edit) (\S+)", str(e.get("preview", "")))
            if e.get("tool") in ("write_file", "edit_file") and m and m.group(1).lower().endswith(WEB_FILES):
                last_web, page = i, (m.group(1) if m.group(1).lower().endswith((".html", ".htm")) else page)
            elif e.get("tool") == "check_page":
                last_check = i
        # Nothing web-related changed, or the model already opened the page after its last change: nothing to prove.
        if last_web < 0 or last_check > last_web:
            return None
        self.emit("step", tool="check_page", preview=f"check_page {page or 'the main page'} (the app opens the page itself before it says it is done)", auto=True)
        # Run the page check (a headless browser opens the page). A missing browser is reported but is not an error in the person's page.
        try:
            report = tool(page) if page else tool()
        except Exception as e:                            # noqa: BLE001  (a missing browser is not a broken page)
            report = "Browser check could not run: " + (getattr(e, "message", None) or str(e))
        self.emit("result", text=clip(report))
        return report

    def switch_model(self, model_id, generate, context_tokens, meter, build_steps=None, default_turns=12):
        """Another model takes over this conversation (the same session, the same history): the next message runs on it.

        In: the new model's id, its model-call function `generate`, its memory size, a new usage Meter, and (for the long-build models) the step
        budget `build_steps`; otherwise `default_turns` steps. Not allowed while a turn is running.
        """
        with self.cv:
            if self.state in ("starting", "working", "asking"):
                raise CodeError("It is still working.", "Wait for it to finish, or press Stop, then pick the other model.")
        # Swap all the model-specific fields at once, remembering the old model's id for the event below.
        old, self.model_id, self.generate, self.context_tokens, self.meter = self.model_id, model_id, generate, context_tokens, meter
        # Having a build_steps number means this is a long-build model: turn the long-build loop on and use that many steps.
        self.build, self.max_turns = bool(build_steps), int(build_steps or default_turns)
        self.emit("model", model=model_id, previous=old)

    def set_effort(self, generate, turns):
        """Another effort for the next message (feature flag vryxcode_effort): its step budget and its model call (Deep thinks before each step)."""
        # Changing settings under a running turn would confuse it, so refuse until it is idle.
        with self.cv:
            if self.state in ("starting", "working", "asking"):
                raise CodeError("It is still working.", "Wait for it to finish, or press Stop, then change the effort.")
        self.generate, self.max_turns = generate, int(turns)

    def catch_up(self, text):
        """For a session brought back from the history (the model's own memory of it is gone): what happened so far, then the new message."""
        # Build a short recap from the saved events: what the person asked (start/user events) and how each turn ended (end events).
        lines = []
        for e in self.events:
            if e["kind"] in ("start", "user") and (e.get("task") or e.get("text")):
                lines.append("The user asked: " + clip(str(e.get("task") or e.get("text")), 600))
            elif e["kind"] == "end" and e.get("summary"):
                lines.append("Result: " + clip(str(e["summary"]), 600))
        # Keep only the last 8 lines so the recap stays short, then put it in front of the new message (only if there is any recap).
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
                # A notification is a convenience: a failure must never break the work.
                pass
        push = getattr(self, "on_push", None)              # pwa_push: the browsers this person turned notifications on in
        if push:
            try:
                push(self, kind)
            except Exception:
                pass

    def _end(self, **data):
        """The end of a turn. When it did any work the end carries its verification report (so it is in the history on disk too)."""
        # Build the verification report (what was changed and checked) from this turn's events.
        try:
            report = code_report.build_report(self.events, end=data)
        except Exception:                                 # the report is a convenience: never fail a turn over it
            report = None
        self._pictures = None                              # the screenshots belong to the message that brought them
        if getattr(self.generate, "guardrails", False) and data.get("summary"):
            v = code_review.verdict(data["summary"])        # vryxcode_guardrails: a review's verdict, decided by the severities; only CRITICAL and MAJOR go back
            if v:
                # "blocking" problems must be fixed; "nits" are minor notes. `**({...} if ... else {})` adds the "fix" request only when needed.
                data["verdict"] = {"status": v["status"], "blocking": len(v["blocking"]), "nits": len(v["defects"]) - len(v["blocking"]),
                                   **({"fix": code_review.fix_request(v["blocking"])} if v["blocking"] else {})}
        # **data spreads the end fields into the event; the report is added only if one was built.
        self.emit("end", **data, **({"report": report} if report else {}))

    REPLAY_MAX = 600                                       # recorded steps per session, each cut at 60,000 characters

    def _record(self, item):
        """One step of the replay recording: the person's message or the model's whole reply (the owner's own sessions, flag vryxcode_record)."""
        # setdefault returns the "replay" list, creating it empty the first time. Recording stops at REPLAY_MAX steps; long text is cut to 60,000 characters.
        rec = self.__dict__.setdefault("replay", [])
        if len(rec) < self.REPLAY_MAX:
            rec.append({k: (v[:60000] if isinstance(v, str) else v) for k, v in item.items()})

    def _keep_history(self):
        """A stopped or failed turn still happened: the next message continues from where it got to."""
        if self.live_messages:
            self.history = list(self.live_messages)


class CodeManager:
    """All projects and sessions on this server.

    One instance is shared by the whole server. It knows where each person's projects live on disk, starts and finds Sessions, and offers the file
    operations the Code screen needs (list, read, save, import, zip). Many web requests use it at once, so shared dicts are guarded by `self.lock`.
    `root` is the data folder (None = use a temporary folder, for tests); `max_turns` the default steps per message; `quotas` the size/time limits.
    """

    def __init__(self, root, max_turns=12, quotas=None):
        self.root, self.max_turns = root, max_turns          # root=None keeps projects in a temporary folder (tests)
        self.quotas = quotas or code_sandbox.Quotas()
        self.cloud = None                                    # the cloud machine: {"host", "port", "user", "key", "known_hosts", "for_others"} set by the server (None = not set up)
        self.sandbox = {"mode": "none"}                      # set from the command line: {"mode": "docker", "image", "runtime", "cpus", "memory", "pids"}
        self._avail = (0, None)                              # a cached answer to "is the sandbox ready?" (when it was checked, the answer)
        self.sessions, self.by_user = {}, {}                 # session id -> Session; person -> their sessions
        self._run_locks = {}                                 # person -> a lock so they run only one editor command at a time
        self.lock = threading.Lock()
        self._tmp = None                                     # the temporary folder, made on first use when root is None
        self._n = 0                                          # counter used to make session ids

    # ---- projects
    def base(self, user):
        """The folder that holds all of one person's projects (made if missing). The person's name is cleaned: any character that is not a letter,
        digit, dash or underscore becomes "_", so a name can never point outside the data folder."""
        if self.root:
            path = os.path.join(self.root, "code", re.sub(r"[^A-Za-z0-9_-]", "_", user))
        else:
            import tempfile
            self._tmp = self._tmp or tempfile.mkdtemp(prefix="vryx_code_")
            path = os.path.join(self._tmp, re.sub(r"[^A-Za-z0-9_-]", "_", user))
        os.makedirs(path, exist_ok=True)
        return path

    def check_name(self, project):
        """Return the project name if it is allowed (see NAME_OK), else raise CodeError. fullmatch means the whole name must fit the pattern."""
        if not NAME_OK.fullmatch(str(project or "")):
            raise CodeError("That project name isn't allowed.", "Use letters, numbers, dashes and underscores (up to 40).")
        return project

    def projects(self, user):
        """The sorted names of this person's projects (the folders with allowed names)."""
        base = self.base(user)
        return sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)) and NAME_OK.fullmatch(d))

    def project_path(self, user, project):
        """The folder of one project; the name is checked first so it cannot contain "../" or slashes."""
        return os.path.join(self.base(user), self.check_name(project))

    def files(self, user, project):
        """The project's file paths (relative, with "/"), sorted, at most 500. Hidden bookkeeping folders and symbolic links are left out."""
        path, out = self.project_path(user, project), []
        if not os.path.isdir(path):
            return out
        for dirpath, dirs, names in os.walk(path):
            # Edit dirs in place so os.walk skips unwanted folders; links are skipped so nothing outside the project is listed.
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d)))
            for n in sorted(names):
                full = os.path.join(dirpath, n)
                if not os.path.islink(full):
                    # Paths are shown with "/" on every system.
                    out.append(os.path.relpath(full, path).replace(os.sep, "/"))
            # Stop walking once there are more than enough.
            if len(out) > 500:
                break
        return out[:500]

    def search(self, user, project, query):
        """Search the project's files for `query` (the work is done by code_map.search)."""
        return code_map.search(self.project_path(user, project), query)

    def project_map(self, user, project):
        """An overview (map) of the project's files and what is in them, from code_map."""
        return code_map.project_map(self.project_path(user, project))

    def read(self, user, project, rel):
        """Read one project file for the page: {"path", "text", "truncated"}. `rel` is its path inside the project."""
        # realpath resolves "..", links and so on, so the startswith check below proves the file is really inside the project folder.
        root = os.path.realpath(self.project_path(user, project))
        full = os.path.realpath(os.path.join(root, rel))
        if not (full == root or full.startswith(root + os.sep)) or not os.path.isfile(full):
            raise CodeError("That file isn't in the project.")
        # Read one byte more than the limit, so we can tell whether the file was cut.
        with open(full, "rb") as f:
            data = f.read(MAX_FILE_BYTES + 1)
        # A zero byte (\0) near the start is the usual sign of a binary file (a picture, a program), which cannot be shown as text.
        if b"\0" in data[:2000]:
            return {"path": rel, "text": "(a binary file)", "truncated": False}
        return {"path": rel, "text": data[:MAX_FILE_BYTES].decode("utf-8", "replace"), "truncated": len(data) > MAX_FILE_BYTES}

    def run_command(self, user, project, command, owner=False, env="local", own_pc=False):
        """The editor's output panel: run one command in the project the way a session would (the same allowed programs, the same sandbox or cloud choice, no network where
        it can be cut), for the person, with no model involved. Refused while VryxCode is working in the same project. Returns {"command", "exit", "output", "secs", "env"}."""
        project = self.check_name(project)
        command = str(command or "").strip()
        if not command or len(command) > 500:
            raise CodeError("Type a command to run.", "For example: python -m unittest")
        # Do not run while a model session is changing the same project.
        for x in self.sessions.values():
            if x.user == user and x.project == project and x.state in ("starting", "working", "asking"):
                raise CodeError("VryxCode is working in this project right now.", "Wait for it to finish, or press Stop, then run it.")
        mine = bool(owner) and bool(own_pc) and str(env or "local") == "local"     # the owner's own This computer (vryxcode_owner_pc)
        # Commands from other people must run inside the sandbox; refuse if it is not ready. (The owner's own computer skips this.)
        ok, why = (True, "") if mine else self.sandbox_ready()
        if not ok:
            raise CodeError("The code sandbox isn't available, so nothing was run. " + why, "The owner needs to start Docker or build the sandbox image.")
        env = "local" if mine else self.resolve_env(env, owner)
        workspace = self.project_path(user, project)
        os.makedirs(workspace, exist_ok=True)
        # `prefix` = the words put in front of the command so it runs somewhere safe: on the cloud machine, in a Docker container, or nothing (None).
        prefix = None if mine else self.cloud_prefix(user, project) if env == "cloud" else self.prefix_for(workspace, force=(env == "sandbox"))
        kw = {}
        if prefix:
            kw.update(command_prefix=prefix, container=not env == "cloud", remote=(env == "cloud"))
        # One command at a time per person: try to take their lock without waiting (blocking=False) and refuse if it is taken.
        lock = self._run_locks.setdefault(user, threading.Lock())
        if not lock.acquire(blocking=False):
            raise CodeError("A command is already running for you.", "Wait for it to finish.")
        started = time.time()
        # try/finally: the lock is always released, even if the command fails.
        try:
            with harness.Sandbox(workspace=workspace, allowed_programs=set(harness.ALLOWED_PROGRAMS), command_timeout=120 if env == "cloud" else 60, output_limit=12000, **kw) as sb:
                try:
                    result = sb.run(command)
                except harness.ToolError as e:
                    # The sandbox refused the command (for example a program that is not allowed). 126 is the shell's usual "cannot run" code.
                    result = f"exit code 126\n{e}"
        finally:
            lock.release()
        # The sandbox's answer starts with a line "exit code N" and then the output; split them apart.
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
        # Turn Windows line endings (\r\n) into plain \n, then encode the text as UTF-8 bytes to measure and write it.
        data = text.replace("\r\n", "\n").encode("utf-8")
        if len(data) > MAX_FILE_BYTES:
            raise CodeError("That file is too big to edit here.", f"The editor handles files up to {MAX_FILE_BYTES // 1000} KB.")
        # _safe_rel cleans the path (or raises if it tries to escape); then block empty names, bookkeeping folders and very long names.
        name = self._safe_rel(rel)
        if not name or any(p in SKIP_DIRS for p in name.split("/")) or len(name) > 200:
            raise CodeError("That file name isn't allowed.", "Use a name inside the project, not in .git or .emvryx.")
        workspace = self.project_path(user, project)
        root = os.path.realpath(workspace)
        full = os.path.realpath(os.path.join(root, name))
        # Second safety check, after links are resolved: the final path must still be inside the project.
        if not full.startswith(root + os.sep):
            raise CodeError("That file isn't in the project.")
        exists = os.path.isfile(full)
        if os.path.islink(os.path.join(root, name)):
            raise CodeError("That is a link, not a file.")
        if os.path.isdir(full):
            raise CodeError("That name is a folder.")
        # An existing file with a zero byte near the start is binary: do not overwrite it with text.
        if exists:
            with open(full, "rb") as f:
                if b"\0" in f.read(2000):
                    raise CodeError("That is a binary file; it can't be edited here.")
        # Check the person still has room (storage size and file count) for this save.
        try:
            os.makedirs(root, exist_ok=True)
            self.quotas.room(self.base(user), workspace, extra_bytes=len(data), extra_files=0 if exists else 1)
        except code_sandbox.QuotaError as e:
            raise CodeError(e.message, e.action)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        # Write to a temporary name first, then swap it into place in one step (os.replace): a crash half-way never leaves a broken file.
        tmp = full + ".saving"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, full)
        return {"path": name, "size": len(data), "created": not exists}

    def built_files(self, user, project):
        """vryxcode_downloads: the programs this project has built, to download: [{"path", "kind", "size"}]. A file counts by what is inside it,
        not only its name (a .exe must really be a Windows program), and nothing in node_modules, .git or caches."""
        root = self.project_path(user, project)
        out, seen = [], 0
        for dirpath, dirs, names in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d)))
            for n in sorted(names):
                full = os.path.join(dirpath, n)
                seen += 1
                # Look at no more than 5000 files, so a huge project does not make this slow.
                if seen > 5000:
                    return out
                if os.path.islink(full):
                    continue
                # built_kind returns the program type (or None); only real programs are listed.
                kind = built_kind(full)
                if kind:
                    out.append({"path": os.path.relpath(full, root).replace(os.sep, "/"), "kind": kind, "size": os.path.getsize(full)})
        return out

    def built_path(self, user, project, rel):
        """The full path of one built program in the project, or None (not built, not there, or outside the project)."""
        root = os.path.realpath(self.project_path(user, project))
        full = os.path.realpath(os.path.join(root, str(rel or "").replace("\\", "/")))
        # Refuse anything outside the project, or inside a skipped folder (such as node_modules).
        if not full.startswith(root + os.sep) or any(p in SKIP_DIRS for p in os.path.relpath(full, root).split(os.sep)):
            return None
        return full if os.path.isfile(full) and built_kind(full) else None

    def export_zip(self, user, project):
        """The whole project as zip bytes (without .git, caches and node_modules)."""
        path = self.project_path(user, project)
        if not os.path.isdir(path):
            raise CodeError("That project isn't here.")
        # io.BytesIO is a file kept in memory; the zip is built into it and handed back as bytes. ZIP_DEFLATED = compress the files.
        buf, total = io.BytesIO(), 0
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for dirpath, dirs, names in os.walk(path):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d)))
                for n in sorted(names):
                    full = os.path.join(dirpath, n)
                    if os.path.islink(full):
                        continue
                    # Add up the sizes and give up past 50 MB.
                    total += os.path.getsize(full)
                    if total > 50_000_000:
                        raise CodeError("That project is too big to download as one zip.")
                    # The second argument is the name inside the zip: the path relative to the project folder.
                    z.write(full, os.path.relpath(full, path))
        return buf.getvalue()

    @staticmethod
    def _safe_rel(name):
        """A path from an upload, made safe: None to skip it, CodeError if it tries to escape."""
        # Use "/" everywhere and drop any leading slash (so the path is relative), then split it into folder/file parts, dropping empty and "." parts.
        name = str(name).replace("\\", "/").lstrip("/")
        parts = [p for p in name.split("/") if p not in ("", ".")]
        if not parts:
            return None
        # ".." means "go up a folder" and "C:" starts a Windows drive path: both try to leave the project, so refuse the whole upload.
        if ".." in parts or re.match(r"^[A-Za-z]:", parts[0]):
            raise CodeError("That upload has a path that leaves the project.", "Nothing was imported.")
        # A file inside .git, node_modules and so on (every part except the last, the file name) is silently skipped.
        if any(p in SKIP_DIRS for p in parts[:-1]):
            return None
        return "/".join(parts)

    def import_files(self, user, project, entries):
        """entries: [(path, bytes)]. Writes them into the project (overwriting). Returns how many were written."""
        if self.running(user):
            raise CodeError("A session is running.", "Stop it first.")
        root = os.path.realpath(self.project_path(user, project))
        # First pass: clean every path and check the size limits, writing nothing yet, so a bad upload imports nothing at all.
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
        # Second check: after links are resolved, every target must still be inside the project.
        for rel, data in clean:
            full = os.path.realpath(os.path.join(root, rel))
            if not full.startswith(root + os.sep):
                raise CodeError("That upload has a path that leaves the project.", "Nothing was imported.")
        os.makedirs(root, exist_ok=True)
        # Make sure the person's storage quota has room for everything.
        try:
            self.quotas.room(self.base(user), root, extra_bytes=total, extra_files=len(clean))
        except code_sandbox.QuotaError as e:
            raise CodeError(e.message, e.action)
        # Everything passed: now write the files.
        for rel, data in clean:
            full = os.path.join(root, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as f:
                f.write(data)
        return len(clean)

    def import_zip(self, user, project, data):
        """Import the files of a zip (`data` = the zip file's bytes) into the project. Returns how many files were written."""
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise CodeError("That isn't a zip file.")
        entries, total = [], 0
        with z:
            for info in z.infolist():
                # The top 16 bits of external_attr hold the Unix file mode; 0o170000 masks the file-type part and 0o120000 means "symbolic link".
                if info.is_dir() or (info.external_attr >> 16) & 0o170000 == 0o120000:     # folders and symlinks are skipped
                    continue
                # Check the sizes the zip declares BEFORE unpacking, so a "zip bomb" (a tiny zip that expands hugely) is refused.
                total += info.file_size
                if info.file_size > MAX_ONE_FILE or total > MAX_IMPORT_BYTES or len(entries) >= MAX_IMPORT_FILES:
                    raise CodeError("That zip is too big to import (up to 1,000 files, 20 MB, 2 MB each).", "Nothing was imported.")
                entries.append((info.filename, z.read(info)))
        return self.import_files(user, project, entries)

    def import_b64(self, user, project, body):
        """Either {"zip_b64": ...} or {"files": [{"path", "b64"}]}. (b64 = base64, text that carries binary data inside JSON.) Returns the file count."""
        try:
            # validate=True makes b64decode reject any character that is not valid base64 instead of silently ignoring it.
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
        # Must be inside the project, a real file, and not a symbolic link (a link could point at a file outside the project).
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
        # Do not copy a project while a session is changing it (the copy could catch a half-finished edit).
        if self.running(user) and any(x.project == project and x.state in ("starting", "working", "asking") for x in self.sessions.values() if x.user == user):
            raise CodeError("A session is working in that project.", "Wait for it to finish, then make the copy.")
        # Strip an existing "-try" or "-try-2" ending so copies of copies do not pile up suffixes; cut to 34 characters so the new name stays
        # under the 40-character limit. Then pick the first free name: shop-try, shop-try-2, shop-try-3 ...
        base = re.sub(r"-try(-\d+)?$", "", project)[:34]
        name, n = base + "-try", 2
        while os.path.exists(self.project_path(user, name)):
            name = f"{base}-try-{n}"
            n += 1
        # Ask the quota checker whether the person may have another project and has room for a copy this size.
        try:
            self.quotas.new_project(self.base(user), name)
            self.quotas.room(self.base(user), src, extra_bytes=0)
        except code_sandbox.QuotaError as e:
            raise CodeError(e.message, e.action)
        dst = self.project_path(user, name)
        # Copy everything except version history, installed packages and caches; symlinks=False copies what a link points to, not the link itself.
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__", ".emvryx"), symlinks=False)
        return name

    def adopt_project(self, user, copy, into):
        """Use a copy's files in the original: the original is first saved as "<into>-before" (so nothing is lost), then its files are replaced by the copy's."""
        # a = the copy, b = the original project that will receive the copy's files.
        a, b = self.project_path(user, copy), self.project_path(user, into)
        if copy == into or not os.path.isdir(a) or not os.path.isdir(b):
            raise CodeError("Pick a copy and the project it came from.")
        if any(x.user == user and x.project in (copy, into) and x.state in ("starting", "working", "asking") for x in self.sessions.values()):
            raise CodeError("A session is working in one of them.", "Wait for it to finish.")
        # Find a free backup name: <into>-before, then -before-2, -before-3 ...
        backup, n = into + "-before", 2
        while os.path.exists(self.project_path(user, backup)):
            backup = f"{into}-before-{n}"
            n += 1
        try:
            self.quotas.new_project(self.base(user), backup)
        except code_sandbox.QuotaError as e:
            raise CodeError(e.message, e.action)
        # Move the original aside as the backup (a rename is instant and loses nothing), then copy the copy's files into the original's place.
        os.rename(b, self.project_path(user, backup))
        shutil.copytree(a, b, ignore=shutil.ignore_patterns(".emvryx"), symlinks=False)
        git = os.path.join(self.project_path(user, backup), ".git")
        if os.path.isdir(git):                                    # the history stays with the original
            shutil.copytree(git, os.path.join(b, ".git"))
        return {"project": into, "backup": backup}

    def delete_project(self, user, project):
        """Delete a whole project folder. Refused while a session of that person is working in it, and reported in words if files stay locked."""
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
        """True if any session of anyone is working now (list(...) takes a copy so the dict can change while we look)."""
        return any(x.state in ("starting", "working", "asking") for x in list(self.sessions.values()))

    def _own_pc(self, generate, owner, env):
        """True when the owner turned on "nothing blocked on this computer" (vryxcode_open_pc, owner only: routes_code sets generate.open_pc) and
        picked This computer: it runs on the PC itself, even where the PC runs everyone else in Docker, and whether or not Docker is answering.
        Their explicit choice, never a quiet fallback for anyone else; picking the isolated sandbox still means the sandbox.
        vryxcode_owner_pc (generate.owner_pc, admins only) does the same with the usual short list of allowed programs."""
        # Either of the two owner-only feature switches (set on the model call) counts.
        mine = bool(getattr(generate, "open_pc", False)) or bool(getattr(generate, "owner_pc", False))
        return bool(owner) and mine and str(env or "local") == "local"

    def sandbox_ready(self):
        """(ok, message). In container mode Docker must answer (checked at most every 30 s); there is no quiet fallback to the host."""
        if self.sandbox.get("mode") != "docker":
            return True, "folder sandbox only"
        now = time.time()
        # Ask Docker again only if the last answer is older than 30 seconds (asking is slow), or there is no answer yet.
        if now - self._avail[0] > 30 or self._avail[1] is None:
            self._avail = (now, code_sandbox.available(self.sandbox.get("image", code_sandbox.DEFAULT_IMAGE)))
        return self._avail[1]

    def prefix_for(self, workspace, force=False):
        """The `docker run ...` words that put a command inside the locked container (project folder only, with CPU/memory/process limits).

        Returns None when containers are not in use (and `force` is False), which means "run in the project folder directly".
        """
        if self.sandbox.get("mode") != "docker" and not force:
            return None
        sb = self.sandbox
        return code_sandbox.docker_prefix(sb.get("image", code_sandbox.DEFAULT_IMAGE), workspace, cpus=sb.get("cpus", "1"), memory=sb.get("memory", code_sandbox.DEFAULT_MEMORY),
                                          pids=sb.get("pids", code_sandbox.DEFAULT_PIDS), runtime=sb.get("runtime"))

    def start(self, user, project, task, model_id, generate, auto_edits=False, context_tokens=None, meter=None, outside=False, tools=None, identity=None, env="local", plan=False, owner=False, queue=False, model_text=None,
              build_steps=None, turns=None, full=False, pictures=None):
        """Start a new coding session. Returns (the Session, a note about the model). Raises CodeError with words for the person if it may not start.

        Main inputs: user and project (whose folder), task (the request), model_id, generate (the model-call function), env ("local", "sandbox"
        or "cloud"), queue (wait in line if the person is already running one), owner (is this the server owner), and optional extras
        (plan-only, long-build step budget, full agent, attached pictures). The work runs on a background thread, or waits in the queue.
        """
        # Check the request text: not empty, at most 8000 characters.
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
        # Everything that checks and changes the shared dicts happens under the lock, so two requests cannot both start a session at once.
        with self.lock:
            busy = self.running(user)
            if busy and not queue:
                raise CodeError("You already have a session running.", "Stop it or wait for it to finish.")
            if busy and sum(1 for x in self.sessions.values() if x.user == user and x.state == "queued") >= MAX_QUEUED:
                raise CodeError(f"{MAX_QUEUED} sessions are already waiting in your queue.", "Wait for some to finish, or stop one.")
            # The owner can choose to run directly on the PC; everyone else must have a working sandbox.
            own_pc = self._own_pc(generate, owner, env)
            if not own_pc:
                ok, why = self.sandbox_ready()
                if not ok:
                    raise CodeError("The code sandbox isn't available, so nothing was run. " + why,
                                    "On the PC, open Docker Desktop and wait until it says Running, then try again. (Or, for your own sessions, switch on "
                                    "\u201cVryxCode: nothing blocked on this computer\u201d in Admin > Previews and pick This computer.)" if owner else
                                    "The owner needs to start Docker or build the sandbox image.")
            env = "local" if own_pc else self.resolve_env(env, owner)
            workspace = self.project_path(user, project)
            # Make the project folder and check the person's limits (number of projects, storage, sessions allowed).
            try:
                self.quotas.new_project(self.base(user), project)
                os.makedirs(workspace, exist_ok=True)
                self.quotas.room(self.base(user), workspace)
                self.quotas.start_session(user)
            except code_sandbox.QuotaError as e:
                raise CodeError(e.message, e.action)
            # A unique id: a counter plus the time. The long Session(...) call gives it the model, the place commands run (prefix) and its helpers;
            # the lambdas (small unnamed functions) take u and p as default arguments so they keep these values.
            self._n += 1
            s = Session(f"s{self._n}-{int(time.time())}", user, project, task, model_id, workspace, auto_edits, meter, tools, identity,
                        prefix=(None if own_pc else self.cloud_prefix(user, project) if env == "cloud" else self.prefix_for(workspace, force=(env == "sandbox"))), quotas=self.quotas, base=self.base(user),
                        env=env, remote=(env == "cloud"), log=code_log.SessionLog(self.base(user)), snapshot=lambda u=user, p=project: self._snapshot(u, p), plan=bool(plan),
                        expand=lambda t, u=user, p=project: self.expand_mentions(u, p, t))
            # Register it so the page can find it.
            self.sessions[s.id], self.by_user[user] = s, s.id
            s._model_text = model_text                          # what the model gets instead of the line the person sees (a second opinion's diff)
            s.build = bool(build_steps)                         # a model made for long builds (VryxCode 3): the long-build loop and its own step budget
            s.full = bool(full)                                 # the Claude Code-style agent (VryxCode 3, feature flag vryxcode_full_agent)
            mark = s.attach_pictures(pictures) if full and pictures else ""
            if mark:                                            # screenshots sent with the task: the model is told, and sees them
                s.task = task + "\n\n" + mark
            turns = int(build_steps or turns or self.max_turns)      # turns: the step budget of the effort picked (feature flag vryxcode_effort)
            # When a turn ends, _session_idle starts this person's next queued session.
            s.on_idle = self._session_idle
            if busy:                                           # one model on one card: sessions wait their turn, so they never work on the same files at once
                s.state, s.run_args = "queued", (generate, turns, context_tokens)
                s.emit("queued", task=task, project=project, position=self.queue_position(user, s.id))
                s.persist(force=True)
                return s, note
        # Not queued: start the work now on a background thread (outside the lock, so other requests are not held up).
        threading.Thread(target=s.run, args=(generate, turns, context_tokens), daemon=True).start()
        return s, note

    def revive(self, user, sid, model_id, generate, context_tokens, meter, tools=None, identity=None, owner=False, auto_edits=False, build_steps=None, turns=None, full=False):
        """Bring a session from the history back to life, so a new message carries on in it (same id, same feed, same Rewind points)."""
        with self.lock:
            if self.running(user):
                raise CodeError("You already have a session running.", "Stop it or wait for it to finish.")
            # Load the saved session (its summary row `meta` and its list of events) from disk.
            d = self.saved(user, sid)
            meta = d["meta"]
            project = meta["project"]
            own_pc = self._own_pc(generate, owner, meta.get("env") or "local")
            env = "local" if own_pc else self.resolve_env(meta.get("env") or "local", owner)
            workspace = self.project_path(user, project)
            os.makedirs(workspace, exist_ok=True)
            s = Session(sid, user, project, meta.get("title") or "", model_id, workspace, auto_edits, meter, tools, identity,
                        prefix=(None if own_pc else self.cloud_prefix(user, project) if env == "cloud" else self.prefix_for(workspace, force=(env == "sandbox"))), quotas=self.quotas, base=self.base(user),
                        env=env, remote=(env == "cloud"), log=code_log.SessionLog(self.base(user)), snapshot=lambda u=user, p=project: self._snapshot(u, p),
                        expand=lambda t, u=user, p=project: self.expand_mentions(u, p, t))
            # Put the saved facts back into the new Session object so it looks exactly as it did before.
            s.events = list(d["events"])
            s.checkpoints = list(meta.get("checkpoints") or [])
            s.started = meta.get("started") or s.started
            s.archived = bool(meta.get("archived"))
            # The turn counter continues from the highest checkpoint turn, or from the number of messages seen so far.
            s.turns_run = max([c.get("turn", 0) for c in s.checkpoints] + [sum(1 for e in s.events if e["kind"] in ("start", "user"))])
            s.generate, s.max_turns, s.context_tokens = generate, int(build_steps or turns or self.max_turns), context_tokens
            s.build, s.full = bool(build_steps), bool(full)
            # An idle session waiting for a new message.
            s.state = "done"
            s.on_idle = self._session_idle
            if meta.get("model") and meta["model"] != model_id:
                s.emit("model", model=model_id, previous=meta["model"])
            self.sessions[sid], self.by_user[user] = s, sid
        return s

    def queue_position(self, user, sid):
        """1 = next to start, or 0 when the session is not waiting."""
        # The person's queued sessions, oldest first; the answer is the 1-based place of `sid` in that list, or 0 if it is not there.
        waiting = sorted((x for x in self.sessions.values() if x.user == user and x.state == "queued"), key=lambda x: x.started)
        return next((i + 1 for i, x in enumerate(waiting) if x.id == sid), 0)

    def _session_idle(self, finished):
        """A session finished a turn: start the user's next queued session, if nothing of theirs is working."""
        # Under the lock: if the person has nothing running, take the oldest queued session and mark it "starting".
        with self.lock:
            if self.running(finished.user):
                return
            waiting = sorted((x for x in self.sessions.values() if x.user == finished.user and x.state == "queued"), key=lambda x: x.started)
            if not waiting:
                return
            nxt = waiting[0]
            nxt.state = "starting"
            args = nxt.run_args
        # args (model call, step budget, memory size) were stored on the session when it was queued. Start it outside the lock.
        threading.Thread(target=nxt.run, args=args, daemon=True).start()

    # ---- @file mentions and the project instructions file
    # Finds "@some/file.py" in a message. (?<![\w@]) = not right after a word character or another @ (so an email address is not matched);
    # then "@" and a path: a word character followed by up to 119 more word characters, dots, slashes or dashes.
    MENTION = re.compile(r"(?<![\w@])@([\w][\w./-]{0,119})")

    def expand_mentions(self, user, project, text):
        """The message for the model: a /command of the project's own (.vryx/commands/<name>.md) becomes its text, and each @path that is a file in the
        project gets its contents added (up to 5 files, 6 KB each), so the person can point at a file."""
        text = code_extras.expand_command(self.project_path(user, project), text)
        out, seen = str(text), []
        for m in self.MENTION.finditer(str(text)):
            # Drop punctuation that likely belongs to the sentence ("see @app.py.") and not to the file name.
            rel = m.group(1).rstrip(".,;:)")
            # Each file once, and at most 5 files.
            if rel in seen or len(seen) >= 5:
                continue
            # read() only returns files inside the project; a mention that is not a real project file is just ignored.
            try:
                f = self.read(user, project, rel)
            except CodeError:
                continue
            seen.append(rel)
            # Add the file's first 6000 characters in a fenced code block after the message.
            body = f["text"][:6000] + ("\n... (shortened)" if f["truncated"] or len(f["text"]) > 6000 else "")
            out += f"\n\nContents of {rel}:\n```\n{body}\n```"
        return out

    # The starter text written into a new VRYX.md (the project's instructions file, which VryxCode reads at the start of every session).
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
        """(ok, why) from code_sandbox.available: can Docker run the sandbox image? The answer is cached for 30 seconds because checking is slow."""
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
            return False, "Not set up. The owner adds it in Admin > Cloud machine."
        # shutil.which looks for a program on the PATH (the list of folders programs are searched in); None means it is not installed.
        if not shutil.which("ssh"):
            return False, "This computer has no SSH program (ssh)."
        if not os.path.exists(c.get("key", "")):
            return False, "No SSH key yet. The owner makes one in Admin > Cloud machine."
        if not owner and not c.get("for_others"):
            return False, "Only the owner can use the cloud machine."
        return True, "ready"

    def cloud_prefix(self, user, project):
        """The command words that run a command on the cloud machine: Python runs cloud_run.py with the SSH host, port, user, key and a work folder.

        Everything after the final "--" is the command itself. The remote work folder is named from the person and project with unsafe characters
        replaced by "_" (and cut to 80 characters).
        """
        c = self.cloud
        work = "emvryx-work/" + re.sub(r"[^A-Za-z0-9_-]", "_", f"{user}-{project}")[:80]
        return [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloud_run.py"), "--host", c["host"], "--port", str(c.get("port", 22)), "--user", c.get("user", "root"),
                "--key", c["key"], "--known-hosts", c["known_hosts"], "--workdir", work, "--timeout", str(c.get("timeout", 90)), "--"]

    def environments(self, owner=False, own_pc=False):
        """The places a session can run, for the page: [{"id", "name", "available", "note"}]. [own_pc]: the owner may still pick This computer
        while everyone else is run in the sandbox (vryxcode_owner_pc for admins / vryxcode_open_pc)."""
        # `forced` = the owner started the server in container mode, so everyone is put in the sandbox. Then Docker is already known to work.
        forced = self.sandbox.get("mode") == "docker"
        d_ok, d_why = (True, "ready") if forced else self._docker_ok()
        return [
            {"id": "local", "name": "This computer", "available": not forced or bool(own_pc),
             "note": "Only admins: works in the project folder on this computer. Everyone else runs in the sandbox." if forced and own_pc else
                     "The owner runs every session in the sandbox." if forced else "Works in the project folder on the computer that runs Emvryx. Only a short list of programs may run."},
            {"id": "sandbox", "name": "Isolated sandbox", "available": bool(d_ok),
             "note": "Runs inside a locked container: no internet, limited memory and time." if d_ok else d_why},
            {"id": "cloud", "name": "Cloud machine", "available": self.cloud_ready(owner)[0],
             "note": (f"Runs on {self.cloud['host']}: your project is copied there for each command and the changes are copied back." if self.cloud_ready(owner)[0] else self.cloud_ready(owner)[1])}]

    def resolve_env(self, env, owner=False):
        """The environment a session will really use, or a CodeError the person can act on."""
        env = str(env or "local")
        if self.sandbox.get("mode") == "docker":
            return "sandbox"                                   # the owner forces the container for everyone
        # Otherwise honour the choice, but only if that place is really available.
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
        """The on-disk history (code_log.SessionLog) of one person's sessions."""
        return code_log.SessionLog(self.base(user))

    def _snapshot(self, user, project):
        """The project as zip bytes for a Rewind checkpoint, or None if it cannot be zipped (for example it is over the size limit)."""
        try:
            return self.export_zip(user, project)
        except CodeError:
            return None

    def list_sessions(self, user, archived=None):
        """Newest first: the running ones from memory, the rest from the history on disk.
        archived=None gives all of them; False only the ones in the normal list; True only the archived ones."""
        now, out = time.time(), {}
        # First the saved rows from disk, keyed by session id.
        for m in self.log(user).metas():
            if m.get("state") in ("starting", "working", "asking", "queued") and m["id"] not in self.sessions:
                m["state"] = "interrupted"                     # the server was restarted while it was working (or waiting)
            out[m["id"]] = m
        # Then the live sessions in memory, which replace the saved rows with the same id because they are newer.
        for sid, s in self.sessions.items():
            if s.user == user:
                out[sid] = s.meta()
                if s.state == "queued":
                    out[sid]["position"] = self.queue_position(user, sid)
        # Newest first, capped at the maximum the list shows; each row gets a words-style age such as "5 minutes ago".
        rows = sorted(out.values(), key=lambda m: m.get("updated", 0), reverse=True)[:code_log.MAX_SESSIONS]
        if archived is not None:
            rows = [m for m in rows if bool(m.get("archived")) == bool(archived)]
        for m in rows:
            m["age"] = code_log.age_words(now, m.get("updated", now))
        return rows

    def saved(self, user, sid):
        """A session from the history: {"meta", "events"} (read-only), or a CodeError."""
        d = self.log(user).load(sid)
        if not d:
            raise CodeError("That session isn't here.")
        # A saved row that still says "working" can only be left over from a server restart.
        if d["meta"].get("state") in ("starting", "working", "asking", "queued"):
            d["meta"]["state"] = "interrupted"
        return d

    def delete_session(self, user, sid):
        """Delete a session and its saved history. A running session must be stopped first."""
        live = self.sessions.get(sid)
        if live and live.user == user and live.state in ("starting", "working", "asking"):
            raise CodeError("That session is running.", "Stop it first.")
        # Hold the same lock the saving code uses, so a save cannot slip in half-way through the delete.
        with Session._save_lock:
            if live and live.user == user:
                live.deleted = True                       # its worker may still save once as it finishes (persist checks this)
            self.sessions.pop(sid, None)
            self.log(user).delete(sid)

    def set_archived(self, user, sid, on):
        """Tuck a session away into the Archived list (on=True) or bring it back (on=False). Its files and history are kept either way.
        A running session must be stopped first, like deleting one."""
        live = self.sessions.get(sid)
        if live and live.user != user:
            live = None                                   # someone else's session id: treated as not found below
        if live and live.state in ("starting", "working", "asking", "queued"):
            raise CodeError("That session is running.", "Stop it first.")
        if live:
            live.archived = bool(on)                      # in memory: saving it writes the new summary (persist takes the save lock itself)
            live.persist(force=True)
            return
        with Session._save_lock:                          # on disk only: the same lock the saving code uses, so a save cannot overlap
            if not self.log(user).set_flag(sid, "archived", bool(on)):
                raise CodeError("That session isn't here.")

    def _before_and_after(self, user, sid):
        """(workspace, the zip of the project before the session's first message, {path: text} then, {path: text} now)."""
        log = self.log(user)
        # Use the live session's summary if it is in memory, else the saved one from disk.
        d = self.saved(user, sid) if sid not in self.sessions else {"meta": self.sessions[sid].meta()}
        # The oldest checkpoint is the project as it was before the session's first message.
        turns = sorted(log.checkpoint_numbers(sid))
        data = log.load_checkpoint(sid, turns[0]) if turns else None
        if not data:
            raise CodeError("The starting point of this session is no longer kept.", "Ask VryxCode to review with git instead: \"run git diff and review it\".")
        workspace = self.project_path(user, d["meta"]["project"])
        # Read every text file as it is now into {path: text}.
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
                # _text_of gives None for a binary or too-big file, which is left out.
                if text is not None:
                    after[os.path.relpath(full, workspace).replace(os.sep, "/")] = text
        return workspace, data, code_review.snapshot_files(data), after

    def review_session(self, user, sid):
        """The review request for what a session changed: the project before its first message (a saved snapshot) against the files now."""
        _, _, before, after = self._before_and_after(user, sid)
        # A text diff of every changed file, plus the list of changed files and whether the diff was cut for size.
        diff, changed, cut = code_review.diff_files(before, after)
        return {"prompt": code_review.review_prompt(diff, changed, cut, "the changes this session made"), "files": changed}

    def changes(self, user, sid):
        """What the session changed, file by file: [{path, status: new|changed|removed, add, del, diff}], so each can be kept or undone."""
        _, _, before, after = self._before_and_after(user, sid)
        out = []
        # Every path that existed before or exists now; a (before text) and b (after text) are None when the file was absent on that side.
        for p in sorted(set(before) | set(after)):
            a, b = before.get(p), after.get(p)
            if a == b:
                continue
            diff, _, _ = code_review.diff_files({p: a} if a is not None else {}, {p: b} if b is not None else {}, limit=6000)
            lines = diff.splitlines()
            # In a unified diff, added lines start with "+" and removed with "-"; the "+++"/"---" lines are file headers, not changes.
            out.append({"path": p, "status": "new" if a is None else "removed" if b is None else "changed",
                        "add": sum(1 for x in lines if x.startswith("+") and not x.startswith("+++")), "del": sum(1 for x in lines if x.startswith("-") and not x.startswith("---")),
                        "diff": diff})
        return out

    def reject_file(self, user, sid, path):
        """Undo one file of a session: put it back as it was before the session's first message (a file the session made is removed)."""
        if self.running(user):
            raise CodeError("A session is running.", "Stop it first.")
        workspace, data, before, after = self._before_and_after(user, sid)
        # Clean the path and make sure it stays inside the project (the same two-step safety check used elsewhere).
        rel = self._safe_rel(str(path or ""))
        if rel is None:
            raise CodeError("That is not a file in this project.")
        root = os.path.realpath(workspace)
        full = os.path.realpath(os.path.join(root, rel))
        if not full.startswith(root + os.sep):
            raise CodeError("That is not a file in this project.")
        if before.get(rel) == after.get(rel):
            raise CodeError("That file has not changed in this session.")
        # The file existed before: write its old bytes back from the saved zip. Otherwise the session created it, so delete it.
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
        # The zip of the project saved just before message number `turn` (None when old checkpoints were thrown away).
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
            # Step 1: delete every current file (links are left alone; .git and the other skipped folders are not entered).
            for dirpath, dirs, files in os.walk(root):
                dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
                for n in files:
                    full = os.path.join(dirpath, n)
                    if not os.path.islink(full):
                        os.remove(full)
            # Step 2: write back every file from the saved zip, skipping any path that is unsafe or would land outside the project.
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
        # The checkpoint's short text label (what the message said), or "" if not found.
        label = next((c["label"] for c in d["meta"].get("checkpoints", []) if c["turn"] == int(turn)), "")
        if live:
            live.history = None                                # what the model remembers no longer matches the files
            live.emit("rewind", turn=int(turn), label=label)
        else:
            # Not live: add the "rewind" event to the saved history on disk instead.
            d = self.saved(user, sid)
            d["events"].append({"n": len(d["events"]) + d.get("offset", 0), "kind": "rewind", "t": 0, "turn": int(turn), "label": label})
            d["meta"]["updated"] = time.time()
            log.save(d["meta"], d["events"])
        return {"project": d["meta"]["project"], "label": label}

    def get(self, user, sid):
        """The live Session with this id, but only if it belongs to `user` (so nobody can read or control another person's session)."""
        s = self.sessions.get(sid)
        if not s or s.user != user:
            raise CodeError("That session isn't here.")
        return s
