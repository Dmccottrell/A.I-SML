"""
app_server.py - The Emvryx app server: a browser chat page that talks to a model, with plans, usage and the device check.

WHAT THIS FILE DOES
    Starts a small web server (Python standard library only) and serves the chat page (web/index.html). The page and the
    server use the pieces built before:
      app_engine.run_turn      one message, start to finish (saved while it streams, Stop button, loop guard, auto-shorten)
      chat_polish.paced        the three-second thinking pause and the steady word-by-word writing
      usage_limits.Limiter     plans (Free / Pro / Mega), the tank, the weekly ceiling, 429 / 403 / 503 answers
      context_window.pick      the device check: how long a chat the model and this machine can handle
      models.catalog           the model picker (badges, greyed-out models)

    Safety (docs/APP_SPEC.md, "Safety, privacy and trust"):
      - every request needs a secret key (cookie or "Authorization: Bearer"); the server listens on this computer only unless
        you pass --host; message text is never written to the log
      - private chats never touch the disk
      - "Delete everything" in Settings wipes the person's chats

    Models: --llama URL talks to a llama-server (llama.cpp). Without it the server runs in DEMO mode (a stand-in that
    says so in every reply), so the whole app can be tried before a model is attached.

Usage:
    python app_server.py                              (demo mode; prints the link with your owner key)
    python app_server.py --llama http://127.0.0.1:8080 --tokenizer data/v3/tokenizer.json
    python app_server.py --add-user sam pro           (a tester: prints their key; plans: free, pro, mega)
    python app_server.py --host 0.0.0.0               (reachable from your phone on the same network)
"""
import argparse
import atexit
import hmac
import http.server
import json
import os
import queue
import re
import secrets
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import app_engine as E
import auth
import chat
import data_tools
import code_sandbox
import chat_polish
import code_sessions
import harness
import vryxcode
import connected_apps
import github_link
import lookup_auto
import mailer
import secret_box
import saved_notes
import user_memory
import context_window as CW
import effort_router
import regen_modes
import models as M
import usage_limits as U
from app_errors import AppError, ModelTooBig, PcUnreachable
from tokenizer import BPETokenizer
from open_tokenizer import OpenTokenizer

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
MAX_BODY = 1_000_000
OUTSIDE_NOTE = ("{label} is an outside coding model ({licence}), not an Emvryx model: it is strong at code but does not carry Emvryx's lessons. "
                "Anything it writes is its work, and it is counted like Solstice.")
SECURITY_DEFAULTS = {"session_days": 90, "pair_minutes": 15, "login_fail_limit": 8, "login_fail_window": 600, "email_start_limit": 5,
                     "email_start_window": 600, "open_signups": False, "trusted_proxies": ["127.0.0.1", "::1"], "audit_notify": True,
                     "allow_key_links": False, "allowed_origins": [], "code_unsandboxed_for_others": False,
                     "require_encryption": False, "github_client_id": "", "contact_email": "", "operator_name": "", "alert_ntfy_topic": "",
                     **code_sandbox.QUOTA_DEFAULTS}
PAIR_PAGE = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             '<meta name="robots" content="noindex"><title>Sign in: Emvryx</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;'
             'background:#07080D;color:#EEF0F6;font:17px/1.5 system-ui,sans-serif}main{max-width:380px;padding:24px}h1{font-size:26px;margin:0 0 8px}'
             'p{color:#9AA3BC}button{width:100%;min-height:48px;border:0;border-radius:12px;background:#F5A524;color:#1A1204;font:600 17px system-ui;cursor:pointer}'
             '</style></head><body><main><h1>Sign in to Emvryx</h1><p>This link signs in <b>one device</b>, once. Only continue if you asked for it.</p>'
             '<form method="post" action="/pair/{{token}}"><button type="submit">Sign in on this device</button></form></main></body></html>')
MAX_UPLOAD = 30_000_000                                # a project upload (base64): see code_sessions.MAX_IMPORT_BYTES
MAX_TEXT = 20_000
EFFORTS = {"quick": 160, "balanced": 320, "deep": 700}          # most words a reply may have, per effort level
TEMPERATURE = {"quick": 0.7, "balanced": 0.8, "deep": 0.8}
DEMO_TEXT = ("hello there this is a demo reply no model is connected yet so i am a stand in the real answer will appear "
             "here once you start the server with a model attached")


# ------------------------------------------------------------------ the model behind the server
class DemoBackend:
    """A stand-in used when no model is attached. It always says so."""

    def __init__(self, question=""):
        q = " ".join(question.split())[:80]
        self.text = ("Demo mode: no model is connected, so this is a stand-in reply. "
                     + (f'You wrote: "{q}". ' if q else "")
                     + "Start the server with --llama and a model to get real answers.")

    def stream(self, ids, max_new):
        for word in self.text.split(" "):
            yield word + " "


def demo_tokenizer():
    tok = BPETokenizer()
    tok.train(("the cat sat on the mat and a quick brown fox jumps over the lazy dog " * 30) + DEMO_TEXT * 5, 300, verbose=False)
    return tok


