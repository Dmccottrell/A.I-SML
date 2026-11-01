"""
routes_get.py - The web routes for reading (GET): pages and files, what a person can read, and what the admins can read. Each part returns UNHANDLED when the address is not one of its own, and the next part is tried.

Where it fits: app_server.py builds its request handler from several "mixin" classes (small classes that each add a group of methods).
For a GET request it calls `get_public` (no sign-in needed), then `get_user` (signed-in people), then `get_admin` (owner/admins), until one of them
answers. A "route" is one web address handled by one `if path == ...` block. `path` is the address without its query string, and `qs` is the
query string parsed into a dict of lists (so ?q=hi becomes {"q": ["hi"]}). `self._send(status, data)` writes the answer.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
# Standard library: json (data as text), re (regular expressions = text patterns).
# The rest are project modules, each providing the data for one kind of route (documents, feedback, updates, flags, shares...).
import json
import re
import data_tools
import app_skills
import teacher_mode
import app_links
import connected_apps
import documents
import feedback
import updater
import crash_log
import chat_plus
import phone_model
import code_log
import model_code_test
import live_data
import flags
import passkeys
import shares
# BACKUP_NAME: a regex that only real backup file names match. PAIR_PAGE: the HTML for the 'pair this device' button page.
# UNHANDLED: a marker value meaning 'not my address, try the next part'.
from app_shared import BACKUP_NAME, PAIR_PAGE
from app_shared import UNHANDLED



# The folder with the website files (web/), found relative to this file (os.pardir = the parent folder).
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "web")


def shell_files():
    """What the installed app keeps for opening offline: the page, its styles, every script in web/js (a new one is included by itself), icons."""
    # All script files in web/js, so a new script is picked up without changing this list.
    js = sorted(n for n in os.listdir(os.path.join(WEB_DIR, "js")) if n.endswith(".js"))
    # The addresses the installed app saves so it can open without the network.
    return ["/", "/editor.js", "/vryx.css", "/modern.css"] + ["/js/" + n for n in js] + ["/icon.svg", "/icon-192.png", "/manifest.webmanifest"]


def shell_version():
    """Changes whenever one of those files changes (after an update), so the installed app takes the new ones and can say so."""
    # Imported here, only when this function runs.
    import hashlib
    # A hash is a short fingerprint of data; if any input changes, the fingerprint changes. (SHA-1 is fine here: it is only a change detector, not security.)
    h = hashlib.sha1()
    # Go through every file of the app shell (leading slash removed so the names are paths inside web/).
    for p in ["index.html", "sw.js"] + [x.lstrip("/") for x in shell_files() if x != "/"]:
        try:
            # Size and last-changed time of the file.
            st = os.stat(os.path.join(WEB_DIR, p))
            # Mix the name, change time (in nanoseconds) and size into the fingerprint.
            h.update(f"{p}:{st.st_mtime_ns}:{st.st_size};".encode())
        # A file that is missing is simply skipped.
        except OSError:
            continue
    # The first 12 characters of the fingerprint are enough as a version label.
    return h.hexdigest()[:12]

class RoutesGet:
    """The GET routes."""

    def get_public(self, path, qs):
        """The pages, files and few public answers that need no sign-in."""
        # The home page.
        if path == "/":
            # An old way to sign in: a key put in the address. qs values are lists, so take the first.
            key = (qs.get("key") or [None])[0]
            # Refused unless the owner allowed it: addresses end up in browser history and logs.
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
        # Regex: /pair/ followed by a token of 16 to 80 letters, digits, dashes or underscores; the token is group 1.
        m = re.fullmatch(r"/pair/([A-Za-z0-9_-]{16,80})", path)
        if m:                                                # a pairing link: show a button; only the button (a POST) uses it up
            if self._locked():
                return
            # Look at the pairing token without using it up. Only the button on the page (a POST) uses it, so link-preview robots cannot burn it.
            user = self.state.auth.peek_pair(m.group(1))
            who = self.state.who_name(user) if user else None
            if who and not who["banned"]:
                # Fill the token into the page. The csp (Content-Security-Policy) header tells the browser what the page may load; here almost nothing, which keeps the page safe.
                return self._send(200, PAIR_PAGE.replace("{{token}}", m.group(1)).encode(), "text/html; charset=utf-8",
                                  csp="default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
            self._fail("bad pairing link")
            # 410 = 'Gone'.
            return self._send(410, "This pairing link was already used or has expired. Ask for a new one.\n", "text/plain; charset=utf-8")
        # The model list for other programs (it checks the app key itself).
        if path == "/api/v1/models":
            return self.api_v1_models()
        # A public status answer for the website.
        if path == "/api/status":                          # for the website's "is Emvryx on?" line and its Open page: harmless, no sign-in, readable from the website
            st = self.state
            # Count ready models, using a made-up 'viewer' record (no real person) so no sign-in is needed.
            ready = sum(1 for m in st.catalog({"user": "", "owner": True, "tier": "mega", "banned": False})["cards"] if m["state"] == "ready")
            return self._send(200, {"up": True, "paused": bool(st.cfg.get("paused")), "resting": bool(st.cfg.get("gaming")), "demo": bool(st.demo), "models_ready": ready, "signup": st.signup_mode()},
                              # Allow any website to read this harmless answer (CORS), and never cache it.
                              headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})
        # Tells the sign-in page which sign-in methods to offer.
        if path == "/api/auth-options":
            return self._send(200, {"email": bool(self.state.mailer), "signups": bool(self.state.mailer and self.state.security["open_signups"]),
                                    "password": True, "signup": self.state.signup_mode(), "google": self.state.google_on(), "passkeys": passkeys.AVAILABLE})
        # A shared chat link: /s/<token>.
        ms = re.fullmatch(r"/s/([A-Za-z0-9_-]{16,80})", path)
        if ms:                                              # a shared chat: no sign-in, a copy of the words only
            if self._locked():
                return
            # The saved copy of the chat, only if sharing is switched on.
            snap = self.state.shares.get(ms.group(1)) if self.state.security.get("sharing") else None
            if not snap:
                self._fail("bad share link")
                return self._send(404, "This link doesn't work any more: it expired, was cancelled, or sharing was switched off.\n", "text/plain; charset=utf-8")
            # Show it as a simple page with a locked-down security policy.
            return self._send(200, shares.render(snap).encode("utf-8"), "text/html; charset=utf-8",
                              csp="default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
        # 'Continue with Google' (handled in routes_account.py).
        if path == "/auth/google/start":
            return self.google_start(qs)
        if path == "/auth/google/callback":
            return self.google_callback(qs)
        # path[1:] drops the leading slash: /privacy becomes privacy.html.
        if path in ("/privacy", "/terms"):
            return self._file(path[1:] + ".html", "text/html; charset=utf-8")
        if path == "/manifest.webmanifest":
            return self._file("manifest.webmanifest", "application/manifest+json")
        # The service worker (the script that lets the installed app work offline).
        if path == "/sw.js":                          # the offline list and the version are worked out from the files themselves
            with open(os.path.join(WEB_DIR, "sw.js"), encoding="utf-8") as f:
                # Fill the placeholders in the file: the version fingerprint and the list of files (as JSON text, with double quotes swapped for single so it fits inside the script's string).
                body = f.read().replace("__VERSION__", shell_version()).replace("__FILES__", json.dumps(shell_files()).replace('"', "'"))
            return self._send(200, body.encode(), "text/javascript")
        # Regex: /js/<name>.js with a simple name (letters, digits, dash, underscore). The tight pattern means a path like ../ can never reach other files.
        mjs = re.fullmatch(r"/js/([a-z0-9_-]{1,40})\.js", path)
        if mjs:                                       # the page's own script files (web/js/): one file per part of the app
            return self._file("js/" + mjs.group(1) + ".js", "text/javascript; charset=utf-8")
        if path == "/editor.js":                      # the VryxCode editor (a plain script of its own, like the files in web/js/)
            return self._file("editor.js", "text/javascript; charset=utf-8")
        if path == "/modern.css":
            return self._file("modern.css", "text/css; charset=utf-8")
        if path == "/vryx.css":                       # VryxCode's own look (violet, glass panels), loaded after the page's styles
            return self._file("vryx.css", "text/css; charset=utf-8")
        if path == "/icon.svg":
            return self._file("icon.svg", "image/svg+xml")
        # Only these exact icon names are served.
        if path in ("/icon-192.png", "/icon-512.png", "/icon-maskable-512.png", "/apple-touch-icon.png"):
            return self._file(path[1:], "image/png")
        # A non-API address that nothing matched is a 404. API addresses fall through to the sign-in checked parts.
        if not path.startswith("/api/"):
            return self._send(404, {"code": "not_found", "message": "Not found."})
        # Not one of ours.
        return UNHANDLED

    def get_user(self, who, path, qs):
        """What a signed-in person can read: their state, chats, documents, settings, memory, account and devices."""
        # The big 'everything the page needs' answer (see routes_chat.py).
        if path == "/api/state":
            return self._send(200, self.api_state(who, qs))
        # The morning briefing from connected apps (calendar and so on); empty if the person switched that off.
        if path == "/api/briefing":
            if not self.state.get_settings(who["user"]).get("connected_apps", True):
                return self._send(200, {"sections": [], "off": True})
            return self._send(200, app_links.briefing(self.state.links, who["user"], self.state.usage.get_user(who["user"]).get("tz_minutes", 0)))
        # The person's own shared chat links.
        if path == "/api/shares":
            return self._send(200, {"shares": self.state.shares.list(who["user"]), "on": bool(self.state.security.get("sharing"))})
        # Archived chats.
        if path == "/api/chats/archived":
            return self._send(200, {"chats": self.state.store(who["user"]).list_chats(archived=True)})
        # Search through the person's own chats.
        if path == "/api/chats/search":
            return self._send(200, {"results": self.state.store(who["user"]).search((qs.get("q") or [""])[0])})
        # Regex: a chat id, which may be negative (-? = optional minus sign; private chats use negative ids), then /followups.
        m = re.fullmatch(r"/api/chats/(-?\d+)/followups", path)
        if m and self.state.flags.on("chat_followups", who):          # what to ask next, from the last answer (no model time)
            store = self.state.store(who["user"])
            cid = int(m.group(1))
            if not store.exists(cid):
                return self._send(404, {"code": "not_found", "message": "That chat is gone."})
            # Real messages only (not squeezed-away ones).
            msgs = [x for x in store.messages(cid) if x["status"] != "compacted" and x["content"]]
            # Walk from the end to find the latest answer and the latest question.
            ans = next((x for x in reversed(msgs) if x["role"] == "assistant"), None)
            q = next((x["content"] for x in reversed(msgs) if x["role"] == "user"), "")
            return self._send(200, {"items": chat_plus.followups(q, ans["content"]) if ans and ans["status"] == "done" else []})
        # Browser push notifications.
        if path == "/api/push" and self.state.flags.on("pwa_push", who):              # pwa_push: the server's public key for the browser to subscribe with
            return self._send(200, {"key": self.state.push.public_key(), "devices": self.state.push.subscribed(who["user"])})
        if path == "/api/schedules" and self.state.flags.on("chat_schedule", who):       # chat_schedule: this person's scheduled tasks
            return self._send(200, {"tasks": self.state.schedules.list(who["user"])})
        if path == "/api/phone-model" and self.state.flags.on("android_offline_model", who):    # android_offline_model: the model the phone runs itself
            return self._send(200, phone_model.for_person(self.state, who, (qs.get("model") or [None])[0]))
        # Download the phone model file (resumable).
        if path == "/api/phone-model/file" and self.state.flags.on("android_offline_model", who):
            f = phone_model.file_for(self.state, (qs.get("model") or [None])[0])
            if not f:
                return self._send(404, {"code": "no_model", "message": "This PC has no model for phones yet."})
            return phone_model.serve_range(self, f, self.headers.get("Range"))
        # The newest build of the Android app.
        if path == "/api/app-latest" and self.state.flags.on("app_updates", who):            # app_updates: the newest build of an Emvryx app
            return self._send(200, self.state.updates.latest((qs.get("platform") or [""])[0]) or {"sha": ""})
        if path == "/api/phone-model/vision" and self.state.flags.on("android_phone_vision", who):    # android_phone_vision: the phone looks at pictures itself
            return self._send(200, phone_model.vision_kit(self.state))
        if path == "/api/phone-model/vision/file" and self.state.flags.on("android_phone_vision", who):
            # Which of the two picture-model files was asked for ("model" or "mmproj"); an unknown part gives None.
            f = (phone_model.vision_paths(self.state) or {}).get((qs.get("part") or [""])[0])
            if not f:
                return self._send(404, {"code": "no_model", "message": "This PC has no picture model yet."})
            return phone_model.serve_range(self, f, self.headers.get("Range"))
        if path == "/api/projects" and self.state.flags.on("chat_projects", who):
            return self._send(200, {"projects": self.state.store(who["user"]).projects()})
        # One chat with its messages.
        m = re.fullmatch(r"/api/chats/(-?\d+)", path)
        if m:
            return self.api_get_chat(who, int(m.group(1)))
        if path == "/api/settings":
            return self._send(200, self.state.get_settings(who["user"]))
        # A picture from the person's library.
        m = re.fullmatch(r"/api/documents/(\d+)/image", path)
        if m:
            img = self.state.docs_for(who["user"]).image(int(m.group(1)))
            if not img:
                return self._send(404, {"code": "not_found", "message": "No picture."})
            # img is (bytes, content type). "private" means only this person's browser may keep it, for an hour.
            return self._send(200, img[0], ctype=img[1], headers={"Cache-Control": "private, max-age=3600"})
        # The person's document library and the upload limits.
        if path == "/api/documents":
            return self._send(200, {"documents": self.state.docs_for(who["user"]).list(), "max_mb": documents.MAX_FILE_BYTES // 1_000_000,
                                    "kinds": documents.KINDS})
        # The list of skills (ready-made task helpers).
        if path == "/api/skills":
            return self._send(200, app_skills.catalog())
        if path == "/api/live/sources":
            # Imported here, only when needed.
            import web_search
            return self._send(200, {"sources": live_data.sources_status(), "web": web_search.pick_source("auto")})
        if path == "/api/teacher/tools":
            return self._send(200, teacher_mode.catalog())
        # Connected apps: the catalog plus what this person has connected. Secrets are never included.
        if path == "/api/apps":
            cat = connected_apps.catalog()
            # Safe public view of the person's connections; GitHub's is added to the same dict.
            cat["connections"] = dict(self.state.links.store.public(who["user"]),
                                      github=dict(self.state.github.public(who["user"]), device=bool(self.state.github_client_id()), encrypted=self.state.secrets.available))
            # Hide owner-only apps from everyone else.
            cat["apps"] = [a for a in cat["apps"] if who["owner"] or not a.get("owner_only")]
            cat["encrypted"] = self.state.secrets.available
            return self._send(200, cat)
        # Release notes, and which ones this person has not seen yet.
        if path == "/api/whats-new":                                         # what has been published, and what this person has not seen yet
            # Shortcut to the feature-flag object (it also keeps the release notes).
            fl = self.state.flags
            seen = self.state.get_settings(who["user"]).get("whats_new_seq", -1)
            if not isinstance(seen, int) or seen < 0:                         # a new account, or one from before releases were numbered: start from now
                seen = fl.last_seq()
                self.state.put_settings(who["user"], {"whats_new_seq": seen})
            # The newest 50 releases, keeping only the fields the page shows.
            rel = [{k: r.get(k) for k in ("seq", "version", "kind", "model", "product", "at", "notes", "items", "fixes")} for r in fl.releases()[:50]]
            return self._send(200, {"version": fl.version(), "seq": fl.last_seq(), "releases": rel, "unseen": [r for r in rel if r["seq"] > seen]})
        # The facts remembered about this person, and whether memory is on.
        if path == "/api/memory":
            return self._send(200, {"facts": self.state.memory_for(who["user"]).list(), "on": self.state.get_settings(who["user"])["memory"]})
        # The person's saved notes.
        if path == "/api/saved-notes":
            return self._send(200, {"notes": self.state.saved_for(who["user"]).list(self.state.clock())})
        # Everything under /api/code is handled in routes_code.py.
        if path.startswith("/api/code"):
            return self.api_code_get(who, path, qs)
        # Download all of the person's data as a .zip.
        if path == "/api/export":
            data = data_tools.export_zip(self.state, who["user"])
            self.state.auth.event("data_export", who["user"], self._ip(), "")
            # Content-Disposition: attachment makes the browser save it as a file with this name.
            return self._send(200, data, "application/zip", {"Content-Disposition": f'attachment; filename="emvryx-{who["user"]}-data.zip"'})
        # Account facts (see routes_account.py).
        if path == "/api/account":
            return self.api_account_get(who)
        if path == "/api/account/activity":
            return self._send(200, {"events": self.state.auth.events(30, None, who["user"])})
        # Signed-in devices; the current one is marked so the page can avoid offering to sign it out.
        if path == "/api/sessions":
            return self._send(200, {"sessions": [dict(x, current=(x["id"] == who.get("session"))) for x in self.state.auth.sessions_for(who["user"])]})
        return UNHANDLED

    def get_admin(self, who, path, qs):
        """What the owner and admins can read (/api/admin/...)."""
        # List backup files (newest first). Only names that match the backup pattern are shown.
        if path == "/api/admin/backups" and who["admin"]:
            d = data_tools.backup_dir(self.state)
            files = sorted((f for f in (os.listdir(d) if os.path.isdir(d) else []) if BACKUP_NAME.fullmatch(f)), reverse=True)
            return self._send(200, {"dir": d, "items": [{"name": f, "size": os.path.getsize(os.path.join(d, f)), "at": os.path.getmtime(os.path.join(d, f))} for f in files],
                                    "keep": 14, "data": self.state.data_dir or ""})
        # Download one backup. The tight regex plus BACKUP_NAME check below stop any path tricks.
        mb = re.fullmatch(r"/api/admin/backups/(emvryx-[0-9-]+\.zip)", path)
        if mb and who["admin"]:
            full = os.path.join(data_tools.backup_dir(self.state), mb.group(1))
            if not BACKUP_NAME.fullmatch(mb.group(1)) or not os.path.isfile(full):
                return self._send(404, {"code": "not_found", "message": "No such backup."})
            with open(full, "rb") as f:
                data = f.read()
            self.state.auth.event("backup_downloaded", "owner", self._ip(), mb.group(1))
            return self._send(200, data, "application/zip", {"Content-Disposition": f'attachment; filename="{mb.group(1)}"'})
        # Feedback people sent. The query can set a limit, status, kind and model filter.
        if path == "/api/admin/feedback" and who["admin"]:
            fb = self.state.feedback
            return self._send(200, {"counts": fb.counts(), "kinds": feedback.KINDS, "items": fb.list(int((qs.get("limit") or ["50"])[0]), (qs.get("status") or ["new"])[0] or None,
                                                                                                        (qs.get("kind") or [None])[0], (qs.get("model") or [None])[0])})
        # Download feedback as JSON Lines (one JSON object per line).
        if path == "/api/admin/feedback/export" and who["admin"]:
            lines = "\n".join(self.state.feedback.export_lines((qs.get("status") or ["new"])[0])) + "\n"
            return self._send(200, lines.encode("utf-8"), "application/x-ndjson", {"Content-Disposition": 'attachment; filename="feedback_export.jsonl"'})
        # Status of the cloud machine.
        if path == "/api/admin/cloud" and who["admin"]:
            return self._send(200, self.state.cloud_status())
        # Dashboard numbers.
        if path == "/api/admin/overview" and who["admin"]:
            return self._send(200, self.state.admin_overview(who))
        # Health checks.
        if path == "/api/admin/health" and who["admin"]:
            return self._send(200, self.state.health())
        # The security log (sign-ins and changes), newest first.
        if path == "/api/admin/audit" and who["admin"]:
            return self._send(200, {"events": self.state.auth.events(int((qs.get("limit") or ["100"])[0]), (qs.get("kind") or [None])[0])})
        # Feature flags, who they are on for, the version and release notes, and the list of people.
        if path == "/api/admin/flags" and who["admin"]:
            return self._send(200, {"flags": self.state.flags.listing(), "audiences": [[a, flags.AUDIENCE_NAMES[a]] for a in flags.AUDIENCES],
                                    "version": self.state.flags.version(), "next": self.state.flags.next_versions(), "releases": self.state.flags.releases(),
                                    "fixes": [f["text"] for f in self.state.flags.pending_fixes(None)],
                                    "people": sorted(u["user"] for u in self.state.users.values() if not u.get("app"))})
        # Model settings for the admin screen.
        if path == "/api/admin/models" and who["admin"]:
            return self._send(200, self.state.models_admin())
        # Other programs' keys and the address they call.
        if path == "/api/admin/apps" and who["admin"]:
            return self._send(200, {"apps": self.state.apps(), "plans": list(self.state.cfg["tiers"]), "url": self._public_base() + "/api/v1/ask"})
        # Check whether a new version of Emvryx is available (owner only).
        if path == "/api/admin/update" and who["owner"]:
            try:
                return self._send(200, self.state.updater.check())
            except updater.UpdateError as e:
                return self._send(200, {"can_update": False, "reason": e.message, "incoming": [], "dirty": []})
        # The coding-model test: its status and how many recorded sessions can be used as test cases.
        if path == "/api/admin/code-test" and who["owner"] and self.state.flags.on("model_code_test", who):
            cases = model_code_test.build_cases(code_log.SessionLog(self.state.code.base(who["user"])))
            return self._send(200, dict(self.state.code_test.status(), recorded=len(cases)))
        if path == "/api/admin/crashes" and who["owner"] and self.state.flags.on("admin_crashes", who):     # tracebacks may hold private text: the owner only
            log = os.path.join(self.state.data_dir, "server.log") if self.state.data_dir else ""
            crashes = crash_log.read(log) if log else []
            return self._send(200, {"crashes": [dict(c, task=crash_log.fix_task(c)) for c in crashes], "log_found": bool(log) and os.path.exists(log)})
        # Status of the PC the server runs on (gaming mode and so on).
        if path == "/api/admin/pc" and who["admin"]:
            self.state.sync_gaming()
            return self._send(200, self.state.pc_status())
        # Everyone's account summary. App keys are left out (`not u.get("app")`).
        if path == "/api/admin/users" and who["admin"]:
            seen = self.state.auth.last_seen_map()
            return self._send(200, {"users": [{"user": u["user"], "tier": self.state.usage.get_user(u["user"])["tier"], "email": u.get("email"),
                                               "banned": bool(u.get("banned")), "owner": bool(u.get("owner")), "admin": bool(u.get("admin")), "unlimited": bool(u.get("unlimited")), "mfa": bool((u.get("mfa") or {}).get("on")),
                                               "has_password": bool(u.get("pw")), "created": u.get("created"), "last_seen": seen.get(u["user"])}
                                              for u in self.state.users.values() if not u.get("app")], "paused": bool(self.state.cfg.get("paused"))})
        return UNHANDLED
