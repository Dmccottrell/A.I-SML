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
import os
import re
import secrets
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import auth
import data_tools
import code_sandbox
import code_sessions
import app_skills
import export_doc
import teacher_mode
import app_links
import connected_apps
import documents
import feedback
import updater
import vision
import live_data
import flags
import model_publish
import model_guard
import github_link
import google_signin
import lookup_auto
import mailer
import passkeys
import secret_box
import shares
import summary
import code_preview
import models as M
import usage_limits as U
from app_errors import AppError  # noqa: F401  (tests reach it through app_server)
from tokenizer import BPETokenizer
from open_tokenizer import OpenTokenizer  # noqa: F401  (tests reach it through app_server)
from app_shared import APP_PREFIX, BACKUP_NAME, Cancelled, DemoBackend, HERE, KEY_NAMES, MAX_BODY, MAX_DOC_BODY, MAX_TEXT, MAX_UPLOAD, PAIR_PAGE, WEB, demo_tokenizer, free_memory_gb, total_memory_gb  # noqa: F401  (the app server hands these on, and uses them below)
from state_accounts import StateAccounts
from state_settings import StateSettings
from state_apps import StateApps
from state_pc import StatePC
from state_code import StateCode
from state_ops import StateOps
from routes_code import RoutesCode
from routes_account import RoutesAccount
from routes_admin import RoutesAdmin
from routes_chat import RoutesChat
from app_runner import ModelRunner, discover_ggufs, find_llama_server, gpu_note  # noqa: F401  (the app server hands these on, and uses them below)


class AppState(StateAccounts, StateSettings, StateApps, StatePC, StateCode, StateOps):
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
        self.updater = updater.Updater(HERE, busy=self.busy)                         # Admin > PC > Update now (owner only)
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


    # ---- apps that use Emvryx through the API (POST /api/v1/ask): each one is a key-only account, never a person who signs in
    APP_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{1,27}")
    LOOKUP_MODES = {"none": "none", "wikipedia": "off", "auto": "auto"}          # what an app's questions may be looked up in ("none": nothing leaves this PC)


    # ---- the safety checks a new model must pass before it is published (model_guard.py)
    GUARD_USER = "emvryx-guard"


# ------------------------------------------------------------------ HTTP
class Handler(RoutesCode, RoutesAccount, RoutesAdmin, RoutesChat, http.server.BaseHTTPRequestHandler):
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
            if path == "/editor.js":                      # the VryxCode editor (a plain script of its own, so the page's one inline script stays the only inline one)
                return self._file("editor.js", "text/javascript; charset=utf-8")
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
            if path == "/api/admin/update" and who["owner"]:
                try:
                    return self._send(200, self.state.updater.check())
                except updater.UpdateError as e:
                    return self._send(200, {"can_update": False, "reason": e.message, "incoming": [], "dirty": []})
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
                if path == "/api/admin/update":                                   # pull the newest main and restart: only the PC owner, and only the change they were shown
                    if not who["owner"]:
                        return self._send(403, {"code": "owner_only", "message": "Only the PC owner can update Emvryx.", "action": "Nothing was changed."})
                    try:
                        res = self.state.updater.apply(str(body.get("expected", "")), force=bool(body.get("force")))
                    except updater.UpdateError as e:
                        return self._send(409 if e.code in ("busy", "changed") else 400, {"code": e.code, "message": e.message, "action": e.action or "Nothing was changed."})
                    self.state.auth.event("update_applied", who["user"], self._ip(), f"{res['from']} -> {res['to']} ({res['changes']} changes, restarting={res['restarting']})")
                    return self._send(200, res)
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
                            self.state.start_guard(mid, by=by)
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