def _windows_memory():
    """(total GB, free GB) of this Windows computer's memory, or None when this is not Windows (or it cannot be read)."""
    try:
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                        ("page_total", ctypes.c_ulonglong), ("page_avail", ctypes.c_ulonglong), ("virt_total", ctypes.c_ulonglong),
                        ("virt_avail", ctypes.c_ulonglong), ("ext", ctypes.c_ulonglong)]
        st = Status()
        st.length = ctypes.sizeof(Status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return None
        return st.total / 1024 ** 3, st.avail / 1024 ** 3
    except (AttributeError, OSError, ImportError):
        return None


def free_memory_gb(fallback=8.0):
    """Memory that is free right now (Linux: MemAvailable; Windows: the system call). Elsewhere: the fallback."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    win = _windows_memory()
    return win[1] if win else fallback


def total_memory_gb(fallback=8.0):
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    win = _windows_memory()                      # without this a Windows PC was always "8 GB", so Solstice showed "Needs 10 GB of memory"
    return win[0] if win else fallback


# ------------------------------------------------------------------ running a GGUF model (llama.cpp's llama-server)
class ModelRunner:
    """Starts llama-server for the model the person picked and stops it when another one is picked (one at a time, so
    a small PC is not asked to hold two models). `files` is {model id: path to a .gguf}."""

    def __init__(self, llama_bin, files, start_timeout=180, extra_args=(), host="127.0.0.1"):
        self.bin, self.files, self.timeout, self.extra, self.host = llama_bin, dict(files), start_timeout, list(extra_args), host
        self.proc = self.model_id = self.url = self.ctx = None
        self.lock = threading.Lock()
        atexit.register(self.stop)

    def available(self, model_id):
        return model_id in self.files and os.path.exists(self.files[model_id]) and bool(self.bin)

    def ready(self, model_id, ctx):
        """True if this model is already running (so the next message won't wait for it to load)."""
        return bool(self.proc and self.proc.poll() is None and self.model_id == model_id and (self.ctx or 0) >= ctx)

    def _free_port(self):
        with socket.socket() as s:
            s.bind((self.host, 0))
            return s.getsockname()[1]

    def stop(self):
        proc, self.proc, self.model_id, self.url = self.proc, None, None, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()

    def ensure(self, model_id, ctx):
        """The URL of a llama-server running this model with at least `ctx` tokens of memory. Starts it if needed."""
        with self.lock:
            if self.proc and self.proc.poll() is None and self.model_id == model_id and (self.ctx or 0) >= ctx:
                return self.url
            self.stop()
            if not self.available(model_id):
                raise AppError("This model's file isn't on this computer.",
                               "Put the .gguf next to the others (see docs/V2.md) or start the server with --gguf.")
            port = self._free_port()
            cmd = [self.bin, "-m", self.files[model_id], "--host", self.host, "--port", str(port), "-c", str(ctx)] + self.extra
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            except OSError as e:
                raise AppError("llama-server could not be started.", f"Check the path given with --llama-bin ({e.strerror}).")
            self.model_id, self.ctx, self.url = model_id, ctx, f"http://{self.host}:{port}"
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                if self.proc.poll() is not None:
                    self.stop()
                    raise AppError("The model stopped while loading.", "Check that the .gguf file is complete and fits in memory.")
                try:
                    with urllib.request.urlopen(self.url + "/health", timeout=2) as r:
                        if json.loads(r.read() or b"{}").get("status", "ok") == "ok":
                            return self.url
                except (urllib.error.URLError, OSError, ValueError):
                    pass                                         # still loading (llama-server answers 503 until ready)
                time.sleep(0.25)
            self.stop()
            raise AppError("The model took too long to load.", "Try a smaller model or check the memory it needs.")


def find_llama_server():
    """llama-server on the PATH, or None."""
    return shutil.which("llama-server") or shutil.which("llama-server.exe")


def discover_ggufs(manifest, root=HERE):
    """{model id: path} for every model whose .gguf already sits where the export scripts put it (see `local_gguf`)."""
    found = {}
    for m in list(manifest["models"]) + list(manifest.get("coders", [])):      # the models, and the outside coding models VryxCode can use
        for rel in m.get("local_gguf", []):
            path = rel if os.path.isabs(rel) else os.path.join(root, rel)
            if os.path.exists(path):
                found[m["id"]] = path
                break
    return found


# ------------------------------------------------------------------ everything the server holds
class AppState:
    def __init__(self, data_dir=None, llama_url=None, llama_key=None, tok=None, manifest=None, cfg=None, ram_gb=None,
                 backend_factory=None, clock=time.time, pace=True, runner=None, root=HERE):
        self.data_dir = data_dir                              # None = keep everything in memory (tests)
        if data_dir:
            os.makedirs(data_dir, exist_ok=True)
        self.manifest = manifest or M.load_manifest()
        self.cfg = cfg or U.load_limits()
        self.default_tok, self.root = tok, root
        self.tokens = {}                                      # model id -> its own tokenizer (each version has one)
        self.runner = runner
        self.llama_url, self.llama_key = llama_url, llama_key
        self.backend_factory = backend_factory
        self.ram_gb = ram_gb or total_memory_gb()
        self.clock, self.pace = clock, pace
        self.verbose = False                                   # print timings (set by the command line)
        self.saved = {}                                        # person -> saved_notes.SavedNotes (approved notes, usable offline)
        self.memories = {}                                     # person -> user_memory.Memory (facts about them, shared by every model)
        self.lookups = {}                                      # (person, chat, message id) -> the notes that answer used, for the thumbs up
        self.wiki = None                                       # the local Wikipedia index (wiki_index.WikiIndex), if there is one
        self.web_fn = None                                     # web(question, k) -> notes; None = this server never searches the web
        self._demo_tok = None
        self.usage = U.UsageStore(os.path.join(data_dir, "usage.db") if data_dir else ":memory:")
        self.limiter = U.Limiter(self.usage, self.cfg, self.manifest)
        self.stores, self.stops, self.settings = {}, {}, {}
        self.lock = threading.Lock()
        self.auth = auth.AuthDB(os.path.join(data_dir, "auth.db") if data_dir else ":memory:")
        self.rl = auth.RateLimiter()                           # per-address sliding windows (sign-in failures, email codes)
        self.security = self._load_security()
        self.auth.prune()
        self.mailer = mailer.from_env()                        # None until EMVRYX_SMTP_* is set: email sign-in is then off
        self._fresh = {}                                       # key hash -> the key, ONLY for keys made in this run (so they can be shown once)
        self._users_mtime = 0
        self.users = self._load_users()
        self.code = code_sessions.CodeManager(data_dir, quotas=code_sandbox.Quotas(self.security))       # VryxCode sessions (projects live under <data>/code/)
        self.secrets = secret_box.SecretBox(data_dir, require=self.security["require_encryption"])
        self.github = github_link.Store(data_dir, self.secrets)  # connected GitHub accounts (tokens encrypted, files mode 600)
        self.metrics = {"errors": 0, "started": time.time()}
        self._alerted = {}
        self.mail_async = True                                  # send the sign-in email in the background so the answer takes the same time for every address
        self.github_device = {}                                 # person -> the sign-in in progress (its device code never leaves the server)
        self.github_http = None                                 # tests: http(method, url, headers, body) -> (status, json)
        self.github_local = False                               # tests only: allow a local folder as the remote
        self.code_generate = None                              # tests: code_generate(model) -> generate(messages)

    # ---- people and keys
    # users.json maps a credential id to the person: "h:<sha256 of their key>" for a key, "e:<name>" for a person who signs in by email.
    # The key itself is never stored: it is shown once, when it is made.
    def _users_path(self):
        return os.path.join(self.data_dir, "users.json") if self.data_dir else None

    def _load_security(self):
        sec = dict(SECURITY_DEFAULTS)
        if self.data_dir:
            try:
                with open(os.path.join(self.data_dir, "security.json"), encoding="utf-8") as f:
                    sec.update({k: v for k, v in json.load(f).items() if k in SECURITY_DEFAULTS})
            except (OSError, ValueError):
                pass
        return sec

    def _load_users(self):
        path, users = self._users_path(), {}
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                users = json.load(f)
        migrated = False
        for k in list(users):
            if not (k.startswith("h:") or k.startswith("e:")):           # an older file that kept the keys themselves: keep them working, store only the hash
                users["h:" + auth.digest(k)] = users.pop(k)
                migrated = True
        if not any(u.get("owner") for u in users.values()):
            key = secrets.token_urlsafe(24)
            users["h:" + auth.digest(key)] = {"user": "owner", "tier": "mega", "owner": True}
            self._fresh["h:" + auth.digest(key)] = key
        self.users = users
        self._save_users()
        for u in users.values():
            self._ensure_usage_user(u)
        return users

    def _save_users(self):
        path = self._users_path()
        if path:
            tmp = path + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.users, f, indent=2)
            os.replace(tmp, path)
            try:
                os.chmod(path, 0o600)
                self._users_mtime = os.stat(path).st_mtime
            except OSError:
                pass

    def _reload_users_if_changed(self):
        """Another process (--rotate-key, --add-user) may have changed users.json while the server runs: read it again."""
        path = self._users_path()
        if not path:
            return
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            return
        if mtime != self._users_mtime:
            try:
                with open(path, encoding="utf-8") as f:
                    self.users = json.load(f)
                self._users_mtime = mtime
            except (OSError, ValueError):
                pass

    def _ensure_usage_user(self, u):
        try:
            self.usage.get_user(u["user"])
        except KeyError:
            self.usage.add_user(u["user"], u["tier"], u.get("tz_minutes", 0), owner=u.get("owner", False))

    def _entries(self, name):
        return [k for k, u in self.users.items() if u["user"] == name]

    def user_record(self, name):
        return next((u for u in self.users.values() if u["user"] == name), None)

    def add_user(self, name, tier, tz_minutes=0, email=None):
        """A new person: returns their key (shown once, never stored). For someone who already exists the plan is updated and None is returned:
        make them a pairing link instead (or rotate their key)."""
        if tier not in self.cfg["tiers"]:
            raise ValueError(f"plan must be one of {', '.join(self.cfg['tiers'])}")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name):
            raise ValueError("a name is letters, numbers, - and _ (up to 32)")
        rec = self.user_record(name)
        if rec is not None:
            if email:
                self.set_email(name, email)
            return None
        if email and not auth.clean_email(email):
            raise ValueError("that does not look like an email address")
        key = secrets.token_urlsafe(24)
        entry = {"user": name, "tier": tier, "owner": False, "tz_minutes": tz_minutes}
        if email:
            entry["email"] = auth.clean_email(email)
        self.users["h:" + auth.digest(key)] = entry
        self._fresh["h:" + auth.digest(key)] = key
        self._save_users()
        self._ensure_usage_user(entry)
        self.auth.event("user_added", name, "", f"plan {tier}")
        return key

    def set_email(self, name, email):
        email = auth.clean_email(email)
        if not email:
            raise ValueError("that does not look like an email address")
        for u in self.users.values():
            if u.get("email") == email and u["user"] != name:
                raise ValueError("that email already belongs to someone else")
        for k in self._entries(name):
            self.users[k]["email"] = email
            self.users[k].pop("email_verified", None)
        self._save_users()

    def rotate_key(self, name):
        """Replace a person's key with a new one (the old key stops working at once, and so do their signed-in devices). Returns the new key."""
        found = self._entries(name)
        if not found:
            raise ValueError(f"no one is called {name!r} (use owner, or a name you added with --add-user)")
        key = secrets.token_urlsafe(24)
        new = "h:" + auth.digest(key)
        rec = dict(self.users[found[0]])
        for old in found:
            self.users.pop(old, None)
            self._fresh.pop(old, None)
        self.users[new] = rec
        self._fresh[new] = key
        self._save_users()
        self.auth.revoke_user(name)
        self.auth.event("key_rotated", name, "", "all signed-in devices were signed out")
        return key

    def owner_key(self):
        """The owner's key, but only if it was made in this run (it is stored hashed: use a pairing link or --rotate-key owner otherwise)."""
        return next((self._fresh[k] for k, u in self.users.items() if u.get("owner") and k in self._fresh), None)

    def _who_of(self, entry):
        row = self.usage.get_user(entry["user"])
        return {"user": entry["user"], "owner": row["owner"], "tier": row["tier"], "banned": bool(entry.get("banned")),
                "email": entry.get("email")}

    def who(self, key):
        """The person a key belongs to, or None."""
        if not key:
            return None
        self._reload_users_if_changed()
        entry = self.users.get("h:" + auth.digest(key))
        return self._who_of(entry) if entry else None

    def who_session(self, token):
        """The person a session cookie belongs to (the session is extended while it is used), or None."""
        self._reload_users_if_changed()
        sess = self.auth.session(token, self.security["session_days"])
        if not sess:
            return None
        rec = self.user_record(sess["user"])
        if not rec:
            return None
        who = self._who_of(rec)
        who["session"] = sess["id"]
        return who

    def who_name(self, name):
        rec = self.user_record(name)
        return self._who_of(rec) if rec else None

    def user_by_email(self, email):
        email = auth.clean_email(email)
        return next((u for u in self.users.values() if email and u.get("email") == email), None)

    def set_ban(self, name, banned):
        rec = self.user_record(name)
        if not rec:
            raise ValueError("no one is called that")
        if rec.get("owner") and banned:
            raise ValueError("the owner cannot be banned")
        for k in self._entries(name):
            self.users[k]["banned"] = bool(banned)
        self._save_users()
        if banned:
            self.auth.revoke_user(name)
        self.auth.event("ban" if banned else "unban", name, "", "")

    def create_email_account(self, email):
        """A free account for an address that proved it owns it (only when open signups are on)."""
        email = auth.clean_email(email)
        base = re.sub(r"[^A-Za-z0-9_-]", "", email.split("@")[0])[:24] or "user"
        name, n = base, 1
        while self.user_record(name):
            n += 1
            name = f"{base}{n}"
        entry = {"user": name, "tier": "free", "owner": False, "tz_minutes": 0, "email": email, "email_verified": True}
        self.users["e:" + name] = entry
        self._save_users()
        self._ensure_usage_user(entry)
        self.auth.event("signup", name, "", "email")
        return name

    def mark_email_verified(self, name):
        for k in self._entries(name):
            self.users[k]["email_verified"] = True
        self._save_users()

    def set_plan(self, name, tier):
        if tier not in self.cfg["tiers"]:
            raise ValueError("unknown plan")
        row = self.usage.get_user(name)
        self.usage.add_user(name, tier, row["tz_minutes"], row["owner"], row["overrides"])
        for u in self.users.values():
            if u["user"] == name:
                u["tier"] = tier
        self._save_users()

    # ---- chats and settings, per person
    def store(self, user):
        with self.lock:
            if user not in self.stores:
                path = os.path.join(self.data_dir, f"chats-{user}.db") if self.data_dir else ":memory:"
                self.stores[user] = E.ChatStore(path)
            return self.stores[user]

    def saved_for(self, user):
        with self.lock:
            if user not in self.saved:
                path = os.path.join(self.data_dir, f"saved-{user}.db") if self.data_dir else ":memory:"
                self.saved[user] = saved_notes.SavedNotes(path)
            return self.saved[user]

    def memory_for(self, user):
        with self.lock:
            if user not in self.memories:
                path = os.path.join(self.data_dir, f"memory-{user}.db") if self.data_dir else ":memory:"
                self.memories[user] = user_memory.Memory(path)
            return self.memories[user]

    def remember_lookup(self, user, chat_id, message_id, question, found):
        """Keep what an answer was written from (the last 200), so a thumbs up can save it. Private chats keep nothing."""
        if chat_id < 0 or not found["used"]:
            return
        with self.lock:
            self.lookups[(user, chat_id, message_id)] = {"question": question, "notes": found["used"], "recent": found.get("recent", False)}
            while len(self.lookups) > 200:
                self.lookups.pop(next(iter(self.lookups)))

    def get_settings(self, user):
        s = {"window_mode": "everyday", "show_tokens": False, "web_search": "auto", "memory": True, "thinking_pause": "short"}
        s.update(self.settings.get(user, {}))
        return s

    def put_settings(self, user, new):
        s = self.get_settings(user)
        if new.get("window_mode") in ("everyday", "long"):
            s["window_mode"] = new["window_mode"]
        if isinstance(new.get("show_tokens"), bool):
            s["show_tokens"] = new["show_tokens"]
        if new.get("thinking_pause") in chat_polish.PAUSE_SCALE:
            s["thinking_pause"] = new["thinking_pause"]
        if isinstance(new.get("memory"), bool):
            s["memory"] = new["memory"]
        if new.get("web_search") in lookup_auto.MODES:
            s["web_search"] = new["web_search"]
        self.settings[user] = s
        return s

    # ---- models
    def _card(self, m, who):
        """One model as the picker shows it. state: ready | locked | too_big | missing | soon."""
        plan = self.cfg["tiers"][who["tier"]]["models"]
        m = dict(m)
        if m["status"] == "planned":
            m["state"], m["badge"] = "soon", "Coming soon"
        elif not who["owner"] and plan != "all" and m["name"].lower() not in plan:
            m["state"], m["badge"] = "locked", "Not in your plan"
        elif self.ram_gb < m["min_ram_gb"]:
            m["state"], m["badge"] = "too_big", f"Needs {m['min_ram_gb']} GB of memory"
        elif self.runner and not self.runner.available(m["id"]):
            m["state"], m["badge"] = "missing", "Not on this computer" if self.runner.bin else "llama-server not found"
        else:
            m["state"], m["badge"] = "ready", "Beta" if m["status"] == "beta" else "Ready"
        m["older"] = False
        return m

    def catalog(self, who):
        """The picker: one card per name (Flare, Equinox, Solstice, Apogee) with its newest usable version, and
        "other" with the older versions that can still be chosen (Flare 2.5, ...)."""
        cards, other = [], []
        for name in M.NAMES:
            versions = sorted((m for m in self.manifest["models"] if m["name"] == name and m["status"] != "off"),
                              key=lambda m: -m["version"])
            if not versions:
                continue
            usable = [m for m in versions if m["status"] != "planned"]
            top = (usable or versions)[0]
            cards.append(self._card(top, who))
            for m in usable[1:]:
                c = self._card(m, who)
                c["older"] = True
                other.append(c)
        return {"cards": cards, "other": other}

    def code_models(self, who):
        """The models VryxCode can use for this person: flagged "vryxcode", and ready to run here."""
        cat = self.catalog(who)
        out = [{"id": m["id"], "name": m["name"], "version": m["version"], "state": m["state"], "badge": m["badge"],
                "label": f"{m['name']} {m['version']:g}", "outside": False, "note": vryxcode.ELIGIBLE_NOTE.get(m["id"], "")}
               for m in cat["cards"] + cat["other"] if m.get("vryxcode")]
        for c in self.manifest.get("coders", []):
            state, badge = self._coder_state(c, who)
            out.append({"id": c["id"], "name": c["label"], "version": "", "state": state, "badge": badge, "label": c["label"] + " (outside model)",
                        "outside": True, "note": OUTSIDE_NOTE.format(label=c["label"], licence=c.get("licence", "open"))})
        return out

    def coder(self, coder_id):
        return next((c for c in self.manifest.get("coders", []) if c["id"] == coder_id), None)

    def _coder_state(self, c, who):
        """ready | locked | too_big | missing for an outside coding model (same plan rule as the Emvryx model it costs like)."""
        plan = self.cfg["tiers"][who["tier"]]["models"]
        if not who["owner"] and plan != "all" and c.get("plan_like", "solstice") not in plan:
            return "locked", "Not in your plan"
        if self.ram_gb < c.get("min_ram_gb", 0):
            return "too_big", f"Needs {c['min_ram_gb']} GB of memory"
        if self.code_generate or self.llama_url or (self.runner and self.runner.available(c["id"])):
            return "ready", "Ready"
        return "missing", "Not on this computer" if (self.runner and self.runner.bin) else "llama-server not found"

    def alert(self, kind, text, per_hour=6):
        """A short message to the owner's phone (ntfy) when something security-relevant happens. Off until "alert_ntfy_topic" is set in security.json.
        At most `per_hour` of the same kind, so an attack cannot flood the phone. Never raises, never contains a key, code or token."""
        topic = str(self.security.get("alert_ntfy_topic") or "")
        if not topic:
            return
        now = time.time()
        recent = [t for t in self._alerted.get(kind, []) if now - t < 3600]
        if len(recent) >= per_hour:
            return
        self._alerted[kind] = recent + [now]
        import notify
        threading.Thread(target=notify.send, args=(topic, text, "Emvryx security"), daemon=True).start()

    def health(self):
        """Numbers for the owner: how it is doing and whether anything looks like an attack."""
        hour = time.time() - 3600
        ev = [e for e in self.auth.events(500) if e["at"] >= hour]
        count = lambda k: sum(1 for e in ev if e["kind"] == k)
        return {"uptime_minutes": int((time.time() - self.metrics["started"]) / 60), "server_errors": self.metrics["errors"],
                "devices_signed_in": self.auth.db.execute("SELECT COUNT(*) FROM sessions WHERE revoked = 0 AND expires > ?", (time.time(),)).fetchone()[0],
                "last_hour": {"sign_ins": count("login_ok"), "failed_tries": count("login_fail"), "lockouts": count("lockout"), "cross_site_refusals": count("bad_origin"),
                              "key_links_refused": count("key_link_refused")},
                "coding_running": sum(1 for x in self.code.sessions.values() if x.state in ("starting", "working", "asking")),
                "encryption": self.secrets.available, "email_sign_in": bool(self.mailer), "code_sandbox": self.code.sandbox.get("mode", "none"),
                "alerts_on": bool(self.security.get("alert_ntfy_topic"))}

    # ---- GitHub (a connected app)
    def github_client_id(self):
        return str(os.environ.get("EMVRYX_GITHUB_CLIENT_ID") or self.security.get("github_client_id") or "")

    def github_api(self, user):
        d = self.github.get(user)
        if not d.get("token"):
            raise github_link.GitHubError("GitHub isn't connected.", "Open Menu > Connected apps > GitHub and connect it.")
        return github_link.Api(d["token"], self.github_http)

    def git_for(self, user, project):
        d = self.github.get(user)
        workspace = self.code.project_path(user, project)
        identity = None
        if d.get("login"):
            identity = (d["login"], f"{d.get('id', 0)}+{d['login']}@users.noreply.github.com")
        return github_link.Git(workspace, d.get("token"), self.github_local, identity)

    def github_tool(self, user, project):
        """The `github` tool the model may call (status, pull, push). It runs here on the server with the person's token; the model never sees it."""
        def github(action="status"):
            g = self.git_for(user, project)
            try:
                if action == "status":
                    return json.dumps(g.status())
                if action == "pull":
                    out = g.pull()
                    self.github.log(user, f"pulled {project}")
                    return out
                if action == "push":
                    out = g.push(allow_protected=False)
                    self.github.log(user, f"pushed {project}")
                    return out
            except github_link.GitHubError as e:
                raise harness.ToolError(e.message + (" " + e.action if e.action else ""))
            raise harness.ToolError("action must be status, pull or push")
        return github

    def code_allowed(self, who):
        """(ok, why not). The owner always may. Others need VryxCode in their plan, and a container sandbox (or the owner explicitly accepting
        the folder sandbox for them): a person must never get to run programs on the host with only the folder sandbox between us."""
        if who["owner"]:
            return True, ""
        if not self.cfg["tiers"][who["tier"]].get("vryxcode", False):
            return False, "VryxCode isn't included in your plan."
        if self.code.sandbox.get("mode") != "docker" and not self.security["code_unsandboxed_for_others"]:
            return False, "VryxCode is only open to the owner until the container sandbox is turned on."
        return True, ""

    def code_backend(self, model):
        """generate(messages) for a coding session on this model (the llama-server that runs it)."""
        if self.code_generate:
            return self.code_generate(model)
        ctx = min(int(model.get("context_tested") or 8192), 32768)
        if self.runner:
            url = self.runner.ensure(model["id"], ctx)
        elif self.llama_url:
            url = self.llama_url
        else:
            raise code_sessions.CodeError("No model is attached to this server.", "Start it with --gguf or --llama (see docs/VRYXCODE.md).")
        return vryxcode.LlamaChat(url)

    def preload(self, model_id):
        """Start the model's llama-server now (with the window the owner's chats would ask for), so the first message is not slow.
        Returns a short message for the log. Never raises: a model that cannot load only costs the head start."""
        if not self.runner:
            return "nothing to preload (no local models)"
        model = next((m for m in list(self.manifest["models"]) + list(self.manifest.get("coders", [])) if m["id"] == model_id), None)
        if not model:
            return f"unknown model {model_id!r}"
        if not self.runner.available(model_id):
            return f"{model_id}: its .gguf file is not on this computer"
        try:
            window = self.window_for({"user": "owner", "tier": "mega", "owner": True}, model)["window"]
            self.runner.ensure(model_id, window)
            return f"{model_id} is loaded and ready"
        except Exception as e:                                   # noqa: BLE001 - a failed head start must not stop the app
            return f"{model_id} could not be preloaded: {getattr(e, 'message', e)}"

    def pick_model(self, who, model_id):
        cat = self.catalog(who)
        for m in cat["cards"] + cat["other"]:
            if m["id"] == model_id:
                return m
        raise KeyError(model_id)

    def window_for(self, who, model, mode=None):
        mode = mode or self.get_settings(who["user"])["window_mode"]
        plan = self.cfg["tiers"][who["tier"]]["windows"]
        device = CW.Device(self.ram_gb, min(self.ram_gb, free_memory_gb(self.ram_gb)))
        return CW.pick(model, device, mode, None if who["owner"] else plan)

    @property
    def demo(self):
        """True when nothing real is attached: every reply is the stand-in."""
        return not (self.llama_url or self.backend_factory or self.runner)

    def tok_for(self, model):
        """The tokenizer this model was trained with: a model's replies are garbage with another version's tokenizer."""
        if model["id"] in self.tokens:
            return self.tokens[model["id"]]
        rel = model.get("tokenizer")
        path = None if not rel else (rel if os.path.isabs(rel) else os.path.join(self.root, rel))
        if not (path and os.path.exists(path)) and model.get("open"):    # a model downloaded from the backup repo has its tokenizer in its export folder
            alt = os.path.join(self.root, "export", "open", model["id"], "my-ai", "tokenizer.json")
            if os.path.exists(alt):
                path = alt
        if path and os.path.exists(path):
            tok = OpenTokenizer.load(path) if model.get("open") else BPETokenizer.load(path)    # "open": a fine-tuned open model (ChatML)
        elif self.default_tok is not None:
            tok = self.default_tok
        elif self.demo or self.backend_factory:
            if self._demo_tok is None:
                self._demo_tok = demo_tokenizer()
            tok = self._demo_tok
        else:
            raise AppError(f"{model['name']} {model['version']:g}: its tokenizer file isn't here.",
                           f"Expected {rel or 'a tokenizer.json'}. Run the app from the project folder, or pass --tokenizer.")
        self.tokens[model["id"]] = tok
        return tok

    def backend_for(self, model, question, ctx=1024):
        if self.backend_factory:
            return self.backend_factory(model, question)
        sampling = {"temperature": TEMPERATURE["balanced"], **model.get("sampling", {})}   # a model's own tested settings win
        if self.runner:
            return E.LlamaServer(self.runner.ensure(model["id"], ctx), None, timeout=120, **sampling)
        if self.llama_url:
            return E.LlamaServer(self.llama_url, self.llama_key, **sampling)
        return DemoBackend(question)

    # ---- the numbers on screen
    def usage_snapshot(self, who, model, effort):
        key = model["name"].lower() if model else "flare"
        snap = self.limiter.snapshot(who["user"], key, effort, self.clock())
        snap["models"] = snap.pop("by_model")
        return snap


