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
import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import argparse
import atexit
import hashlib
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
import accounts
import auth
import chat
import data_tools
import code_sandbox
import chat_polish
import code_review
import code_sessions
import harness
import vryxcode
import app_skills
import export_doc
import teacher_mode
import app_links
import connected_apps
import documents
import feedback
import vision
import live_data
import flags
import model_publish
import model_guard
import github_link
import identity_answer
import google_signin
import lookup_auto
import mailer
import passkeys
import secret_box
import shares
import summary
import saved_notes
import user_memory
import code_preview
import browser_check
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
                     "email_start_window": 600, "open_signups": False, "signup_mode": "closed", "trusted_proxies": ["127.0.0.1", "::1"], "audit_notify": True,
                     "allow_key_links": False, "allowed_origins": [], "code_unsandboxed_for_others": False,
                     "require_encryption": False, "grant_emails": ["darrylmccottrell16@gmail.com"], "public_url": "", "sharing": False, "weekly_summary": False, "backup_dir": "", "cloud_host": "", "cloud_user": "root", "cloud_port": 22, "cloud_for_others": False, "github_client_id": "", "contact_email": "", "operator_name": "", "alert_ntfy_topic": "",
                     "idle_unload_minutes": 15,
                     **code_sandbox.QUOTA_DEFAULTS}
API_KEY_PREFIX = "emvx_"                      # an app's key starts with this, so a key that leaks into a log or a repository is easy to recognise
APP_PREFIX = "app-"
PAIR_PAGE = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             '<meta name="robots" content="noindex"><title>Sign in: Emvryx</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;'
             'background:#07080D;color:#EEF0F6;font:17px/1.5 system-ui,sans-serif}main{max-width:380px;padding:24px}h1{font-size:26px;margin:0 0 8px}'
             'p{color:#9AA3BC}button{width:100%;min-height:48px;border:0;border-radius:12px;background:#F5A524;color:#1A1204;font:600 17px system-ui;cursor:pointer}'
             '</style></head><body><main><h1>Sign in to Emvryx</h1><p>This link signs in <b>one device</b>, once. Only continue if you asked for it.</p>'
             '<form method="post" action="/pair/{{token}}"><button type="submit">Sign in on this device</button></form></main></body></html>')
MAX_DOC_BODY = 15_000_000                              # a document upload (base64): documents.MAX_FILE_BYTES is 10 MB
MAX_UPLOAD = 30_000_000                                # a project upload (base64): see code_sessions.MAX_IMPORT_BYTES
MAX_TEXT = 20_000
EFFORTS = {"quick": 160, "balanced": 320, "deep": 700}          # most tokens a reply may have, per effort level (the small from-scratch models)
OPEN_EFFORTS = {"quick": 512, "balanced": 1536, "deep": 4096}   # the open-base models know and write much more: a code answer was cut off at about 300 tokens
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
class Cancelled(Exception):
    """The person pressed Stop while a model was loading."""


class ModelRunner:
    """Starts llama-server for the model the person picked and stops it when another one is picked (one at a time, so
    a small PC is not asked to hold two models). `files` is {model id: path to a .gguf}."""

    def __init__(self, llama_bin, files, start_timeout=180, extra_args=(), host="127.0.0.1"):
        self.bin, self.files, self.timeout, self.extra, self.host = llama_bin, dict(files), start_timeout, list(extra_args), host
        self.proc = self.model_id = self.url = self.ctx = None
        self.memo = None                                        # a file that remembers the last model, so a restart can load it ahead of the first message
        self.last_used = time.time()                            # the last time a message needed the model (idle unload looks at this)
        self.loaded_at = None
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

    def loaded(self):
        """The id of the model that is loaded right now, or None."""
        return self.model_id if (self.proc and self.proc.poll() is None) else None

    def touch(self):
        self.last_used = time.time()

    def unload(self):
        """Free the graphics card and memory: stop llama-server. Not while a model is being loaded (the lock is busy). True if something was stopped."""
        if not self.lock.acquire(blocking=False):
            return False
        try:
            if not self.loaded():
                return False
            self.stop()
            return True
        finally:
            self.lock.release()

    def stop(self):
        proc, self.proc, self.model_id, self.url, self.loaded_at = self.proc, None, None, None, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _prime(self, deadline):
        """One tiny request so the model is truly loaded (weights read from disk, graphics card warmed) before anyone waits on it. Best effort."""
        try:
            req = urllib.request.Request(self.url + "/completion", data=json.dumps({"prompt": "Hi", "n_predict": 1, "temperature": 0}).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=max(5, deadline - time.monotonic())) as r:
                r.read()
        except (urllib.error.URLError, OSError, ValueError):
            pass

    def remember(self, model_id, ctx):
        if self.memo:
            try:
                with open(self.memo, "w", encoding="utf-8") as f:
                    json.dump({"model": model_id, "ctx": ctx}, f)
            except OSError:
                pass

    def warm_last(self):
        """Load, in the background, the model that was in use before the last stop, so the first message after a restart is quick."""
        try:
            with open(self.memo, encoding="utf-8") as f:
                last = json.load(f)
            mid, ctx = str(last["model"]), int(last["ctx"])
        except (OSError, ValueError, KeyError, TypeError):
            return False
        if not self.available(mid):
            return False
        threading.Thread(target=lambda: self._quiet_ensure(mid, ctx), daemon=True).start()
        return True

    def _quiet_ensure(self, mid, ctx):
        try:
            self.ensure(mid, ctx)
        except Exception:                                        # noqa: BLE001 - a failed head start costs nothing but the head start
            pass

    def ensure(self, model_id, ctx, cancel=None):
        """The URL of a llama-server running this model with at least `ctx` tokens of memory. Starts it if needed.
        `cancel()` is asked while it loads: when it says yes the half-loaded server is stopped and Cancelled is raised."""
        with self.lock:
            self.last_used = time.time()
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
            began = time.monotonic()
            deadline = began + self.timeout
            while time.monotonic() < deadline:
                if cancel and cancel():
                    self.stop()
                    raise Cancelled()
                if self.proc.poll() is not None:
                    self.stop()
                    raise AppError("The model stopped while loading.", "Check that the .gguf file is complete and fits in memory.")
                try:
                    with urllib.request.urlopen(self.url + "/health", timeout=2) as r:
                        if json.loads(r.read() or b"{}").get("status", "ok") == "ok":
                            self._prime(deadline)                 # health says "ready" before the weights are really in memory: the first word would then wait for them
                            took = time.monotonic() - began
                            if took > 15:                      # a slow load is worth a line in the log: it is what makes the first answer late
                                print(f"(loading {model_id} took {took:.0f} s; switching models reloads it each time)", flush=True)
                            self.remember(model_id, ctx)
                            self.loaded_at = self.last_used = time.time()
                            return self.url
                except (urllib.error.URLError, OSError, ValueError):
                    pass                                         # still loading (llama-server answers 503 until ready)
                time.sleep(0.25)
            self.stop()
            raise AppError("The model took too long to load.", "Try a smaller model or check the memory it needs.")


