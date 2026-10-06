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
import chat
import chat_polish
import code_sessions
import vryxcode
import connected_apps
import lookup_auto
import saved_notes
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


def free_memory_gb(fallback=8.0):
    """Memory that is free right now (Linux: MemAvailable). Elsewhere: the fallback."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    return fallback


def total_memory_gb(fallback=8.0):
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    return fallback


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
        self.lookups = {}                                      # (person, chat, message id) -> the notes that answer used, for the thumbs up
        self.wiki = None                                       # the local Wikipedia index (wiki_index.WikiIndex), if there is one
        self.web_fn = None                                     # web(question, k) -> notes; None = this server never searches the web
        self._demo_tok = None
        self.usage = U.UsageStore(os.path.join(data_dir, "usage.db") if data_dir else ":memory:")
        self.limiter = U.Limiter(self.usage, self.cfg, self.manifest)
        self.stores, self.stops, self.settings = {}, {}, {}
        self.lock = threading.Lock()
        self.users = self._load_users()
        self.code = code_sessions.CodeManager(data_dir)       # VryxCode sessions (projects live under <data>/code/)
        self.code_generate = None                              # tests: code_generate(model) -> generate(messages)

    # ---- people and keys
    def _users_path(self):
        return os.path.join(self.data_dir, "users.json") if self.data_dir else None

    def _load_users(self):
        path, users = self._users_path(), {}
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                users = json.load(f)
        if not any(u.get("owner") for u in users.values()):
            users[secrets.token_urlsafe(24)] = {"user": "owner", "tier": "mega", "owner": True}
        self.users = users
        self._save_users()
        for u in users.values():
            self._ensure_usage_user(u)
        return users

    def _save_users(self):
        path = self._users_path()
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.users, f, indent=2)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass

    def _ensure_usage_user(self, u):
        try:
            self.usage.get_user(u["user"])
        except KeyError:
            self.usage.add_user(u["user"], u["tier"], u.get("tz_minutes", 0), owner=u.get("owner", False))

    def add_user(self, name, tier, tz_minutes=0):
        if tier not in self.cfg["tiers"]:
            raise ValueError(f"plan must be one of {', '.join(self.cfg['tiers'])}")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name):
            raise ValueError("a name is letters, numbers, - and _ (up to 32)")
        for k, u in self.users.items():
            if u["user"] == name:
                return k
        key = secrets.token_urlsafe(24)
        self.users[key] = {"user": name, "tier": tier, "owner": False, "tz_minutes": tz_minutes}
        self._save_users()
        self._ensure_usage_user(self.users[key])
        return key

    def rotate_key(self, name):
        """Replace a person's key with a new one (the old key stops working at once). Their chats and usage stay. Returns the new key."""
        found = [k for k, u in self.users.items() if u["user"] == name]
        if not found:
            raise ValueError(f"no one is called {name!r} (use owner, or a name you added with --add-user)")
        key = secrets.token_urlsafe(24)
        for old in found:
            self.users[key] = self.users.pop(old)
        self._save_users()
        return key

    def owner_key(self):
        return next(k for k, u in self.users.items() if u.get("owner"))

    def who(self, key):
        """The person a key belongs to, or None. Compares in constant time."""
        found = None
        for k, u in self.users.items():
            if key and hmac.compare_digest(k.encode(), key.encode()):
                found = u
        if not found:
            return None
        row = self.usage.get_user(found["user"])
        return {"user": found["user"], "owner": row["owner"], "tier": row["tier"]}

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

    def remember_lookup(self, user, chat_id, message_id, question, found):
        """Keep what an answer was written from (the last 200), so a thumbs up can save it. Private chats keep nothing."""
        if chat_id < 0 or not found["used"]:
            return
        with self.lock:
            self.lookups[(user, chat_id, message_id)] = {"question": question, "notes": found["used"], "recent": found.get("recent", False)}
            while len(self.lookups) > 200:
                self.lookups.pop(next(iter(self.lookups)))

    def get_settings(self, user):
        s = {"window_mode": "everyday", "show_tokens": False, "web_search": "auto"}
        s.update(self.settings.get(user, {}))
        return s

    def put_settings(self, user, new):
        s = self.get_settings(user)
        if new.get("window_mode") in ("everyday", "long"):
            s["window_mode"] = new["window_mode"]
        if isinstance(new.get("show_tokens"), bool):
            s["show_tokens"] = new["show_tokens"]
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
    pause = chat_polish.pause_for(question, effort)            # the thinking pause fits the message
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
            if text:                                                               # Auto lookup (lookup_auto.py)
                web_mode = state.get_settings(who["user"])["web_search"]
                notes, found = lookup_auto.gather(text, state.wiki, state.web_fn, web_mode, private=chat_id < 0,
                                                  max_notes=5 if window >= 6000 else 3,
                                                  saved=state.saved_for(who["user"]), now=state.clock())
                if found["asked"]:
                    q.put(("notes", {k: v for k, v in found.items() if k != "used"}))
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
            if found and found["asked"] and not regenerate and not found["web_tried"] and state.web_fn is not None and \
                    state.get_settings(who["user"])["web_search"] != "off" and chat_id >= 0 and lookup_auto.gave_up(r["text"]):
                # The model said it doesn't know and the web hasn't been tried: search it and answer again (the second chance)
                notes2, found2 = lookup_auto.gather(text, state.wiki, state.web_fn, "always", private=False,
                                                    max_notes=5 if window >= 6000 else 3, saved=state.saved_for(who["user"]),
                                                    now=state.clock(), force_web=True)
                if found2["web"]:
                    q.put(("notes", {k: v for k, v in found2.items() if k != "used"} | {"retry": True}))
                    msgs = [m for m in store.messages(chat_id) if m["status"] != "compacted"]
                    if msgs and msgs[-1]["role"] == "assistant":
                        store.remove_message(chat_id, msgs[-1]["id"])
                    r = E.run_turn(tok, store, chat_id, backend, counted_model, window, max_new, user_text=None, stop=stop, notes=notes2,
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

    # ---- helpers
    def _send(self, status, body=b"", ctype="application/json", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > (MAX_UPLOAD if self.path.split("?")[0] == "/api/code/import" else MAX_BODY):
            raise ValueError("too big")
        raw = self.rfile.read(n) if n else b""
        return json.loads(raw) if raw else {}

    def _key(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:].strip()
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "emvryx_key":
                return urllib.parse.unquote(v)
        return None

    def _who(self):
        who = self.state.who(self._key())
        if not who:
            self._send(401, {"code": "bad_key", "message": "That key isn't right.",
                             "action": "Open the link the server printed, or ask the owner for your key."})
        return who

    def _cookie(self, key):
        return {"Set-Cookie": f"emvryx_key={urllib.parse.quote(key)}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000"}

    def _file(self, name, ctype):
        path = os.path.join(WEB, name)
        if not os.path.exists(path):
            return self._send(404, {"code": "not_found", "message": "Not found."})
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    # ---- routes
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        path, qs = url.path, urllib.parse.parse_qs(url.query)
        try:
            if path == "/":
                key = (qs.get("key") or [None])[0]
                if key and self.state.who(key):                 # the printed link: remember the key, then drop it from the URL
                    return self._send(302, b"", "text/plain", {"Location": "/", **self._cookie(key)})
                return self._file("index.html", "text/html; charset=utf-8")
            if path == "/manifest.webmanifest":
                return self._file("manifest.webmanifest", "application/manifest+json")
            if path == "/sw.js":
                return self._file("sw.js", "text/javascript")
            if path == "/icon.svg":
                return self._file("icon.svg", "image/svg+xml")
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
                return self._send(200, connected_apps.catalog())
            if path == "/api/saved-notes":
                return self._send(200, {"notes": self.state.saved_for(who["user"]).list(self.state.clock())})
            if path.startswith("/api/code"):
                return self.api_code_get(who, path, qs)
            if path == "/api/admin/users" and who["owner"]:
                return self._send(200, {"users": [{"user": u["user"], "tier": self.state.usage.get_user(u["user"])["tier"]}
                                                  for u in self.state.users.values()], "paused": bool(self.state.cfg.get("paused"))})
            return self._send(404, {"code": "not_found", "message": "Not found."})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self._send(500, {"code": "error", "message": "Something went wrong. Please try again."})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            body = self._json()
            if path == "/api/login":
                key = str(body.get("key", "")).strip()
                if not self.state.who(key):
                    return self._send(401, {"code": "bad_key", "message": "That key isn't right.",
                                            "action": "Check it and try again."})
                return self._send(200, {"ok": True}, headers=self._cookie(key))
            who = self._who()
            if not who:
                return
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

    def api_code_get(self, who, path, qs):
        st, user = self.state, who["user"]
        arg = lambda k: (qs.get(k) or [""])[0]
        try:
            if path == "/api/code":
                run = st.code.running(user)
                return self._send(200, {"usage": self._code_usage(who, None), "models": st.code_models(who), "projects": st.code.projects(user),
                                        "running": run.id if run else None, "project": run.project if run else None})
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
                                        "usage": self._code_usage(who, s.model_id)})
            return self._send(404, {"code": "not_found", "message": "Not found."})
        except code_sessions.CodeError as e:
            self._code_error(e)

    def api_code_post(self, who, path, body):
        st, user = self.state, who["user"]
        try:
            if path == "/api/code/start":
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
                    reply = box["fn"](messages)
                    generate.usage = getattr(box["fn"], "usage", None)      # the real counts, for the usage meter
                    return reply
                snap = st.limiter.snapshot(user, model["limiter_key"], "balanced", st.clock())
                if not snap["exempt"] and snap["can_send"] < 1:
                    raise code_sessions.CodeError("Your usage has run out for now.", "Coding steps are counted like chat messages. Wait for the tank to refill or the week to reset.")
                meter = code_sessions.Meter(st.limiter, user, model["limiter_key"], st.clock)
                s, note = st.code.start(user, project, body.get("task"), model["id"], generate, bool(body.get("auto_edits")),
                                        int(model.get("context_tested") or 8192), meter, outside=bool(model.get("outside")))
                return self._send(200, {"id": s.id, "note": note})
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/answer", path)
            if m:
                ok = st.code.get(user, m.group(1)).respond(int(body.get("id", -1)), body.get("allow"), body.get("always"))
                return self._send(200, {"ok": ok})
            m = re.fullmatch(r"/api/code/sessions/([\w-]+)/stop", path)
            if m:
                st.code.get(user, m.group(1)).request_stop()
                return self._send(200, {"ok": True})
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
        return {"user": who["user"], "owner": who["owner"], "plan": who["tier"], "demo": st.demo,
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
            key = st.add_user(name, tier)
            st.set_plan(name, tier)
            return self._send(200, {"user": name, "tier": tier, "key": key})
        if path == "/api/admin/pause":
            st.cfg["paused"] = bool(body.get("paused"))
            return self._send(200, {"paused": st.cfg["paused"]})
        self._send(404, {"code": "not_found", "message": "Not found."})

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
    if args.rotate_key:
        try:
            key = state.rotate_key(args.rotate_key)
        except ValueError as e:
            sys.exit(str(e))
        print(f"{args.rotate_key}: http://localhost:{args.port}/?key={key}")
        print("The old key no longer works. Restart the app so it reads the new key.")
        return
    if args.add_user:
        key = state.add_user(*args.add_user)
        print(f"{args.add_user[0]} ({args.add_user[1]}): http://localhost:{args.port}/?key={key}")
        return
    if os.path.exists(args.wiki):
        from wiki_index import WikiIndex
        state.wiki = lookup_auto.LockedWiki(WikiIndex(args.wiki))
        print(f"Looking things up in the Wikipedia index {args.wiki}")
    else:
        print(f"No Wikipedia index at {args.wiki}: answers come from the model's memory (see wiki_index.py)")
    if not args.no_web:
        from web_search import web_notes
        state.web_fn = lambda question, k: web_notes(question, k)        # Auto: only when the person's setting and the question call for it
    srv = make_server(state, args.host, args.port)
    shown = "localhost" if args.host in ("127.0.0.1", "0.0.0.0") else args.host
    if state.demo:
        print("Emvryx is running in DEMO mode (no model files found; see docs/V2.md to make a .gguf)")
    else:
        print("Emvryx is running. Models on this computer: " + (", ".join(sorted(files)) or "none") + (" (via --llama)" if args.llama else ""))
        if runner and not runner.bin:
            print("llama-server was not found. Install llama.cpp and pass --llama-bin <path to llama-server.exe>.")
    print(f"Open: http://{shown}:{args.port}/?key={state.owner_key()}")
    if args.host == "0.0.0.0":
        print("Reachable from your network. Anyone with a key can use it; keep keys private.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
