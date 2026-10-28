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
import http.server
import json
import sqlite3
import os
import re
import secrets
import socketserver
import sys
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import auth
import code_sandbox
import code_sessions
import app_links
import documents
import feedback
import updater
import vision
import flags
import model_publish
import model_guard
import github_link
import google_signin
import lookup_auto
import mailer
import secret_box
import code_secrets
import model_code_test
import chat_plus
import phone_model
import private_files
import scheduled
import web_push
import shares
import summary
import code_preview
import code_servers
import models as M
import usage_limits as U
from app_errors import AppError  # noqa: F401  (tests reach it through app_server)
from tokenizer import BPETokenizer
from open_tokenizer import OpenTokenizer  # noqa: F401  (tests reach it through app_server)
from app_shared import UNHANDLED, Cancelled, DemoBackend, HERE, KEY_NAMES, MAX_BODY, MAX_DOC_BODY, MAX_TEXT, MAX_UPLOAD, WEB, demo_tokenizer, free_memory_gb, total_memory_gb  # noqa: F401  (the app server hands these on, and uses them below)
from state_accounts import StateAccounts
from state_settings import StateSettings
from state_apps import StateApps
from state_pc import StatePC
from state_code import StateCode
from state_ops import StateOps
from routes_get import RoutesGet
from routes_post import RoutesPost
from routes_code import RoutesCode
from routes_account import RoutesAccount
from routes_admin import RoutesAdmin
from routes_chat import RoutesChat
from app_runner import ModelRunner, discover_ggufs, find_llama_server, gpu_note  # noqa: F401  (the app server hands these on, and uses them below)


class AppState(StateAccounts, StateSettings, StateApps, StatePC, StateCode, StateOps):
    def close_databases(self):
        """Close every SQLite file this state holds open (the stores, and the per-person ones in its caches). Windows cannot delete or move an
        open file, so this runs before the data folder goes away (the tests' temporary folders)."""
        seen = set()

        def shut(obj):
            for name in ("db", "conn"):
                c = getattr(obj, name, None)
                if isinstance(c, sqlite3.Connection) and id(c) not in seen:
                    seen.add(id(c))
                    try:
                        c.close()
                    except sqlite3.Error:
                        pass
        for v in list(vars(self).values()):
            shut(v)
            if isinstance(v, dict):
                for x in list(v.values()):
                    shut(x)

    def __init__(self, data_dir=None, llama_url=None, llama_key=None, tok=None, manifest=None, cfg=None, ram_gb=None,
                 backend_factory=None, clock=time.time, pace=True, runner=None, root=HERE):
        self.data_dir = data_dir                              # None = keep everything in memory (tests)
        if data_dir:
            os.makedirs(data_dir, exist_ok=True)
            private_files.lock_folder(data_dir)               # Windows: only this user may read the data folder (Linux: each file is 0600)
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
        self.app_servers = code_servers.AppServers()                  # servers VryxCode built, running sealed in a container (flag vryxcode_servers)
        self.lookups = {}                                      # (person, chat, message id) -> the notes that answer used, for the thumbs up
        self.wiki = None                                       # the local Wikipedia index (wiki_index.WikiIndex), if there is one
        self.live_net = None                                   # live_data.Net (tests pass a fake)
        self.default_place = ""                                # the weather place (--weather-place), also used for air quality
        self.web_fn = None                                     # web(question, k) -> notes; None = this server never searches the web
        self._warm_target, self._warm_thread, self._warm_lock = None, None, threading.Lock()
        self.vision = None                                     # vision.VisionHelper: describes pictures for the models (None = only the words in a picture are read)
        self.seeing = set()                                    # model ids that look at pictures themselves without a runner (tests, a remote server with --mmproj)
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
        contact = self.security.get("contact_email")
        self.push = web_push.WebPush(data_dir, self.secrets, ("mailto:" + contact) if contact else (self.security.get("public_url") or "https://emvryx.app"))   # pwa_push
        self.phone_synced = phone_model.Synced(data_dir)       # android_offline_model: phone chats already taken in (a retried sync is not added twice)
        self.phone_sha = phone_model.Checksums(data_dir)       # android_offline_model: the phone model file's checksum, worked out once
        self.schedules = scheduled.Schedules(data_dir)          # chat_schedule: messages answered by themselves at a set time
        self.panels = chat_plus.Panels()                     # chat_panel: pages from answers for the side panel's sealed frame
        self.code_test = model_code_test.Runner(os.path.join(data_dir, "code_test.json") if data_dir else None)   # model_code_test: Admin > Models
        self.code_secrets = code_secrets.ProjectSecrets(data_dir, self.secrets)      # vryxcode_secrets: per project, never shown to the model
        self.github = github_link.Store(data_dir, self.secrets)  # connected GitHub accounts (tokens encrypted, files mode 600)
        self.models_pub = model_publish.ModelPublisher(os.path.join(data_dir, "models_state.json") if data_dir else None, None, guard=self.guard_ok, file_sig=self.model_file_sig)
        self.flags = flags.Flags(os.path.join(data_dir, "flags.json") if data_dir else None)
        self.models_pub.flags = self.flags
        if data_dir and os.path.exists(os.path.join(data_dir, "ci_watch.json")):
            self.ci_watcher()                                  # VryxCode's "Watch CI" carries on after a restart
        self.updater = updater.Updater(HERE, busy=self.busy)                         # Admin > PC > Update now (owner only)
        self.guard_sheet = os.path.join(HERE, "eval", "everyday.jsonl")            # the safety checks a new model must pass before it can be published
        self.guards = model_guard.GuardStore(os.path.join(data_dir, "guard") if data_dir else None)
        self.guard_run, self._guard_lock = None, threading.Lock()    # which new features each kind of person can see (Admin > Previews)
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


    # ---- apps that use Emvryx through the API (POST /api/v1/ask): each one is a key-only account, never a person who signs in
    APP_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{1,27}")
    LOOKUP_MODES = {"none": "none", "wikipedia": "off", "auto": "auto"}          # what an app's questions may be looked up in ("none": nothing leaves this PC)


    # ---- the safety checks a new model must pass before it is published (model_guard.py)
    GUARD_USER = "emvryx-guard"


