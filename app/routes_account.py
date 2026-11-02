"""
routes_account.py - The sign-in and account web routes: password, two-step, passkeys, Google, email codes, sign-up, the account screen.

Where it fits: app_server.py builds one request handler class out of several "mixin" classes (small classes that each add a group of methods).
This is the mixin for everything about who a person is and how they sign in. Each method here answers one web address (a "route") and
sends back JSON (a text format for data) with `self._send(status, data)`. `self.state` is the shared server object (users, sessions, settings).
Words used below: MFA / "two-step" = a second code from an authenticator app; a passkey = sign in with fingerprint/face/screen lock;
a rate limit (`st.rl`) = refusing someone who tried too often in a short time.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
# Standard library: hashlib (fingerprints), hmac (safe comparing of secrets), json, secrets (random tokens), threading (background work), time,
# urllib.request (web requests, and urllib.parse is used through it).
import hashlib
import hmac
import json
import secrets
import threading
import time
import urllib.request
# Project modules: accounts (password checks), auth (codes, sessions), app_links (connected apps), google_signin (Google OAuth helpers),
# mailer (sending email), passkeys (WebAuthn passkey checks).
import accounts
import auth
import app_links
import google_signin
import mailer
import passkeys


class RoutesAccount:
    """The sign-in and account routes (a mixin: it relies on the main handler for self._send, self.state, self._ip, self.headers and so on)."""

    def _finish_login(self, user, how):
        """The first step (a key, a password, an email code) is right: start the session, or ask for the authenticator code when the person turned that on."""
        # The shared server state (users, sessions, rate limiter, settings).
        st = self.state
        # Two-step is on: do not log in yet. Send back a short-lived 'ticket' so the next request can prove the authenticator code.
        if st.mfa_on(user):
            return self._send(200, {"mfa": True, "ticket": st.mfa_ticket(user, how)})
        # No second step needed: create the session (sets the sign-in cookie).
        self._start_session(user, how)
        return self._send(200, {"ok": True})

    def api_password_login(self, body):
        """POST sign-in with an account name (or email) and password. body: parsed JSON dict {"id", "password"}. Sends 200, or 401/403/429 with a plain message."""
        st = self.state
        # Refuse (it already sent a 429 answer) when this address has had too many wrong tries lately.
        if self._locked():
            return
        # Read the typed values as text and cap their length (254 = longest valid email, 400 = a generous password cap) so huge input cannot waste time.
        ident, password = str(body.get("id", "")).strip()[:254], str(body.get("password", ""))[:400]
        # The rate-limit bucket is per account name, not per address, so one account cannot be hammered from many addresses.
        key = "pw:" + ident.lower()
        # More than 20 wrong tries in the last hour for this account: `wait` is how many seconds to wait (0 = allowed).
        wait = st.rl.blocked(key, 20, 3600)
        if wait:
            return self._send(429, {"code": "too_many", "message": "Too many wrong tries for that account.", "action": f"Wait about {max(1, wait // 60)} minute(s), or use an email code.",
                                    "retry_after": wait}, headers={"Retry-After": str(wait)})
        # Returns the user's record when the password is right, else None.
        rec = st.check_password(ident, password)
        if not rec:
            # Count this wrong try against the account.
            st.rl.hit(key)
            # Housekeeping so the memory of attempts does not grow forever.
            if len(st.rl.hits) > 5000:
                st.rl.trim(3600)
            # Also count it against the caller's address and write it to the security log.
            self._fail("bad password")
            # the same answer whether or not the account exists; only what was typed (an email or a name) changes the hint
            action = ("Check them and try again, or sign in with your account name instead of the email."
                      if "@" in ident else "Check them and try again.")
            return self._send(401, {"code": "bad_login", "message": "That name or password isn't right.", "action": action})
        # A right password wipes the wrong-try count.
        st.rl.clear(key)
        # The password was right but the owner turned this account off.
        if rec.get("banned"):
            return self._send(403, {"code": "banned", "message": "This account has been turned off.", "action": "Ask the owner if you think that is a mistake."})
        return self._finish_login(rec["user"], "password")

    def api_mfa_login(self, body):
        """POST the second step of sign-in: the ticket from the first step plus the 6-digit authenticator code (or a recovery code)."""
        st = self.state
        if self._locked():
            return
        # Checks the ticket and the code together; gives (user, how they first signed in) or None.
        res = st.mfa_finish(str(body.get("ticket", "")), str(body.get("code", "")))
        if not res:
            self._fail("bad two-step code")
            return self._send(401, {"code": "bad_code", "message": "That code isn't right, or it has run out.",
                                    "action": "Use the newest 6-digit code from your authenticator app, or one of your recovery codes."})
        # `how` is the first step used (password, key, email code...), kept for the security log.
        user, how = res
        rec = st.user_record(user)
        if not rec or rec.get("banned"):
            return self._send(403, {"code": "banned", "message": "This account has been turned off.", "action": "Ask the owner if you think that is a mistake."})
        # Both steps passed: start the session.
        self._start_session(user, how + " + two-step")
        return self._send(200, {"ok": True})

    def api_signup(self, body):
        """POST make a new account (name, email, password, maybe an invite code), if sign-ups are open for this server."""
        st = self.state
        # One of "closed", "invite" (needs an invite code) or open.
        mode = st.signup_mode()
        if mode == "closed":
            return self._send(403, {"code": "signups_closed", "message": "Sign-ups are closed right now.", "action": "Ask the owner for an invite code or a sign-in link."})
        ip = self._ip()
        # At most 5 new accounts per address per hour, to stop mass sign-ups.
        wait = st.rl.blocked("signup:" + ip, 5, 3600)
        if wait:
            return self._send(429, {"code": "too_many", "message": "Too many accounts were made from this address.", "action": f"Try again in about {max(1, wait // 60)} minute(s).",
                                    "retry_after": wait}, headers={"Retry-After": str(wait)})
        if self._locked():
            return
        # An ordinary new account is on the "free" plan; an invite code can give a different plan.
        invite, tier = str(body.get("invite", "")).strip(), "free"
        if mode == "invite":
            # Look at the invite without using it up yet; gives its plan or None if it is wrong.
            tier = st.auth.peek_invite(invite) if invite else None
            if not tier:
                self._fail("bad invite code")
                return self._send(403, {"code": "bad_invite", "message": "That invite code isn't right, or it has run out.", "action": "Ask the owner for a new one."})
        try:
            # Raises ValueError with a readable message for a bad name, email or password; we pass that message back as a 400.
            name = st.create_account(body.get("name"), body.get("email"), str(body.get("password", "")), tier)
        except ValueError as e:
            return self._send(400, {"code": "bad_request", "message": str(e)})
        if mode == "invite":
            # Only now, after the account exists, is the invite code used up.
            st.auth.use_invite(invite)
        # Count this sign-up for the per-address limit above.
        st.rl.hit("signup:" + ip)
        self._start_session(name, "sign-up")
        return self._send(200, {"ok": True})

    # ---- the signed-in person's own account (Settings > Account and Security)
    def api_account_get(self, who):
        """GET the signed-in person's own account facts for the Settings screen. `who` is their info dict (user, plan tier, owner/admin flags)."""
        st = self.state
        rec = st.user_record(who["user"]) or {}
        # Only fields the person may see; never the password hash itself (`has_password` is just a yes/no).
        out = {"user": who["user"], "email": rec.get("email"), "email_verified": bool(rec.get("email") and rec.get("email_verified") is not False),
               "has_password": bool(rec.get("pw")), "mfa": st.mfa_info(who["user"]), "plan": who["tier"], "owner": who["owner"], "admin": who["admin"], "founder": who["founder"], "granter": who["granter"],
               "created": rec.get("created"), "mail": bool(st.mailer), "encrypted": st.secrets.available,
               "passkeys": st.passkey_list(who["user"]), "passkeys_ok": passkeys.AVAILABLE}
        # Only admins also see how sign-ups are set.
        if who["admin"]:
            out["signup_mode"] = st.signup_mode()
        return self._send(200, out)

    def _reauth(self, who, body):
        """Sensitive changes ask again: the password (when there is one) and, when two-step is on, a code. Returns an error message or None."""
        st = self.state
        # Re-checking the password is rate limited too: 10 wrong tries per 10 minutes.
        key = "reauth:" + who["user"]
        if st.rl.blocked(key, 10, 600):
            return "Too many wrong tries. Wait a few minutes."
        rec = st.user_record(who["user"]) or {}
        bad = None
        # If the account has a password, the typed one must match its stored hash (a scrambled one-way form).
        if rec.get("pw") and not accounts.verify_password(str(body.get("password", ""))[:400], rec["pw"]):
            bad = "That password isn't right."
        # If two-step is on, a right authenticator code is needed as well.
        elif st.mfa_on(who["user"]) and not st.mfa_check(who["user"], str(body.get("code", ""))):
            bad = "That two-step code isn't right."
        # A wrong answer is counted and logged.
        if bad:
            st.rl.hit(key)
            st.auth.event("reauth_fail", who["user"], self._ip(), "")
        return bad

    def api_account(self, who, path, body):
        """POST the account-changing routes (/api/account/...): password, email, passkeys, two-step. Which one runs depends on `path`; each asks for the
        password again first when the change is sensitive."""
        st, name = self.state, who["user"]
        # Small helper that sends a 400 error with a code the page can react to.
        bad = lambda msg, code="bad_request": self._send(400, {"code": code, "message": msg})
        if path == "/api/account/password":
            err = self._reauth(who, {"password": body.get("current"), "code": body.get("code")})
            if err:
                return bad(err, "reauth")
            try:
                st.set_password(name, str(body.get("new", "")))
            except ValueError as e:
                return bad(str(e))
            # Sign out every OTHER session of this person (keeping this one), because the password changed.
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
            # A new address is not trusted until its code is checked.
            st._set_fields(name, email_verified=False)
            st.auth.event("email_changed", name, self._ip(), "")
            return self._send(200, {"ok": True})
        if path == "/api/account/email/send":
            rec = st.user_record(name) or {}
            # No mail server set up on this PC: say so plainly.
            if not st.mailer:
                return self._send(501, {"code": "email_off", "message": "Email isn't set up on this server, so addresses can't be checked.", "action": "Ask the owner."})
            # Needs an email on file, and at most 3 codes per 10 minutes.
            if not rec.get("email") or st.rl.blocked("verify:" + name, 3, 600):
                return bad("Add an email address first, and wait a few minutes between codes.")
            st.rl.hit("verify:" + name)
            # A short random one-time code.
            code = auth.make_code()
            st.auth.put_code(rec["email"], code)
            # Send the email in the background so the answer to the web page is not slowed by the mail server.
            threading.Thread(target=lambda: st.mailer.send(rec["email"], *mailer.code_email(code)), daemon=True).start()
            return self._send(200, {"ok": True})
        if path == "/api/account/email/verify":
            rec = st.user_record(name) or {}
            if not rec.get("email") or not st.auth.check_code(rec["email"], str(body.get("code", ""))):
                return bad("That code isn't right, or it has run out.", "bad_code")
            st.mark_email_verified(name)
            return self._send(200, {"ok": True})
        # path.rsplit("/", 1)[1] is the last part ("begin" or "finish").
        if path in ("/api/account/passkey/begin", "/api/account/passkey/finish"):
            return self.api_passkey_account(who, path.rsplit("/", 1)[1], body)
        if path == "/api/account/passkey/delete":
            err = self._reauth(who, body)
            if err:
                return bad(err, "reauth")
            return self._send(200, {"ok": st.passkey_remove(name, str(body.get("id", ""))), "passkeys": st.passkey_list(name)})
        # Turning on two-step takes two calls: start (shows the secret/QR) then enable (proves a first code).
        if path == "/api/account/mfa/start":
            if st.mfa_on(name):
                return bad("Two-step sign-in is already on.")
            err = self._reauth(who, body)
            if err:
                return bad(err, "reauth")
            return self._send(200, st.mfa_begin(name))
        if path == "/api/account/mfa/enable":
            # Gives the one-time recovery codes when the first code was right, else nothing.
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
        # Make a fresh set of recovery codes.
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
        """Connect, disconnect or try one outside app (a 'link', id `sid`) for the signed-in person. `action`: "connect", "disconnect", else a test question."""
        st, user = self.state, who["user"]
        # The person's time-zone offset in minutes, so dates like 'tomorrow' mean their tomorrow.
        tz = st.usage.get_user(user).get("tz_minutes", 0)
        try:
            if action == "connect":
                # A cap of 25 connected apps per person.
                if st.links.store.connected(user) and sid not in st.links.store.connected(user) and len(st.links.store.connected(user)) >= 25:
                    return self._send(400, {"code": "too_many", "message": "That is a lot of connected apps already.", "action": "Disconnect one you do not use."})
                # `fields` are what the person typed (like a token); it is stored by the link store, never sent back.
                label = st.links.connect(user, sid, body.get("fields") if isinstance(body.get("fields"), dict) else {}, owner=who["owner"], tz=tz)
                st.auth.event("app_connected", user, self._ip(), sid)
                return self._send(200, {"ok": True, "label": label, "connection": st.links.store.public(user).get(sid)})
            if action == "disconnect":
                st.links.store.disconnect(user, sid)
                # Disconnecting also deletes the saved secret.
                st.links.store.log(user, sid, "disconnected (saved secret deleted)")
                st.auth.event("app_disconnected", user, self._ip(), sid)
                return self._send(200, {"ok": True})
            q = str(body.get("query", ""))[:200]                       # "Try it": what was typed is both the search words and the question (so "tomorrow" works for a calendar)
            # Ask the connected app; a KeyError here (unknown sid) is handled below.
            items = st.links.ask(user, sid, app_links.question_words(q, app_links.BY_ID[sid]), tz, q)
            return self._send(200, {"items": [{"title": i["title"], "text": i.get("text", ""), "url": i.get("url")} for i in items]})
        # A problem the app reported, with a readable message and what to do.
        except app_links.LinkError as e:
            return self._send(400, {"code": "app", "message": e.message, "action": e.action})
        except KeyError:
            return self._send(404, {"code": "not_found", "message": "That app isn't in the list."})

    # ---- passkeys: the two steps of making one, and of signing in with one
    # WebAuthn needs a 'relying party': the site's host name (id) and its full origin (scheme://host).
    def _rp(self):
        # Works out this site's own public address.
        base = self._public_base()
        p = urllib.parse.urlparse(base)
        return p.hostname or "localhost", f"{p.scheme}://{p.netloc}"

    # Sign in with a passkey. Two calls: step "begin" hands out a random challenge; the next call sends back the phone/computer's signed answer.
    def api_passkey_login(self, step, body):
        st = self.state
        if not passkeys.AVAILABLE:
            return self._send(501, {"code": "no_passkeys", "message": "Passkeys need the cryptography package on this server."})
        if self._locked():
            return
        rp_id, origin = self._rp()
        # Step 1: a random one-time challenge the passkey must sign. Empty allowCredentials = let the device offer any passkey it has for this site.
        if step == "begin":
            return self._send(200, {"challenge": st.passkey_challenge("get"), "rpId": rp_id, "timeout": 120000, "userVerification": "required", "allowCredentials": []})
        # Step 2: the signed answer from the device (a dict), or empty if missing.
        cred = body.get("credential") if isinstance(body.get("credential"), dict) else {}
        try:
            # Find which account and which stored passkey this credential id belongs to.
            rec, pk = st.passkey_find(str(cred.get("id", "")))
            try:
                # The device's signed data includes the challenge we gave it, in base64url text; decode it to read the challenge back.
                challenge = json.loads(passkeys.unb64u(cred.get("clientDataJSON", ""))).get("challenge", "")
            except (ValueError, passkeys.PasskeyError):
                challenge = ""
            # The passkey must be known and the challenge must be one we issued and not used before (take removes it, so it works only once).
            if not rec or not st.passkey_take(challenge, "get"):
                raise passkeys.PasskeyError("That passkey isn't known here, or the request ran out.")
            # Checks the cryptographic signature; raises PasskeyError when it is wrong. `counter` rises with each use.
            counter = passkeys.verify_assertion(cred, pk, challenge, origin, rp_id)
            if rec.get("banned"):
                return self._send(403, {"code": "banned", "message": "This account has been turned off.", "action": "Ask the owner if you think that is a mistake."})
        except passkeys.PasskeyError as e:
            self._fail("bad passkey")
            return self._send(401, {"code": "bad_passkey", "message": str(e), "action": "Try again, or sign in another way."})
        # Store the new counter and save: a replayed old answer would show a lower counter.
        pk["counter"] = counter
        st._save_users()
        self._start_session(rec["user"], "passkey")                  # a passkey needs your fingerprint, face or screen lock: it is two factors already
        return self._send(200, {"ok": True})

    # Add a passkey to the signed-in person's account (also two calls, "begin" and "finish").
    def api_passkey_account(self, who, step, body):
        st, name = self.state, who["user"]
        if not passkeys.AVAILABLE:
            return self._send(501, {"code": "no_passkeys", "message": "Passkeys need the cryptography package on this server.", "action": "Ask the owner to run: pip install cryptography"})
        rp_id, origin = self._rp()
        if step == "begin":
            err = self._reauth(who, body)
            if err:
                return self._send(400, {"code": "reauth", "message": err})
            # Existing passkeys, listed in `excludeCredentials` so the same device is not added twice.
            have = st.user_record(name).get("passkeys", [])
            return self._send(200, {"challenge": st.passkey_challenge("create", name), "rp": {"id": rp_id, "name": "Emvryx"},
                                    # A stable user id made by hashing the name, so it reveals nothing and does not change.
                                    "user": {"id": passkeys.b64u(hashlib.sha256(("emvryx:" + name).encode()).digest()), "name": name, "displayName": name},
                                    # The signature types we can check (two common ones).
                                    "pubKeyCredParams": [{"type": "public-key", "alg": passkeys.ES256}, {"type": "public-key", "alg": passkeys.RS256}],
                                    "authenticatorSelection": {"residentKey": "preferred", "userVerification": "required"}, "attestation": "none", "timeout": 120000,
                                    "excludeCredentials": [{"type": "public-key", "id": p["id"]} for p in have]})
        cred = body.get("credential") if isinstance(body.get("credential"), dict) else {}
        try:
            challenge = json.loads(passkeys.unb64u(cred.get("clientDataJSON", ""))).get("challenge", "")
        except (ValueError, passkeys.PasskeyError):
            challenge = ""
        # The challenge must be one issued to this very person and not used yet.
        if not st.passkey_take(challenge, "create", name):
            return self._send(400, {"code": "bad_passkey", "message": "That passkey request ran out. Start again."})
        try:
            # Checks the new passkey's proof and gives the data to store.
            pk = passkeys.verify_registration(cred, challenge, origin, rp_id)
        except passkeys.PasskeyError as e:
            return self._send(400, {"code": "bad_passkey", "message": str(e)})
        # A friendly name for the list: the typed one, or a guess from the browser's User-Agent text.
        label = str(body.get("name") or auth.device_label(self.headers.get("User-Agent", "")))
        st.passkey_add(name, pk, label)
        return self._send(200, {"ok": True, "passkeys": st.passkey_list(name)})

    # ---- "Continue with Google"
    # The site's public address without a trailing slash: from the owner's setting, then an environment variable, then the request's own Host header.
    def _public_base(self):
        base = str(self.state.security.get("public_url") or os.environ.get("EMVRYX_PUBLIC_URL") or "").rstrip("/")
        if base:
            return base
        host = self.headers.get("Host", "localhost")
        return ("https://" if self._https() else "http://") + host

    # Send a 302 'go to this other address' answer, adding any cookies to set.
    def _redirect(self, where, cookies=()):
        for c in cookies:
            self._cookies.append(c)
        return self._send(302, b"", "text/plain", {"Location": where})

    def google_start(self, qs):
        """GET /auth/google: begin 'Continue with Google'. Remembers a one-time `state` and a PKCE verifier, then sends the browser to Google.
        qs: the parsed query string (dict of lists)."""
        st = self.state
        if not st.google_on():
            return self._redirect("/?gerr=off")
        if self._locked():
            return
        now = time.time()
        # Forget sign-in attempts older than their 10 minutes.
        for k in [k for k, v in st.oauth_pending.items() if v["expires"] < now]:
            st.oauth_pending.pop(k, None)
        # Also never keep more than 200 waiting attempts: drop the oldest.
        while len(st.oauth_pending) > 200:
            st.oauth_pending.pop(next(iter(st.oauth_pending)))
        # `state`: a random value that comes back with Google's answer; it proves the answer belongs to a sign-in we started (stops forged requests).
        state = secrets.token_urlsafe(24)
        # PKCE: a secret `verifier` is kept here and only its hash (`challenge`) goes to Google, so a stolen redirect cannot be completed.
        verifier, challenge = google_signin.pkce()
        # Store under a hash of the state (not the state itself); it expires in 600 seconds and remembers an invite code typed on the page.
        st.oauth_pending[auth.digest(state)] = {"verifier": verifier, "invite": str((qs.get("invite") or [""])[0])[:60], "expires": now + 600}
        redirect_uri = self._public_base() + "/auth/google/callback"
        # A short-lived cookie holds the same state so the callback can check it is the same browser. HttpOnly = scripts cannot read it; Secure = only over https.
        cookie = f"emvryx_oauth={state}; Path=/auth/google; HttpOnly; SameSite=Lax; Max-Age=600" + ("; Secure" if self._https() else "")
        return self._redirect(google_signin.auth_url(os.environ["GOOGLE_CLIENT_ID"], redirect_uri, state, challenge), [cookie])

    def google_callback(self, qs):
        """GET /auth/google/callback: Google sends the person back here with a code. Checks it, finds or makes the account and signs in."""
        st = self.state
        # A cookie with Max-Age=0 tells the browser to delete it.
        clear = "emvryx_oauth=; Path=/auth/google; HttpOnly; SameSite=Lax; Max-Age=0" + ("; Secure" if self._https() else "")
        # Every failure sends the person back to the home page with a short error code in the address, and removes the cookie.
        fail = lambda code: self._redirect("/?gerr=" + code, [clear])
        if not st.google_on():
            return fail("off")
        if self._locked():
            return
        state = str((qs.get("state") or [""])[0])
        # Take (and so use up) the waiting attempt for this state.
        pending = st.oauth_pending.pop(auth.digest(state), None) if state else None
        # It must exist, be fresh, and match the browser's cookie. compare_digest compares in constant time so timing cannot leak the value.
        if not pending or pending["expires"] < time.time() or not hmac.compare_digest(self._cookie_dict().get("emvryx_oauth", ""), state):
            self._fail("google: bad state")
            return fail("state")
        # The person said no on Google's page, or no code came back.
        if (qs.get("error") or [""])[0] or not (qs.get("code") or [""])[0]:
            return fail("denied")
        # Trade the code (plus the PKCE verifier) for tokens by calling Google's server directly.
        status, tok = st.google_http("POST", google_signin.TOKEN_URL, google_signin.token_form(
            os.environ["GOOGLE_CLIENT_ID"], os.environ["GOOGLE_CLIENT_SECRET"], self._public_base() + "/auth/google/callback", qs["code"][0], pending["verifier"]))
        # Read the verified email out of Google's signed id token (it is checked to be meant for our app).
        email = google_signin.email_from_id_token(tok.get("id_token", ""), os.environ["GOOGLE_CLIENT_ID"]) if status == 200 else None
        if not email:
            self._fail("google: token")
            return fail("token")
        # Is there already an account with this verified email?
        rec = st.user_by_email(email)
        if not rec:
            # Someone typed this email at sign-up but never proved it: do not let a Google sign-in take that account over.
            if any(u.get("email") == email for u in st.users.values()):         # typed at sign-up but never verified: not taken over
                return fail("unverified")
            mode = st.signup_mode()
            if mode == "closed" or (mode == "invite" and not st.auth.peek_invite(pending["invite"])):
                return fail("closed" if mode == "closed" else "invite")
            # No account yet and sign-ups allow it: make one from the email.
            user = st.create_email_account(email)
            if mode == "invite":
                # Use the invite code and give the plan it carries.
                tier = st.auth.use_invite(pending["invite"])
                if tier:
                    st.set_plan(user, tier)
            st.auth.event("signup", user, self._ip(), "google")
        else:
            if rec.get("banned"):
                return fail("banned")
            user = rec["user"]
            # Google already proved the address, so mark it verified.
            st.mark_email_verified(user)
        if st.mfa_on(user):
            # Two-step is on: the page shows the code box using this ticket.
            return self._redirect("/?mfa=" + st.mfa_ticket(user, "google"), [clear])
        self._start_session(user, "google")
        return self._redirect("/", [clear])

    # ---- email sign-in
    def api_email_start(self, body):
        """POST ask for a sign-in code by email. It always answers the same way so nobody can find out which addresses have accounts."""
        st = self.state
        if not st.mailer:
            return self._send(501, {"code": "email_off", "message": "Email sign-in isn't set up on this server.", "action": "Use your key or a pairing link."})
        ip = self._ip()
        # Limit by address how often codes may be asked for (numbers come from the security settings).
        wait = st.rl.blocked("email-ip:" + ip, st.security["email_start_limit"], st.security["email_start_window"])
        if wait:
            return self._send(429, {"code": "too_many", "message": "Too many codes asked for from this address.", "action": f"Wait about {max(1, wait // 60)} minute(s).",
                                    "retry_after": wait}, headers={"Retry-After": str(wait)})
        st.rl.hit("email-ip:" + ip)
        email = auth.clean_email(body.get("email"))
        generic = {"ok": True, "message": "If that address can sign in, a code is on its way."}      # the same answer whether or not it can: nobody can probe who has an account
        # Not a usable email, or already 3 codes in 10 minutes for it: say the same friendly thing but send nothing.
        if not email or st.rl.blocked("email:" + email, 3, 600):
            return self._send(200, generic)
        st.rl.hit("email:" + email)
        if len(st.rl.hits) > 5000:
            st.rl.trim(3600)
        rec = st.user_by_email(email)
        # Send a code to a known, not-banned account, or to a new address when anyone may sign up.
        if (rec and not rec.get("banned")) or (not rec and st.security["open_signups"]):
            code = auth.make_code()
            st.auth.put_code(email, code)
            # Sends the email. Defined here so it can run either in the background or right away.
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
        """POST the emailed code to sign in (or sign up, when sign-ups are open). A right code proves the person owns the address."""
        st = self.state
        if self._locked():
            return
        email = auth.clean_email(body.get("email"))
        # check_code accepts a right, unused, unexpired code and uses it up.
        if not email or not st.auth.check_code(email, str(body.get("code", ""))):
            self._fail("bad email code")
            return self._send(401, {"code": "bad_code", "message": "That code isn't right, or it has run out.", "action": "Ask for a new one."})
        rec = st.user_by_email(email)
        if rec:
            if rec.get("banned"):
                return self._send(403, {"code": "banned", "message": "This account has been turned off.", "action": "Ask the owner if you think that is a mistake."})
            user = rec["user"]
            st.mark_email_verified(user)
        # Unknown address but sign-ups are open: the proven email becomes a new account.
        elif st.security["open_signups"]:
            user = st.create_email_account(email)
        else:
            self._fail("email code for unknown address")
            return self._send(401, {"code": "bad_code", "message": "That code isn't right, or it has run out.", "action": "Ask for a new one."})
        # Second step (authenticator code) if the person turned it on, otherwise sign in.
        return self._finish_login(user, "email code")