def gpu_note(llama_bin, extra_args):
    """One plain line at start-up saying whether the models will use the graphics card, or None when it looks fine."""
    args = [str(a) for a in (extra_args or [])]
    path = str(llama_bin or "")
    gpu = any(a in ("-ngl", "--n-gpu-layers", "--gpu-layers") or a.startswith(("-ngl=", "--n-gpu-layers=")) for a in args)
    low = path.lower()
    if re.search(r"(^|[\\/_.-])cpu([\\/_.-]|$)", low):
        return ("This llama-server looks like a CPU-only build (its path says cpu), so every model runs on the processor and answers can take minutes. "
                "Use the CUDA build instead and add --llama-args \"-ngl 99\".")
    if not gpu:
        return ("No graphics-card option was given. Many llama-server builds then use the processor only, which is slow. "
                "Add --llama-args \"-ngl 99\" to use the graphics card (Apogee 2 may need a smaller number such as -ngl 40 if it does not fit).")
    return None


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
BACKUP_NAME = re.compile(r"emvryx-\d{4}-\d{2}-\d{2}-\d{4}\.zip")


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
        self.libraries = {}                                    # person -> documents.Library (files they added)
        self.saved = {}                                        # person -> saved_notes.SavedNotes (approved notes, usable offline)
        self.memories = {}                                     # person -> user_memory.Memory (facts about them, shared by every model)
        self.previews = code_preview.Previews()               # short-lived tokens for the live preview of a project
        self.lookups = {}                                      # (person, chat, message id) -> the notes that answer used, for the thumbs up
        self.wiki = None                                       # the local Wikipedia index (wiki_index.WikiIndex), if there is one
        self.live_net = None                                   # live_data.Net (tests pass a fake)
        self.default_place = ""                                # the weather place (--weather-place), also used for air quality
        self.web_fn = None                                     # web(question, k) -> notes; None = this server never searches the web
        self._warm_target, self._warm_thread, self._warm_lock = None, None, threading.Lock()
        self.vision = None                                     # vision.VisionHelper: describes pictures for the models (None = only the words in a picture are read)
        self._demo_tok = None
        self.usage = U.UsageStore(os.path.join(data_dir, "usage.db") if data_dir else ":memory:")
        self.limiter = U.Limiter(self.usage, self.cfg, self.manifest)
        self.stores, self.stops, self.settings = {}, {}, {}
        self._api_hits = {}                                    # app name -> times of its recent API calls (the per-minute limit)
        self._load_settings()
        self.lock = threading.Lock()
        self.auth = auth.AuthDB(os.path.join(data_dir, "auth.db") if data_dir else ":memory:")
        self.rl = auth.RateLimiter()                           # per-address sliding windows (sign-in failures, email codes)
        self.security = self._load_security()
        self.auth.prune()
        self.mailer = mailer.from_env()                        # None until EMVRYX_SMTP_* is set: email sign-in is then off
        self._mfa_pending, self.mfa_tickets = {}, {}              # person -> the authenticator secret being set up; ticket hash -> a sign-in waiting for its code
        self._fresh = {}                                       # key hash -> the key, ONLY for keys made in this run (so they can be shown once)
        self._users_mtime = 0
        self.users = self._load_users()
        self.code = code_sessions.CodeManager(data_dir, quotas=code_sandbox.Quotas(self.security))       # VryxCode sessions (projects live under <data>/code/)
        self.secrets = secret_box.SecretBox(data_dir, require=self.security["require_encryption"])
        self.github = github_link.Store(data_dir, self.secrets)  # connected GitHub accounts (tokens encrypted, files mode 600)
        self.models_pub = model_publish.ModelPublisher(os.path.join(data_dir, "models_state.json") if data_dir else None, None, guard=self.guard_ok)
        self.flags = flags.Flags(os.path.join(data_dir, "flags.json") if data_dir else None)
        self.models_pub.flags = self.flags
        self.guard_sheet = os.path.join(HERE, "eval", "everyday.jsonl")            # the safety checks a new model must pass before it can be published
        self.guards = model_guard.GuardStore(os.path.join(data_dir, "guard") if data_dir else None)
        self.guard_run, self._guard_lock = None, threading.Lock()    # which new features each kind of person can see (Settings > Owner > Features and testing)
        self.shares = shares.Shares(os.path.join(data_dir, "shares.db") if data_dir else ":memory:")   # read-only links to a copy of a chat (the owner switches sharing on)
        self.feedback = feedback.Feedback(os.path.join(data_dir, "feedback.db") if data_dir else ":memory:")   # "That didn't work" reports, for the owner
        self.links = app_links.Hub(app_links.Store(data_dir, self.secrets))   # the other connected apps (a token, link or app password; read-only)
        self.apply_cloud()
        self.metrics = {"errors": 0, "started": time.time()}
        self._alerted = {}
        self.mail_async = True                                  # send the sign-in email in the background so the answer takes the same time for every address
        self.github_device = {}                                 # person -> the sign-in in progress (its device code never leaves the server)
        self.github_http = None                                 # tests: http(method, url, headers, body) -> (status, json)
        self.google_http = google_signin.default_http           # tests: http(method, url, data) -> (status, json)
        self.pk_pending = {}                                    # passkeys: challenge hash -> {kind, user, expires}
        self.oauth_pending = {}                                 # "Continue with Google": state -> {verifier, invite, expires}
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
            self.usage.add_user(u["user"], u["tier"], u.get("tz_minutes", 0), owner=bool(u.get("owner") or u.get("unlimited")))

    def _entries(self, name):
        return [k for k, u in self.users.items() if u["user"] == name]

    def user_record(self, name):
        return next((u for u in self.users.values() if u["user"] == name), None)

    def add_user(self, name, tier, tz_minutes=0, email=None, key_prefix=""):
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
        key = key_prefix + secrets.token_urlsafe(24)
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
        rec = dict(self.users[found[0]])
        key = (API_KEY_PREFIX if rec.get("app") else "") + secrets.token_urlsafe(24)
        new = "h:" + auth.digest(key)
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
        admin = bool(row["owner"] or entry.get("admin"))
        granters = {auth.clean_email(e) for e in (self.security.get("grant_emails") or []) if auth.clean_email(e)}
        # who may give out plans, no-limits and admin rights: the PC owner, and an account that was made an admin by the PC owner AND has one of these emails
        granter = bool(entry.get("owner")) or bool(entry.get("admin") and auth.clean_email(entry.get("email") or "") in granters)
        return {"user": entry["user"], "owner": row["owner"], "admin": admin, "founder": bool(entry.get("owner")), "granter": granter,
                "tier": row["tier"], "banned": bool(entry.get("banned")), "app": bool(entry.get("app")),
                "email": entry.get("email"), "has_password": bool(entry.get("pw")), "mfa": bool((entry.get("mfa") or {}).get("on"))}

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
        return next((u for u in self.users.values() if email and u.get("email") == email and u.get("email_verified") is not False), None)

    def set_access(self, name, plan=None, unlimited=None, admin=None):
        """Change one person's plan, whether they have no limits, and whether they have admin rights. The first owner account is never changed here."""
        rec = self.user_record(name)
        if not rec:
            raise ValueError("no one is called that")
        if rec.get("owner"):
            raise ValueError("the first owner account always has full rights; change another account")
        fields = {}
        if plan is not None:
            if plan not in self.cfg["tiers"]:
                raise ValueError("choose " + ", ".join(self.cfg["tiers"]))
            fields["tier"] = plan
        if unlimited is not None:
            fields["unlimited"] = bool(unlimited)
        if admin is not None:
            fields["admin"] = bool(admin)
        self._set_fields(name, **fields)
        row = self.usage.get_user(name)
        now = self.user_record(name)
        self.usage.add_user(name, now["tier"], row["tz_minutes"], bool(now.get("unlimited")), row["overrides"])
        self.auth.event("access_changed", name, "", f"plan={now['tier']} unlimited={bool(now.get('unlimited'))} admin={bool(now.get('admin'))}")
        return {"user": name, "plan": now["tier"], "unlimited": bool(now.get("unlimited")), "admin": bool(now.get("admin"))}

    def set_ban(self, name, banned):
        rec = self.user_record(name)
        if not rec:
            raise ValueError("no one is called that")
        if (rec.get("owner") or rec.get("admin") or rec.get("unlimited")) and banned:
            raise ValueError("an owner or admin account cannot be turned off here")
        for k in self._entries(name):
            self.users[k]["banned"] = bool(banned)
        self._save_users()
        if banned:
            self.auth.revoke_user(name)
        self.auth.event("ban" if banned else "unban", name, "", "")

    def create_email_account(self, email):
        """A free account for an address that proved it owns it (only when open signups are on)."""
        email = auth.clean_email(email)
        base = re.sub(r"[^A-Za-z0-9_-]", "", email.split("@")[0])[:24]
        if not accounts.clean_name(base):                       # too short, or a name nobody should be able to pick (admin, support...)
            base = (base + "user")[:24]
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

    # ---- passwords, MFA, sign-up
    # Kept in the person's users.json entry: "pw" (a scrypt hash) and "mfa" {"secret" (encrypted), "on", "last" (last time step used), "recovery" [hashes]}.
    def _set_fields(self, name, **fields):
        for k in self._entries(name):
            self.users[k].update(fields)
        self._save_users()

    def find_login(self, ident):
        """The account a sign-in name or email points to (a name, or a verified email), or None."""
        ident = str(ident or "").strip()
        if "@" in ident:
            return self.user_by_email(ident)
        ident = re.sub(r"\s+", "_", ident)                                       # a name typed with a space is the name with an underscore
        return next((u for u in self.users.values() if u["user"].lower() == ident.lower()), None)

    def find_account(self, ident):
        """Like find_login, but an email also matches when it was never verified (for the owner's own tools, never for signing in)."""
        ident = str(ident or "").strip()
        if "@" in ident:
            em = auth.clean_email(ident)
            return next((u for u in self.users.values() if em and u.get("email") == em), None)
        return self.find_login(ident)

    def check_password(self, ident, password):
        """The account when the password is right, else None (a missing account costs the same time as a wrong password)."""
        rec = self.find_login(ident)
        if not rec or not rec.get("pw"):
            accounts.burn_time(password)
            return None
        return rec if accounts.verify_password(password, rec["pw"]) else None

    def set_password(self, name, password):
        problem = accounts.password_problem(password, name, (self.user_record(name) or {}).get("email", ""))
        if problem:
            raise ValueError(problem)
        self._set_fields(name, pw=accounts.hash_password(password))
        self.auth.event("password_set", name, "", "")

    def mfa_on(self, name):
        rec = self.user_record(name)
        return bool(rec and (rec.get("mfa") or {}).get("on"))

    def mfa_info(self, name):
        m = (self.user_record(name) or {}).get("mfa") or {}
        return {"on": bool(m.get("on")), "recovery_left": len(m.get("recovery") or [])}

    def mfa_begin(self, name):
        """A fresh secret for the person to add to their authenticator app. It is not active until a code from the app proves it works."""
        secret = accounts.new_secret()
        self._mfa_pending[name] = {"secret": secret, "expires": time.time() + 900}
        rec = self.user_record(name) or {}
        account = rec.get("email") or name
        return {"secret": accounts.group_secret(secret), "uri": accounts.otpauth_uri(account, secret)}

    def mfa_enable(self, name, code):
        """The 8 recovery codes (shown once) when `code` from the app matches the pending secret, else None."""
        pend = self._mfa_pending.get(name)
        if not pend or pend["expires"] < time.time():
            return None
        counter = accounts.check_totp(pend["secret"], code)
        if counter is None:
            return None
        codes = accounts.make_recovery_codes()
        self._set_fields(name, mfa={"secret": self.secrets.encrypt(pend["secret"]), "on": True, "last": counter,
                                    "recovery": [accounts.hash_recovery(c) for c in codes]})
        self._mfa_pending.pop(name, None)
        self.auth.event("mfa_on", name, "", "")
        return codes

    def mfa_disable(self, name):
        self._set_fields(name, mfa={})
        self.auth.event("mfa_off", name, "", "")

    def mfa_new_recovery(self, name):
        rec = self.user_record(name)
        m = dict((rec or {}).get("mfa") or {})
        if not m.get("on"):
            raise ValueError("Turn on two-step sign-in first.")
        codes = accounts.make_recovery_codes()
        m["recovery"] = [accounts.hash_recovery(c) for c in codes]
        self._set_fields(name, mfa=m)
        self.auth.event("mfa_recovery_new", name, "", "")
        return codes

    def mfa_check(self, name, code):
        """True when `code` is a right authenticator code (not used before) or an unused recovery code."""
        if self.rl.blocked("mfa:" + name, 10, 600):
            return False
        rec = self.user_record(name)
        m = dict((rec or {}).get("mfa") or {})
        if not m.get("on"):
            return False
        secret = self.secrets.decrypt(m.get("secret"))
        counter = accounts.check_totp(secret, code, m.get("last", 0)) if secret else None
        if counter is not None:
            m["last"] = counter
            self._set_fields(name, mfa=m)
            return True
        used, left = accounts.use_recovery(m.get("recovery") or [], code)
        if used:
            m["recovery"] = left
            self._set_fields(name, mfa=m)
            self.auth.event("mfa_recovery_used", name, "", f"{len(left)} left")
            return True
        self.rl.hit("mfa:" + name)
        return False

    def mfa_ticket(self, name, how):
        """A short-lived ticket that says 'the first step of signing in is done': the second step (a code) trades it for a session."""
        now = time.time()
        for k in [k for k, v in self.mfa_tickets.items() if v["expires"] < now]:
            self.mfa_tickets.pop(k, None)
        while len(self.mfa_tickets) > 500:
            self.mfa_tickets.pop(next(iter(self.mfa_tickets)))
        ticket = secrets.token_urlsafe(24)
        self.mfa_tickets[auth.digest(ticket)] = {"user": name, "how": how, "expires": now + 300, "tries": 0}
        return ticket

    def mfa_finish(self, ticket, code):
        """(name, how) when the ticket is live and the code is right; otherwise None. A ticket allows 5 wrong codes."""
        t = self.mfa_tickets.get(auth.digest(ticket or ""))
        if not t or t["expires"] < time.time():
            return None
        if self.mfa_check(t["user"], code):
            self.mfa_tickets.pop(auth.digest(ticket), None)
            return t["user"], t["how"]
        t["tries"] += 1
        if t["tries"] >= 5:
            self.mfa_tickets.pop(auth.digest(ticket), None)
        return None

    # ---- passkeys (WebAuthn): kept in the person's users.json entry as "passkeys": [{id, alg, pem, counter, name, created}]
    def passkey_list(self, name):
        return [{"id": p["id"], "name": p.get("name", "Passkey"), "created": p.get("created")} for p in (self.user_record(name) or {}).get("passkeys", [])]

    def passkey_challenge(self, kind, user=""):
        now = time.time()
        for k in [k for k, v in self.pk_pending.items() if v["expires"] < now]:
            self.pk_pending.pop(k, None)
        while len(self.pk_pending) > 300:
            self.pk_pending.pop(next(iter(self.pk_pending)))
        challenge = passkeys.b64u(secrets.token_bytes(32))
        self.pk_pending[auth.digest(challenge)] = {"kind": kind, "user": user, "expires": now + 300}
        return challenge

    def passkey_take(self, challenge, kind, user=None):
        """Use up a challenge (each works once): True when it was issued by us, for this purpose (and this person)."""
        p = self.pk_pending.pop(auth.digest(challenge or ""), None)
        return bool(p and p["kind"] == kind and p["expires"] >= time.time() and (user is None or p["user"] == user))

    def passkey_add(self, name, pk, label):
        rec = self.user_record(name) or {}
        keep = [p for p in rec.get("passkeys", []) if p["id"] != pk["id"]][:9]
        self._set_fields(name, passkeys=keep + [dict(pk, name=str(label)[:40] or "Passkey", created=int(time.time()))])
        self.auth.event("passkey_added", name, "", str(label)[:40])

    def passkey_remove(self, name, cred_id):
        rec = self.user_record(name) or {}
        left = [p for p in rec.get("passkeys", []) if p["id"] != cred_id]
        if len(left) == len(rec.get("passkeys", [])):
            return False
        self._set_fields(name, passkeys=left)
        self.auth.event("passkey_removed", name, "", "")
        return True

    def passkey_find(self, cred_id):
        for u in self.users.values():
            for p in u.get("passkeys", []):
                if p["id"] == cred_id:
                    return u, p
        return None, None

    # ---- the cloud machine for VryxCode (SSH)
    def cloud_paths(self):
        d = self.data_dir or os.path.join(HERE, ".emvryx")
        return os.path.join(d, "cloud_key"), os.path.join(d, "cloud_known_hosts")

    def apply_cloud(self):
        key, known = self.cloud_paths()
        host = str(os.environ.get("EMVRYX_CLOUD_HOST") or self.security.get("cloud_host") or "").strip()
        self.code.cloud = ({"host": host, "port": int(os.environ.get("EMVRYX_CLOUD_PORT") or self.security.get("cloud_port") or 22),
                            "user": str(os.environ.get("EMVRYX_CLOUD_USER") or self.security.get("cloud_user") or "root"), "key": os.environ.get("EMVRYX_CLOUD_KEY") or key,
                            "known_hosts": known, "for_others": bool(self.security.get("cloud_for_others"))} if host else None)

    def cloud_status(self):
        key, known = self.cloud_paths()
        pub = ""
        try:
            with open(key + ".pub", encoding="utf-8") as f:
                pub = f.read().strip()
        except OSError:
            pass
        c = self.code.cloud or {}
        return {"host": c.get("host", ""), "port": c.get("port", 22), "user": c.get("user", "root"), "for_others": bool(c.get("for_others")), "key_made": os.path.exists(key),
                "public_key": pub, "ssh_found": bool(shutil.which("ssh")), "keygen_found": bool(shutil.which("ssh-keygen")), "ready": self.code.cloud_ready(True)[0],
                "why_not": "" if self.code.cloud_ready(True)[0] else self.code.cloud_ready(True)[1], "from_env": bool(os.environ.get("EMVRYX_CLOUD_HOST"))}

    def google_on(self):
        return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))

    def signup_mode(self):
        return self.security.get("signup_mode") if self.security.get("signup_mode") in ("closed", "invite", "open") else "closed"

    def save_security(self, **changes):
        """Change a setting in security.json (and keep it for the next start)."""
        clean = {k: v for k, v in changes.items() if k in SECURITY_DEFAULTS}
        self.security.update(clean)
        if self.data_dir:
            path = os.path.join(self.data_dir, "security.json")
            try:
                with open(path, encoding="utf-8") as f:
                    saved = json.load(f)
            except (OSError, ValueError):
                saved = {}
            saved.update(clean)
            fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(saved, f, indent=2)
            os.replace(path + ".tmp", path)

    def create_account(self, name, email, password, tier="free"):
        """A person who signed up with a name, an email and a password. Raises ValueError with a sentence the person can read."""
        name = accounts.clean_name(name)
        if not name:
            raise ValueError("A name is 3 to 32 letters, numbers, - or _ (spaces become _), and not a reserved word like admin.")
        email = auth.clean_email(email)
        if not email:
            raise ValueError("That does not look like an email address.")
        problem = accounts.password_problem(password, name, email)
        if problem:
            raise ValueError(problem)
        if self.user_record(name) or any(u["user"].lower() == name.lower() for u in self.users.values()):
            raise ValueError("That name is taken. Try another.")
        if any(u.get("email") == email for u in self.users.values()):
            raise ValueError("There is already an account with that email. Sign in instead.")
        entry = {"user": name, "tier": tier, "owner": False, "tz_minutes": 0, "email": email, "email_verified": False,
                 "pw": accounts.hash_password(password), "created": int(time.time())}
        self.users["e:" + name] = entry
        self._save_users()
        self._ensure_usage_user(entry)
        self.set_plan(name, tier)
        self.auth.event("signup", name, "", "password")
        return name

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

    def docs_for(self, user):
        with self.lock:
            if user not in self.libraries:
                path = os.path.join(self.data_dir, f"docs-{user}.db") if self.data_dir else ":memory:"
                self.libraries[user] = documents.Library(path, clock=self.clock)
            return self.libraries[user]

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

    def _load_settings(self):
        """Each person's settings are kept in settings.json, so a restart does not put them back to the defaults."""
        if not self.data_dir:
            return
        try:
            with open(os.path.join(self.data_dir, "settings.json"), encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.settings = {k: v for k, v in data.items() if isinstance(v, dict)}
        except (OSError, ValueError):
            pass

    def _save_settings(self):
        if not self.data_dir:
            return
        path = os.path.join(self.data_dir, "settings.json")
        try:
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(self.settings, f)
            os.replace(path + ".tmp", path)
        except OSError:
            pass

    def get_settings(self, user):
        s = {"window_mode": "everyday", "show_tokens": False, "web_search": "auto", "memory": True, "thinking_pause": "short", "live_data": True, "connected_apps": True, "tour_seen": 0, "tour_devices": {}, "whats_new_seq": -1}
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
        if isinstance(new.get("live_data"), bool):
            s["live_data"] = new["live_data"]
        if isinstance(new.get("custom_instructions"), str):
            s["custom_instructions"] = " ".join(new["custom_instructions"].split())[:app_skills.MAX_CUSTOM]
        if isinstance(new.get("connected_apps"), bool):
            s["connected_apps"] = new["connected_apps"]
        if new.get("web_search") in lookup_auto.MODES:
            s["web_search"] = new["web_search"]
        if isinstance(new.get("whats_new_seq"), int) and not isinstance(new.get("whats_new_seq"), bool):
            s["whats_new_seq"] = max(0, min(10 ** 6, new["whats_new_seq"]))
        if isinstance(new.get("tour_seen"), int) and not isinstance(new.get("tour_seen"), bool):
            n = max(0, min(1000, new["tour_seen"]))
            s["tour_seen"] = n
            if new.get("device") in ("desktop", "pwa", "mobile"):          # the tour shows once on each kind of device: a computer, the installed app, a phone's browser
                s["tour_devices"] = dict(s.get("tour_devices") or {}, **{new["device"]: n})
        self.settings[user] = s
        self._save_settings()
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
            m["state"], m["badge"] = "ready", "Preview" if m.get("preview") else "Beta" if m["status"] == "beta" else "Ready"
        m["older"] = False
        return m

    def catalog(self, who):
        """The picker: one card per name (Flare, Equinox, Solstice, Apogee) with its newest usable version, and
        "other" with the older versions that can still be chosen (Flare 2.5, ...)."""
        cards, other = [], []
        self.models_pub.run_due(self.manifest)                                  # a scheduled model that is due goes live now
        keep = int(self.manifest.get("keep_older_versions", 6))
        for name in M.NAMES:
            eff = [dict(m, status=self.models_pub.status_of(m), preview=(m["status"] == "preview" and not self.models_pub.live(m["id"]))) for m in self.manifest["models"] if m["name"] == name]
            versions = sorted((m for m in eff if m["status"] != "off" and (not m["preview"] or who.get("admin"))), key=lambda m: -m["version"])
            if not versions:
                continue
            usable = [m for m in versions if m["status"] != "planned"]
            top = (usable or versions)[0]
            cards.append(self._card(top, who))
            for m in usable[1:1 + keep]:
                c = self._card(m, who)
                c["older"] = True
                other.append(c)
        return {"cards": cards, "other": other}

    # ---- apps that use Emvryx through the API (POST /api/v1/ask): each one is a key-only account, never a person who signs in
    APP_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{1,27}")
    LOOKUP_MODES = {"none": "none", "wikipedia": "off", "auto": "auto"}          # what an app's questions may be looked up in ("none": nothing leaves this PC)

    def add_app(self, slug, display, tier="free", instructions="", rpm=20, model="flare", effort="balanced", lookup="none"):
        """Make an app and return its key (shown once, never stored). The app's name in the logs is app-<slug>."""
        slug = str(slug or "").strip().lower()
        if not self.APP_SLUG.fullmatch(slug):
            raise ValueError("an app's name is lowercase letters, numbers and - (2 to 28 characters), for example finance")
        if lookup not in self.LOOKUP_MODES:
            raise ValueError("lookup is none, wikipedia or auto")
        name = APP_PREFIX + slug
        key = self.add_user(name, tier, key_prefix=API_KEY_PREFIX)
        if key is None:
            raise ValueError("an app with that name already exists")
        self._set_fields(name, app=True, app_name=(str(display or slug).strip() or slug)[:60], app_instructions=" ".join(str(instructions or "").split())[:2000],
                         app_rpm=max(1, min(600, int(rpm))), app_model=str(model or "flare")[:40], app_effort=effort if effort in ("auto", "quick", "balanced", "deep") else "balanced",
                         app_enabled=True, app_created=int(time.time()), app_lookup=lookup)
        self.put_settings(name, {"memory": False, "live_data": False, "connected_apps": False, "web_search": "none", "custom_instructions": ""})
        self.auth.event("app_added", name, "", f"plan {tier}")
        return key

    def app_record(self, name):
        rec = self.user_record(name)
        return rec if rec and rec.get("app") else None

    def update_app(self, name, **ch):
        rec = self.app_record(name)
        if not rec:
            raise ValueError("no such app")
        fields = {}
        if "display" in ch:
            fields["app_name"] = (str(ch["display"]).strip() or name)[:60]
        if "instructions" in ch:
            fields["app_instructions"] = " ".join(str(ch["instructions"]).split())[:2000]
        if "rpm" in ch:
            fields["app_rpm"] = max(1, min(600, int(ch["rpm"])))
        if "model" in ch:
            fields["app_model"] = str(ch["model"])[:40]
        if "effort" in ch and ch["effort"] in ("auto", "quick", "balanced", "deep"):
            fields["app_effort"] = ch["effort"]
        if "enabled" in ch:
            fields["app_enabled"] = bool(ch["enabled"])
        if "lookup" in ch:
            if ch["lookup"] not in self.LOOKUP_MODES:
                raise ValueError("lookup is none, wikipedia or auto")
            fields["app_lookup"] = ch["lookup"]
            self.put_settings(name, {"web_search": self.LOOKUP_MODES[ch["lookup"]]})
        if "plan" in ch:
            self.set_plan(name, ch["plan"])
        if fields:
            self._set_fields(name, **fields)

    def apps(self):
        out = []
        for u in self.users.values():
            if not u.get("app") or u.get("internal"):
                continue
            row = self.usage.get_user(u["user"])
            out.append({"name": u["user"], "slug": u["user"][len(APP_PREFIX):], "display": u.get("app_name") or u["user"], "plan": row["tier"], "enabled": u.get("app_enabled", True),
                        "instructions": u.get("app_instructions", ""), "rpm": u.get("app_rpm", 20), "model": u.get("app_model", "flare"), "effort": u.get("app_effort", "balanced"),
                        "lookup": u.get("app_lookup", "none"), "created": u.get("app_created"), "last_used": u.get("app_last_used"), "calls": u.get("app_calls", 0)})
        return sorted(out, key=lambda a: a["slug"])

    def app_rate_ok(self, name, rpm, now=None):
        """A sliding minute per app: True if this call may go ahead (and records it), else the seconds to wait."""
        now = time.time() if now is None else now
        with self.lock:
            hits = [t for t in self._api_hits.get(name, []) if now - t < 60]
            if len(hits) >= rpm:
                self._api_hits[name] = hits
                return False, max(1, int(60 - (now - hits[0])) + 1)
            hits.append(now)
            self._api_hits[name] = hits
        return True, 0

    def note_app_call(self, name):
        rec = self.user_record(name)
        if rec:
            self._set_fields(name, app_last_used=int(time.time()), app_calls=int(rec.get("app_calls", 0)) + 1)

    # ---- the graphics card: idle unload and Gaming mode
    def gaming_file(self):
        return os.path.join(self.data_dir, "gaming.flag") if self.data_dir else None

    def sync_gaming(self):
        """Gaming mode is on when the switch says so OR the file gaming.flag exists in the data folder (so a shortcut on the desktop can switch it with no key)."""
        f = self.gaming_file()
        if f:
            self.cfg["gaming"] = os.path.exists(f) or bool(self.cfg.get("gaming_mem"))
        return bool(self.cfg.get("gaming"))

    def set_gaming(self, on, by=""):
        """Switch Gaming mode. On: nobody can start a reply, and the model is unloaded now (or as soon as the replies running finish)."""
        on = bool(on)
        f = self.gaming_file()
        self.cfg["gaming_mem"] = on
        if f:
            try:
                if on:
                    with open(f, "w", encoding="utf-8") as h:
                        h.write("Emvryx is paused for gaming. Delete this file (or use Admin > PC) to turn it off.\n")
                elif os.path.exists(f):
                    os.remove(f)
            except OSError:
                pass
        self.cfg["gaming"] = on
        unloaded = self.unload_model("gaming mode") if on else False
        self.auth.event("gaming_mode", by or "owner", "", "on" if on else "off")
        return {"gaming": on, "unloaded": unloaded, "loaded": self.runner.loaded() if self.runner else None}

    def busy(self):
        """True while a reply or a coding session is using the model."""
        return bool(self.stops or self.code.any_running())

    def unload_model(self, why=""):
        """Stop the loaded model if nothing is using it. True if it was stopped."""
        if not self.runner or self.busy():
            return False
        stopped = self.runner.unload()
        if stopped:
            self.auth.event("model_unloaded", "system", "", why)
            print(f"(model unloaded: {why})", flush=True)
        return stopped

    def idle_tick(self, now=None):
        """Called every few seconds by a background thread: honour Gaming mode, and unload a model nobody has used for `idle_unload_minutes`."""
        if not self.runner:
            return None
        now = time.time() if now is None else now
        if self.busy():
            self.runner.touch()
            return None
        if self.sync_gaming():
            return "gaming" if self.unload_model("gaming mode") else None
        minutes = int(self.security.get("idle_unload_minutes") or 0)
        if minutes > 0 and self.runner.loaded() and now - self.runner.last_used >= minutes * 60:
            return "idle" if self.unload_model(f"idle for {minutes} minutes") else None
        return None

    def pc_status(self):
        r = self.runner
        loaded = r.loaded() if r else None
        model = next((m for m in self.manifest["models"] if m["id"] == loaded), None) if loaded else None
        return {"gaming": bool(self.cfg.get("gaming")), "has_runner": bool(r), "loaded": loaded, "loaded_label": (f"{model['name']} {model['version']:g}" if model else None),
                "idle_seconds": int(time.time() - r.last_used) if (r and loaded) else None, "idle_unload_minutes": int(self.security.get("idle_unload_minutes") or 0),
                "busy": self.busy()}

    # ---- the safety checks a new model must pass before it is published (model_guard.py)
    GUARD_USER = "emvryx-guard"

    def _model_fingerprint(self, model_id):
        path = (self.runner.files.get(model_id) if self.runner else None) or ""
        try:
            st = os.stat(path)
            return f"{st.st_size}-{int(st.st_mtime)}"
        except OSError:
            return ""

    def guard_ok(self, model_id):
        """(True, "") when this model's latest safety checks passed (and the model file has not changed since); otherwise (False, why)."""
        rec = self.guards.load(model_id)
        if not rec:
            return False, "Run the safety checks first (Admin > Models > Run safety checks): a new model must pass them before it is published."
        if rec.get("fingerprint") and rec["fingerprint"] != self._model_fingerprint(model_id):
            return False, "The model file changed after the safety checks: run them again."
        if not rec["passed"]:
            return False, "The safety checks did not pass: " + "; ".join(rec["reasons"]) + "."
        return True, ""

    def _guard_who(self):
        """An internal account with no limits that asks the check questions (it sees models in preview, keeps no memory and never searches the web)."""
        if not self.user_record(self.GUARD_USER):
            self.add_user(self.GUARD_USER, "mega", key_prefix=API_KEY_PREFIX)
            self._set_fields(self.GUARD_USER, app=True, internal=True, app_enabled=True)
            self.set_access(self.GUARD_USER, unlimited=True)
            self.put_settings(self.GUARD_USER, {"memory": False, "live_data": False, "connected_apps": False, "web_search": "none", "custom_instructions": ""})
        return self.who_name(self.GUARD_USER)

    def ask_quietly(self, who, model_id, prompt, effort="balanced", timeout=420):
        """(reply, error) for one question through the whole app, in a private chat that is thrown away."""
        store = self.store(who["user"])
        cid = store.new_chat(private=True)
        try:
            q, stop, model, win, decision = start_turn(self, who, cid, prompt, model_id, effort, pace=False)
        except Exception as e:                                 # noqa: BLE001
            store.delete_chat(cid)
            return "", str(error_payload(e)[2].get("message", "error"))
        try:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    kind, val = q.get(timeout=1)
                except queue.Empty:
                    if time.monotonic() > deadline:
                        stop.set()
                        return "", "took too long"
                    continue
                if kind == "done":
                    return (val.get("text") or "").strip(), None
                if kind == "error":
                    return "", str(error_payload(val)[2].get("message", "error"))
        finally:
            store.delete_chat(cid)

    def start_guard(self, model_id, by=""):
        """Run the safety checks on a model in the background (one at a time). Raises ValueError when they cannot start."""
        model = next((m for m in self.manifest["models"] if m["id"] == model_id), None)
        if not model or model["status"] in ("off", "planned"):
            raise ValueError("no such model")
        if self.cfg.get("gaming"):
            raise ValueError("Gaming mode is on: turn it off first, the checks need the model loaded")
        if self.runner and not self.runner.available(model_id):
            raise ValueError("That model's file is not on this computer yet.")
        with self._guard_lock:
            if self.guard_run and self.guard_run["state"] == "running":
                raise ValueError("The checks are already running for " + self.guard_run["model_id"])
            tests = model_guard_tests(self.guard_sheet)
            run = {"model_id": model_id, "state": "running", "i": 0, "n": len(tests), "started": time.time()}
            self.guard_run = run
        who = self._guard_who()
        older_id = None
        olds = self.models_pub._older(self.manifest, model)
        if olds:
            older_id = olds[0]["id"]

        def work():
            import quality_check
            results = []
            try:
                for i, t in enumerate(tests):
                    reply, error = self.ask_quietly(who, model_id, t["prompt"])
                    results.append({"prompt": t["prompt"], "category": t["category"], "ok": bool(not error and quality_check.check(t, reply)), "reply": reply[:600], "error": error})
                    run["i"] = i + 1
                    if i == 2 and all(r["error"] for r in results):          # the first three could not even be asked: do not keep going
                        break
                older = self.guards.load(older_id) if older_id else None
                older_label = next((f"{m['name']} {m['version']:g}" for m in self.manifest["models"] if m["id"] == older_id), "")
                passed, reasons, summary = model_guard.judge(results, older["summary"] if older else None, older_label)
                self.guards.save(model_id, {"model_id": model_id, "when": time.time(), "by": by, "passed": passed, "reasons": reasons, "summary": summary, "results": results,
                                           "fingerprint": self._model_fingerprint(model_id)})
                self.auth.event("model_checks", by or "owner", "", f"{model_id}: {'passed' if passed else 'failed'} {summary['percent']:g}%")
            except Exception as e:                                           # noqa: BLE001
                print(f"(safety checks for {model_id} stopped: {e})", flush=True)
            finally:
                run["state"] = "done"
        threading.Thread(target=work, daemon=True).start()
        return {"started": True, "n": len(tests)}

    def models_admin(self):
        """The Models tab: every model in the family, whether it is in preview or live, what a publish would replace, and the model releases so far."""
        mp, out = self.models_pub, []
        mp.run_due(self.manifest)
        for name in M.NAMES:
            for m in sorted((x for x in self.manifest["models"] if x["name"] == name and x["status"] not in ("off", "planned")), key=lambda x: -x["version"]):
                preview = m["status"] == "preview" and not mp.live(m["id"])
                olds = mp._older(self.manifest, m)
                out.append({"id": m["id"], "name": m["name"], "version": m["version"], "label": f"{m['name']} {m['version']:g}", "tagline": m.get("tagline", ""), "preview": preview,
                            "scheduled": mp.scheduled(m["id"]), "live": mp.data["live"].get(m["id"]), "replaces": f"{olds[0]['name']} {olds[0]['version']:g}" if (preview and olds) else None,
                            "available": bool(self.runner.available(m["id"])) if self.runner else True,
                            "guard": model_guard.public(self.guards.load(m["id"]), self.guard_run if (self.guard_run and self.guard_run["state"] == "running" and self.guard_run["model_id"] == m["id"]) else None),
                            "schedule_failed": mp.data["failed"].get(m["id"])})
        return {"models": out, "keep_older": int(self.manifest.get("keep_older_versions", 6)), "checks_running": bool(self.guard_run and self.guard_run["state"] == "running"),
                "releases": [r for r in self.flags.releases() if str(r.get("kind", "")).startswith("model")]}

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

    def admin_overview(self, who):
        """What the owner sees first in the Admin area: sign-up mode, invites, and a checklist of what makes this server safe to share."""
        rec = self.user_record(who["user"]) or {}
        mfa = bool((rec.get("mfa") or {}).get("on"))
        check = lambda id_, ok, title, how: {"id": id_, "ok": bool(ok), "title": title, "how": how}
        people = list({u["user"]: u for u in self.users.values()}.values())
        return {"signup_mode": self.signup_mode(), "sharing": bool(self.security.get("sharing")), "weekly_summary": bool(self.security.get("weekly_summary")), "invites": self.auth.invites(), "people": len(people), "banned": sum(1 for u in people if u.get("banned")),
                "plans": {t: sum(1 for u in people if self.usage.get_user(u["user"])["tier"] == t) for t in self.cfg["tiers"]},
                "checklist": [
                    check("password", rec.get("pw"), "Your owner account has a password", "Settings > Security > Set a password."),
                    check("mfa", mfa, "Your owner account uses two-step sign-in", "Settings > Security > Two-step sign-in."),
                    check("email", rec.get("email") and rec.get("email_verified") is not False, "Your owner account has an email address", "Settings > Account."),
                    check("encryption", self.secrets.available, "Saved tokens and two-step secrets are encrypted", "pip install cryptography, then restart."),
                    check("alerts", self.security.get("alert_ntfy_topic"), "Security alerts reach your phone", "Set alert_ntfy_topic in security.json (see docs/SECURITY.md)."),
                    check("backup", (summary.latest_backup_age_days(self, time.time()) is not None and summary.latest_backup_age_days(self, time.time()) <= 7), "A backup from the last 7 days exists", "Settings > Owner > Backups > Make a backup now."),
                    check("mail", self.mailer, "Email sign-in codes work", "Set EMVRYX_SMTP_* (see docs/DEPLOY.md). Optional.")],
                "health": self.health()}

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

    def browser_tool(self, user, project):
        """The `check_page` tool the model may call: a hidden browser opens a page of the project, clicks around and audits it (coding/browser_check.py)."""
        def check_page(path="", width=390, height=844):
            folder = self.code.project_path(user, project)
            try:
                width, height = max(240, min(1600, int(width))), max(320, min(2400, int(height)))
            except (TypeError, ValueError):
                raise harness.ToolError("width and height must be numbers (for example 390 and 844 for a phone)")
            entry = browser_check.safe_page_path(folder, path) if path else code_preview.entry_page(folder)
            if not entry:
                raise harness.ToolError("there is no web page (.html file) at that path in this project to check" if path else "this project has no web page (.html file) to check yet")
            return browser_check.format_report(browser_check.check_page(folder, entry, width, height), entry, width, height)
        return check_page

    def code_allowed(self, who):
        """(ok, why not). The owner and the admins the owner appointed always may. Others need VryxCode in their plan, and a container sandbox (or the owner
        explicitly accepting the folder sandbox for them): a person must never get to run programs on the host with only the folder sandbox between us."""
        if who["owner"] or who["admin"]:
            return True, ""
        if not self.cfg["tiers"][who["tier"]].get("vryxcode", False):
            return False, "VryxCode isn't included in your plan."
        if self.code.sandbox.get("mode") != "docker" and not self.security["code_unsandboxed_for_others"]:
            return False, "VryxCode is only open to the owner until the container sandbox is turned on."
        return True, ""

    def code_backend(self, model, cancel=None):
        """generate(messages) for a coding session on this model (the llama-server that runs it)."""
        if self.code_generate:
            return self.code_generate(model)
        if self.cfg.get("gaming"):
            raise code_sessions.CodeError("Emvryx is resting while the PC is being used for something else.", "Try again in a little while.")
        ctx = min(int(model.get("context_tested") or 8192), 32768)
        if self.runner:
            url = self.runner.ensure(model["id"], ctx, cancel=cancel)
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
        if self.sync_gaming():
            return "Gaming mode is on: not loading any model"
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

    def warm(self, who, model_id):
        """Load this model in the background (the person just picked it or opened a chat), so their next message does not wait for it. Skipped while a reply
        or a coding session is running (it would take that model away). Several quick picks only load the last one. True if a load was started or is under way."""
        if not self.runner:
            return False
        try:
            model = self.pick_model(who, model_id)
        except KeyError:
            return False
        if model["state"] != "ready" or not self.runner.available(model_id):
            return False
        if self.stops or self.code.any_running() or self.cfg.get("gaming"):
            return False
        self._warm_target = (model_id, self.window_for(who, model)["window"])
        with self._warm_lock:
            if self._warm_thread and self._warm_thread.is_alive():
                return True
            self._warm_thread = threading.Thread(target=self._warm_loop, daemon=True)
            self._warm_thread.start()
        return True

    def _warm_loop(self):
        while True:
            target, self._warm_target = self._warm_target, None
            if not target:
                return
            try:
                self.runner.ensure(*target)
            except Exception:                                    # noqa: BLE001 - a failed head start costs nothing but the head start
                pass

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
            tok = OpenTokenizer.load(path, think=model.get("think")) if model.get("open") else BPETokenizer.load(path)    # "open": a fine-tuned open model (ChatML)
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
CONTINUE_HINT = "[Your last answer was cut off because it hit the length limit. Continue it from exactly where it stopped. Do not repeat anything you already wrote, do not start over and do not apologise.]"


def start_turn(state, who, chat_id, text, model_id, effort, regenerate=False, regen_mode=None, cont=False, pace=None, extra_notes=None, extra_hint=""):
    """Begin a reply in a worker thread. Returns (queue, stop_event); the queue yields ("piece", text), then
    ("done", result) or ("error", exception). With effort "auto" the level is chosen from the message (effort_router);
    the page is told which one in `decision`. The API passes pace=False (no show of thinking), extra_notes (facts the app sends) and extra_hint (the app's instructions)."""
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
    caps = OPEN_EFFORTS if model.get("open") else EFFORTS
    max_new = min(caps[effort], max(32, window // 2), model.get("max_reply_tokens", caps[effort]))
    if mode:
        max_new = min(regen_modes.length_for(max_new, mode), max(32, window // 2))
    pause = round(chat_polish.pause_for(question, effort) * chat_polish.PAUSE_SCALE[state.get_settings(who["user"])["thinking_pause"]], 2)   # fits the message, then the person's setting
    decision["pause"] = pause
    bounds = tuple(model.get("temperature_bounds", effort_router.DEFAULT_BOUNDS))
    base_temp = model.get("sampling", {}).get("temperature", TEMPERATURE["balanced"])
    decision["temperature"] = None                             # None = keep the model's own setting
    if decision["auto"]:                                       # Auto also picks how adventurous the wording is
        decision["temperature"], decision["temperature_reason"] = effort_router.choose_temperature(question, base_temp, bounds)
    think = effort == "deep" and model.get("think") == "empty"   # Deep on a model that can think: it reasons first (hidden), Quick and Balanced answer straight away
    decision["thinking"] = think
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

    skill_hint = "\n\n".join(h for h in (app_skills.custom_hint(state.get_settings(who["user"]).get("custom_instructions")),
                                         app_skills.hint(store.skill(chat_id)),
                                         CONTINUE_HINT if cont else "") if h)   # the person's own preference, then the chat's skill (Study helper ...), then "continue": extra instructions for the model only
    if extra_hint:
        skill_hint = (skill_hint + "\n\n" if skill_hint else "") + extra_hint
    library = state.docs_for(who["user"])
    attached = [d for d in (library.info(i) for i in store.docs(chat_id)) if d]     # documents attached to this chat: their passages go in as notes
    if attached:
        skill_hint = (skill_hint + "\n\n" if skill_hint else "") + documents.hint([d["name"] for d in attached])

    sent_before = store.sent_docs(chat_id)                     # pictures and files that went with an earlier message: only new ones go with this one
    timing = {}

    def timed(stream):
        """Notes when the model's first word arrives (before the pause and the steady writing are added)."""
        for piece in stream:
            timing.setdefault("first", time.monotonic())
            yield piece

    def pacer(stream):
        stream = timed(stream)
        gen = chat_polish.paced(stream, min_first_s=pause, start=started) if (state.pace if pace is None else pace) else stream
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
            asked_id = text or next((m["content"] for m in reversed(store.messages(chat_id)) if m["role"] == "user"), "")
            canned = identity_answer.answer(asked_id) if not attached else None      # "who are you?": the app answers in the owner's words, no model, no web search
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
            doc_notes = []
            pictures = {"looked": 0, "read": 0}
            if attached:                                                           # the question is about the documents: no Wikipedia or web notes to distract
                asked_doc = text or next((m["content"] for m in reversed(store.messages(chat_id)) if m["role"] == "user"), "")
                described, picture_notes = set(), []
                helper = state.vision if (state.vision and state.vision.available()) else None
                for d in attached:
                    if d["kind"] not in documents.IMAGE_KINDS:
                        continue
                    pictures["read"] += 1
                    img = library.image(d["id"]) if helper else None
                    if not img:
                        continue
                    try:
                        q.put(("loading", "the picture reader")) if not helper.proc and not helper.fixed_url else None
                        picture_notes.append({"title": "Picture: " + d["name"], "text": helper.describe(d["id"], img[0], img[1], asked_doc)})
                        described.add(d["id"]); pictures["looked"] += 1
                    except RuntimeError as e:
                        sys.stderr.write(f"vision: {e}\n")
                rest = [d["id"] for d in attached if d["id"] not in described]
                doc_notes = picture_notes + (documents.notes_for(library, rest, asked_doc, budget=int(min(24000, max(3000, window * 3.5 * 0.45)))) if rest else [])
                unreadable = [d["name"] for d in attached if d["id"] not in described and (not (library.text(d["id"]) or "").strip() or (library.text(d["id"]) or "").startswith(documents.PICTURE_ONLY))]      # nothing could be read from it (a scan, a photo with no text)
                if unreadable:                                                     # say so, instead of letting the model answer around it
                    shown = ", ".join(f'"{n}"' for n in unreadable[:3])
                    doc_notes.append({"title": "Could not read: " + ", ".join(unreadable[:3]),
                                      "text": f"No text could be read from {shown} (it has no readable text, and the picture reader is not available). Tell the person you could not read it "
                                              "and ask them to type out the part they mean. Do not guess what it says."})
                if pictures["read"] or unreadable:
                    q.put(("notes", {"asked": True, "saved": 0, "wiki": 0, "web": 0, "web_tried": False, "recent": False, "live": 0, "names": [], "sources": [],
                                     "pictures": pictures["looked"], "ocr": pictures["read"] - pictures["looked"], "unreadable": unreadable}))
            live_notes = []
            live_mode = state.get_settings(who["user"])["web_search"]
            if not attached and not canned and live_mode != "none" and state.get_settings(who["user"]).get("live_data", True):
                asked_live = text or next((m["content"] for m in reversed(store.messages(chat_id)) if m["role"] == "user"), "")
                live_notes, live_found = live_data.gather(asked_live, state.clock(), online=(live_mode in ("auto", "always") and chat_id >= 0), net=state.live_net,
                                                          default_place=state.default_place)
                if live_notes:                                                     # exact facts (a sum, a date, a price): no Wikipedia or web notes needed
                    q.put(("notes", dict(live_found, saved=0, wiki=0, web=0, web_tried=False, recent=False)))
            app_notes = []
            if (chat_id >= 0 and not attached and not canned and live_mode != "none" and state.get_settings(who["user"]).get("connected_apps", True)
                    and state.links.store.connected(who["user"])):                  # the person's own connected apps (calendar, notes, tasks...): only when the question is about them
                asked_app = text or next((m["content"] for m in reversed(store.messages(chat_id)) if m["role"] == "user"), "")
                app_notes, app_found = state.links.gather(who["user"], asked_app, state.usage.get_user(who["user"]).get("tz_minutes", 0))
                if app_notes:
                    q.put(("notes", {"asked": True, "saved": 0, "wiki": 0, "web": 0, "web_tried": False, "recent": False, "live": 0, "names": [], "sources": [], "apps": app_found["apps"],
                                     "app_errors": app_found["errors"]}))
            earlier = [m["content"] for m in store.messages(chat_id) if m["role"] == "user"]      # what was asked before: a follow-up ("how many has he scored?") needs it to be searched
            if text and not attached and not canned and not live_notes and not app_notes:         # Auto lookup (lookup_auto.py)
                web_mode = state.get_settings(who["user"])["web_search"]
                ordered = lookup_auto.asks_for_web(text)                           # "look online", "check again": an order, so the web is searched whatever the rules say
                notes, found = lookup_auto.gather(lookup_auto.search_query(text, earlier), state.wiki, state.web_fn, web_mode, private=chat_id < 0,
                                                  max_notes=5 if window >= 6000 else 3, force_web=ordered, force_notes=ordered,
                                                  saved=state.saved_for(who["user"]), now=state.clock(), policy=model.get("lookup", "always"))
                if found["asked"]:
                    import web_search
                    q.put(("notes", {k: v for k, v in found.items() if k != "used"} | ({"web_source": web_search.pick_source("auto")} if found.get("recent") else {})))
            if doc_notes:
                notes = doc_notes + list(notes or [])
            if live_notes:
                notes = [{"title": n["title"], "text": n["text"]} for n in live_notes] + list(notes or [])
            if app_notes:
                notes = list(app_notes) + list(notes or [])
            if extra_notes:                                                        # facts an app sent with its question: the answer must come from these
                notes = list(extra_notes) + list(notes or [])
            today = lookup_auto.date_note(text or (store.messages(chat_id)[-1]["content"] if regenerate and store.messages(chat_id) else ""), state.clock())
            if today:                                                              # "what day is Christmas this year": the model has no clock
                notes = [today] + list(notes or [])
            if mem_note:
                notes = [mem_note] + list(notes or [])
            t_load = time.monotonic()
            backend = E.FakeBackend(canned) if canned else state.backend_for(model, text or "", window)     # may load the model the first time (can take a while)
            timing["load"] = time.monotonic() - t_load
            if decision["temperature"] is not None and hasattr(backend, "sampling"):
                backend.sampling = dict(backend.sampling, temperature=decision["temperature"])
            if regenerate and hasattr(backend, "sampling"):
                t = regen_modes.sampling_for(backend.sampling.get("temperature", 0.8), mode)
                backend.sampling = dict(backend.sampling, temperature=round(min(bounds[1], max(bounds[0], t)), 2))   # never outside the model's safe range
            prior_reply = next((m["content"] for m in reversed(store.messages(chat_id)) if m["role"] == "assistant"), "")      # to notice a reply that is only a copy of this one
            r = E.run_turn(tok, store, chat_id, backend, counted_model, window, max_new, user_text=text, stop=stop, notes=notes or None,
                           user_docs=[d["id"] for d in attached if d["id"] not in sent_before] if text else None,
                           limiter=state.limiter, user=who["user"], effort=effort, clock=state.clock, pacer=pacer, think=think,
                           style_hint="\n\n".join(h for h in (skill_hint, regen_modes.get(mode)["hint"] if regenerate else "",
                                                    "" if regenerate else (chat_polish.answer_hint(text, next((m["content"] for m in reversed(store.messages(chat_id)) if m["role"] == "assistant"), ""))
                                                                                 or chat_polish.follow_up_hint(text, any(m["role"] == "assistant" for m in store.messages(chat_id))))) if h))
            if text and not canned and not regenerate and r.get("reason") in ("done", None) and chat_polish.is_repeat(r["text"], prior_reply):
                # A small model answered its own last message again. Take that reply back and ask once more, firmly, a little less predictably.
                msgs = [m for m in store.messages(chat_id) if m["status"] != "compacted"]
                if msgs and msgs[-1]["role"] == "assistant":
                    store.remove_message(chat_id, msgs[-1]["id"])
                if hasattr(backend, "sampling"):
                    backend.sampling = dict(backend.sampling, temperature=round(min(1.0, backend.sampling.get("temperature", 0.8) + 0.2), 2),
                                            repeat_penalty=max(1.3, backend.sampling.get("repeat_penalty", 1.15)))
                r = E.run_turn(tok, store, chat_id, backend, counted_model, window, max_new, user_text=None, stop=stop, notes=notes or None,
                               limiter=state.limiter, user=who["user"], effort=effort, clock=state.clock, pacer=pacer, think=think,
                               style_hint="\n\n".join(h for h in (skill_hint, chat_polish.repeat_hint(text)) if h))
            web_mode_now = state.get_settings(who["user"])["web_search"]
            knowledge_first = (model.get("lookup") == "when_needed" and found is not None and not found["asked"] and bool(text) and not regenerate
                               and web_mode_now != "none" and lookup_auto.wants_lookup(text))
            old_way = (found and found["asked"] and not regenerate and not found["web_tried"] and state.web_fn is not None and
                       web_mode_now not in ("off", "none") and chat_id >= 0)
            pretended = bool(text and not regenerate and chat_id >= 0 and state.web_fn is not None and web_mode_now not in ("off", "none")
                             and not (found and found.get("web")) and lookup_auto.pretends_to_search(r["text"]))      # it wrote "checking online" but no search ran: do the real one
            if ((old_way or knowledge_first) and lookup_auto.gave_up(r["text"])) or pretended:
                # The model said it doesn't know. Old way: the web has not been tried, so search it. Knowledge-first models (Qwen) had no notes yet:
                # look it up now. Then answer again (the second chance).
                notes2, found2 = lookup_auto.gather(lookup_auto.search_query(text, earlier, force=pretended), state.wiki, state.web_fn, "always" if (old_way or pretended) else web_mode_now, private=(chat_id < 0 and knowledge_first),
                                                    max_notes=5 if window >= 6000 else 3, saved=state.saved_for(who["user"]),
                                                    now=state.clock(), force_web=True, force_notes=True)
                if found2["web"] or (knowledge_first and (found2["wiki"] or found2["saved"])):
                    q.put(("notes", {k: v for k, v in found2.items() if k != "used"} | {"retry": True}))
                    msgs = [m for m in store.messages(chat_id) if m["status"] != "compacted"]
                    if msgs and msgs[-1]["role"] == "assistant":
                        store.remove_message(chat_id, msgs[-1]["id"])
                    r = E.run_turn(tok, store, chat_id, backend, counted_model, window, max_new, user_text=None, stop=stop, notes=([mem_note] if mem_note else []) + list(notes2 or []),
                                   limiter=state.limiter, user=who["user"], effort=effort, clock=state.clock, pacer=pacer, think=think, style_hint=skill_hint)
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


def model_guard_tests(path):
    import quality_check
    return quality_check.load_sheet(path)


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

    def _send_preview(self, status, ctype, body):
        """A page of someone's project, for the preview frame: an empty identity (sandbox), no framing by other sites, readable by the sandboxed frame."""
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", code_preview.PREVIEW_CSP)
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "cross-origin")      # the sandboxed frame has no origin of its own, so its own files count as cross-origin
        self.send_header("Access-Control-Allow-Origin", "*")                  # ...and its scripts are fetched with CORS so their errors can be described
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        if self._https():
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        self.end_headers()
        self.wfile.write(body)

    def _json(self):
        n = int(self.headers.get("Content-Length") or 0)
        limit = {"/api/code/import": MAX_UPLOAD, "/api/documents": MAX_DOC_BODY}.get(self.path.split("?")[0], MAX_BODY)
        if n > limit:
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
            elif who.get("app"):                            # an app's key opens the API only, never the app's screens or a person's data
                self._send(403, {"code": "app_key", "message": "This key is for an app and works only with the Emvryx API.", "action": "Use POST /api/v1/ask."})
                return None
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
        pv = re.fullmatch(r"/preview/([A-Za-z0-9_-]{16,64})/(.*)", path)
        if pv:                                                   # the live preview: a token in the address instead of the cookie (the sandboxed frame sends none)
            folder = self.state.previews.folder(pv.group(1))
            if not folder:
                return self._send(404, "This preview link has expired. Open Preview again.\n", "text/plain; charset=utf-8")
            return self._send_preview(*code_preview.serve(folder, urllib.parse.unquote(pv.group(2))))
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
            if path == "/api/v1/models":
                return self.api_v1_models()
            if path == "/api/status":                          # for the website's "is Emvryx on?" line and its Open page: harmless, no sign-in, readable from the website
                st = self.state
                ready = sum(1 for m in st.catalog({"user": "", "owner": True, "tier": "mega", "banned": False})["cards"] if m["state"] == "ready")
                return self._send(200, {"up": True, "paused": bool(st.cfg.get("paused")), "resting": bool(st.cfg.get("gaming")), "demo": bool(st.demo), "models_ready": ready, "signup": st.signup_mode()},
                                  headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})
            if path == "/api/auth-options":
                return self._send(200, {"email": bool(self.state.mailer), "signups": bool(self.state.mailer and self.state.security["open_signups"]),
                                        "password": True, "signup": self.state.signup_mode(), "google": self.state.google_on(), "passkeys": passkeys.AVAILABLE})
            ms = re.fullmatch(r"/s/([A-Za-z0-9_-]{16,80})", path)
            if ms:                                              # a shared chat: no sign-in, a copy of the words only
                if self._locked():
                    return
                snap = self.state.shares.get(ms.group(1)) if self.state.security.get("sharing") else None
                if not snap:
                    self._fail("bad share link")
                    return self._send(404, "This link doesn't work any more: it expired, was cancelled, or sharing was switched off.\n", "text/plain; charset=utf-8")
                return self._send(200, shares.render(snap).encode("utf-8"), "text/html; charset=utf-8",
                                  csp="default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
            if path == "/auth/google/start":
                return self.google_start(qs)
            if path == "/auth/google/callback":
                return self.google_callback(qs)
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
            if path == "/api/briefing":
                if not self.state.get_settings(who["user"]).get("connected_apps", True):
                    return self._send(200, {"sections": [], "off": True})
                return self._send(200, app_links.briefing(self.state.links, who["user"], self.state.usage.get_user(who["user"]).get("tz_minutes", 0)))
            if path == "/api/shares":
                return self._send(200, {"shares": self.state.shares.list(who["user"]), "on": bool(self.state.security.get("sharing"))})
            if path == "/api/chats/search":
                return self._send(200, {"results": self.state.store(who["user"]).search((qs.get("q") or [""])[0])})
            m = re.fullmatch(r"/api/chats/(-?\d+)", path)
            if m:
                return self.api_get_chat(who, int(m.group(1)))
            if path == "/api/settings":
                return self._send(200, self.state.get_settings(who["user"]))
            m = re.fullmatch(r"/api/documents/(\d+)/image", path)
            if m:
                img = self.state.docs_for(who["user"]).image(int(m.group(1)))
                if not img:
                    return self._send(404, {"code": "not_found", "message": "No picture."})
                return self._send(200, img[0], ctype=img[1], headers={"Cache-Control": "private, max-age=3600"})
            if path == "/api/documents":
                return self._send(200, {"documents": self.state.docs_for(who["user"]).list(), "max_mb": documents.MAX_FILE_BYTES // 1_000_000,
                                        "kinds": documents.KINDS})
            if path == "/api/skills":
                return self._send(200, app_skills.catalog())
            if path == "/api/live/sources":
                import web_search
                return self._send(200, {"sources": live_data.sources_status(), "web": web_search.pick_source("auto")})
            if path == "/api/teacher/tools":
                return self._send(200, teacher_mode.catalog())
            if path == "/api/apps":
                cat = connected_apps.catalog()
                cat["connections"] = dict(self.state.links.store.public(who["user"]),
                                          github=dict(self.state.github.public(who["user"]), device=bool(self.state.github_client_id()), encrypted=self.state.secrets.available))
                cat["apps"] = [a for a in cat["apps"] if who["owner"] or not a.get("owner_only")]
                cat["encrypted"] = self.state.secrets.available
                return self._send(200, cat)
            if path == "/api/whats-new":                                         # what has been published, and what this person has not seen yet
                fl = self.state.flags
                seen = self.state.get_settings(who["user"]).get("whats_new_seq", -1)
                if not isinstance(seen, int) or seen < 0:                         # a new account, or one from before releases were numbered: start from now
                    seen = fl.last_seq()
                    self.state.put_settings(who["user"], {"whats_new_seq": seen})
                rel = [{k: r.get(k) for k in ("seq", "version", "kind", "model", "at", "notes", "items")} for r in fl.releases()[:50]]
                return self._send(200, {"version": fl.version(), "seq": fl.last_seq(), "releases": rel, "unseen": [r for r in rel if r["seq"] > seen]})
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
            if path == "/api/account":
                return self.api_account_get(who)
            if path == "/api/account/activity":
                return self._send(200, {"events": self.state.auth.events(30, None, who["user"])})
            if path == "/api/admin/backups" and who["admin"]:
                d = data_tools.backup_dir(self.state)
                files = sorted((f for f in (os.listdir(d) if os.path.isdir(d) else []) if BACKUP_NAME.fullmatch(f)), reverse=True)
                return self._send(200, {"dir": d, "items": [{"name": f, "size": os.path.getsize(os.path.join(d, f)), "at": os.path.getmtime(os.path.join(d, f))} for f in files],
                                        "keep": 14, "data": self.state.data_dir or ""})
            mb = re.fullmatch(r"/api/admin/backups/(emvryx-[0-9-]+\.zip)", path)
            if mb and who["admin"]:
                full = os.path.join(data_tools.backup_dir(self.state), mb.group(1))
                if not BACKUP_NAME.fullmatch(mb.group(1)) or not os.path.isfile(full):
                    return self._send(404, {"code": "not_found", "message": "No such backup."})
                with open(full, "rb") as f:
                    data = f.read()
                self.state.auth.event("backup_downloaded", "owner", self._ip(), mb.group(1))
                return self._send(200, data, "application/zip", {"Content-Disposition": f'attachment; filename="{mb.group(1)}"'})
            if path == "/api/admin/feedback" and who["admin"]:
                fb = self.state.feedback
                return self._send(200, {"counts": fb.counts(), "kinds": feedback.KINDS, "items": fb.list(int((qs.get("limit") or ["50"])[0]), (qs.get("status") or ["new"])[0] or None,
                                                                                                            (qs.get("kind") or [None])[0], (qs.get("model") or [None])[0])})
            if path == "/api/admin/feedback/export" and who["admin"]:
                lines = "\n".join(self.state.feedback.export_lines((qs.get("status") or ["new"])[0])) + "\n"
                return self._send(200, lines.encode("utf-8"), "application/x-ndjson", {"Content-Disposition": 'attachment; filename="feedback_export.jsonl"'})
            if path == "/api/admin/cloud" and who["admin"]:
                return self._send(200, self.state.cloud_status())
            if path == "/api/admin/overview" and who["admin"]:
                return self._send(200, self.state.admin_overview(who))
            if path == "/api/sessions":
                return self._send(200, {"sessions": [dict(x, current=(x["id"] == who.get("session"))) for x in self.state.auth.sessions_for(who["user"])]})
            if path == "/api/admin/health" and who["admin"]:
                return self._send(200, self.state.health())
            if path == "/api/admin/audit" and who["admin"]:
                return self._send(200, {"events": self.state.auth.events(int((qs.get("limit") or ["100"])[0]), (qs.get("kind") or [None])[0])})
            if path == "/api/admin/flags" and who["admin"]:
                return self._send(200, {"flags": self.state.flags.listing(), "audiences": [[a, flags.AUDIENCE_NAMES[a]] for a in flags.AUDIENCES],
                                        "version": self.state.flags.version(), "releases": self.state.flags.releases(),
                                        "people": sorted(u["user"] for u in self.state.users.values() if not u.get("app"))})
            if path == "/api/admin/models" and who["admin"]:
                return self._send(200, self.state.models_admin())
            if path == "/api/admin/apps" and who["admin"]:
                return self._send(200, {"apps": self.state.apps(), "plans": list(self.state.cfg["tiers"]), "url": self._public_base() + "/api/v1/ask"})
            if path == "/api/admin/pc" and who["admin"]:
                self.state.sync_gaming()
                return self._send(200, self.state.pc_status())
            if path == "/api/admin/users" and who["admin"]:
                seen = self.state.auth.last_seen_map()
                return self._send(200, {"users": [{"user": u["user"], "tier": self.state.usage.get_user(u["user"])["tier"], "email": u.get("email"),
                                                   "banned": bool(u.get("banned")), "owner": bool(u.get("owner")), "admin": bool(u.get("admin")), "unlimited": bool(u.get("unlimited")), "mfa": bool((u.get("mfa") or {}).get("on")),
                                                   "has_password": bool(u.get("pw")), "created": u.get("created"), "last_seen": seen.get(u["user"])}
                                                  for u in self.state.users.values() if not u.get("app")], "paused": bool(self.state.cfg.get("paused"))})
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
                if who and who.get("app"):
                    return self._send(403, {"code": "app_key", "message": "This key is for an app, not a person.", "action": "Use POST /api/v1/ask."})
                if not who:
                    self._fail("bad key")
                    return self._send(401, {"code": "bad_key", "message": "That key isn't right.", "action": "Check it and try again."})
                if who["banned"]:
                    return self._send(403, {"code": "banned", "message": "This account has been turned off.", "action": "Ask the owner if you think that is a mistake."})
                return self._finish_login(who["user"], "key")
            if path == "/api/login/password":
                return self.api_password_login(body)
            if path == "/api/login/mfa":
                return self.api_mfa_login(body)
            if path in ("/api/login/passkey/begin", "/api/login/passkey/finish"):
                return self.api_passkey_login(path.rsplit("/", 1)[1], body)
            if path == "/api/signup":
                return self.api_signup(body)
            if path == "/api/login/email/start":
                return self.api_email_start(body)
            if path == "/api/login/email/verify":
                return self.api_email_verify(body)
            if path == "/api/v1/ask":
                return self.api_v1_ask(body)
            who = self._who()
            if not who:
                return
            if path.startswith("/api/account/"):
                return self.api_account(who, path, body)
            if path == "/api/delete-account":
                if who.get("has_password") or who.get("mfa"):
                    err = self._reauth(who, body)
                    if err:
                        return self._send(400, {"code": "reauth", "message": err, "action": "Nothing was deleted."})
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
                skill = str(body.get("skill") or "")
                if skill and not app_skills.get(skill):
                    return self._send(400, {"code": "bad_skill", "message": "That skill isn't available."})
                store = self.state.store(who["user"])
                cid = store.new_chat(private=bool(body.get("private")), skill=skill)
                lib = self.state.docs_for(who["user"])
                store.set_docs(cid, [i for i in (body.get("docs") or []) if isinstance(i, int) and lib.info(i)])
                return self._send(200, {"id": cid})
            if path == "/api/documents":
                import base64
                try:
                    data = base64.b64decode(str(body.get("data", "")), validate=False)
                    return self._send(200, self.state.docs_for(who["user"]).add(str(body.get("name", "")), data, allow_picture=bool(self.state.vision and self.state.vision.available())))
                except (ValueError, TypeError) as e:
                    return self._send(400, {"code": "bad_document", "message": str(e) if isinstance(e, ValueError) and not str(e).startswith("Incorrect padding") else "That file couldn't be read."})
            m = re.fullmatch(r"/api/chats/(-?\d+)/docs", path)
            if m:
                cid = int(m.group(1))
                store = self.state.store(who["user"])
                if not store.exists(cid):
                    return self._send(404, {"code": "not_found", "message": "That chat is gone."})
                lib = self.state.docs_for(who["user"])
                ids = [i for i in (body.get("ids") or []) if isinstance(i, int) and lib.info(i)]
                store.set_docs(cid, ids)
                return self._send(200, {"docs": [lib.info(i) for i in store.docs(cid)]})
            if path == "/api/teacher/calc":
                try:
                    return self._send(200, teacher_mode.calculate(str(body.get("tool", "")), body.get("values") or {}))
                except ValueError as e:
                    return self._send(400, {"code": "bad_numbers", "message": str(e)})
            if path == "/api/teacher/prompt":
                try:
                    return self._send(200, {"prompt": teacher_mode.fill(str(body.get("tool", "")), body.get("values") or {}),
                                            "skill": "teacher" if teacher_mode.BY_ID[str(body["tool"])]["side"] == "teacher" else "study"})
                except (ValueError, KeyError):
                    return self._send(400, {"code": "bad_tool", "message": "That tool doesn't exist."})
            if path == "/api/export-doc":
                text = str(body.get("text", ""))
                ext = "." + str(body.get("format", "pdf")).lower().lstrip(".")
                if not text.strip() or len(text) > 200_000:
                    return self._send(400, {"code": "empty", "message": "There is nothing to save."})
                if ext not in export_doc.MIME:
                    return self._send(400, {"code": "bad_format", "message": "Pick PDF, Word or Markdown."})
                try:
                    data, mime, title = export_doc.to_bytes(text, ext)
                except RuntimeError as e:
                    return self._send(501, {"code": "needs_package", "message": str(e)})
                name = re.sub(r"[^A-Za-z0-9 _-]", "", str(body.get("title") or title)).strip()[:60] or "document"
                return self._send(200, data, mime, {"Content-Disposition": f'attachment; filename="{name}{ext}"'})
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
            if path == "/api/models/warm":
                return self._send(200, {"ok": self.state.warm(who, str(body.get("model", "")))})
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
            m = re.fullmatch(r"/api/apps/([a-z]+)/(connect|disconnect|ask)", path)
            if m and m.group(1) in app_links.BY_ID:
                return self.api_app_link(who, m.group(1), m.group(2), body)
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
                self.state.docs_for(who["user"]).clear()
                return self._send(200, {"ok": True})
            if path == "/api/shares/revoke":
                return self._send(200, {"ok": self.state.shares.revoke(who["user"], body.get("id", ""))})
            m = re.fullmatch(r"/api/chats/(-?\d+)/share", path)
            if m:
                cid, store = int(m.group(1)), self.state.store(who["user"])
                if not self.state.security.get("sharing"):
                    return self._send(403, {"code": "sharing_off", "message": "Sharing links is switched off.", "action": "Ask the owner to turn it on (Settings > Owner > Overview)."})
                if cid < 0:
                    return self._send(400, {"code": "private", "message": "Private chats can't be shared: nothing about them is saved."})
                if not store.exists(cid):
                    return self._send(404, {"code": "not_found", "message": "That chat is gone."})
                models_by_id = {x["id"]: x for x in self.state.catalog(who)["cards"] + self.state.catalog(who)["other"]}
                msgs = [{"role": x["role"], "content": x["content"], "model": (models_by_id.get(x["model_id"]) or {}).get("name", "")} for x in store.messages(cid)
                        if x["status"] not in ("compacted", "summary") and x["content"]]
                try:
                    token = self.state.shares.create(who["user"], cid, store.title(cid), msgs, int(body.get("days") or 7))
                except ValueError as e:
                    return self._send(400, {"code": "bad_request", "message": str(e)})
                self.state.auth.event("share_made", who["user"], self._ip(), "")
                return self._send(200, {"url": "/s/" + token, "shares": self.state.shares.list(who["user"])})
            m = re.fullmatch(r"/api/chats/(-?\d+)/(pin|folder|branch)", path)
            if m:
                cid, what, store = int(m.group(1)), m.group(2), self.state.store(who["user"])
                if not store.exists(cid):
                    return self._send(404, {"code": "not_found", "message": "That chat is gone."})
                if what == "pin":
                    store.set_pinned(cid, bool(body.get("pinned", True)))
                    return self._send(200, store.meta(cid))
                if what == "folder":
                    store.set_folder(cid, body.get("folder", ""))
                    return self._send(200, store.meta(cid))
                new = store.branch(cid, int(body.get("message_id", -1)))
                if new is None:
                    return self._send(400, {"code": "bad_request", "message": "That message isn't in this chat."})
                return self._send(200, {"id": new, "title": store.title(new)})
            m = re.fullmatch(r"/api/chats/(-?\d+)/messages/(\d+)/(edit|feedback)", path)
            if m:
                cid, mid, what, store = int(m.group(1)), int(m.group(2)), m.group(3), self.state.store(who["user"])
                if not store.exists(cid):
                    return self._send(404, {"code": "not_found", "message": "That chat is gone."})
                if what == "edit":
                    if (who["user"], cid) in self.state.stops:
                        return self._send(400, {"code": "busy", "message": "It is still answering.", "action": "Wait for it to finish, or press Stop."})
                    text = str(body.get("text", "")).strip()
                    if len(text) > MAX_TEXT:
                        return self._send(400, {"code": "too_long", "message": "That message is too long. Please shorten it."})
                    if not store.edit_message(cid, mid, text):
                        return self._send(400, {"code": "bad_request", "message": "Only your own messages can be edited."})
                    return self._send(200, {"ok": True})
                if cid < 0:
                    return self._send(400, {"code": "private", "message": "Private chats can't be reported: nothing about them is saved."})
                msgs = store.messages(cid)
                i = next((n for n, x in enumerate(msgs) if x["id"] == mid and x["role"] == "assistant"), None)
                if i is None:
                    return self._send(400, {"code": "bad_request", "message": "That answer isn't here."})
                question = next((x["content"] for x in reversed(msgs[:i]) if x["role"] == "user" and x["status"] != "summary"), "")
                kind = str(body.get("kind", "other"))
                used = self.state.lookups.get((who["user"], cid, mid)) or {}
                self.state.feedback.add(who["user"], msgs[i]["model_id"], kind, body.get("note"), question, msgs[i]["content"], [n.get("title") for n in used.get("notes", [])])
                store.set_flag(cid, mid, "fb", kind if kind in feedback.KINDS else "other")
                self.state.auth.event("feedback", who["user"], self._ip(), kind)
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
                if not who["admin"]:
                    return self._send(403, {"code": "owner_only", "message": "Only the owner or an admin can change this."})
                if path == "/api/admin/flags":                                   # any admin may widen or narrow who sees a new feature
                    try:
                        if body.get("publish") == "all":                                      # everything in preview, as one release
                            ids = self.state.flags.publish_all(by=who["user"], kind=str(body.get("kind") or "minor"), notes=str(body.get("notes") or ""))
                            self.state.auth.event("flag_changed", who["user"], self._ip(), "published all: " + ", ".join(ids))
                        elif body.get("id") and body.get("publish") == "now":                # publish to everyone straight away
                            self.state.flags.publish_now(str(body["id"]), by=who["user"], kind=str(body.get("kind") or "minor"), notes=str(body.get("notes") or ""))
                            self.state.auth.event("flag_changed", who["user"], self._ip(), f"{body['id']} -> everyone (published)")
                        elif body.get("id") and body.get("cancel_schedule"):
                            self.state.flags.cancel_schedule(str(body["id"]))
                            self.state.auth.event("flag_changed", who["user"], self._ip(), f"{body['id']}: schedule cancelled")
                        elif body.get("id") and "schedule_at" in body:                       # publish at a chosen time (seconds since 1970)
                            self.state.flags.schedule(str(body["id"]), body.get("schedule_at"), str(body.get("audience") or "everyone"), by=who["user"])
                            self.state.auth.event("flag_changed", who["user"], self._ip(), f"{body['id']}: scheduled for {time.strftime('%Y-%m-%d %H:%M', time.localtime(float(body['schedule_at'])))}")
                        elif body.get("id"):
                            self.state.flags.set_audience(str(body["id"]), str(body.get("audience", "")), by=who["user"])
                            self.state.auth.event("flag_changed", who["user"], self._ip(), f"{body['id']} -> {body.get('audience')}")
                    except ValueError as e:
                        return self._send(400, {"code": "bad_request", "message": str(e)})
                    return self._send(200, {"flags": self.state.flags.listing(), "version": self.state.flags.version(), "releases": self.state.flags.releases()})
                if path == "/api/admin/apps":                                     # make, change, switch off, rotate the key of, or remove an app
                    st, act = self.state, str(body.get("action", ""))
                    try:
                        if act == "create":
                            key = st.add_app(body.get("slug"), body.get("display"), body.get("plan", "free"), body.get("instructions", ""), body.get("rpm", 20),
                                             body.get("model", "flare"), body.get("effort", "balanced"), body.get("lookup", "none"))
                            return self._send(200, {"key": key, "apps": st.apps(), "url": self._public_base() + "/api/v1/ask"})
                        name = APP_PREFIX + str(body.get("slug", ""))
                        if not st.app_record(name):
                            return self._send(404, {"code": "not_found", "message": "No such app."})
                        if act == "rotate":
                            key = st.rotate_key(name)
                            st.auth.event("app_key_rotated", name, self._ip(), "by " + who["user"])
                            return self._send(200, {"key": key, "apps": st.apps()})
                        if act == "delete":
                            if str(body.get("confirm", "")) != str(body.get("slug", "")):
                                return self._send(400, {"code": "confirm", "message": "Type the app's name to confirm."})
                            data_tools.delete_account(st, name, by=who["user"])
                        elif act == "update":
                            st.update_app(name, **{k: body[k] for k in ("display", "instructions", "rpm", "model", "effort", "enabled", "lookup", "plan") if k in body})
                            st.auth.event("app_changed", name, self._ip(), "by " + who["user"])
                        else:
                            return self._send(400, {"code": "bad_request", "message": "Nothing to do."})
                    except (ValueError, TypeError) as e:
                        return self._send(400, {"code": "bad_request", "message": str(e)})
                    return self._send(200, {"apps": st.apps()})
                if path == "/api/admin/pc":                                       # Gaming mode, idle unload, unload now
                    st = self.state
                    if "gaming" in body:
                        st.set_gaming(bool(body.get("gaming")), by=who["user"])
                    if "idle_unload_minutes" in body:
                        try:
                            minutes = int(body["idle_unload_minutes"])
                        except (TypeError, ValueError):
                            return self._send(400, {"code": "bad_request", "message": "Choose a number of minutes (0 turns idle unload off)."})
                        if not 0 <= minutes <= 720:
                            return self._send(400, {"code": "bad_request", "message": "Choose between 0 and 720 minutes (0 turns idle unload off)."})
                        st.save_security(idle_unload_minutes=minutes)
                        st.auth.event("idle_unload_changed", who["user"], self._ip(), str(minutes))
                    if body.get("unload"):
                        if st.busy():
                            return self._send(409, {"code": "busy", "message": "A reply is being written right now.", "action": "Try again in a moment."})
                        st.unload_model(f"unloaded by {who['user']}")
                    return self._send(200, st.pc_status())
                if path == "/api/admin/models":                                   # publish a model that is in preview, schedule it, or record an update that keeps its version
                    mp, man, mid, by = self.state.models_pub, self.state.manifest, str(body.get("id", "")), who["user"]
                    try:
                        if body.get("run_checks"):
                            st_ = self.state.start_guard(mid, by=by)
                            self.state.auth.event("model_checks", by, self._ip(), f"{mid}: started")
                        elif body.get("publish") == "now":
                            if self.state.runner and not self.state.runner.available(mid):
                                return self._send(400, {"code": "bad_request", "message": "That model's file is not on this computer yet, so it cannot be published."})
                            skip = bool(body.get("skip_checks"))
                            label = mp.publish(man, mid, by=by, notes=str(body.get("notes") or ""), skip_checks=skip)
                            self.state.auth.event("model_published", by, self._ip(), label + (" WITHOUT the safety checks" if skip else ""))
                        elif body.get("cancel_schedule"):
                            mp.cancel_schedule(mid)
                        elif "schedule_at" in body:
                            mp.schedule(man, mid, body.get("schedule_at"), by=by)
                            self.state.auth.event("model_published", by, self._ip(), f"{mid} scheduled")
                        elif body.get("record_update"):
                            mp.record_update(man, mid, str(body.get("notes") or ""), by=by)
                            self.state.auth.event("model_published", by, self._ip(), f"{mid} update recorded")
                        else:
                            return self._send(400, {"code": "bad_request", "message": "Nothing to do."})
                    except ValueError as e:
                        return self._send(400, {"code": "bad_request", "message": str(e)})
                    return self._send(200, self.state.models_admin())
                if path == "/api/admin/reset-password":                          # a password reset: the old password stops working and a one-time link lets them choose a new one
                    target = str(body.get("user", ""))
                    rec = self.state.user_record(target)
                    if not rec:
                        return self._send(404, {"code": "not_found", "message": "No one is called that."})
                    if rec.get("owner") or target == who["user"]:
                        return self._send(400, {"code": "bad_request", "message": "Change your own password in Settings > Security.", "action": "Nothing was changed."})
                    if (rec.get("admin") or rec.get("unlimited")) and not who["granter"]:
                        return self._send(403, {"code": "owner_only", "message": "Only the PC owner and the owner's email account can reset an admin or no-limits account.", "action": "Nothing was changed."})
                    st = self.state
                    st._set_fields(target, pw="")
                    st.auth.revoke_user(target)
                    pair = st.auth.new_pair(target, st.security["pair_minutes"], made_by=who["user"])
                    link = self._public_base() + "/pair/" + pair
                    emailed = False
                    if st.mailer and rec.get("email"):
                        text = (f"An Emvryx admin reset your password. Open this link to sign in and choose a new one (it works once, for {st.security['pair_minutes']} minutes):\n\n{link}\n\n"
                                "If you did not expect this, ignore it: the link does nothing until it is opened.")
                        threading.Thread(target=lambda: st.mailer.send(rec["email"], "Your Emvryx password was reset", text), daemon=True).start()
                        emailed = True
                    st.auth.event("password_reset_by_admin", target, self._ip(), "by " + who["user"] + (", emailed" if emailed else ""))
                    return self._send(200, {"ok": True, "link": link, "emailed": emailed, "minutes": st.security["pair_minutes"]})
                if path == "/api/admin/delete-user":                             # an admin removes an account and everything it owned
                    target = str(body.get("user", ""))
                    rec = self.state.user_record(target)
                    if not rec:
                        return self._send(400, {"code": "bad_request", "message": "No one is called that.", "action": "Nothing was deleted."})
                    if rec.get("owner"):
                        return self._send(400, {"code": "bad_request", "message": "The first owner account can't be deleted.", "action": "Nothing was deleted."})
                    if target == who["user"]:
                        return self._send(400, {"code": "bad_request", "message": "That is your own account.", "action": "Use Settings > Account > Delete my account. Nothing was deleted."})
                    if (rec.get("admin") or rec.get("unlimited")) and not who["granter"]:
                        return self._send(403, {"code": "owner_only", "message": "Only the PC owner and the owner's email account can delete an admin or no-limits account.", "action": "Nothing was deleted."})
                    if who.get("has_password") or who.get("mfa"):
                        err = self._reauth(who, body)
                        if err:
                            return self._send(400, {"code": "reauth", "message": err, "action": "Nothing was deleted."})
                    if str(body.get("confirm", "")) != target:
                        return self._send(400, {"code": "confirm", "message": "Type the person's name to confirm.", "action": "Nothing was deleted."})
                    try:
                        data_tools.delete_account(self.state, target, by=who["user"])
                    except ValueError as e:
                        return self._send(400, {"code": "bad_request", "message": str(e), "action": "Nothing was deleted."})
                    return self._send(200, {"ok": True})
                if path == "/api/admin/access":                                  # who gets a plan, no limits or admin rights: only the first owner decides
                    if not who["granter"]:
                        return self._send(403, {"code": "owner_only", "message": "Only the PC owner and the owner's own email account can give out plans, admin rights or no-limits."})
                    try:
                        out = self.state.set_access(str(body.get("user", "")), body.get("plan"), body.get("unlimited"), body.get("admin"))
                    except ValueError as e:
                        return self._send(400, {"code": "bad_request", "message": str(e)})
                    return self._send(200, out)
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
        m = re.fullmatch(r"/api/documents/(\d+)", path)
        if m:
            return self._send(200, {"ok": self.state.docs_for(who["user"]).delete(int(m.group(1)))})
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
        if action not in ("create_repo", "link", "clone", "pull", "push", "import"):
            raise code_sessions.CodeError("Choose create_repo, link, clone, pull, push or import.")
        if st.code.running(user):
            raise code_sessions.CodeError("A coding session is running.", "Stop it first, then use GitHub.")
        try:
            api = st.github_api(user)
            if action == "import":                                   # a repository you already have, copied into a NEW project of its own
                owner, repo = github_link.parse_repo(body.get("repo"))
                base = (re.sub(r"[^A-Za-z0-9_-]", "-", repo).strip("-") or "project")[:36]
                name, n = base, 1
                while name in st.code.projects(user):
                    n += 1
                    name = f"{base}-{n}"
                os.makedirs(st.code.project_path(user, name), exist_ok=True)
                try:
                    st.git_for(user, name).clone(owner, repo)
                except Exception:
                    shutil.rmtree(st.code.project_path(user, name), ignore_errors=True)         # a failed copy leaves no half-empty project behind
                    raise
                st.github.log(user, f"imported {owner}/{repo} as {name}")
                return {"ok": True, "message": f"Imported {owner}/{repo} as the project {name}.", "project": name}
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
                                        "running": run.id if run else None, "project": run.project if run else None, "environments": st.code.environments(who["admin"]),
                                        "browser_check": browser_check.available()})
            if path == "/api/code/sessions":
                return self._send(200, {"sessions": st.code.list_sessions(user)})
            if path == "/api/code/github/repos":
                try:
                    repos = st.github_api(user).my_repos()
                    token = st.github.get(user).get("token") or ""
                    kind = "fine-grained" if token.startswith("github_pat_") else "classic" if token.startswith("ghp_") else "sign-in" if token.startswith("gho_") else "other"
                    return self._send(200, {"repos": repos, "private_seen": sum(1 for r in repos if r["private"]), "token_kind": kind})
                except github_link.GitHubError as e:
                    raise code_sessions.CodeError(e.message, e.action)
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
            if path == "/api/code/shot":                                  # a screenshot the browser check took (only the owner of the project, only its own check files)
                name = arg("name")
                folder = st.code.project_path(user, arg("project"))
                if not browser_check.SHOT_RX.fullmatch(name):
                    return self._send(404, {"code": "not_found", "message": "Not found."})
                try:
                    with open(os.path.join(folder, browser_check.SHOT_DIR, name), "rb") as f:
                        data = f.read()
                except OSError:
                    return self._send(404, {"code": "not_found", "message": "That screenshot is no longer kept."})
                return self._send(200, data, "image/png", {"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})
            if path == "/api/code/files":
                return self._send(200, {"files": st.code.files(user, arg("project"))})
            if path == "/api/code/file":
                return self._send(200, st.code.read(user, arg("project"), arg("path")))
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)", path)
            if m:
                if m.group(1) not in st.code.sessions:                  # a finished session from the history (read-only): also after a restart
                    d = st.code.saved(user, m.group(1))
                    after = max(0, int(arg("after") or 0))
                    return self._send(200, {"events": d["events"][max(0, after - d.get("offset", 0)):], "state": d["meta"].get("state", "done"), "pending": None, "saved": True,
                                            "task": d["meta"]["title"], "project": d["meta"]["project"], "model": d["meta"]["model"], "env": d["meta"].get("env", "local"),
                                            "checkpoints": d["meta"].get("checkpoints", []), "used": 0, "steps": d["meta"].get("steps", 0), "live": None,
                                            "usage": self._code_usage(who, d["meta"]["model"])})
                s = st.code.get(user, m.group(1))
                events, state, pending = s.since(max(0, int(arg("after") or 0)))
                return self._send(200, {"events": events, "state": state, "pending": pending, "task": s.task, "project": s.project, "model": s.model_id,
                                        "env": s.env, "checkpoints": list(s.checkpoints),
                                        "used": round(s.meter.counted) if s.meter else 0, "steps": s.meter.steps if s.meter else 0,
                                        "live": s.live_view(), "usage": self._code_usage(who, s.model_id)})
            return self._send(404, {"code": "not_found", "message": "Not found."})
        except code_sessions.CodeError as e:
            self._code_error(e)

    def _review_prompt(self, st, user, sid, review):
        """The request the model gets for a code review: a GitHub pull request ({"pr": link}, read-only, with the connected token) or this session's changes."""
        pr = review.get("pr") if isinstance(review, dict) else None
        if not pr:
            return st.code.review_session(user, sid)["prompt"]
        ref = code_review.parse_pr_ref(pr)
        if not ref:
            raise code_sessions.CodeError("That isn't a pull request link.", "Paste a link like https://github.com/owner/repo/pull/12.")
        try:
            title, diff = st.github_api(user).pull_diff(*ref)
        except github_link.GitHubError as e:
            raise code_sessions.CodeError(e.message, e.action)
        files = sorted(set(re.findall(r"^diff --git a/\S+ b/(\S+)", diff, re.M)))
        cut = max(0, len(diff) - code_review.DEFAULT_LIMIT)
        return code_review.review_prompt(diff[:code_review.DEFAULT_LIMIT], files, cut, f"pull request {ref[0]}/{ref[1]}#{ref[2]}" + (f" ({title})" if title else ""))

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
                            box["fn"] = st.code_backend(model, cancel=getattr(generate, "should_stop", None))
                        except Cancelled:
                            raise vryxcode.Interrupted()
                        except AppError as e:
                            raise code_sessions.CodeError(e.message, e.action)
                    if hasattr(box["fn"], "on_delta"):
                        box["fn"].on_delta = getattr(generate, "on_delta", None)     # live progress for the page's "working" line
                        box["fn"].should_stop = getattr(generate, "should_stop", None)     # Stop works while it is still reading the prompt
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
                if browser_check.available():                                  # needs the playwright package: pip install playwright
                    tools = dict(tools or {}, check_page=st.browser_tool(user, project))
                s, note = st.code.start(user, project, body.get("task"), model["id"], generate, bool(body.get("auto_edits")),
                                        int(model.get("context_tested") or 8192), meter, outside=bool(model.get("outside")), tools=tools, identity=identity,
                                        env=str(body.get("env") or "local"), plan=bool(body.get("plan")), owner=who["admin"], queue=bool(body.get("queue")))
                return self._send(200, {"id": s.id, "note": note, "queued": s.state == "queued", "position": st.code.queue_position(user, s.id)})
            if path == "/api/code/preview":
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                folder = st.code.project_path(user, body.get("project"))
                entry = code_preview.entry_page(folder) if os.path.isdir(folder) else None
                if not entry:
                    return self._send(200, {"entry": None})
                token = st.previews.make(user, folder)
                return self._send(200, {"entry": entry, "url": f"/preview/{token}/{urllib.parse.quote(entry)}"})
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/message", path)
            if m:                                                # the next message of a conversation that is already going
                allowed, why = st.code_allowed(who)
                if not allowed:
                    raise code_sessions.CodeError(why, "Ask the owner about VryxCode access.")
                review = body.get("review")
                if review:                                           # a code review: the person sees a short line, the model gets the change (read-only, Plan-first)
                    sess = st.code.get(user, m.group(1))
                    sess.send(body.get("text") or "Review these changes", plan=True, model_text=self._review_prompt(st, user, m.group(1), review))
                    return self._send(200, {"ok": True})
                st.code.get(user, m.group(1)).send(body.get("text"), plan=bool(body.get("plan")))
                return self._send(200, {"ok": True})
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/answer", path)
            if m:
                ok = st.code.get(user, m.group(1)).respond(int(body.get("id", -1)), body.get("allow"), body.get("always"))
                return self._send(200, {"ok": ok})
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/stop", path)
            if m:
                st.code.get(user, m.group(1)).request_stop()
                return self._send(200, {"ok": True})
            if path == "/api/code/init":
                project = st.code.check_name(body.get("project"))
                return self._send(200, st.code.init_instructions(user, project))
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/rewind", path)
            if m:
                return self._send(200, st.code.rewind(user, m.group(1), int(body.get("turn", -1))))
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/delete", path)
            if m:
                st.code.delete_session(user, m.group(1))
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
        return {"user": who["user"], "owner": who["owner"], "admin": who["admin"], "founder": who["founder"], "granter": who["granter"], "plan": who["tier"], "demo": st.demo, "contact": st.security.get("contact_email") or None,
                "models": cat, "model": model["id"], "efforts": [
                    {"id": "auto", "name": "Auto", "use": "Picks for you",
                     "blurb": "Decides how long to think from your message: quick for simple questions, deeper for hard ones."},
                    {"id": "quick", "name": "Quick", "use": "Uses less", "blurb": "Answers fast and thinks briefly. Best for simple questions."},
                    {"id": "balanced", "name": "Balanced", "use": "Normal usage", "blurb": "A good mix of speed and care. The default."},
                    {"id": "deep", "name": "Deep", "use": "Uses more",
                     "blurb": "Takes longer: thinks it through and checks its work. More accurate on hard questions."}],
                "usage": snap, "window": {k: win[k] for k in ("window", "reason", "mode", "limited_by", "cache_bits", "cache_mb")},
                "chats": st.store(who["user"]).list_chats(), "settings": st.get_settings(who["user"]),
                "briefing": bool(st.get_settings(who["user"]).get("connected_apps", True) and st.links.store.connected(who["user"]) & set(app_links.BRIEF_APPS)),
                "thinking_words": list(chat_polish.THINKING_WORDS), "think_switch_s": chat_polish.THINKING_SWITCH_S,
                "pause_by_effort": chat_polish.PAUSE_BASE, "regen_options": regen_modes.menu(),
                "features": st.flags.mapping(who), "gaming": bool(st.cfg.get("gaming"))}

    def api_get_chat(self, who, cid):
        store = self.state.store(who["user"])
        if not store.exists(cid):
            return self._send(404, {"code": "not_found", "message": "That chat is gone."})
        lib = self.state.docs_for(who["user"])
        msgs = [{"id": m["id"], "role": m["role"], "content": m["content"], "model_id": m["model_id"], "status": m["status"],
                 "cut": bool((m.get("flags") or {}).get("cut")), "fb": (m.get("flags") or {}).get("fb", ""),
                 "docs": [{"id": d["id"], "name": d["name"], "kind": d["kind"]} for d in (lib.info(i) for i in m.get("docs") or []) if d]}
                for m in store.messages(cid) if not (m["status"] == "compacted" and not m["content"])]
        self._send(200, {"id": cid, "title": store.title(cid), "private": cid < 0, "skill": store.skill(cid), "messages": msgs, **store.meta(cid),
                         "generating": (who["user"], cid) in self.state.stops,
                         "docs": [d for d in (self.state.docs_for(who["user"]).info(i) for i in store.docs(cid)) if d]})

    def _finish_login(self, user, how):
        """The first step (a key, a password, an email code) is right: start the session, or ask for the authenticator code when the person turned that on."""
        st = self.state
        if st.mfa_on(user):
            return self._send(200, {"mfa": True, "ticket": st.mfa_ticket(user, how)})
        self._start_session(user, how)
        return self._send(200, {"ok": True})

    def api_password_login(self, body):
        st = self.state
        if self._locked():
            return
        ident, password = str(body.get("id", "")).strip()[:254], str(body.get("password", ""))[:400]
        key = "pw:" + ident.lower()
        wait = st.rl.blocked(key, 20, 3600)
        if wait:
            return self._send(429, {"code": "too_many", "message": "Too many wrong tries for that account.", "action": f"Wait about {max(1, wait // 60)} minute(s), or use an email code.",
                                    "retry_after": wait}, headers={"Retry-After": str(wait)})
        rec = st.check_password(ident, password)
        if not rec:
            st.rl.hit(key)
            if len(st.rl.hits) > 5000:
                st.rl.trim(3600)
            self._fail("bad password")
            return self._send(401, {"code": "bad_login", "message": "That name or password isn't right.", "action": "Check them and try again."})
        st.rl.clear(key)
        if rec.get("banned"):
            return self._send(403, {"code": "banned", "message": "This account has been turned off.", "action": "Ask the owner if you think that is a mistake."})
        return self._finish_login(rec["user"], "password")

    def api_mfa_login(self, body):
        st = self.state
        if self._locked():
            return
        res = st.mfa_finish(str(body.get("ticket", "")), str(body.get("code", "")))
        if not res:
            self._fail("bad two-step code")
            return self._send(401, {"code": "bad_code", "message": "That code isn't right, or it has run out.",
                                    "action": "Use the newest 6-digit code from your authenticator app, or one of your recovery codes."})
        user, how = res
        rec = st.user_record(user)
        if not rec or rec.get("banned"):
            return self._send(403, {"code": "banned", "message": "This account has been turned off.", "action": "Ask the owner if you think that is a mistake."})
        self._start_session(user, how + " + two-step")
        return self._send(200, {"ok": True})

    def api_signup(self, body):
        st = self.state
        mode = st.signup_mode()
        if mode == "closed":
            return self._send(403, {"code": "signups_closed", "message": "Sign-ups are closed right now.", "action": "Ask the owner for an invite code or a sign-in link."})
        ip = self._ip()
        wait = st.rl.blocked("signup:" + ip, 5, 3600)
        if wait:
            return self._send(429, {"code": "too_many", "message": "Too many accounts were made from this address.", "action": f"Try again in about {max(1, wait // 60)} minute(s).",
                                    "retry_after": wait}, headers={"Retry-After": str(wait)})
        if self._locked():
            return
        invite, tier = str(body.get("invite", "")).strip(), "free"
        if mode == "invite":
            tier = st.auth.peek_invite(invite) if invite else None
            if not tier:
                self._fail("bad invite code")
                return self._send(403, {"code": "bad_invite", "message": "That invite code isn't right, or it has run out.", "action": "Ask the owner for a new one."})
        try:
            name = st.create_account(body.get("name"), body.get("email"), str(body.get("password", "")), tier)
        except ValueError as e:
            return self._send(400, {"code": "bad_request", "message": str(e)})
        if mode == "invite":
            st.auth.use_invite(invite)
        st.rl.hit("signup:" + ip)
        self._start_session(name, "sign-up")
        return self._send(200, {"ok": True})

    # ---- the signed-in person's own account (Settings > Account and Security)
    def api_account_get(self, who):
        st = self.state
        rec = st.user_record(who["user"]) or {}
        out = {"user": who["user"], "email": rec.get("email"), "email_verified": bool(rec.get("email") and rec.get("email_verified") is not False),
               "has_password": bool(rec.get("pw")), "mfa": st.mfa_info(who["user"]), "plan": who["tier"], "owner": who["owner"], "admin": who["admin"], "founder": who["founder"], "granter": who["granter"],
               "created": rec.get("created"), "mail": bool(st.mailer), "encrypted": st.secrets.available,
               "passkeys": st.passkey_list(who["user"]), "passkeys_ok": passkeys.AVAILABLE}
        if who["admin"]:
            out["signup_mode"] = st.signup_mode()
        return self._send(200, out)

    def _reauth(self, who, body):
        """Sensitive changes ask again: the password (when there is one) and, when two-step is on, a code. Returns an error message or None."""
        st = self.state
        key = "reauth:" + who["user"]
        if st.rl.blocked(key, 10, 600):
            return "Too many wrong tries. Wait a few minutes."
        rec = st.user_record(who["user"]) or {}
        bad = None
        if rec.get("pw") and not accounts.verify_password(str(body.get("password", ""))[:400], rec["pw"]):
            bad = "That password isn't right."
        elif st.mfa_on(who["user"]) and not st.mfa_check(who["user"], str(body.get("code", ""))):
            bad = "That two-step code isn't right."
        if bad:
            st.rl.hit(key)
            st.auth.event("reauth_fail", who["user"], self._ip(), "")
        return bad

    def api_account(self, who, path, body):
        st, name = self.state, who["user"]
        bad = lambda msg, code="bad_request": self._send(400, {"code": code, "message": msg})
        if path == "/api/account/password":
            err = self._reauth(who, {"password": body.get("current"), "code": body.get("code")})
            if err:
                return bad(err, "reauth")
            try:
                st.set_password(name, str(body.get("new", "")))
            except ValueError as e:
                return bad(str(e))
            n = st.auth.revoke_user(name, who.get("session"))
            return self._send(200, {"ok": True, "signed_out_others": n})
        if path == "/api/account/email":
            err = self._reauth(who, body)
            if err:
                return bad(err, "reauth")
            try:
                st.set_email(name, body.get("email"))
            except ValueError as e:
                return bad(str(e))
            st._set_fields(name, email_verified=False)
            st.auth.event("email_changed", name, self._ip(), "")
            return self._send(200, {"ok": True})
        if path == "/api/account/email/send":
            rec = st.user_record(name) or {}
            if not st.mailer:
                return self._send(501, {"code": "email_off", "message": "Email isn't set up on this server, so addresses can't be checked.", "action": "Ask the owner."})
            if not rec.get("email") or st.rl.blocked("verify:" + name, 3, 600):
                return bad("Add an email address first, and wait a few minutes between codes.")
            st.rl.hit("verify:" + name)
            code = auth.make_code()
            st.auth.put_code(rec["email"], code)
            threading.Thread(target=lambda: st.mailer.send(rec["email"], *mailer.code_email(code)), daemon=True).start()
            return self._send(200, {"ok": True})
        if path == "/api/account/email/verify":
            rec = st.user_record(name) or {}
            if not rec.get("email") or not st.auth.check_code(rec["email"], str(body.get("code", ""))):
                return bad("That code isn't right, or it has run out.", "bad_code")
            st.mark_email_verified(name)
            return self._send(200, {"ok": True})
        if path in ("/api/account/passkey/begin", "/api/account/passkey/finish"):
            return self.api_passkey_account(who, path.rsplit("/", 1)[1], body)
        if path == "/api/account/passkey/delete":
            err = self._reauth(who, body)
            if err:
                return bad(err, "reauth")
            return self._send(200, {"ok": st.passkey_remove(name, str(body.get("id", ""))), "passkeys": st.passkey_list(name)})
        if path == "/api/account/mfa/start":
            if st.mfa_on(name):
                return bad("Two-step sign-in is already on.")
            err = self._reauth(who, body)
            if err:
                return bad(err, "reauth")
            return self._send(200, st.mfa_begin(name))
        if path == "/api/account/mfa/enable":
            codes = st.mfa_enable(name, str(body.get("code", "")))
            if not codes:
                return bad("That code isn't right. Wait for the next one in your app and try again.", "bad_code")
            n = st.auth.revoke_user(name, who.get("session"))
            return self._send(200, {"ok": True, "recovery": codes, "signed_out_others": n})
        if path == "/api/account/mfa/disable":
            if not st.mfa_on(name):
                return self._send(200, {"ok": True})
            err = self._reauth(who, body)
            if err:
                return bad(err, "reauth")
            st.mfa_disable(name)
            return self._send(200, {"ok": True})
        if path == "/api/account/mfa/recovery":
            err = self._reauth(who, body)
            if err:
                return bad(err, "reauth")
            try:
                return self._send(200, {"recovery": st.mfa_new_recovery(name)})
            except ValueError as e:
                return bad(str(e))
        return self._send(404, {"code": "not_found", "message": "Not found."})

    def api_app_link(self, who, sid, action, body):
        st, user = self.state, who["user"]
        tz = st.usage.get_user(user).get("tz_minutes", 0)
        try:
            if action == "connect":
                if st.links.store.connected(user) and sid not in st.links.store.connected(user) and len(st.links.store.connected(user)) >= 25:
                    return self._send(400, {"code": "too_many", "message": "That is a lot of connected apps already.", "action": "Disconnect one you do not use."})
                label = st.links.connect(user, sid, body.get("fields") if isinstance(body.get("fields"), dict) else {}, owner=who["owner"], tz=tz)
                st.auth.event("app_connected", user, self._ip(), sid)
                return self._send(200, {"ok": True, "label": label, "connection": st.links.store.public(user).get(sid)})
            if action == "disconnect":
                st.links.store.disconnect(user, sid)
                st.links.store.log(user, sid, "disconnected (saved secret deleted)")
                st.auth.event("app_disconnected", user, self._ip(), sid)
                return self._send(200, {"ok": True})
            q = str(body.get("query", ""))[:200]                       # "Try it": what was typed is both the search words and the question (so "tomorrow" works for a calendar)
            items = st.links.ask(user, sid, app_links.question_words(q, app_links.BY_ID[sid]), tz, q)
            return self._send(200, {"items": [{"title": i["title"], "text": i.get("text", ""), "url": i.get("url")} for i in items]})
        except app_links.LinkError as e:
            return self._send(400, {"code": "app", "message": e.message, "action": e.action})
        except KeyError:
            return self._send(404, {"code": "not_found", "message": "That app isn't in the list."})

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
        if path == "/api/admin/signups":
            mode = str(body.get("mode", ""))
            if mode not in ("closed", "invite", "open"):
                return self._send(400, {"code": "bad_request", "message": "Choose closed, invite or open."})
            st.save_security(signup_mode=mode, open_signups=(mode == "open"))
            st.auth.event("signups_changed", "owner", self._ip(), mode)
            return self._send(200, {"mode": mode})
        if path == "/api/admin/invites":
            tier = str(body.get("tier", "free"))
            if tier not in st.cfg["tiers"]:
                return self._send(400, {"code": "bad_request", "message": "Unknown plan."})
            code = st.auth.new_invite(tier, int(body.get("uses") or 1), max(1, min(int(body.get("days") or 14), 90)), str(body.get("note", "")))
            st.auth.event("invite_made", "owner", self._ip(), tier)
            return self._send(200, {"code": code, "tier": tier})
        if path == "/api/admin/invites/revoke":
            return self._send(200, {"ok": st.auth.revoke_invite(str(body.get("id", "")))})
        if path == "/api/admin/mfa-reset":
            name = str(body.get("user", ""))
            if not st.user_record(name):
                return self._send(404, {"code": "not_found", "message": "No one is called that."})
            st.mfa_disable(name)
            st.auth.revoke_user(name)
            st.auth.event("mfa_reset_by_owner", name, self._ip(), "")
            return self._send(200, {"ok": True})
        if path == "/api/admin/cloud":
            host, user = str(body.get("host", "")).strip(), str(body.get("user", "root")).strip() or "root"
            try:
                port = int(body.get("port") or 22)
            except (TypeError, ValueError):
                port = 0
            if host and not re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", host):
                return self._send(400, {"code": "bad_request", "message": "That host doesn't look right.", "action": "Use the address from your provider, like ssh5.vast.ai or 203.0.113.7."})
            if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user) or not 1 <= port <= 65535:
                return self._send(400, {"code": "bad_request", "message": "The user or port doesn't look right.", "action": "Usually the user is root and the port is the one your provider shows."})
            st.save_security(cloud_host=host, cloud_user=user, cloud_port=port, cloud_for_others=bool(body.get("for_others")))
            st.apply_cloud()
            st.auth.event("cloud_changed", "owner", self._ip(), host)
            return self._send(200, st.cloud_status())
        if path == "/api/admin/cloud/keygen":
            key, _ = st.cloud_paths()
            if os.path.exists(key) and not body.get("replace"):
                return self._send(200, st.cloud_status())
            if not shutil.which("ssh-keygen"):
                return self._send(400, {"code": "no_keygen", "message": "This computer has no ssh-keygen program.", "action": "On Windows, turn on 'OpenSSH Client' in Optional features."})
            for f in (key, key + ".pub"):
                try:
                    os.remove(f)
                except OSError:
                    pass
            os.makedirs(os.path.dirname(key), exist_ok=True)
            r = subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "emvryx-cloud", "-f", key], capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                return self._send(400, {"code": "keygen", "message": "Making the key failed: " + (r.stderr or r.stdout).strip()[-160:]})
            try:
                os.chmod(key, 0o600)
            except OSError:
                pass
            st.auth.event("cloud_key_made", "owner", self._ip(), "")
            return self._send(200, st.cloud_status())
        if path == "/api/admin/cloud/test":
            ok, why = st.code.cloud_ready(True)
            if not ok:
                return self._send(400, {"code": "cloud", "message": why})
            import cloud_run
            c = st.code.cloud
            r = None
            try:
                r = subprocess.run(cloud_run.ssh_base(c["host"], c["port"], c["user"], c["key"], c["known_hosts"]) + ["echo emvryx-ok; uname -sm; (python3 --version 2>&1 || echo 'python3: missing'); (timeout --version >/dev/null 2>&1 && echo timeout-ok || echo 'timeout: missing')"],
                                   capture_output=True, text=True, timeout=45)
            except (OSError, subprocess.SubprocessError) as e:
                return self._send(400, {"code": "cloud", "message": "Could not run ssh: " + str(e)[:120]})
            if r.returncode != 0 or "emvryx-ok" not in r.stdout:
                return self._send(400, {"code": "cloud", "message": "Could not connect: " + (r.stderr.strip()[-220:] or f"ssh exit {r.returncode}"),
                                        "action": "Check the host, port and user, and that the public key is added to the machine."})
            return self._send(200, {"ok": True, "text": r.stdout.strip()})
        if path == "/api/admin/backups/now":
            if not st.data_dir:
                return self._send(400, {"code": "no_data", "message": "This server keeps nothing on disk (demo mode), so there is nothing to back up."})
            import backup_data
            try:
                target, count, removed = backup_data.make_backup(st.data_dir, data_tools.backup_dir(st), keep=14, projects=bool(body.get("projects", True)))
            except (OSError, SystemExit) as e:
                return self._send(400, {"code": "backup_failed", "message": "The backup did not work: " + str(e)[:160]})
            st.auth.event("backup_made", "owner", self._ip(), os.path.basename(target))
            return self._send(200, {"name": os.path.basename(target), "files": count, "removed": removed})
        if path == "/api/admin/summary":
            import summary as summary_mod
            if body.get("send"):
                return self._send(200, summary_mod.deliver(st))
            built = summary_mod.build(st)
            return self._send(200, {"text": built["text"], "subject": built["subject"]})
        if path == "/api/admin/summary-settings":
            on = bool(body.get("on"))
            st.save_security(weekly_summary=on)
            if on:
                import summary as summary_mod
                if not summary_mod.last_sent(st):
                    summary_mod.set_last(st, time.time())                  # the first one comes a week after switching on
            return self._send(200, {"on": on})
        if path == "/api/admin/sharing":
            st.save_security(sharing=bool(body.get("on")))
            st.auth.event("sharing_changed", "owner", self._ip(), "on" if body.get("on") else "off")
            return self._send(200, {"on": bool(st.security.get("sharing"))})
        if path == "/api/admin/feedback/handle":
            return self._send(200, {"ok": st.feedback.set_status(body.get("id", 0), "handled" if body.get("handled", True) else "new")})
        if path == "/api/admin/sources/test":
            import web_search

            def web_check(name):
                try:
                    got = web_search.SOURCES[name]("who won the most recent world cup", 3, fetch=web_search.get_json)
                except Exception as e:
                    return False, "failed: " + str(e)[:140]
                return bool(got), (f"returned {len(got)} results" if got else "answered, but with no results")
            rows = live_data.check_sources(web_check=web_check)
            st.auth.event("sources_test", "owner", self._ip(), "")
            return self._send(200, {"rows": rows, "using": web_search.pick_source("auto")})
        if path == "/api/admin/mail-test":
            rec = st.user_record("owner") or {}
            if not st.mailer:
                return self._send(400, {"code": "email_off", "message": "Email isn't set up on this server yet.", "action": "Add EMVRYX_SMTP_HOST, EMVRYX_SMTP_USER and EMVRYX_SMTP_PASS to .emvryx\\keys.env and restart (see docs/DEPLOY.md)."})
            if not rec.get("email"):
                return self._send(400, {"code": "no_email", "message": "Your owner account has no email address yet.", "action": "Add it in Settings > Account first."})
            try:
                st.mailer.send(rec["email"], "Emvryx test email", "This is a test from your Emvryx server. If you can read it, email sign-in codes will work.")
            except Exception as e:
                return self._send(400, {"code": "mail_failed", "message": "The mail server said: " + str(e)[:160], "action": "Check the host, port, login and app password."})
            st.auth.event("mail_test", "owner", self._ip(), "")
            return self._send(200, {"ok": True, "to": rec["email"]})
        if path == "/api/admin/pause":
            st.cfg["paused"] = bool(body.get("paused"))
            return self._send(200, {"paused": st.cfg["paused"]})
        self._send(404, {"code": "not_found", "message": "Not found."})

    # ---- passkeys: the two steps of making one, and of signing in with one
    def _rp(self):
        base = self._public_base()
        p = urllib.parse.urlparse(base)
        return p.hostname or "localhost", f"{p.scheme}://{p.netloc}"

    def api_passkey_login(self, step, body):
        st = self.state
        if not passkeys.AVAILABLE:
            return self._send(501, {"code": "no_passkeys", "message": "Passkeys need the cryptography package on this server."})
        if self._locked():
            return
        rp_id, origin = self._rp()
        if step == "begin":
            return self._send(200, {"challenge": st.passkey_challenge("get"), "rpId": rp_id, "timeout": 120000, "userVerification": "required", "allowCredentials": []})
        cred = body.get("credential") if isinstance(body.get("credential"), dict) else {}
        try:
            rec, pk = st.passkey_find(str(cred.get("id", "")))
            try:
                challenge = json.loads(passkeys.unb64u(cred.get("clientDataJSON", ""))).get("challenge", "")
            except (ValueError, passkeys.PasskeyError):
                challenge = ""
            if not rec or not st.passkey_take(challenge, "get"):
                raise passkeys.PasskeyError("That passkey isn't known here, or the request ran out.")
            counter = passkeys.verify_assertion(cred, pk, challenge, origin, rp_id)
            if rec.get("banned"):
                return self._send(403, {"code": "banned", "message": "This account has been turned off.", "action": "Ask the owner if you think that is a mistake."})
        except passkeys.PasskeyError as e:
            self._fail("bad passkey")
            return self._send(401, {"code": "bad_passkey", "message": str(e), "action": "Try again, or sign in another way."})
        pk["counter"] = counter
        st._save_users()
        self._start_session(rec["user"], "passkey")                  # a passkey needs your fingerprint, face or screen lock: it is two factors already
        return self._send(200, {"ok": True})

    def api_passkey_account(self, who, step, body):
        st, name = self.state, who["user"]
        if not passkeys.AVAILABLE:
            return self._send(501, {"code": "no_passkeys", "message": "Passkeys need the cryptography package on this server.", "action": "Ask the owner to run: pip install cryptography"})
        rp_id, origin = self._rp()
        if step == "begin":
            err = self._reauth(who, body)
            if err:
                return self._send(400, {"code": "reauth", "message": err})
            have = st.user_record(name).get("passkeys", [])
            return self._send(200, {"challenge": st.passkey_challenge("create", name), "rp": {"id": rp_id, "name": "Emvryx"},
                                    "user": {"id": passkeys.b64u(hashlib.sha256(("emvryx:" + name).encode()).digest()), "name": name, "displayName": name},
                                    "pubKeyCredParams": [{"type": "public-key", "alg": passkeys.ES256}, {"type": "public-key", "alg": passkeys.RS256}],
                                    "authenticatorSelection": {"residentKey": "preferred", "userVerification": "required"}, "attestation": "none", "timeout": 120000,
                                    "excludeCredentials": [{"type": "public-key", "id": p["id"]} for p in have]})
        cred = body.get("credential") if isinstance(body.get("credential"), dict) else {}
        try:
            challenge = json.loads(passkeys.unb64u(cred.get("clientDataJSON", ""))).get("challenge", "")
        except (ValueError, passkeys.PasskeyError):
            challenge = ""
        if not st.passkey_take(challenge, "create", name):
            return self._send(400, {"code": "bad_passkey", "message": "That passkey request ran out. Start again."})
        try:
            pk = passkeys.verify_registration(cred, challenge, origin, rp_id)
        except passkeys.PasskeyError as e:
            return self._send(400, {"code": "bad_passkey", "message": str(e)})
        label = str(body.get("name") or auth.device_label(self.headers.get("User-Agent", "")))
        st.passkey_add(name, pk, label)
        return self._send(200, {"ok": True, "passkeys": st.passkey_list(name)})

    # ---- "Continue with Google"
    def _public_base(self):
        base = str(self.state.security.get("public_url") or os.environ.get("EMVRYX_PUBLIC_URL") or "").rstrip("/")
        if base:
            return base
        host = self.headers.get("Host", "localhost")
        return ("https://" if self._https() else "http://") + host

    def _redirect(self, where, cookies=()):
        for c in cookies:
            self._cookies.append(c)
        return self._send(302, b"", "text/plain", {"Location": where})

    def google_start(self, qs):
        st = self.state
        if not st.google_on():
            return self._redirect("/?gerr=off")
        if self._locked():
            return
        now = time.time()
        for k in [k for k, v in st.oauth_pending.items() if v["expires"] < now]:
            st.oauth_pending.pop(k, None)
        while len(st.oauth_pending) > 200:
            st.oauth_pending.pop(next(iter(st.oauth_pending)))
        state = secrets.token_urlsafe(24)
        verifier, challenge = google_signin.pkce()
        st.oauth_pending[auth.digest(state)] = {"verifier": verifier, "invite": str((qs.get("invite") or [""])[0])[:60], "expires": now + 600}
        redirect_uri = self._public_base() + "/auth/google/callback"
        cookie = f"emvryx_oauth={state}; Path=/auth/google; HttpOnly; SameSite=Lax; Max-Age=600" + ("; Secure" if self._https() else "")
        return self._redirect(google_signin.auth_url(os.environ["GOOGLE_CLIENT_ID"], redirect_uri, state, challenge), [cookie])

    def google_callback(self, qs):
        st = self.state
        clear = f"emvryx_oauth=; Path=/auth/google; HttpOnly; SameSite=Lax; Max-Age=0" + ("; Secure" if self._https() else "")
        fail = lambda code: self._redirect("/?gerr=" + code, [clear])
        if not st.google_on():
            return fail("off")
        if self._locked():
            return
        state = str((qs.get("state") or [""])[0])
        pending = st.oauth_pending.pop(auth.digest(state), None) if state else None
        if not pending or pending["expires"] < time.time() or not hmac.compare_digest(self._cookie_dict().get("emvryx_oauth", ""), state):
            self._fail("google: bad state")
            return fail("state")
        if (qs.get("error") or [""])[0] or not (qs.get("code") or [""])[0]:
            return fail("denied")
        status, tok = st.google_http("POST", google_signin.TOKEN_URL, google_signin.token_form(
            os.environ["GOOGLE_CLIENT_ID"], os.environ["GOOGLE_CLIENT_SECRET"], self._public_base() + "/auth/google/callback", qs["code"][0], pending["verifier"]))
        email = google_signin.email_from_id_token(tok.get("id_token", ""), os.environ["GOOGLE_CLIENT_ID"]) if status == 200 else None
        if not email:
            self._fail("google: token")
            return fail("token")
        rec = st.user_by_email(email)
        if not rec:
            if any(u.get("email") == email for u in st.users.values()):         # typed at sign-up but never verified: not taken over
                return fail("unverified")
            mode = st.signup_mode()
            if mode == "closed" or (mode == "invite" and not st.auth.peek_invite(pending["invite"])):
                return fail("closed" if mode == "closed" else "invite")
            user = st.create_email_account(email)
            if mode == "invite":
                tier = st.auth.use_invite(pending["invite"])
                if tier:
                    st.set_plan(user, tier)
            st.auth.event("signup", user, self._ip(), "google")
        else:
            if rec.get("banned"):
                return fail("banned")
            user = rec["user"]
            st.mark_email_verified(user)
        if st.mfa_on(user):
            return self._redirect("/?mfa=" + st.mfa_ticket(user, "google"), [clear])
        self._start_session(user, "google")
        return self._redirect("/", [clear])

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
        return self._finish_login(user, "email code")

    # ---- the Emvryx API: other programs (your own apps) ask a question and get an answer. Key-only, one key per app, never a browser.
    def _app_auth(self):
        """(who, record) for the app behind this request's key, or None after the right error was sent."""
        st = self.state
        if self._locked():
            return None
        h = self.headers.get("Authorization", "")
        key = h[7:].strip() if h.startswith("Bearer ") else ""
        who = st.who(key) if key else None
        if not who or not who.get("app"):
            self._fail("bad app key")
            self._send(401, {"code": "bad_key", "message": "That key isn't right.", "action": "Use the key made for this app (Admin > Apps). It starts with emvx_."})
            return None
        rec = st.app_record(who["user"]) or {}
        if who["banned"] or not rec.get("app_enabled", True):
            self._send(403, {"code": "app_off", "message": "This app has been switched off.", "action": "Ask the owner of Emvryx to switch it on."})
            return None
        return who, rec

    def _api_model_id(self, who, ref):
        """A model's id from a name (flare, equinox, solstice, apogee: the newest of that name) or an id (flare-2.5), or None."""
        cat = self.state.catalog(who)
        ref = str(ref or "").strip().lower()
        for m in cat["cards"]:
            if m["name"].lower() == ref:
                return m["id"]
        return next((m["id"] for m in cat["cards"] + cat["other"] if m["id"].lower() == ref), None)

    def api_v1_models(self):
        got = self._app_auth()
        if not got:
            return
        who, rec = got
        cat = self.state.catalog(who)
        self._send(200, {"default": rec.get("app_model", "flare"), "models": [{"name": m["name"].lower(), "id": m["id"], "label": f"{m['name']} {m['version']:g}", "state": m["state"]}
                                                                          for m in cat["cards"]]})

    def api_v1_ask(self, body):
        st = self.state
        got = self._app_auth()
        if not got:
            return
        who, rec = got
        ok, wait = st.app_rate_ok(who["user"], int(rec.get("app_rpm", 20)))
        if not ok:
            return self._send(429, {"code": "rate_limit", "message": "This app is asking too fast.", "action": f"Wait {wait} seconds and try again.", "retry_after": wait},
                              headers={"Retry-After": str(wait)})
        question = str(body.get("question") or "").strip()
        if not question:
            return self._send(400, {"code": "empty", "message": "Send a question.", "action": 'POST {"question": "..."} to /api/v1/ask.'})
        if len(question) > 8000:
            return self._send(400, {"code": "too_long", "message": "The question is too long (8,000 characters at most)."})
        facts = body.get("facts") or []
        if not isinstance(facts, list) or len(facts) > 50 or not all(isinstance(f, str) for f in facts) or sum(len(f) for f in facts) > 20000:
            return self._send(400, {"code": "bad_facts", "message": '"facts" is a list of up to 50 short texts (20,000 characters in all).'})
        history = body.get("history") or []
        if (not isinstance(history, list) or len(history) > 10 or not all(isinstance(h, dict) and h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str)
                                                                      and len(h["content"]) <= 2000 for h in history)):
            return self._send(400, {"code": "bad_history", "message": '"history" is up to 10 earlier turns: {"role": "user" or "assistant", "content": "..."} (2,000 characters each).'})
        effort = str(body.get("effort") or rec.get("app_effort", "balanced"))
        if effort not in ("auto", "quick", "balanced", "deep"):
            return self._send(400, {"code": "bad_effort", "message": "effort is auto, quick, balanced or deep."})
        if st.cfg.get("gaming"):
            status, headers, payload = U.LimitError("gaming", "Emvryx is resting while the PC is being used for something else. Please try again in a little while.", retry_after=300).to_http()
            return self._send(status, payload, headers=headers)
        model_id = self._api_model_id(who, body.get("model") or rec.get("app_model", "flare"))
        if not model_id:
            return self._send(400, {"code": "bad_model", "message": "That model isn't available to this app.", "action": "GET /api/v1/models lists them."})
        hints = [rec.get("app_instructions", ""), " ".join(str(body.get("instructions") or "").split())[:2000]]
        if facts:
            hints.append("Use only the facts in the notes for any number or figure. Quote numbers exactly as given and never calculate or invent totals. If the notes do not contain the answer, say so.")
        notes = [{"title": f"Fact {i + 1}", "text": f[:2000]} for i, f in enumerate(facts)]
        store = st.store(who["user"])
        cid = store.new_chat(private=True)                      # nothing about a call is ever saved
        for h in history:                                       # the earlier turns of a conversation the app keeps itself (Emvryx remembers nothing between calls)
            store.add(cid, h["role"], h["content"].strip() or "...")
        stream = bool(body.get("stream"))
        try:
            q, stop, model, win, decision = start_turn(st, who, cid, question, model_id, effort, pace=False, extra_notes=notes, extra_hint="\n\n".join(h for h in hints if h))
        except ValueError as e:
            store.delete_chat(cid)
            return self._send(400, {"code": "bad_option", "message": str(e)})
        except KeyError:
            store.delete_chat(cid)
            return self._send(400, {"code": "bad_model", "message": "That model isn't available to this app."})
        except Exception as e:                                 # noqa: BLE001
            store.delete_chat(cid)
            status, headers, payload = error_payload(e)
            return self._send(status, payload, headers=headers)
        st.note_app_call(who["user"])

        def finished(r):
            snap = st.usage_snapshot(who, model, decision["effort"])
            return {"answer": (r.get("text") or "").strip(), "model": f"{model['name']} {model['version']:g}", "model_id": model["id"], "effort": decision["effort"],
                    "complete": r.get("reason") in ("done", None), "usage": {"left_pct": int(snap["tank"]["pct"]), "messages_left": int(snap["tank"]["messages_left"])}}
        try:
            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                for k, v in self._security_headers().items():
                    self.send_header(k, v)
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                emit = lambda ev, data: (self.wfile.write(f"event: {ev}\ndata: {json.dumps(data)}\n\n".encode()), self.wfile.flush())
                deadline = time.monotonic() + 900
                while True:
                    try:
                        kind, val = q.get(timeout=1)
                    except queue.Empty:
                        if time.monotonic() > deadline:
                            stop.set()
                            return emit("error", {"code": "timeout", "message": "The model took too long."})
                        continue
                    if kind == "piece":
                        emit("piece", {"text": val})
                    elif kind == "done":
                        return emit("done", finished(val))
                    elif kind == "error":
                        return emit("error", error_payload(val)[2])
            deadline = time.monotonic() + 900
            while True:
                try:
                    kind, val = q.get(timeout=1)
                except queue.Empty:
                    if time.monotonic() > deadline:
                        stop.set()
                        return self._send(504, {"code": "timeout", "message": "The model took too long.", "action": "Try a shorter question or a smaller model."})
                    continue
                if kind == "done":
                    return self._send(200, finished(val))
                if kind == "error":
                    status, headers, payload = error_payload(val)
                    return self._send(status, payload, headers=headers)
        except (BrokenPipeError, ConnectionResetError):
            stop.set()
        finally:
            store.delete_chat(cid)

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
        if st.cfg.get("gaming"):                              # Gaming mode: a plain "resting" answer at once, nothing is saved or counted
            status, headers, payload = U.LimitError("gaming", "Emvryx is resting while the PC is being used for something else. Please try again in a little while.", retry_after=300).to_http()
            return self._send(status, payload, headers=headers)
        try:
            q, stop, model, win, decision = start_turn(st, who, cid, text, str(body.get("model", "")), str(body.get("effort", "balanced")),
                                             regenerate, body.get("regen_mode") or None, cont=bool(body.get("continue")))
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
                                  "title": store.title(cid), "usage": snap, "effort": decision["effort"], "auto": decision["auto"], "cut": bool(val.get("cut"))})
                    return
                else:
                    status, headers, payload = error_payload(val)
                    payload["http"] = status
                    emit("error", payload)
                    return
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass                                               # the page went away (the app was closed or switched away from): the reply keeps being written and saved, and shows when they come back


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


