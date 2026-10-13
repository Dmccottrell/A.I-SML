"""
routes_account.py - The sign-in and account web routes: password, two-step, passkeys, Google, email codes, sign-up, the account screen.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import hashlib
import hmac
import json
import secrets
import threading
import time
import urllib.request
import accounts
import auth
import app_links
import google_signin
import mailer
import passkeys


class RoutesAccount:
    """The sign-in and account routes."""

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
        clear = "emvryx_oauth=; Path=/auth/google; HttpOnly; SameSite=Lax; Max-Age=0" + ("; Secure" if self._https() else "")
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
