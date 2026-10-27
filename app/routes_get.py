"""
routes_get.py - The web routes for reading (GET): pages and files, what a person can read, and what the admins can read. Each part returns UNHANDLED when the address is not one of its own, and the next part is tried.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
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
import code_log
import model_code_test
import live_data
import flags
import passkeys
import shares
from app_shared import BACKUP_NAME, PAIR_PAGE
from app_shared import UNHANDLED


class RoutesGet:
    """The GET routes."""

    def get_public(self, path, qs):
        """The pages, files and few public answers that need no sign-in."""
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
        if path in ("/icon-192.png", "/icon-512.png", "/icon-maskable-512.png", "/apple-touch-icon.png"):
            return self._file(path[1:], "image/png")
        if not path.startswith("/api/"):
            return self._send(404, {"code": "not_found", "message": "Not found."})
        return UNHANDLED

    def get_user(self, who, path, qs):
        """What a signed-in person can read: their state, chats, documents, settings, memory, account and devices."""
        if path == "/api/state":
            return self._send(200, self.api_state(who, qs))
        if path == "/api/briefing":
            if not self.state.get_settings(who["user"]).get("connected_apps", True):
                return self._send(200, {"sections": [], "off": True})
            return self._send(200, app_links.briefing(self.state.links, who["user"], self.state.usage.get_user(who["user"]).get("tz_minutes", 0)))
        if path == "/api/shares":
            return self._send(200, {"shares": self.state.shares.list(who["user"]), "on": bool(self.state.security.get("sharing"))})
        if path == "/api/chats/archived":
            return self._send(200, {"chats": self.state.store(who["user"]).list_chats(archived=True)})
        if path == "/api/chats/search":
            return self._send(200, {"results": self.state.store(who["user"]).search((qs.get("q") or [""])[0])})
        m = re.fullmatch(r"/api/chats/(-?\d+)/followups", path)
        if m and self.state.flags.on("chat_followups", who):          # what to ask next, from the last answer (no model time)
            store = self.state.store(who["user"])
            cid = int(m.group(1))
            if not store.exists(cid):
                return self._send(404, {"code": "not_found", "message": "That chat is gone."})
            msgs = [x for x in store.messages(cid) if x["status"] != "compacted" and x["content"]]
            ans = next((x for x in reversed(msgs) if x["role"] == "assistant"), None)
            q = next((x["content"] for x in reversed(msgs) if x["role"] == "user"), "")
            return self._send(200, {"items": chat_plus.followups(q, ans["content"]) if ans and ans["status"] == "done" else []})
        if path == "/api/projects" and self.state.flags.on("chat_projects", who):
            return self._send(200, {"projects": self.state.store(who["user"]).projects()})
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
        if path == "/api/sessions":
            return self._send(200, {"sessions": [dict(x, current=(x["id"] == who.get("session"))) for x in self.state.auth.sessions_for(who["user"])]})
        return UNHANDLED

    def get_admin(self, who, path, qs):
        """What the owner and admins can read (/api/admin/...)."""
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
        if path == "/api/admin/code-test" and who["owner"] and self.state.flags.on("model_code_test", who):
            cases = model_code_test.build_cases(code_log.SessionLog(self.state.code.base(who["user"])))
            return self._send(200, dict(self.state.code_test.status(), recorded=len(cases)))
        if path == "/api/admin/crashes" and who["owner"] and self.state.flags.on("admin_crashes", who):     # tracebacks may hold private text: the owner only
            log = os.path.join(self.state.data_dir, "server.log") if self.state.data_dir else ""
            crashes = crash_log.read(log) if log else []
            return self._send(200, {"crashes": [dict(c, task=crash_log.fix_task(c)) for c in crashes], "log_found": bool(log) and os.path.exists(log)})
        if path == "/api/admin/pc" and who["admin"]:
            self.state.sync_gaming()
            return self._send(200, self.state.pc_status())
        if path == "/api/admin/users" and who["admin"]:
            seen = self.state.auth.last_seen_map()
            return self._send(200, {"users": [{"user": u["user"], "tier": self.state.usage.get_user(u["user"])["tier"], "email": u.get("email"),
                                               "banned": bool(u.get("banned")), "owner": bool(u.get("owner")), "admin": bool(u.get("admin")), "unlimited": bool(u.get("unlimited")), "mfa": bool((u.get("mfa") or {}).get("on")),
                                               "has_password": bool(u.get("pw")), "created": u.get("created"), "last_seen": seen.get(u["user"])}
                                              for u in self.state.users.values() if not u.get("app")], "paused": bool(self.state.cfg.get("paused"))})
        return UNHANDLED