KEY_NAMES = ("TAVILY_API_KEY", "BRAVE_API_KEY", "GEMINI_API_KEY", "RAWG_API_KEY", "TMDB_API_KEY", "USDA_API_KEY", "FRED_API_KEY", "WOLFRAM_APPID",
             "EMVRYX_SMTP_HOST", "EMVRYX_SMTP_PORT", "EMVRYX_SMTP_USER", "EMVRYX_SMTP_PASS", "EMVRYX_MAIL_FROM", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")


def load_keys_file(path, environ=None):
    """Read API keys from a small text file (one NAME=value per line, in the app's data folder, which is never committed) into the environment, without overriding
    a key that is already set. This works the same however the app was started (a scheduled task does not always see a key set with setx). Returns the names loaded."""
    environ = os.environ if environ is None else environ
    loaded = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return loaded
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name, value = name.strip(), value.strip().strip('"').strip("'")
        if name in KEY_NAMES and value and not environ.get(name):
            environ[name] = value
            loaded.append(name)
    return loaded


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
    ap.add_argument("--vision-gguf", default=None, help="a vision model file, so pictures can be looked at (found by itself in export/open/vision)")
    ap.add_argument("--vision-mmproj", default=None, help="the picture reader (mmproj .gguf) that goes with --vision-gguf")
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
    ap.add_argument("--set-password", metavar="NAME", help="set (or change) a person's password, typed at a hidden prompt; their devices are signed out. Restart the app afterwards")
    ap.add_argument("--reset-mfa", metavar="NAME", help="turn off a person's two-step sign-in (a lost phone and no recovery codes); their devices are signed out. Restart the app afterwards")
    ap.add_argument("--rotate-key", metavar="NAME", help="give someone a new key (owner, or a name from --add-user); the old key stops working. Restart the app afterwards")
    ap.add_argument("--add-user", nargs=2, metavar=("NAME", "PLAN"), help="add a tester (free, pro or mega) and print their key")
    ap.add_argument("--make-admin", metavar="NAME_OR_EMAIL", help="give an existing account admin rights (add --plan free|pro|mega, and --unlimited for no limits). Restart the app afterwards")
    ap.add_argument("--plan", default=None, help="with --make-admin: the plan to set")
    ap.add_argument("--unlimited", action="store_true", help="with --make-admin: no usage limits")
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
        runner.memo = os.path.join(args.data, "last_model.json")
        note = gpu_note(args.llama_bin or find_llama_server(), args.llama_args.split())
        if note:
            print("Speed: " + note, flush=True)
    got = load_keys_file(os.path.join(args.data, "keys.env"))
    if got:
        print("Keys loaded from " + os.path.join(args.data, "keys.env") + ": " + ", ".join(got), flush=True)      # the names only, never the keys
    state = AppState(args.data, args.llama, args.llama_key, tok, manifest=manifest, ram_gb=args.ram, runner=runner)
    state.verbose = args.timings
    v_model, v_proj = vision.discover(HERE)
    if args.vision_gguf and args.vision_mmproj:
        v_model, v_proj = args.vision_gguf, args.vision_mmproj
    if v_model and v_proj and (args.llama_bin or find_llama_server()):
        state.vision = vision.VisionHelper(args.llama_bin or find_llama_server(), v_model, v_proj, extra_args=args.llama_args.split())
    state.code.sandbox = {"mode": args.code_sandbox, "image": args.code_image, "runtime": args.code_runtime, "cpus": args.code_cpus, "memory": args.code_memory}
    base = f"http://localhost:{args.port}"
    if args.set_password:
        import getpass
        if not state.user_record(args.set_password):
            sys.exit(f"no one is called {args.set_password!r}")
        first = getpass.getpass(f"New password for {args.set_password}: ")
        if first != getpass.getpass("Type it again: "):
            sys.exit("The two did not match. Nothing was changed.")
        try:
            state.set_password(args.set_password, first)
        except ValueError as e:
            sys.exit(str(e))
        state.auth.revoke_user(args.set_password)
        print(f"Password set for {args.set_password}. Every device that was signed in as them has been signed out. Restart the app so it reads the change.")
        return
    if args.reset_mfa:
        if not state.user_record(args.reset_mfa):
            sys.exit(f"no one is called {args.reset_mfa!r}")
        state.mfa_disable(args.reset_mfa)
        state.auth.revoke_user(args.reset_mfa)
        print(f"Two-step sign-in is off for {args.reset_mfa}. They can turn it on again in Settings > Security. Restart the app so it reads the change.")
        return
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
    if args.make_admin:
        rec = state.find_account(args.make_admin)
        if not rec:
            sys.exit(f"no account matches {args.make_admin!r}. Sign up first (or use --add-user), then run this again.")
        try:
            out = state.set_access(rec["user"], args.plan, True if args.unlimited else None, True)
        except ValueError as e:
            sys.exit(str(e))
        print(f"{out['user']}: admin rights on, plan {out['plan']}, {'no usage limits' if out['unlimited'] else 'normal usage limits'}. Restart the app so it reads the change.")
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
        state.default_place = args.weather_place or ""
        state.web_fn = lambda question, k: web_answer(question, k, place=args.weather_place)        # Auto: only when the person's setting and the question call for it
    srv = make_server(state, args.host, args.port)
    threading.Thread(target=documents.warm_ocr, daemon=True).start()          # loads the picture reader now, so the first screenshot is quick
    state.sync_gaming()
    if state.runner:
        def _idle_loop():                                    # frees the graphics card when nobody has used the model for a while, and in Gaming mode
            while True:
                time.sleep(15)
                try:
                    state.idle_tick()
                except Exception as e:                       # noqa: BLE001 - a hiccup here must never take the app down
                    print(f"(idle check failed: {e})", flush=True)
        threading.Thread(target=_idle_loop, daemon=True).start()
        if state.cfg.get("gaming"):
            print("Gaming mode is ON (Admin > PC, or delete gaming.flag in the data folder): models stay unloaded and chats say Emvryx is resting.", flush=True)
        else:
            minutes = int(state.security.get("idle_unload_minutes") or 0)
            print(f"A model nobody has used for {minutes} minutes is unloaded to free the graphics card (Admin > PC)." if minutes else "Idle unload is off (Admin > PC).", flush=True)
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
        def say_docker():                                   # in the background: Docker Desktop can take a minute to wake, and the app must answer meanwhile
            ok, why = code_sandbox.available(args.code_image)
            print(("VryxCode runs in Docker containers (no network, hard limits)." if ok else f"VryxCode sandbox NOT ready, so VryxCode will refuse to run: {why}"), flush=True)
        print("Checking Docker for VryxCode in the background...", flush=True)
        threading.Thread(target=say_docker, daemon=True).start()
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
        summary.start(state)                                # the owner's weekly summary, when switched on
        if runner and not state.cfg.get("gaming") and runner.warm_last():
            print("Loading the model you used last in the background, so your first message is quick.", flush=True)
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