# ------------------------------------------------------------------ HTTP
def log_crash(method, path):
    """A request that failed in an unexpected way: the error and where it happened, to server.log (stderr). The address is cut at "?" so nothing
    from a query string (codes, keys) is written down."""
    import traceback
    sys.stderr.write(time.strftime("%Y-%m-%d %H:%M:%S") + f" request failed: {method} {str(path).split('?', 1)[0]}\n" + traceback.format_exc())
    sys.stderr.flush()


class Handler(RoutesGet, RoutesPost, RoutesCode, RoutesAccount, RoutesAdmin, RoutesChat, http.server.BaseHTTPRequestHandler):
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
        """Headers every answer carries. The page gets a content security policy that allows only its own script files, its own
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

    APP_PATH = re.compile(r"/preview-app/([A-Za-z0-9_-]{16,64})(?:/(.*))?")

    def _preview_app(self, method):
        """A request from the preview frame to an app VryxCode started (coding/code_servers.py): carried into its sealed container and back.
        True when this was such a request. The token in the address is the key (the sandboxed frame has no cookie and no origin)."""
        url = urllib.parse.urlparse(self.path)
        m = self.APP_PATH.fullmatch(url.path)
        if not m:
            return False
        if m.group(2) is None:                                   # /preview-app/<token>: the app's own links expect a trailing slash
            self._send_app(301, [("Location", url.path + "/")], b"")
            return True
        try:
            size = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            size = 0
        if size > code_servers.MAX_BODY:
            self._send_app(413, [("Content-Type", "text/plain; charset=utf-8")], b"That is too big to send to the app.\n")
            return True
        body = self.rfile.read(size) if size > 0 else b""
        try:
            status, headers, data = self.state.app_servers.relay(m.group(1), method, urllib.parse.unquote(m.group(2)), url.query, dict(self.headers.items()), body)
        except Exception:
            log_crash(method, self.path)
            status, headers, data = 502, [("Content-Type", "text/plain; charset=utf-8")], b"The app could not be reached.\n"
        if any(k.lower() == "content-type" and "text/html" in v.lower() for k, v in headers):
            data = code_preview.inject(data, True, root_urls=False)     # its errors reach the preview panel, storage works in the sandboxed frame
        self._send_app(status, headers, data)
        return True

    def _send_app(self, status, headers, body):
        """An app's answer for the preview frame, with the same protection as a previewed page (_send_preview)."""
        self.send_response(status)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", code_preview.PREVIEW_CSP)
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "cross-origin")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_PUT(self):
        if not self._preview_app("PUT"):
            self._send(405, {"code": "not_allowed", "message": "Not allowed."})

    def do_PATCH(self):
        if not self._preview_app("PATCH"):
            self._send(405, {"code": "not_allowed", "message": "Not allowed."})

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

    PAGE_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; manifest-src 'self'; worker-src 'self'; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")

    def _file(self, name, ctype):
        path = os.path.join(WEB, name)
        if not os.path.exists(path):
            return self._send(404, {"code": "not_found", "message": "Not found."})
        with open(path, "rb") as f:
            data = f.read()
        if name == "index.html":                      # the page has no inline script at all (its code is the files in web/js/), so only its own files may run
            return self._send(200, data, ctype, csp=self.PAGE_CSP)
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
        if path.startswith("/preview-app/") and self._preview_app("GET"):
            return
        pn = re.fullmatch(r"/panel/([A-Za-z0-9_-]{16,64})", path)
        if pn:                                                # chat_panel: the token is the key; the frame is sealed (no identity, no cookies)
            data = self.state.panels.get(pn.group(1))
            if data is None:
                return self._send_preview(404, "text/plain; charset=utf-8", b"This page is no longer kept. Open it again from the chat.\n")
            return self._send_preview(200, "text/html; charset=utf-8", code_preview.inject(data, True, root_urls=False))
        pv = re.fullmatch(r"/preview/([A-Za-z0-9_-]{16,64})/(.*)", path)
        if pv:                                                   # the live preview: a token in the address instead of the cookie (the sandboxed frame sends none)
            folder = self.state.previews.folder(pv.group(1))
            if not folder:
                return self._send(404, "This preview link has expired. Open Preview again.\n", "text/plain; charset=utf-8")
            return self._send_preview(*code_preview.serve(folder, urllib.parse.unquote(pv.group(2)), fixes=self.state.previews.fixes(pv.group(1))))
        try:
            if self.get_public(path, qs) is not UNHANDLED:
                return
            who = self._who()
            if not who:
                return
            for stage in (self.get_user, self.get_admin):
                if stage(who, path, qs) is not UNHANDLED:
                    return
            return self._send(404, {"code": "not_found", "message": "Not found."})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            log_crash(self.command, self.path)                 # what broke goes in server.log, so it can be found and fixed
            self._send(500, {"code": "error", "message": "Something went wrong. Please try again."})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/preview-app/") and self._preview_app("POST"):     # a form in the previewed app: its frame has no origin, the token is the key
            return
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
            if self.post_public(path, body) is not UNHANDLED:
                return
            who = self._who()
            if not who:
                return
            for stage in (self.post_account, self.post_chats, self.post_apps, self.post_data, self.post_admin):
                if stage(who, path, body) is not UNHANDLED:
                    return
            return self._send(404, {"code": "not_found", "message": "Not found."})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except ValueError as e:
            self._send(400, {"code": "bad_request", "message": str(e)})
        except Exception:
            log_crash(self.command, self.path)                 # what broke goes in server.log, so it can be found and fixed
            self._send(500, {"code": "error", "message": "Something went wrong. Please try again."})

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/preview-app/") and self._preview_app("DELETE"):
            return
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


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


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
        runner.manifest = manifest                                                      # models downloaded later are found without a restart
        runner.min_ctx = {m["id"]: m["code_context"] for m in manifest["models"] if m.get("code_context")}   # Apogee 3: loaded at 128K for chat too, so VryxCode never reloads it
        runner.draft_ahead = {m["id"] for m in manifest["models"] if m.get("mtp")}      # Emvryx 3 models with their guess-ahead head kept
        runner.kv8 = {m["id"] for m in manifest["models"] if m.get("cache_bits") == 8}   # long windows (256K) tested with 8-bit chat memory
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
    def _schedule_loop():                                    # chat_schedule: the scheduled tasks whose time has come
        while True:
            time.sleep(30)
            try:
                scheduled.tick(state)
            except Exception as e:                           # noqa: BLE001 - a hiccup here must never take the app down
                print(f"(scheduled tasks check failed: {e})", flush=True)
    threading.Thread(target=_schedule_loop, daemon=True).start()
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
    if shutil.which("docker"):
        threading.Thread(target=state.app_servers.cleanup, daemon=True).start()     # apps left over from before a crash or power cut are stopped
    try:
        summary.start(state)                                # the owner's weekly summary, when switched on
        if runner and not state.cfg.get("gaming") and runner.warm_last():
            print("Loading the model you used last in the background, so your first message is quick.", flush=True)
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        state.app_servers.stop_all()                               # the apps VryxCode started end with the server


if __name__ == "__main__":
    main()
