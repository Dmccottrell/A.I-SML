"""
routes_post.py - The web routes for changing things (POST): sign-in, the account, chats, VryxCode and apps, personal data and the admin changes. Each part returns UNHANDLED when the address is not one of its own.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import re
import threading
import time
import data_tools
import app_skills
import export_doc
import teacher_mode
import app_links
import connected_apps
import feedback
import updater
import github_link
from app_shared import APP_PREFIX, MAX_TEXT
from app_shared import UNHANDLED


class RoutesPost:
    """The POST routes."""

    def post_public(self, path, body):
        """The sign-in and sign-up answers that need no session, and the /api/v1 interface."""
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
        return UNHANDLED

    def post_account(self, who, path, body):
        """The account and devices: the account screen, deleting the account, signing out, ending sessions."""
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
        return UNHANDLED

    def post_chats(self, who, path, body):
        """Chats and what goes in them: new chats, documents, the teacher tools, sending, stopping."""
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
        return UNHANDLED

    def post_apps(self, who, path, body):
        """VryxCode, settings, warming a model and the connected apps (GitHub and the others)."""
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
        return UNHANDLED

    def post_data(self, who, path, body):
        """The person's own data: delete everything, shares, chat actions, memory and saved notes."""
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
        return UNHANDLED

    def post_admin(self, who, path, body):
        """The owner and admin changes (/api/admin/...)."""
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
        return UNHANDLED
