"""
app_server.py - The Yuvra app server: a browser chat page that talks to a model, with plans, usage and the device check.

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
import hmac
import http.server
import json
import os
import queue
import re
import secrets
import socketserver
import sys
import threading
import time
import urllib.parse

import app_engine as E
import chat
import chat_polish
import context_window as CW
import models as M
import usage_limits as U
from app_errors import AppError, ModelTooBig, PcUnreachable
from tokenizer import BPETokenizer

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
MAX_BODY = 1_000_000
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


# ------------------------------------------------------------------ everything the server holds
class AppState:
    def __init__(self, data_dir=None, llama_url=None, llama_key=None, tok=None, manifest=None, cfg=None, ram_gb=None,
                 backend_factory=None, clock=time.time, pace=True):
        self.data_dir = data_dir                              # None = keep everything in memory (tests)
        if data_dir:
            os.makedirs(data_dir, exist_ok=True)
        self.manifest = manifest or M.load_manifest()
        self.cfg = cfg or U.load_limits()
        self.tok = tok or demo_tokenizer()
        self.llama_url, self.llama_key = llama_url, llama_key
        self.backend_factory = backend_factory
        self.ram_gb = ram_gb or total_memory_gb()
        self.clock, self.pace = clock, pace
        self.usage = U.UsageStore(os.path.join(data_dir, "usage.db") if data_dir else ":memory:")
        self.limiter = U.Limiter(self.usage, self.cfg, self.manifest)
        self.stores, self.stops, self.settings = {}, {}, {}
        self.lock = threading.Lock()
        self.users = self._load_users()

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

    def get_settings(self, user):
        s = {"window_mode": "everyday", "show_tokens": False}
        s.update(self.settings.get(user, {}))
        return s

    def put_settings(self, user, new):
        s = self.get_settings(user)
        if new.get("window_mode") in ("everyday", "long"):
            s["window_mode"] = new["window_mode"]
        if isinstance(new.get("show_tokens"), bool):
            s["show_tokens"] = new["show_tokens"]
        self.settings[user] = s
        return s

    # ---- models
    def catalog(self, who):
        """The picker's cards, one per name (Flare, Equinox, Solstice, Apogee), newest usable version first.
        state: ready | locked (not in the plan) | too_big (this computer is too small) | soon (not built yet)."""
        plan = self.cfg["tiers"][who["tier"]]["models"]
        cards = []
        for name in M.NAMES:
            versions = sorted((m for m in self.manifest["models"] if m["name"] == name and m["status"] != "off"),
                              key=lambda m: -m["version"])
            if not versions:
                continue
            usable = [m for m in versions if m["status"] != "planned"]
            m = dict((usable or versions)[0])
            if m["status"] == "planned":
                m["state"], m["badge"] = "soon", "Coming soon"
            elif not who["owner"] and plan != "all" and name.lower() not in plan:
                m["state"], m["badge"] = "locked", "Not in your plan"
            elif self.ram_gb < m["min_ram_gb"]:
                m["state"], m["badge"] = "too_big", f"Needs {m['min_ram_gb']} GB of memory"
            else:
                m["state"], m["badge"] = "ready", "Beta" if m["status"] == "beta" else "Ready"
            cards.append(m)
        return {"cards": cards, "other": []}

    def pick_model(self, who, model_id):
        for m in self.catalog(who)["cards"]:
            if m["id"] == model_id:
                return m
        raise KeyError(model_id)

    def window_for(self, who, model, mode=None):
        mode = mode or self.get_settings(who["user"])["window_mode"]
        plan = self.cfg["tiers"][who["tier"]]["windows"]
        device = CW.Device(self.ram_gb, min(self.ram_gb, free_memory_gb(self.ram_gb)))
        return CW.pick(model, device, mode, None if who["owner"] else plan)

    def backend_for(self, model, question):
        if self.backend_factory:
            return self.backend_factory(model, question)
        if self.llama_url:
            return E.LlamaServer(self.llama_url, self.llama_key, temperature=TEMPERATURE["balanced"])
        return DemoBackend(question)

    # ---- the numbers on screen
    def usage_snapshot(self, who, model, effort):
        key = model["name"].lower() if model else "flare"
        snap = self.limiter.snapshot(who["user"], key, effort, self.clock())
        snap["models"] = snap.pop("by_model")
        return snap


# ------------------------------------------------------------------ one message, streamed to the browser
def start_turn(state, who, chat_id, text, model_id, effort, regenerate=False):
    """Begin a reply in a worker thread. Returns (queue, stop_event); the queue yields ("piece", text), then
    ("done", result) or ("error", exception)."""
    store = state.store(who["user"])
    model = state.pick_model(who, model_id)
    if model["state"] == "too_big":
        raise ModelTooBig(model, state.ram_gb, None)
    if model["state"] != "ready":
        raise U.LimitError("model_unavailable", f"{model['name']}: {model['badge']}.")
    if effort not in EFFORTS:
        raise U.LimitError("bad_effort", "Pick Quick, Balanced or Deep.")
    if effort == "deep" and model["name"] == "Flare":
        raise U.LimitError("deep_needs_bigger", "Deep needs Equinox or a bigger model.", choices=["equinox"])
    win = state.window_for(who, model)
    if not win["fits"]:
        raise AppError("There isn't enough free memory for this model.", "Close other apps or pick a smaller model.")
    window, max_new = win["window"], min(EFFORTS[effort], max(32, win["window"] // 2))
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
    backend = state.backend_for(model, text or "")

    def pacer(stream):
        gen = chat_polish.paced(stream, start=started) if state.pace else stream
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
            r = E.run_turn(state.tok, store, chat_id, backend, counted_model, window, max_new, user_text=text, stop=stop,
                           limiter=state.limiter, user=who["user"], effort=effort, clock=state.clock, pacer=pacer)
            if text and store.title(chat_id) == "New chat":
                store.set_title(chat_id, " ".join(text.split())[:48] or "New chat")
            q.put(("done", r))
        except BaseException as e:                              # sent to the page as an error event
            q.put(("error", e))
        finally:
            state.stops.pop(key, None)

    threading.Thread(target=work, daemon=True).start()
    return q, stop, model, win


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
    server_version = "Yuvra"
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
        if n > MAX_BODY:
            raise ValueError("too big")
        raw = self.rfile.read(n) if n else b""
        return json.loads(raw) if raw else {}

    def _key(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:].strip()
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "yuvra_key":
                return urllib.parse.unquote(v)
        return None

    def _who(self):
        who = self.state.who(self._key())
        if not who:
            self._send(401, {"code": "bad_key", "message": "That key isn't right.",
                             "action": "Open the link the server printed, or ask the owner for your key."})
        return who

    def _cookie(self, key):
        return {"Set-Cookie": f"yuvra_key={urllib.parse.quote(key)}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000"}

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
            if path == "/api/settings":
                return self._send(200, self.state.put_settings(who["user"], body))
            if path == "/api/delete-everything":
                self.state.store(who["user"]).delete_everything()
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

    # ---- the API
    def api_state(self, who, qs):
        st = self.state
        cat = st.catalog(who)
        model_id = (qs.get("model") or [None])[0]
        effort = (qs.get("effort") or ["balanced"])[0]
        effort = effort if effort in EFFORTS else "balanced"
        pool = {m["id"]: m for m in cat["cards"]}
        default = next((m for m in cat["cards"] if m["state"] == "ready"), cat["cards"][0])
        model = pool.get(model_id) or default
        snap = st.usage_snapshot(who, model, effort)
        win = st.window_for(who, model)
        return {"user": who["user"], "owner": who["owner"], "plan": who["tier"], "demo": not (st.llama_url or st.backend_factory),
                "models": cat, "model": model["id"], "efforts": [
                    {"id": "quick", "name": "Quick", "use": "Uses less", "blurb": "Answers fast and thinks briefly. Best for simple questions."},
                    {"id": "balanced", "name": "Balanced", "use": "Normal usage", "blurb": "A good mix of speed and care. The default."},
                    {"id": "deep", "name": "Deep", "use": "Uses more",
                     "blurb": "Takes longer: thinks it through and checks its work. More accurate on hard questions."}],
                "usage": snap, "window": {k: win[k] for k in ("window", "reason", "mode", "limited_by", "cache_bits", "cache_mb")},
                "chats": st.store(who["user"]).list_chats(), "settings": st.get_settings(who["user"]),
                "thinking_words": list(chat_polish.THINKING_WORDS), "think_switch_s": chat_polish.THINKING_SWITCH_S,
                "min_first_s": chat_polish.MIN_FIRST_S}

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
            q, stop, model, win = start_turn(st, who, cid, text, str(body.get("model", "")), str(body.get("effort", "balanced")),
                                             regenerate)
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
            emit("thinking", {"min_first_s": chat_polish.MIN_FIRST_S})
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
                if kind == "piece":
                    emit("piece", {"t": val})
                elif kind == "done":
                    snap = st.usage_snapshot(who, model, str(body.get("effort", "balanced")))
                    emit("done", {"reason": val["reason"], "compacted": val["compacted_messages"],
                                  "forgotten": val["forgotten_messages"], "message_id": val["message_id"],
                                  "title": store.title(cid), "usage": snap})
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
    ap.add_argument("--data", default=".yuvra", help="where chats, usage and keys are kept")
    ap.add_argument("--llama", default=None, help="URL of a llama-server (llama.cpp) running the model")
    ap.add_argument("--llama_key", default=None)
    ap.add_argument("--tokenizer", default=None, help="the model's tokenizer.json (needed with --llama)")
    ap.add_argument("--ram", type=float, default=None, help="this computer's memory in GB (default: detected)")
    ap.add_argument("--add-user", nargs=2, metavar=("NAME", "PLAN"), help="add a tester (free, pro or mega) and print their key")
    args = ap.parse_args()
    if args.llama and not args.tokenizer:
        sys.exit("With --llama you also need --tokenizer data/<version>/tokenizer.json (the model's own tokenizer).")
    tok = BPETokenizer.load(args.tokenizer) if args.tokenizer else None
    state = AppState(args.data, args.llama, args.llama_key, tok, ram_gb=args.ram)
    if args.add_user:
        key = state.add_user(*args.add_user)
        print(f"{args.add_user[0]} ({args.add_user[1]}): http://localhost:{args.port}/?key={key}")
        return
    srv = make_server(state, args.host, args.port)
    shown = "localhost" if args.host in ("127.0.0.1", "0.0.0.0") else args.host
    print("Yuvra is running" + ("" if args.llama else " in DEMO mode (no model attached; use --llama)"))
    print(f"Open: http://{shown}:{args.port}/?key={state.owner_key()}")
    if args.host == "0.0.0.0":
        print("Reachable from your network. Anyone with a key can use it; keep keys private.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