# ------------------------------------------------------------------ one message, streamed to the browser
def start_turn(state, who, chat_id, text, model_id, effort, regenerate=False, regen_mode=None):
    """Begin a reply in a worker thread. Returns (queue, stop_event); the queue yields ("piece", text), then
    ("done", result) or ("error", exception). With effort "auto" the level is chosen from the message (effort_router);
    the page is told which one in `decision`."""
    store = state.store(who["user"])
    model = state.pick_model(who, model_id)
    if model["state"] == "too_big":
        raise ModelTooBig(model, state.ram_gb, None)
    if model["state"] != "ready":
        raise U.LimitError("model_unavailable", f"{model['name']} {model['version']:g}: {model['badge']}.")
    tok = state.tok_for(model)
    if effort != "auto" and effort not in EFFORTS:
        raise U.LimitError("bad_effort", "Pick Auto, Quick, Balanced or Deep.")
    decision = {"effort": effort, "auto": False, "reason": ""}
    question = text
    if regenerate:                                             # the question is the last one already in the chat
        question = next((m["content"] for m in reversed(store.messages(chat_id)) if m["role"] == "user" and m["status"] != "compacted"), "")
    if effort == "auto":
        allowed = tuple(model.get("efforts", effort_router.ORDER))
        pct = 100.0 if who["owner"] else state.usage_snapshot(who, model, "balanced")["tank"]["pct"]
        chosen, why = effort_router.choose_effort(question, allowed, pct)
        decision = {"effort": chosen, "auto": True, "reason": why}
        effort = chosen
    if effort not in model.get("efforts", effort_router.ORDER):    # a model lists the levels it offers (Ember has no Deep)
        raise U.LimitError("effort_not_available", f"{model['name']} doesn't offer {effort.title()}. Deep needs Flare or a bigger model.",
                           choices=["flare"])
    win = state.window_for(who, model)
    if not win["fits"]:
        raise AppError("There isn't enough free memory for this model.", "Close other apps or pick a smaller model.")
    window = win["window"]
    mode = regen_mode if regenerate else None
    regen_modes.get(mode)                                      # an unknown option is a ValueError (a 400 for the page)
    max_new = min(EFFORTS[effort], max(32, window // 2), model.get("max_reply_tokens", EFFORTS[effort]))
    if mode:
        max_new = min(regen_modes.length_for(max_new, mode), max(32, window // 2))
    pause = round(chat_polish.pause_for(question, effort) * chat_polish.PAUSE_SCALE[state.get_settings(who["user"])["thinking_pause"]], 2)   # fits the message, then the person's setting
    decision["pause"] = pause
    bounds = tuple(model.get("temperature_bounds", effort_router.DEFAULT_BOUNDS))
    base_temp = model.get("sampling", {}).get("temperature", TEMPERATURE["balanced"])
    decision["temperature"] = None                             # None = keep the model's own setting
    if decision["auto"]:                                       # Auto also picks how adventurous the wording is
        decision["temperature"], decision["temperature_reason"] = effort_router.choose_temperature(question, base_temp, bounds)
    q, stop = queue.Queue(), threading.Event()
    key = (who["user"], chat_id)
    state.stops[key] = stop
    started = time.monotonic()
    counted_model = dict(model, where="online")                # the server runs it, so the person's plan counts it
    if regenerate:
        msgs = [m for m in store.messages(chat_id) if m["status"] != "compacted"]
        if msgs and msgs[-1]["role"] == "assistant":
            store.remove_message(chat_id, msgs[-1]["id"])
        text = None

    timing = {}

    def timed(stream):
        """Notes when the model's first word arrives (before the pause and the steady writing are added)."""
        for piece in stream:
            timing.setdefault("first", time.monotonic())
            yield piece

    def pacer(stream):
        stream = timed(stream)
        gen = chat_polish.paced(stream, min_first_s=pause, start=started) if state.pace else stream
        try:
            for bit in gen:
                q.put(("piece", bit))
                yield bit
        finally:
            close = getattr(gen, "close", None)
            if close:
                close()

    def work():
        try:
            if state.runner and not state.runner.ready(model["id"], window):
                q.put(("loading", model["name"]))
            notes, found = None, None
            mem_note = None
            if chat_id >= 0 and state.get_settings(who["user"])["memory"]:         # what the app knows about this person: the same for every model
                memory = state.memory_for(who["user"])
                if text:
                    learned = memory.learn(text)
                    if learned["saved"] or learned["forgot"]:
                        q.put(("memory", learned))
                asked = text
                if not asked:                                                       # a regenerate: the question is the last thing they said
                    last = [m for m in store.messages(chat_id) if m["role"] == "user"]
                    asked = last[-1]["content"] if last else ""
                mem_note = memory.note(asked)
            if text:                                                               # Auto lookup (lookup_auto.py)
                web_mode = state.get_settings(who["user"])["web_search"]
                notes, found = lookup_auto.gather(text, state.wiki, state.web_fn, web_mode, private=chat_id < 0,
                                                  max_notes=5 if window >= 6000 else 3,
                                                  saved=state.saved_for(who["user"]), now=state.clock(), policy=model.get("lookup", "always"))
                if found["asked"]:
                    q.put(("notes", {k: v for k, v in found.items() if k != "used"}))
            if mem_note:
                notes = [mem_note] + list(notes or [])
            t_load = time.monotonic()
            backend = state.backend_for(model, text or "", window)     # may load the model the first time (can take a while)
            timing["load"] = time.monotonic() - t_load
            if decision["temperature"] is not None and hasattr(backend, "sampling"):
                backend.sampling = dict(backend.sampling, temperature=decision["temperature"])
            if regenerate and hasattr(backend, "sampling"):
                t = regen_modes.sampling_for(backend.sampling.get("temperature", 0.8), mode)
                backend.sampling = dict(backend.sampling, temperature=round(min(bounds[1], max(bounds[0], t)), 2))   # never outside the model's safe range
            r = E.run_turn(tok, store, chat_id, backend, counted_model, window, max_new, user_text=text, stop=stop, notes=notes or None,
                           limiter=state.limiter, user=who["user"], effort=effort, clock=state.clock, pacer=pacer,
                           style_hint=regen_modes.get(mode)["hint"] if regenerate else "")
            web_mode_now = state.get_settings(who["user"])["web_search"]
            knowledge_first = (model.get("lookup") == "when_needed" and found is not None and not found["asked"] and bool(text) and not regenerate
                               and web_mode_now != "none" and lookup_auto.wants_lookup(text))
            old_way = (found and found["asked"] and not regenerate and not found["web_tried"] and state.web_fn is not None and
                       web_mode_now not in ("off", "none") and chat_id >= 0)
            if (old_way or knowledge_first) and lookup_auto.gave_up(r["text"]):
                # The model said it doesn't know. Old way: the web has not been tried, so search it. Knowledge-first models (Qwen) had no notes yet:
                # look it up now. Then answer again (the second chance).
                notes2, found2 = lookup_auto.gather(text, state.wiki, state.web_fn, "always" if old_way else web_mode_now, private=(chat_id < 0 and knowledge_first),
                                                    max_notes=5 if window >= 6000 else 3, saved=state.saved_for(who["user"]),
                                                    now=state.clock(), force_web=True, force_notes=True)
                if found2["web"] or (knowledge_first and (found2["wiki"] or found2["saved"])):
                    q.put(("notes", {k: v for k, v in found2.items() if k != "used"} | {"retry": True}))
                    msgs = [m for m in store.messages(chat_id) if m["status"] != "compacted"]
                    if msgs and msgs[-1]["role"] == "assistant":
                        store.remove_message(chat_id, msgs[-1]["id"])
                    r = E.run_turn(tok, store, chat_id, backend, counted_model, window, max_new, user_text=None, stop=stop, notes=([mem_note] if mem_note else []) + list(notes2 or []),
                                   limiter=state.limiter, user=who["user"], effort=effort, clock=state.clock, pacer=pacer)
                    found = found2
            if found and found["asked"] and text:
                state.remember_lookup(who["user"], chat_id, r["message_id"], text, found)
            if text and store.title(chat_id) == "New chat":
                store.set_title(chat_id, " ".join(text.split())[:48] or "New chat")
            q.put(("done", r))
            if state.verbose:                                  # numbers only, never any text
                end = time.monotonic()
                first = timing.get("first", end) - started
                sys.stderr.write(f"reply: {model['id']} load={timing.get('load', 0):.1f}s model_first_word={first:.1f}s "
                                 f"total={end - started:.1f}s chars={len(r['text'])} window={window}\n")
        except BaseException as e:                              # sent to the page as an error event
            q.put(("error", e))
        finally:
            state.stops.pop(key, None)

    threading.Thread(target=work, daemon=True).start()
    return q, stop, model, win, decision


def error_payload(e):
    """(http status, headers, body) for anything that can go wrong in a turn."""
    if isinstance(e, U.LimitError):
        return e.to_http()
    if isinstance(e, PcUnreachable):
        return 503, {}, {"code": "unreachable", "message": e.message, "action": e.action}
    if isinstance(e, ModelTooBig):
        return 409, {}, {"code": "too_big", "message": e.message, "action": e.action}
    if isinstance(e, AppError):
        return 502, {}, {"code": "model_error", "message": e.message, "action": e.action}
    return 500, {}, {"code": "error", "message": "Something went wrong. Please try again."}


# ------------------------------------------------------------------ HTTP
class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "Emvryx"
    protocol_version = "HTTP/1.1"

    state = None            # set by make_server

    # never log message text (or anything after the "?"): only the method and the path
    def log_message(self, fmt, *args):
        if getattr(self.server, "quiet", False):
            return
        sys.stderr.write("%s %s\n" % (self.command, self.path.split("?")[0]))

    def handle_one_request(self):
        self._cookies = []
        super().handle_one_request()

    # ---- browser protections
    def _security_headers(self, csp=None):
        """Headers every answer carries. The page gets a content security policy that allows only its own script (by a one-time nonce), its own
        files and Google's font files; everything else (JSON answers, icons) gets a policy that allows nothing."""
        h = {"Content-Security-Policy": csp or "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
             "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Cross-Origin-Opener-Policy": "same-origin",
             "Cross-Origin-Resource-Policy": "same-origin", "X-Robots-Tag": "noindex, nofollow",
             "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()"}
        if self._https():
            h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return h

    def _origin_ok(self):
        """Refuse a state-changing request that a different website made on the person's behalf (CSRF). Browsers say where a request came from
        (Sec-Fetch-Site, and Origin); a program like curl says nothing and is not a browser, so it is let through (it still needs its key)."""
        sec = self.headers.get("Sec-Fetch-Site")
        origin = self.headers.get("Origin")
        if sec and sec in ("same-origin", "none"):
            return True
        if sec == "cross-site":
            return False
        if not origin:
            return not sec                                    # no origin and no fetch-site: not a browser form post
        if origin == "null":
            return False
        host = urllib.parse.urlparse(origin).netloc.lower()
        ok = {(self.headers.get("Host") or "").lower()}
        if self._peer_trusted():
            ok.add((self.headers.get("X-Forwarded-Host") or "").lower())
        ok |= {urllib.parse.urlparse(o).netloc.lower() for o in self.state.security["allowed_origins"]}
        return host in ok

    # ---- helpers
    def _send(self, status, body=b"", ctype="application/json", headers=None, csp=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        if status >= 500:
            self.state.metrics["errors"] += 1
            self.state.alert("server_error", f"Emvryx: a server error ({status}) on {self.path.split('?')[0]}", per_hour=3)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in self._security_headers(csp).items():
            self.send_header(k, v)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        for cookie in getattr(self, "_cookies", []):
            self.send_header("Set-Cookie", cookie)
        self._cookies = []
        self.end_headers()
        self.wfile.write(body)

    def _json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > (MAX_UPLOAD if self.path.split("?")[0] == "/api/code/import" else MAX_BODY):
            raise ValueError("too big")
        raw = self.rfile.read(n) if n else b""
        return json.loads(raw) if raw else {}

    # ---- who is asking
    def _peer_trusted(self):
        return bool(self.client_address) and self.client_address[0] in self.state.security["trusted_proxies"]

    def _ip(self):
        """The caller's address. Behind the Cloudflare tunnel every request comes from this computer, so the real address is taken from the
        proxy's header, but only when the request really came from the proxy (a trusted address), never from an outside caller."""
        if self._peer_trusted():
            # Cloudflare sets CF-Connecting-IP itself. A plain proxy APPENDS to X-Forwarded-For, so only the LAST entry (added by our own proxy)
            # can be trusted: the first is whatever the caller wrote.
            ip = self.headers.get("CF-Connecting-IP") or (self.headers.get("X-Forwarded-For") or "").split(",")[-1].strip()
            if ip:
                return ip[:64]
        return self.client_address[0] if self.client_address else ""

    def _https(self):
        if not self._peer_trusted():
            return False
        return (self.headers.get("X-Forwarded-Proto") or "").lower() == "https" or '"https"' in (self.headers.get("CF-Visitor") or "")

    def _cookie_dict(self):
        out = {}
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k:
                out[k] = urllib.parse.unquote(v)
        return out

    def _set_session_cookie(self, token):
        days = self.state.security["session_days"]
        self._cookies.append(f"emvryx_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={days * 86400}" + ("; Secure" if self._https() else ""))

    def _expire_cookie(self, name):
        self._cookies.append(f"{name}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0" + ("; Secure" if self._https() else ""))

    def _start_session(self, user, how):
        st = self.state
        sid, token = st.auth.new_session(user, self.headers.get("User-Agent", ""), self._ip(), st.security["session_days"])
        st.auth.event("login_ok", user, self._ip(), how)
        if st.user_record(user) and st.user_record(user).get("owner"):
            st.alert("owner_signin", f"Emvryx: the owner signed in ({auth.device_label(self.headers.get('User-Agent', ''))}, {how})", per_hour=6)
        if secrets.randbelow(50) == 0:
            st.auth.prune()
        self._set_session_cookie(token)
        return sid

    def _locked(self):
        """True (and a 429 is sent) when this address has had too many wrong tries lately."""
        st = self.state
        wait = st.rl.blocked("fail:" + self._ip(), st.security["login_fail_limit"], st.security["login_fail_window"])
        if wait:
            key = "lock:" + self._ip()
            if st.rl.blocked(key, 1, st.security["login_fail_window"]) == 0:           # the first refusal of this lockout: log it once and tell the owner
                st.rl.hit(key)
                st.auth.event("lockout", "", self._ip(), f"{st.security['login_fail_limit']} wrong tries")
                st.alert("lockout", "Emvryx: an address was locked out after repeated wrong sign-in tries", per_hour=4)
            self._send(429, {"code": "too_many", "message": "Too many wrong tries from this address.", "action": f"Wait about {max(1, wait // 60)} minute(s) and try again.",
                             "retry_after": wait}, headers={"Retry-After": str(wait)})
        return bool(wait)

    def _fail(self, what):
        st, ip = self.state, self._ip()
        st.rl.hit("fail:" + ip)
        if len(st.rl.hits) > 5000:
            st.rl.trim(3600)
        st.auth.event("login_fail", "", ip, what)

    def _credential_kind(self):
        if (self.headers.get("Authorization") or "").startswith("Bearer "):
            return "key"
        c = self._cookie_dict()
        if c.get("emvryx_session"):
            return "session"
        return "key" if c.get("emvryx_key") else None

    def _key(self):
        """Kept for the few callers that only need to know whether a key was sent."""
        auth_h = self.headers.get("Authorization", "")
        return auth_h[7:].strip() if auth_h.startswith("Bearer ") else self._cookie_dict().get("emvryx_key")

    def _who(self):
        """The signed-in person, or None after sending the right error. A key (bearer header, or the old key cookie) is checked against the
        rate limit first, then turned into a session; a session cookie is checked as is."""
        st = self.state
        kind = self._credential_kind()
        who = None
        if kind == "key":
            if self._locked():
                return None
            auth_h = self.headers.get("Authorization", "")
            if auth_h.startswith("Bearer "):
                who = st.who(auth_h[7:].strip())
            else:                                           # the old cookie that held the key itself: swap it for a session
                who = st.who(self._cookie_dict().get("emvryx_key"))
                self._expire_cookie("emvryx_key")
                if who and not who["banned"]:
                    who["session"] = self._start_session(who["user"], "old cookie upgraded")
            if not who:
                self._fail("bad key")
        elif kind == "session":
            who = st.who_session(self._cookie_dict().get("emvryx_session"))
            if not who:
                self._expire_cookie("emvryx_session")       # revoked or expired: clear it so the page shows the sign-in
        if who and who["banned"]:
            self._send(403, {"code": "banned", "message": "This account has been turned off.", "action": "Ask the owner if you think that is a mistake."})
            return None
        if not who:
            self._send(401, {"code": "bad_key", "message": "You are not signed in." if kind != "key" else "That key isn't right.",
                             "action": "Open the link the server printed, a pairing link from the owner, or sign in with an email code."})
        return who

    PAGE_CSP = ("default-src 'self'; script-src 'self' 'nonce-{nonce}'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; manifest-src 'self'; worker-src 'self'; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")

    def _file(self, name, ctype):
        path = os.path.join(WEB, name)
        if not os.path.exists(path):
            return self._send(404, {"code": "not_found", "message": "Not found."})
        with open(path, "rb") as f:
            data = f.read()
        if name == "index.html":                      # the one inline script gets a fresh nonce each time; nothing else may run
            nonce = secrets.token_urlsafe(16)
            data = data.replace(b"<script>", b'<script nonce="' + nonce.encode() + b'">')
            return self._send(200, data, ctype, csp=self.PAGE_CSP.format(nonce=nonce))
        csp = None
        if name in ("privacy.html", "terms.html"):               # the owner's name and contact go in where the page says {{operator}} and {{contact}}
            import html as _html
            contact = str(self.state.security.get("contact_email") or "")
            operator = str(self.state.security.get("operator_name") or "")
            data = (data.replace(b"{{contact}}", (f'<a href="mailto:{_html.escape(contact, quote=True)}">{_html.escape(contact)}</a>' if contact
                                                 else "the person who gave you access").encode())
                        .replace(b"{{operator}}", (_html.escape(operator) if operator else "the person who runs this server").encode()))
        if name.endswith(".svg") or name in ("privacy.html", "terms.html"):
            csp = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"
        self._send(200, data, ctype, csp=csp)

    # ---- routes
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        path, qs = url.path, urllib.parse.parse_qs(url.query)
        try:
            if path == "/":
                key = (qs.get("key") or [None])[0]
                if key and not self.state.security["allow_key_links"]:
                    self.state.auth.event("key_link_refused", "", self._ip(), "")      # a key in an address ends up in history and logs: not accepted
                    return self._send(302, b"", "text/plain", {"Location": "/?notice=keylink"})
                if key:                                          # (only when the owner turned allow_key_links on) turn it into a session and drop the key
                    if self._locked():
                        return
                    who = self.state.who(key)
                    if who and not who["banned"]:
                        self._start_session(who["user"], "key link")
                        return self._send(302, b"", "text/plain", {"Location": "/"})
                    self._fail("bad key link")
                return self._file("index.html", "text/html; charset=utf-8")
            m = re.fullmatch(r"/pair/([A-Za-z0-9_-]{16,80})", path)
            if m:                                                # a pairing link: show a button; only the button (a POST) uses it up
                if self._locked():
                    return
                user = self.state.auth.peek_pair(m.group(1))
                who = self.state.who_name(user) if user else None
                if who and not who["banned"]:
                    return self._send(200, PAIR_PAGE.replace("{{token}}", m.group(1)).encode(), "text/html; charset=utf-8",
                                      csp="default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
                self._fail("bad pairing link")
                return self._send(410, "This pairing link was already used or has expired. Ask for a new one.\n", "text/plain; charset=utf-8")
            if path == "/api/auth-options":
                return self._send(200, {"email": bool(self.state.mailer), "signups": bool(self.state.mailer and self.state.security["open_signups"])})
            if path in ("/privacy", "/terms"):
                return self._file(path[1:] + ".html", "text/html; charset=utf-8")
            if path == "/manifest.webmanifest":
                return self._file("manifest.webmanifest", "application/manifest+json")
            if path == "/sw.js":
                return self._file("sw.js", "text/javascript")
            if path == "/icon.svg":
                return self._file("icon.svg", "image/svg+xml")
            if path in ("/icon-192.png", "/icon-512.png", "/icon-maskable-512.png", "/apple-touch-icon.png"):
                return self._file(path[1:], "image/png")
            if not path.startswith("/api/"):
                return self._send(404, {"code": "not_found", "message": "Not found."})
            who = self._who()
            if not who:
                return
            if path == "/api/state":
                return self._send(200, self.api_state(who, qs))
            m = re.fullmatch(r"/api/chats/(-?\d+)", path)
            if m:
                return self.api_get_chat(who, int(m.group(1)))
            if path == "/api/settings":
                return self._send(200, self.state.get_settings(who["user"]))
            if path == "/api/apps":
                cat = connected_apps.catalog()
                cat["connections"] = {"github": dict(self.state.github.public(who["user"]), device=bool(self.state.github_client_id()),
                                                     encrypted=self.state.secrets.available)}
                return self._send(200, cat)
            if path == "/api/memory":
                return self._send(200, {"facts": self.state.memory_for(who["user"]).list(), "on": self.state.get_settings(who["user"])["memory"]})
            if path == "/api/saved-notes":
                return self._send(200, {"notes": self.state.saved_for(who["user"]).list(self.state.clock())})
            if path.startswith("/api/code"):
                return self.api_code_get(who, path, qs)
            if path == "/api/export":
                data = data_tools.export_zip(self.state, who["user"])
                self.state.auth.event("data_export", who["user"], self._ip(), "")
                return self._send(200, data, "application/zip", {"Content-Disposition": f'attachment; filename="emvryx-{who["user"]}-data.zip"'})
            if path == "/api/sessions":
                return self._send(200, {"sessions": [dict(x, current=(x["id"] == who.get("session"))) for x in self.state.auth.sessions_for(who["user"])]})
            if path == "/api/admin/health" and who["owner"]:
                return self._send(200, self.state.health())
            if path == "/api/admin/audit" and who["owner"]:
                return self._send(200, {"events": self.state.auth.events(int((qs.get("limit") or ["100"])[0]), (qs.get("kind") or [None])[0])})
            if path == "/api/admin/users" and who["owner"]:
                return self._send(200, {"users": [{"user": u["user"], "tier": self.state.usage.get_user(u["user"])["tier"], "email": u.get("email"),
                                                   "banned": bool(u.get("banned")), "owner": bool(u.get("owner"))}
                                                  for u in self.state.users.values()], "paused": bool(self.state.cfg.get("paused"))})
            return self._send(404, {"code": "not_found", "message": "Not found."})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self._send(500, {"code": "error", "message": "Something went wrong. Please try again."})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._origin_ok():
            self.state.auth.event("bad_origin", "", self._ip(), f"POST {path}")
            return self._send(403, {"code": "bad_origin", "message": "That request came from another website, so it was refused.", "action": "Use Emvryx at its own address."})
        m = re.fullmatch(r"/pair/([A-Za-z0-9_-]{16,80})", path)
        if m:                                                    # the button on the pairing page: this is what uses the link up
            try:
                if self._locked():
                    return
                user = self.state.auth.use_pair(m.group(1))
                who = self.state.who_name(user) if user else None
                if who and not who["banned"]:
                    self.state.auth.event("pair_used", user, self._ip(), "")
                    self._start_session(user, "pairing link")
                    return self._send(303, b"", "text/plain", {"Location": "/"})
                self._fail("bad pairing link")
                return self._send(410, "This pairing link was already used or has expired. Ask for a new one.\n", "text/plain; charset=utf-8")
            except (BrokenPipeError, ConnectionResetError):
                return
        try:
            body = self._json()
            if path == "/api/login":
                if self._locked():
                    return
                key = str(body.get("key", "")).strip()
                who = self.state.who(key)
                if not who:
                    self._fail("bad key")
                    return self._send(401, {"code": "bad_key", "message": "That key isn't right.", "action": "Check it and try again."})
                if who["banned"]:
                    return self._send(403, {"code": "banned", "message": "This account has been turned off.", "action": "Ask the owner if you think that is a mistake."})
                self._start_session(who["user"], "key")
                return self._send(200, {"ok": True})
            if path == "/api/login/email/start":
                return self.api_email_start(body)
            if path == "/api/login/email/verify":
                return self.api_email_verify(body)
            who = self._who()
            if not who:
                return
            if path == "/api/delete-account":
                if str(body.get("confirm", "")) != who["user"]:
                    return self._send(400, {"code": "confirm", "message": "Type your name to confirm.", "action": "Nothing was deleted."})
                try:
                    data_tools.delete_account(self.state, who["user"])
                except ValueError as e:
                    return self._send(400, {"code": "bad_request", "message": str(e)})
                self._expire_cookie("emvryx_session")
                return self._send(200, {"ok": True})
            if path == "/api/logout":
                if who.get("session"):
                    self.state.auth.revoke(who["session"], who["user"])
                    self.state.auth.event("logout", who["user"], self._ip(), "")
                self._expire_cookie("emvryx_session")
                return self._send(200, {"ok": True})
            if path == "/api/sessions/revoke":
                ok = self.state.auth.revoke(str(body.get("id", "")), who["user"])
                self.state.auth.event("session_revoked", who["user"], self._ip(), "one device")
                return self._send(200, {"ok": ok})
            if path == "/api/sessions/revoke-others":
                n = self.state.auth.revoke_user(who["user"], who.get("session"))
                self.state.auth.event("session_revoked", who["user"], self._ip(), f"{n} other devices")
                return self._send(200, {"revoked": n})
            if path == "/api/chats":
                cid = self.state.store(who["user"]).new_chat(private=bool(body.get("private")))
                return self._send(200, {"id": cid})
            m = re.fullmatch(r"/api/chats/(-?\d+)/send", path)
            if m:
                return self.api_send(who, int(m.group(1)), body)
            m = re.fullmatch(r"/api/chats/(-?\d+)/stop", path)
            if m:
                ev = self.state.stops.get((who["user"], int(m.group(1))))
                if ev:
                    ev.set()
                return self._send(200, {"ok": True})
            if path.startswith("/api/code/"):
                return self.api_code_post(who, path, body)
            if path == "/api/settings":
                return self._send(200, self.state.put_settings(who["user"], body))
            if path == "/api/apps/github/device/start":
                try:
                    flow = github_link.DeviceFlow(self.state.github_client_id(), self.state.github_http)
                    d = flow.start()
                except github_link.GitHubError as e:
                    return self._send(400, {"code": "github", "message": e.message, "action": e.action})
                self.state.github_device[who["user"]] = {"device_code": d["device_code"], "expires": time.time() + d["expires_in"], "interval": d["interval"], "last": 0}
                self.state.auth.event("github_device_start", who["user"], self._ip(), "")
                return self._send(200, {"user_code": d["user_code"], "verification_uri": d["verification_uri"], "interval": d["interval"], "expires_in": d["expires_in"]})
            if path == "/api/apps/github/device/poll":
                pend = self.state.github_device.get(who["user"])
                if not pend or pend["expires"] < time.time():
                    self.state.github_device.pop(who["user"], None)
                    return self._send(400, {"code": "github", "message": "That sign-in has run out.", "action": "Start it again."})
                wait = pend["last"] + pend["interval"] - time.time()
                if wait > 0:                                       # never ask GitHub faster than it said
                    return self._send(200, {"status": "pending", "wait": int(wait) + 1})
                pend["last"] = time.time()
                try:
                    status, token = github_link.DeviceFlow(self.state.github_client_id(), self.state.github_http).poll(pend["device_code"])
                    if status == "done":
                        login, uid = github_link.Api(token, self.state.github_http).me()
                except github_link.GitHubError as e:
                    return self._send(400, {"code": "github", "message": e.message, "action": e.action})
                if status == "slow_down":
                    pend["interval"] += 5
                if status == "done":
                    self.state.github_device.pop(who["user"], None)
                    self.state.github.connect(who["user"], token, login, uid)
                    self.state.github.log(who["user"], f"connected as {login} (GitHub sign-in)")
                    self.state.auth.event("github_connected", who["user"], self._ip(), "device flow")
                    return self._send(200, {"status": "done", **self.state.github.public(who["user"])})
                if status in ("expired", "denied"):
                    self.state.github_device.pop(who["user"], None)
                    return self._send(200, {"status": status})
                return self._send(200, {"status": "pending", "wait": pend["interval"]})
            if path == "/api/apps/github/connect":
                try:
                    token = github_link.validate_token(body.get("token"))
                    login, uid = github_link.Api(token, self.state.github_http).me()
                except github_link.GitHubError as e:
                    return self._send(400, {"code": "github", "message": e.message, "action": e.action})
                self.state.github.connect(who["user"], token, login, uid)
                self.state.github.log(who["user"], f"connected as {login}")
                self.state.auth.event("github_connected", who["user"], self._ip(), "pasted token")
                return self._send(200, self.state.github.public(who["user"]))
            if path == "/api/apps/github/disconnect":
                self.state.github.disconnect(who["user"])
                self.state.github.log(who["user"], "disconnected (token deleted)")
                self.state.auth.event("github_disconnected", who["user"], self._ip(), "")
                return self._send(200, self.state.github.public(who["user"]))
            m = re.fullmatch(r"/api/apps/([a-z]+)/connect", path)
            if m:
                try:
                    app = connected_apps.get(m.group(1))
                except KeyError:
                    return self._send(404, {"code": "not_found", "message": "That app isn't in the list."})
                return self._send(501, {"code": "coming_soon", "message": f"{app['name']} isn't available yet.",
                                        "action": "Connected apps are planned: nothing is connected, and nothing is shared."})
            if path == "/api/delete-everything":
                self.state.store(who["user"]).delete_everything()
                self.state.saved_for(who["user"]).clear()
                return self._send(200, {"ok": True})
            m = re.fullmatch(r"/api/chats/(-?\d+)/messages/(\d+)/like", path)
            if m:
                cid, mid = int(m.group(1)), int(m.group(2))
                if cid < 0:
                    return self._send(400, {"code": "private", "message": "Private chats save nothing."})
                used = self.state.lookups.get((who["user"], cid, mid))
                if not used:
                    return self._send(200, {"saved": 0})
                n = self.state.saved_for(who["user"]).save(used["question"], used["notes"], self.state.clock(), used["recent"])
                return self._send(200, {"saved": n, "notes": len(used["notes"])})
            if path == "/api/memory/add":
                if not self.state.memory_for(who["user"]).add(str(body.get("text", ""))):
                    return self._send(400, {"code": "not_saved", "message": "That was not saved.",
                                            "action": "It is empty, already there, or looks like a password, number or address, which are never kept."})
                return self._send(200, {"facts": self.state.memory_for(who["user"]).list()})
            if path == "/api/memory/delete":
                self.state.memory_for(who["user"]).delete(int(body.get("id", 0)))
                return self._send(200, {"ok": True})
            if path == "/api/memory/clear":
                self.state.memory_for(who["user"]).clear()
                return self._send(200, {"ok": True})
            if path == "/api/saved-notes/delete":
                self.state.saved_for(who["user"]).delete(int(body.get("id", 0)))
                return self._send(200, {"ok": True})
            if path == "/api/saved-notes/clear":
                self.state.saved_for(who["user"]).clear()
                return self._send(200, {"ok": True})
            if path.startswith("/api/admin/"):
                if not who["owner"]:
                    return self._send(403, {"code": "owner_only", "message": "Only the owner can change plans."})
                return self.api_admin(path, body)
            return self._send(404, {"code": "not_found", "message": "Not found."})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except ValueError as e:
            self._send(400, {"code": "bad_request", "message": str(e)})
        except Exception:
            self._send(500, {"code": "error", "message": "Something went wrong. Please try again."})

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._origin_ok():
            self.state.auth.event("bad_origin", "", self._ip(), f"DELETE {path}")
            return self._send(403, {"code": "bad_origin", "message": "That request came from another website, so it was refused.", "action": "Use Emvryx at its own address."})
        who = self._who()
        if not who:
            return
        m = re.fullmatch(r"/api/chats/(-?\d+)", path)
        if not m:
            return self._send(404, {"code": "not_found", "message": "Not found."})
        self.state.store(who["user"]).delete_chat(int(m.group(1)))
        self._send(200, {"ok": True})

    # ---- VryxCode
    def _code_error(self, e):
        self._send(400, {"code": "code_error", "message": e.message, "action": e.action})

    def _code_usage(self, who, model_id):
        """The same numbers as the chat's usage line, in 'coding steps' (one step = one model call at Balanced)."""
        st = self.state
        coder = st.coder(model_id)
        name = coder.get("plan_like", "solstice") if coder else next((m["name"] for m in st.manifest["models"] if m["id"] == model_id), "Equinox").lower()
        snap = st.limiter.snapshot(who["user"], name, "balanced", st.clock())
        return {"status": snap["status"], "exempt": snap["exempt"], "tank_pct": round(snap["tank"]["pct"]), "week_pct": round(snap["week"]["pct_left"]),
                "steps_left": snap["can_send"], "plan": snap["plan"]}

    def api_code_git(self, who, body):
        """create_repo | link | clone | pull | push for a project, always started by the person (a button), never silently."""
        st, user = self.state, who["user"]
        project = st.code.check_name(body.get("project"))
        action = str(body.get("action", ""))
        if action not in ("create_repo", "link", "clone", "pull", "push"):
            raise code_sessions.CodeError("Choose create_repo, link, clone, pull or push.")
        if st.code.running(user):
            raise code_sessions.CodeError("A coding session is running.", "Stop it first, then use GitHub.")
        try:
            api = st.github_api(user)
            os.makedirs(st.code.project_path(user, project), exist_ok=True)
            g = st.git_for(user, project)
            if action == "create_repo":
                owner, repo = api.create_repo(str(body.get("name") or project), bool(body.get("private", True)), str(body.get("description", "")))
                g.init_and_link(owner, repo)
                st.github.log(user, f"created {owner}/{repo} for {project}")
                return {"ok": True, "message": f"Created {owner}/{repo} and linked this project to it."}
            if action in ("link", "clone"):
                owner, repo = github_link.parse_repo(body.get("repo"))
                if action == "link":
                    g.init_and_link(owner, repo)
                    st.github.log(user, f"linked {project} to {owner}/{repo}")
                    return {"ok": True, "message": f"Linked this project to {owner}/{repo}."}
                g.clone(owner, repo)
                st.github.log(user, f"cloned {owner}/{repo} into {project}")
                return {"ok": True, "message": f"Cloned {owner}/{repo} into this project."}
            if action == "pull":
                out = g.pull()
                st.github.log(user, f"pulled {project}")
                return {"ok": True, "message": out}
            out = g.push(allow_protected=bool(body.get("confirm_protected")))
            st.github.log(user, f"pushed {project}")
            return {"ok": True, "message": out}
        except github_link.GitHubError as e:
            raise code_sessions.CodeError(e.message, e.action)

    def api_code_get(self, who, path, qs):
        st, user = self.state, who["user"]
        arg = lambda k: (qs.get(k) or [""])[0]
        try:
            if path == "/api/code":
                run = st.code.running(user)
                allowed, why = st.code_allowed(who)
                return self._send(200, {"allowed": allowed, "why_not": why, "sandbox": st.code.sandbox.get("mode", "none"),
                                        "usage": self._code_usage(who, None), "models": st.code_models(who), "projects": st.code.projects(user),
                                        "running": run.id if run else None, "project": run.project if run else None})
            if path == "/api/code/git":
                project = st.code.check_name(arg("project"))
                g = st.git_for(user, project)
                try:
                    status = g.status()
                except github_link.GitHubError as e:
                    status = {"repo": True, "linked": False, "problem": e.message}
                return self._send(200, {"connected": st.github.connected(user), "login": st.github.get(user).get("login"), **status})
            if path == "/api/code/zip":
                project = st.code.check_name(arg("project"))
                return self._send(200, st.code.export_zip(user, project), "application/zip",
                                  {"Content-Disposition": f'attachment; filename="{project}.zip"'})
            if path == "/api/code/files":
                return self._send(200, {"files": st.code.files(user, arg("project"))})
            if path == "/api/code/file":
                return self._send(200, st.code.read(user, arg("project"), arg("path")))
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)", path)
            if m:
                s = st.code.get(user, m.group(1))
                events, state, pending = s.since(max(0, int(arg("after") or 0)))
                return self._send(200, {"events": events, "state": state, "pending": pending, "task": s.task, "project": s.project, "model": s.model_id,
                                        "used": round(s.meter.counted) if s.meter else 0, "steps": s.meter.steps if s.meter else 0,
                                        "live": s.live_view(), "usage": self._code_usage(who, s.model_id)})
            return self._send(404, {"code": "not_found", "message": "Not found."})
        except code_sessions.CodeError as e:
            self._code_error(e)

    def api_code_post(self, who, path, body):
        st, user = self.state, who["user"]
        try:
            if path == "/api/code/start":
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                coder = st.coder(str(body.get("model", "")))
                if coder:                                            # an outside coding model: labelled as such, costs like its plan_like model
                    cstate, cbadge = st._coder_state(coder, who)
                    if cstate != "ready":
                        raise code_sessions.CodeError(f"{coder['label']} isn't ready: {cbadge}.")
                    model = {"id": coder["id"], "name": coder["label"], "version": 0, "context_tested": coder.get("context_tested", 8192),
                             "limiter_key": coder.get("plan_like", "solstice"), "outside": True}
                else:
                    try:
                        model = st.pick_model(who, str(body.get("model", "")))
                    except KeyError:
                        raise code_sessions.CodeError("Pick a model for VryxCode.")
                    if not model.get("vryxcode"):
                        raise code_sessions.CodeError(vryxcode.check_model(model["id"])[1])
                    if model["state"] != "ready":
                        raise code_sessions.CodeError(f"{model['name']} {model['version']:g} isn't ready: {model['badge']}.")
                    model["limiter_key"] = model["name"].lower()
                project = st.code.check_name(body.get("project"))
                box = {}

                def generate(messages, model=model):          # the model loads on the first step, in the session's thread (it can take a minute)
                    if "fn" not in box:
                        try:
                            box["fn"] = st.code_backend(model)
                        except AppError as e:
                            raise code_sessions.CodeError(e.message, e.action)
                    if hasattr(box["fn"], "on_delta"):
                        box["fn"].on_delta = getattr(generate, "on_delta", None)     # live progress for the page's "working" line
                    reply = box["fn"](messages)
                    generate.usage = getattr(box["fn"], "usage", None)      # the real counts, for the usage meter
                    return reply
                snap = st.limiter.snapshot(user, model["limiter_key"], "balanced", st.clock())
                if not snap["exempt"] and snap["can_send"] < 1:
                    raise code_sessions.CodeError("Your usage has run out for now.", "Coding steps are counted like chat messages. Wait for the tank to refill or the week to reset.")
                meter = code_sessions.Meter(st.limiter, user, model["limiter_key"], st.clock)
                tools, identity = None, None
                if st.github.connected(user):
                    g = st.git_for(user, project)
                    identity = g.identity
                    try:
                        linked = g.is_repo() and bool(g.remote())
                    except github_link.GitHubError:
                        linked = False
                    if linked:
                        tools = {"github": st.github_tool(user, project)}
                s, note = st.code.start(user, project, body.get("task"), model["id"], generate, bool(body.get("auto_edits")),
                                        int(model.get("context_tested") or 8192), meter, outside=bool(model.get("outside")), tools=tools, identity=identity)
                return self._send(200, {"id": s.id, "note": note})
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/answer", path)
            if m:
                ok = st.code.get(user, m.group(1)).respond(int(body.get("id", -1)), body.get("allow"), body.get("always"))
                return self._send(200, {"ok": ok})
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/stop", path)
            if m:
                st.code.get(user, m.group(1)).request_stop()
                return self._send(200, {"ok": True})
            if path == "/api/code/git":
                return self._send(200, self.api_code_git(who, body))
            if path == "/api/code/import":
                project = st.code.check_name(body.get("project"))
                return self._send(200, {"imported": st.code.import_b64(user, project, body), "project": project})
            if path == "/api/code/projects/delete":
                st.code.delete_project(user, body.get("project"))
                return self._send(200, {"ok": True})
            return self._send(404, {"code": "not_found", "message": "Not found."})
        except code_sessions.CodeError as e:
            self._code_error(e)

    # ---- the API
    def api_state(self, who, qs):
        st = self.state
        cat = st.catalog(who)
        model_id = (qs.get("model") or [None])[0]
        effort = (qs.get("effort") or ["balanced"])[0]
        effort = "balanced" if effort == "auto" else (effort if effort in EFFORTS else "balanced")   # Auto: show Balanced's numbers
        pool = {m["id"]: m for m in cat["cards"] + cat["other"]}
        ready = [m for m in cat["cards"] + cat["other"] if m["state"] == "ready"]
        default = next((m for m in ready if m["name"] == "Flare"), ready[0] if ready else cat["cards"][0])
        model = pool.get(model_id) or default
        snap = st.usage_snapshot(who, model, effort)
        win = st.window_for(who, model)
        return {"user": who["user"], "owner": who["owner"], "plan": who["tier"], "demo": st.demo, "contact": st.security.get("contact_email") or None,
                "models": cat, "model": model["id"], "efforts": [
                    {"id": "auto", "name": "Auto", "use": "Picks for you",
                     "blurb": "Decides how long to think from your message: quick for simple questions, deeper for hard ones."},
                    {"id": "quick", "name": "Quick", "use": "Uses less", "blurb": "Answers fast and thinks briefly. Best for simple questions."},
                    {"id": "balanced", "name": "Balanced", "use": "Normal usage", "blurb": "A good mix of speed and care. The default."},
                    {"id": "deep", "name": "Deep", "use": "Uses more",
                     "blurb": "Takes longer: thinks it through and checks its work. More accurate on hard questions."}],
                "usage": snap, "window": {k: win[k] for k in ("window", "reason", "mode", "limited_by", "cache_bits", "cache_mb")},
                "chats": st.store(who["user"]).list_chats(), "settings": st.get_settings(who["user"]),
                "thinking_words": list(chat_polish.THINKING_WORDS), "think_switch_s": chat_polish.THINKING_SWITCH_S,
                "pause_by_effort": chat_polish.PAUSE_BASE, "regen_options": regen_modes.menu()}

    def api_get_chat(self, who, cid):
        store = self.state.store(who["user"])
        if not store.exists(cid):
            return self._send(404, {"code": "not_found", "message": "That chat is gone."})
        msgs = [{"id": m["id"], "role": m["role"], "content": m["content"], "model_id": m["model_id"], "status": m["status"]}
                for m in store.messages(cid) if not (m["status"] == "compacted" and not m["content"])]
        self._send(200, {"id": cid, "title": store.title(cid), "private": cid < 0, "messages": msgs})

    def api_admin(self, path, body):
        st = self.state
        if path == "/api/admin/users":
            name, tier = str(body.get("user", "")), str(body.get("tier", "free"))
            try:
                key = st.add_user(name, tier, email=body.get("email") or None)
            except ValueError as e:
                return self._send(400, {"code": "bad_request", "message": str(e)})
            st.set_plan(name, tier)
            pair = st.auth.new_pair(name, st.security["pair_minutes"], made_by="owner")
            st.auth.event("pair_created", name, self._ip(), "by owner")
            return self._send(200, {"user": name, "tier": tier, "key": key, "pair": pair, "pair_minutes": st.security["pair_minutes"]})
        if path == "/api/admin/pairing":
            name = str(body.get("user", ""))
            if not st.user_record(name):
                return self._send(404, {"code": "not_found", "message": "No one is called that."})
            pair = st.auth.new_pair(name, st.security["pair_minutes"], made_by="owner")
            st.auth.event("pair_created", name, self._ip(), "by owner")
            return self._send(200, {"user": name, "pair": pair, "pair_minutes": st.security["pair_minutes"]})
        if path == "/api/admin/ban":
            try:
                st.set_ban(str(body.get("user", "")), bool(body.get("banned", True)))
            except ValueError as e:
                return self._send(400, {"code": "bad_request", "message": str(e)})
            return self._send(200, {"ok": True})
        if path == "/api/admin/pause":
            st.cfg["paused"] = bool(body.get("paused"))
            return self._send(200, {"paused": st.cfg["paused"]})
        self._send(404, {"code": "not_found", "message": "Not found."})

    # ---- email sign-in
    def api_email_start(self, body):
        st = self.state
        if not st.mailer:
            return self._send(501, {"code": "email_off", "message": "Email sign-in isn't set up on this server.", "action": "Use your key or a pairing link."})
        ip = self._ip()
        wait = st.rl.blocked("email-ip:" + ip, st.security["email_start_limit"], st.security["email_start_window"])
        if wait:
            return self._send(429, {"code": "too_many", "message": "Too many codes asked for from this address.", "action": f"Wait about {max(1, wait // 60)} minute(s).",
                                    "retry_after": wait}, headers={"Retry-After": str(wait)})
        st.rl.hit("email-ip:" + ip)
        email = auth.clean_email(body.get("email"))
        generic = {"ok": True, "message": "If that address can sign in, a code is on its way."}      # the same answer whether or not it can: nobody can probe who has an account
        if not email or st.rl.blocked("email:" + email, 3, 600):
            return self._send(200, generic)
        st.rl.hit("email:" + email)
        if len(st.rl.hits) > 5000:
            st.rl.trim(3600)
        rec = st.user_by_email(email)
        if (rec and not rec.get("banned")) or (not rec and st.security["open_signups"]):
            code = auth.make_code()
            st.auth.put_code(email, code)
            def deliver():
                try:
                    st.mailer.send(email, *mailer.code_email(code))
                    st.auth.event("email_code", rec["user"] if rec else "", ip, "sent")
                except Exception as e:                       # never tell the caller: it would show whether the address is known
                    st.auth.event("email_send_failed", "", ip, str(e)[:120])
            if st.mail_async:                                # in the background: a known address must not take longer to answer than an unknown one
                threading.Thread(target=deliver, daemon=True).start()
            else:
                deliver()
        return self._send(200, generic)

    def api_email_verify(self, body):
        st = self.state
        if self._locked():
            return
        email = auth.clean_email(body.get("email"))
        if not email or not st.auth.check_code(email, str(body.get("code", ""))):
            self._fail("bad email code")
            return self._send(401, {"code": "bad_code", "message": "That code isn't right, or it has run out.", "action": "Ask for a new one."})
        rec = st.user_by_email(email)
        if rec:
            if rec.get("banned"):
                return self._send(403, {"code": "banned", "message": "This account has been turned off.", "action": "Ask the owner if you think that is a mistake."})
            user = rec["user"]
            st.mark_email_verified(user)
        elif st.security["open_signups"]:
            user = st.create_email_account(email)
        else:
            self._fail("email code for unknown address")
            return self._send(401, {"code": "bad_code", "message": "That code isn't right, or it has run out.", "action": "Ask for a new one."})
        self._start_session(user, "email code")
        return self._send(200, {"ok": True})

    def api_send(self, who, cid, body):
        st = self.state
        store = st.store(who["user"])
        if not store.exists(cid):
            return self._send(404, {"code": "not_found", "message": "That chat is gone."})
        text = str(body.get("text", "")).strip()
        regenerate = bool(body.get("regenerate"))
        if not regenerate and not text:
            return self._send(400, {"code": "empty", "message": "Type a message first."})
        if len(text) > MAX_TEXT:
            return self._send(400, {"code": "too_long", "message": "That message is too long. Please shorten it."})
        try:
            q, stop, model, win, decision = start_turn(st, who, cid, text, str(body.get("model", "")), str(body.get("effort", "balanced")),
                                             regenerate, body.get("regen_mode") or None)
        except ValueError as e:
            return self._send(400, {"code": "bad_option", "message": str(e)})
        except KeyError:
            return self._send(400, {"code": "bad_model", "message": "That model isn't available."})
        except Exception as e:
            status, headers, payload = error_payload(e)
            return self._send(status, payload, headers=headers)
        # wait a moment: limits and connection errors come back at once and deserve a proper HTTP status
        first = None
        try:
            first = q.get(timeout=0.4)
        except queue.Empty:
            pass
        if first and first[0] == "error":
            status, headers, payload = error_payload(first[1])
            return self._send(status, payload, headers=headers)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in self._security_headers().items():
            self.send_header(k, v)
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def emit(event, data):
            self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
            self.wfile.flush()
        try:
            emit("thinking", {"min_first_s": decision["pause"], "effort": decision["effort"], "auto": decision["auto"],
                              "reason": decision["reason"], "temperature": decision["temperature"]})
            item = first
            while True:
                if item is None:
                    try:
                        item = q.get(timeout=10)
                    except queue.Empty:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                        continue
                kind, val = item
                item = None
                if kind == "loading":
                    emit("loading", {"model": val})
                elif kind == "notes":
                    emit("notes", val)
                elif kind == "memory":
                    emit("memory", val)
                elif kind == "piece":
                    emit("piece", {"t": val})
                elif kind == "done":
                    snap = st.usage_snapshot(who, model, decision["effort"])
                    emit("done", {"reason": val["reason"], "compacted": val["compacted_messages"],
                                  "forgotten": val["forgotten_messages"], "message_id": val["message_id"],
                                  "title": store.title(cid), "usage": snap, "effort": decision["effort"], "auto": decision["auto"]})
                    return
                else:
                    status, headers, payload = error_payload(val)
                    payload["http"] = status
                    emit("error", payload)
                    return
        except (BrokenPipeError, ConnectionResetError, OSError):
            stop.set()                                         # the page went away: stop writing, keep what was written


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(state, host="127.0.0.1", port=8000, quiet=False):
    handler = type("BoundHandler", (Handler,), {"state": state})
    srv = Server((host, port), handler)
    srv.quiet = quiet
    return srv


# ------------------------------------------------------------------ command line
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--host", default="127.0.0.1", help="127.0.0.1 = this computer only. 0.0.0.0 = your whole network")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--data", default=".emvryx", help="where chats, usage and keys are kept")
    ap.add_argument("--llama", default=None, help="URL of a llama-server (llama.cpp) running the model")
    ap.add_argument("--llama_key", default=None)
    ap.add_argument("--tokenizer", default=None, help="the model's tokenizer.json (only needed with --llama)")
    ap.add_argument("--llama-bin", default=None, help="path to llama-server (llama.cpp); default: found on the PATH")
    ap.add_argument("--gguf", action="append", default=[], metavar="ID=PATH",
                    help="a model file to run, e.g. ember-2=export/dev/v2/my-ai-q8_0.gguf (the exports are found by themselves)")
    ap.add_argument("--llama-args", default="", help="extra options for llama-server, e.g. \"-ngl 99\" to use the GPU")
    ap.add_argument("--ram", type=float, default=None, help="this computer's memory in GB (default: detected)")
    ap.add_argument("--wiki", default=os.path.join("data", "wiki", "wiki.db"),
                    help="the Wikipedia index (wiki_index.py) the chat looks things up in; skipped if the file isn't there")
    ap.add_argument("--no-web", action="store_true", help="never search the web (people's own Settings choice then has no effect)")
    ap.add_argument("--timings", action="store_true", help="print how long each reply took (loading, first word, total)")
    ap.add_argument("--code-sandbox", choices=("none", "docker"), default="none", help="run VryxCode's commands in a throwaway Docker container (see docker/code-sandbox)")
    ap.add_argument("--code-image", default=code_sandbox.DEFAULT_IMAGE)
    ap.add_argument("--code-runtime", default=None, help="a stronger container runtime such as runsc (gVisor), if installed")
    ap.add_argument("--code-cpus", default="1")
    ap.add_argument("--code-memory", default="768m")
    ap.add_argument("--weather-place", default=os.environ.get("EMVRYX_WEATHER_PLACE", ""), metavar="PLACE",
                    help="the place weather questions use when they do not name one, for example \"Austin, Texas\"")
    ap.add_argument("--preload", metavar="MODEL_ID", default=None, help="load this model when the app starts, so the first message does not wait for it (for example flare-2.5)")
    ap.add_argument("--pair", metavar="NAME", default=None, help="print a one-time link (valid 15 minutes) that signs NAME in on one device, then exit")
    ap.add_argument("--rotate-key", metavar="NAME", help="give someone a new key (owner, or a name from --add-user); the old key stops working. Restart the app afterwards")
    ap.add_argument("--add-user", nargs=2, metavar=("NAME", "PLAN"), help="add a tester (free, pro or mega) and print their key")
    args = ap.parse_args()
    if args.data == ".emvryx" and not os.path.exists(".emvryx") and os.path.isdir(".yuvra"):   # the app was called Yuvra before
        os.rename(".yuvra", ".emvryx")
        print("Moved your saved chats, keys and usage from .yuvra to .emvryx (the app is now called Emvryx).")
    if args.llama and not args.tokenizer:
        sys.exit("With --llama you also need --tokenizer data/<version>/tokenizer.json (the model's own tokenizer).")
    tok = BPETokenizer.load(args.tokenizer) if args.tokenizer else None
    manifest = M.load_manifest()
    files = discover_ggufs(manifest)
    for item in args.gguf:
        mid, _, path = item.partition("=")
        if not path or not any(m["id"] == mid for m in list(manifest["models"]) + list(manifest.get("coders", []))):
            sys.exit(f"--gguf wants ID=PATH with an id from models.json (got {item!r}).")
        files[mid] = path
    runner = None
    if files and not args.llama:
        runner = ModelRunner(args.llama_bin or find_llama_server(), files, extra_args=args.llama_args.split())
    state = AppState(args.data, args.llama, args.llama_key, tok, manifest=manifest, ram_gb=args.ram, runner=runner)
    state.verbose = args.timings
    state.code.sandbox = {"mode": args.code_sandbox, "image": args.code_image, "runtime": args.code_runtime, "cpus": args.code_cpus, "memory": args.code_memory}
    base = f"http://localhost:{args.port}"
    if args.rotate_key:
        try:
            key = state.rotate_key(args.rotate_key)
        except ValueError as e:
            sys.exit(str(e))
        pair = state.auth.new_pair(args.rotate_key, state.security["pair_minutes"], made_by="command line")
        print(f"New key for {args.rotate_key} (shown once, it is not stored): {key}")
        print(f"Or sign in on one device with this one-time link (valid {state.security['pair_minutes']} minutes): {base}/pair/{pair}")
        print("The old key no longer works, and every device that was signed in as them has been signed out. Restart the app so it reads the change.")
        return
    if args.pair:
        if not state.user_record(args.pair):
            sys.exit(f"no one is called {args.pair!r}")
        pair = state.auth.new_pair(args.pair, state.security["pair_minutes"], made_by="command line")
        state.auth.event("pair_created", args.pair, "", "command line")
        print(f"One-time sign-in link for {args.pair} (valid {state.security['pair_minutes']} minutes, works once): {base}/pair/{pair}")
        print("Use your own address instead of localhost if you open it from another device (for example https://chat.emvryx.app/pair/...).")
        return
    if args.add_user:
        key = state.add_user(*args.add_user)
        if key is None:
            print(f"{args.add_user[0]} already exists (their plan was kept). Use --pair or --rotate-key to give them a way in.")
            return
        pair = state.auth.new_pair(args.add_user[0], state.security["pair_minutes"], made_by="command line")
        print(f"{args.add_user[0]} ({args.add_user[1]}). Key (shown once, not stored): {key}")
        print(f"One-time sign-in link (valid {state.security['pair_minutes']} minutes): {base}/pair/{pair}")
        return
    if os.path.exists(args.wiki):
        from wiki_index import WikiIndex
        state.wiki = lookup_auto.LockedWiki(WikiIndex(args.wiki))
        print(f"Looking things up in the Wikipedia index {args.wiki}")
    else:
        print(f"No Wikipedia index at {args.wiki}: answers come from the model's memory (see wiki_index.py)")
    if not args.no_web:
        from web_search import web_answer
        state.web_fn = lambda question, k: web_answer(question, k, place=args.weather_place)        # Auto: only when the person's setting and the question call for it
    srv = make_server(state, args.host, args.port)
    if args.preload:
        def _preload():
            print("Preload: " + state.preload(args.preload), flush=True)
        threading.Thread(target=_preload, daemon=True).start()
    shown = "localhost" if args.host in ("127.0.0.1", "0.0.0.0") else args.host
    if state.demo:
        print("Emvryx is running in DEMO mode (no model files found; see docs/V2.md to make a .gguf)")
    else:
        print("Emvryx is running. Models on this computer: " + (", ".join(sorted(files)) or "none") + (" (via --llama)" if args.llama else ""))
        if runner and not runner.bin:
            print("llama-server was not found. Install llama.cpp and pass --llama-bin <path to llama-server.exe>.")
    if args.code_sandbox == "docker":
        ok, why = code_sandbox.available(args.code_image)
        print(("VryxCode runs in Docker containers (no network, hard limits)." if ok else f"VryxCode sandbox NOT ready, so VryxCode will refuse to run: {why}"))
    else:
        print("VryxCode runs with the folder sandbox only: it is open to the owner only. For other people use --code-sandbox docker (docs/SECURITY.md).")
    fresh = state.owner_key()
    if fresh:                                            # the first run: the owner's key exists only now
        print(f"Your owner key (shown once, it is not stored): {fresh}")
    pair = state.auth.new_pair("owner", state.security["pair_minutes"], made_by="startup")
    print(f"Open (one time, valid {state.security['pair_minutes']} minutes): http://{shown}:{args.port}/pair/{pair}")
    print("Need another link later?  python app_server.py --pair owner")
    if args.host == "0.0.0.0":
        print("Reachable from your network. Anyone with a key can use it; keep keys private.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
