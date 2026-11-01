"""
state_accounts.py - AppState's accounts part: users, keys, passwords, two-step sign-in, passkeys, plans and sign-up rules.

WHERE IT FITS
    AppState (the server's big shared object) is built from several "mixin" classes, each in its own state_*.py file. A mixin is a class that is
    not used on its own: its methods are mixed into AppState, so `self` below is the whole AppState and can use attributes made elsewhere
    (self.users, self.usage, self.auth, self.cfg, self.security, self.secrets, self.rl, self.data_dir ...). This file holds the people part.
    People are stored in users.json; the key a person signs in with is stored only as a hash (a one-way scrambled fingerprint).
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import json
import re
import secrets
import time
import accounts
import auth
import passkeys
from app_shared import API_KEY_PREFIX, SECURITY_DEFAULTS


class StateAccounts:
    """The people: accounts, sign-in methods and what they may do."""

    # ---- people and keys
    # users.json maps a credential id to the person: "h:<sha256 of their key>" for a key, "e:<name>" for a person who signs in by email.
    # The key itself is never stored: it is shown once, when it is made.
    def _users_path(self):
        """Where users.json lives, or None when the server keeps everything in memory (no data folder)."""
        return os.path.join(self.data_dir, "users.json") if self.data_dir else None

    def _load_security(self):
        """Read security.json (sign-up mode, session days...) and return the settings: the defaults, overridden by the saved known ones."""
        # Start from the built-in defaults so a missing file or missing setting still has a value.
        sec = dict(SECURITY_DEFAULTS)
        if self.data_dir:
            try:
                with open(os.path.join(self.data_dir, "security.json"), encoding="utf-8") as f:
                    # Take only settings we know about (ignore unknown names), so a typo in the file cannot add odd settings.
                    sec.update({k: v for k, v in json.load(f).items() if k in SECURITY_DEFAULTS})
            except (OSError, ValueError):
                pass                                    # no file, or not valid JSON: just use the defaults
        return sec

    def _load_users(self):
        """Read users.json into self.users (a dict of credential id -> person record), upgrade old formats, and make sure an owner exists.

        Returns the dict. Also makes the usage-tracking record for each person.
        """
        path, users = self._users_path(), {}
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                users = json.load(f)
        migrated = False
        # list(users) makes a copy of the keys, because we change the dict while looping over it.
        for k in list(users):
            if not (k.startswith("h:") or k.startswith("e:")):           # an older file that kept the keys themselves: keep them working, store only the hash
                users["h:" + auth.digest(k)] = users.pop(k)
                migrated = True
        # First run (nobody is the owner yet): make the owner account with a random key. It is kept in self._fresh (memory only) so it can be
        # shown once; only the hash goes into the file.
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
        """Write self.users to users.json safely (private permissions, written to a temp file first and then swapped in)."""
        path = self._users_path()
        if path:
            tmp = path + ".tmp"
            # 0o600 = only the owner of the file may read or write it (the file holds password hashes). os.fdopen turns the low-level
            # file number into a normal file object.
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.users, f, indent=2)
            # os.replace swaps the finished file in as one step, so a crash cannot leave a half-written users.json.
            os.replace(tmp, path)
            try:
                os.chmod(path, 0o600)
                # Remember the file's last-changed time so _reload_users_if_changed can tell when someone ELSE edits it.
                self._users_mtime = os.stat(path).st_mtime
            except OSError:
                pass

    def _reload_users_if_changed(self):
        """Another process (--rotate-key, --add-user) may have changed users.json while the server runs: read it again."""
        path = self._users_path()
        if not path:
            return
        # mtime = "modification time", when the file last changed. If it differs from what we saw at our last save/read, another process edited it.
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
        """Make sure the usage tracker (limits and counts per plan) knows this person; add them if it does not."""
        try:
            self.usage.get_user(u["user"])
        except KeyError:
            self.usage.add_user(u["user"], u["tier"], u.get("tz_minutes", 0), owner=bool(u.get("owner") or u.get("unlimited")))

    def _entries(self, name):
        """The credential ids (keys of self.users) that belong to the person `name`. One person can have a key entry and an email entry."""
        return [k for k, u in self.users.items() if u["user"] == name]

    def user_record(self, name):
        """The stored record (dict) of the person called `name`, or None if there is no such person."""
        return next((u for u in self.users.values() if u["user"] == name), None)

    def add_user(self, name, tier, tz_minutes=0, email=None, key_prefix=""):
        """A new person: returns their key (shown once, never stored). For someone who already exists the plan is updated and None is returned:
        make them a pairing link instead (or rotate their key)."""
        # Validate the plan and the name. The regex allows 1-32 characters from letters, digits, "-" and "_" and nothing else (fullmatch =
        # the whole name must fit the pattern).
        if tier not in self.cfg["tiers"]:
            raise ValueError(f"plan must be one of {', '.join(self.cfg['tiers'])}")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name):
            raise ValueError("a name is letters, numbers, - and _ (up to 32)")
        # The person already exists: do not make a second key; only save a new email if one was given.
        rec = self.user_record(name)
        if rec is not None:
            if email:
                self.set_email(name, email)
            return None
        if email and not auth.clean_email(email):
            raise ValueError("that does not look like an email address")
        # A new random key (24 random bytes as URL-safe text). Only its hash is stored in users.json; the key itself is kept in memory in
        # self._fresh so the caller can show it once.
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
        """Save an email address for a person (it must look valid and not belong to someone else). It counts as unverified until confirmed."""
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
        # All of this person's credential entries; the new key replaces them all.
        found = self._entries(name)
        if not found:
            raise ValueError(f"no one is called {name!r} (use owner, or a name you added with --add-user)")
        # Copy the old record, so the person keeps their plan and settings; app accounts get the special API-key prefix.
        rec = dict(self.users[found[0]])
        key = (API_KEY_PREFIX if rec.get("app") else "") + secrets.token_urlsafe(24)
        new = "h:" + auth.digest(key)
        # Remove the old entries, add the record under the new key's hash, save, then sign out every device that used the old key.
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
        """Turn a stored user record into the "who" dict the rest of the server uses (name, rights, plan, ban state, email, sign-in options)."""
        row = self.usage.get_user(entry["user"])
        admin = bool(row["owner"] or entry.get("admin"))
        # Emails of admins the owner has chosen to trust as granters (the set comprehension also drops empty or invalid addresses).
        granters = {auth.clean_email(e) for e in (self.security.get("grant_emails") or []) if auth.clean_email(e)}
        # who may give out plans, no-limits and admin rights: the PC owner, and an account that was made an admin by the PC owner AND has one of these emails
        granter = bool(entry.get("owner")) or bool(entry.get("admin") and auth.clean_email(entry.get("email") or "") in granters)
        owner = bool(row["owner"]) or granter                  # an admin the PC owner trusts (their email is in grant_emails) acts as the owner for everything
        admin = admin or owner
        # "founder" = the very first owner account. "granter" = may hand out plans and rights. "has_password"/"mfa" tell the sign-in screen which
        # options this person has. (mfa = multi-factor authentication, a second check such as an authenticator-app code.)
        return {"user": entry["user"], "owner": owner, "admin": admin, "founder": bool(entry.get("owner")), "granter": granter,
                "tier": row["tier"], "banned": bool(entry.get("banned")), "app": bool(entry.get("app")),
                "email": entry.get("email"), "has_password": bool(entry.get("pw")), "mfa": bool((entry.get("mfa") or {}).get("on"))}

    def who(self, key):
        """The person a key belongs to, or None."""
        if not key:
            return None
        # Pick up edits another process made to users.json, then look the key up by its hash (the key itself is never stored).
        self._reload_users_if_changed()
        entry = self.users.get("h:" + auth.digest(key))
        return self._who_of(entry) if entry else None

    def who_session(self, token):
        """The person a session cookie belongs to (the session is extended while it is used), or None."""
        self._reload_users_if_changed()
        # Ask the auth layer whether this cookie is a live session (it also pushes its expiry forward by session_days).
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
        """The "who" dict for a person looked up by name (for server-side jobs that act for someone), or None."""
        rec = self.user_record(name)
        return self._who_of(rec) if rec else None

    def user_by_email(self, email):
        """The record whose email matches, or None. An address that was marked not verified is ignored (only a verified one can be used to sign in)."""
        email = auth.clean_email(email)
        return next((u for u in self.users.values() if email and u.get("email") == email and u.get("email_verified") is not False), None)

    def set_access(self, name, plan=None, unlimited=None, admin=None):
        """Change one person's plan, whether they have no limits, and whether they have admin rights. The first owner account is never changed here."""
        rec = self.user_record(name)
        if not rec:
            raise ValueError("no one is called that")
        # Protection: the first owner can never be demoted from here (that would lock everyone out).
        if rec.get("owner"):
            raise ValueError("the first owner account always has full rights; change another account")
        # Collect only the things that were asked to change (None = leave alone).
        fields = {}
        if plan is not None:
            if plan not in self.cfg["tiers"]:
                raise ValueError("choose " + ", ".join(self.cfg["tiers"]))
            fields["tier"] = plan
        if unlimited is not None:
            fields["unlimited"] = bool(unlimited)
        if admin is not None:
            fields["admin"] = bool(admin)
        # Save to users.json, then tell the usage tracker the new plan/unlimited flag, keeping their time zone and any custom limits.
        self._set_fields(name, **fields)
        row = self.usage.get_user(name)
        now = self.user_record(name)
        self.usage.add_user(name, now["tier"], row["tz_minutes"], bool(now.get("unlimited")), row["overrides"])
        self.auth.event("access_changed", name, "", f"plan={now['tier']} unlimited={bool(now.get('unlimited'))} admin={bool(now.get('admin'))}")
        return {"user": name, "plan": now["tier"], "unlimited": bool(now.get("unlimited")), "admin": bool(now.get("admin"))}

    def set_ban(self, name, banned):
        """Turn an account off (banned=True) or back on (False). Banning also signs the person out everywhere. Owners/admins cannot be banned."""
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
        # Make a username from the part of the email before "@": the regex removes everything that is not a letter, digit, "-" or "_".
        # [:24] cuts it to 24 characters.
        base = re.sub(r"[^A-Za-z0-9_-]", "", email.split("@")[0])[:24]
        if not accounts.clean_name(base):                       # too short, or a name nobody should be able to pick (admin, support...)
            base = (base + "user")[:24]
        # If the name is taken, add a number (name2, name3 ...) until it is free.
        name, n = base, 1
        while self.user_record(name):
            n += 1
            name = f"{base}{n}"
        # "e:<name>" marks a person who signs in by email (no key). The email is already verified because they proved they own it.
        entry = {"user": name, "tier": "free", "owner": False, "tz_minutes": 0, "email": email, "email_verified": True}
        self.users["e:" + name] = entry
        self._save_users()
        self._ensure_usage_user(entry)
        self.auth.event("signup", name, "", "email")
        return name

    def mark_email_verified(self, name):
        """Record that this person proved they own their email address."""
        for k in self._entries(name):
            self.users[k]["email_verified"] = True
        self._save_users()

    # ---- passwords, MFA, sign-up
    # Kept in the person's users.json entry: "pw" (a scrypt hash) and "mfa" {"secret" (encrypted), "on", "last" (last time step used), "recovery" [hashes]}.
    def _set_fields(self, name, **fields):
        """Set the given fields (e.g. tier=..., pw=...) on every credential entry of this person and save users.json."""
        for k in self._entries(name):
            self.users[k].update(fields)
        self._save_users()

    def find_login(self, ident):
        """The account a sign-in name or email points to (a name, or a verified email), or None."""
        ident = str(ident or "").strip()
        # Contains "@": treat it as an email. Otherwise it is a name.
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
        """The account when the password is right, else None (a missing account costs the same time as a wrong password).
        An email that was never verified also works here, with the password, when it belongs to exactly one account: people type the
        email they gave, and refusing it looked like a wrong password. The password is the proof; an email shared by two accounts is
        never guessed between. Email codes and recovery still need a verified email (user_by_email)."""
        rec = self.find_login(ident)
        # (see the docstring) fall back to an unverified email only when exactly one account has it.
        if not rec and "@" in str(ident or ""):                              # an email that was never confirmed: still the account's own email, and the password is still needed
            em = auth.clean_email(ident)
            same = [u for u in self.users.values() if em and u.get("email") == em]
            rec = same[0] if len(same) == 1 else None
        # No such account, or it has no password: still spend about the same time as a real check, so an attacker cannot tell by timing
        # whether the account exists (burn_time does that fake work).
        if not rec or not rec.get("pw"):
            accounts.burn_time(password)
            return None
        return rec if accounts.verify_password(password, rec["pw"]) else None

    def set_password(self, name, password):
        """Set a new password for a person. Raises ValueError with a readable sentence if it is too weak. Only a hash (scrypt) is stored."""
        # password_problem returns a message when the password is bad (too short, too like the name or email) and "" when it is fine.
        problem = accounts.password_problem(password, name, (self.user_record(name) or {}).get("email", ""))
        if problem:
            raise ValueError(problem)
        self._set_fields(name, pw=accounts.hash_password(password))
        self.auth.event("password_set", name, "", "")

    def mfa_on(self, name):
        """True if this person has two-step sign-in switched on."""
        rec = self.user_record(name)
        return bool(rec and (rec.get("mfa") or {}).get("on"))

    def mfa_info(self, name):
        """What the settings screen shows: whether two-step is on, and how many recovery codes are still unused."""
        m = (self.user_record(name) or {}).get("mfa") or {}
        return {"on": bool(m.get("on")), "recovery_left": len(m.get("recovery") or [])}

    def mfa_begin(self, name):
        """A fresh secret for the person to add to their authenticator app. It is not active until a code from the app proves it works."""
        secret = accounts.new_secret()
        # Held in memory only for 900 seconds (15 minutes) until the person enters a first valid code.
        self._mfa_pending[name] = {"secret": secret, "expires": time.time() + 900}
        rec = self.user_record(name) or {}
        account = rec.get("email") or name
        # "secret" is shown as typeable groups of characters; "uri" is the otpauth:// text that a QR code carries for the authenticator app.
        return {"secret": accounts.group_secret(secret), "uri": accounts.otpauth_uri(account, secret)}

    def mfa_enable(self, name, code):
        """The 8 recovery codes (shown once) when `code` from the app matches the pending secret, else None."""
        pend = self._mfa_pending.get(name)
        if not pend or pend["expires"] < time.time():
            return None
        # check_totp: a TOTP code is the 6-digit number an authenticator app shows; it changes every 30 seconds ("time step").
        # It returns that time step number if the code is right, else None.
        counter = accounts.check_totp(pend["secret"], code)
        if counter is None:
            return None
        # Turn two-step on: store the secret encrypted, remember the last time step used (so a code cannot be reused), and store only
        # hashes of the recovery codes. The plain codes are returned once for the person to write down.
        codes = accounts.make_recovery_codes()
        self._set_fields(name, mfa={"secret": self.secrets.encrypt(pend["secret"]), "on": True, "last": counter,
                                    "recovery": [accounts.hash_recovery(c) for c in codes]})
        self._mfa_pending.pop(name, None)
        self.auth.event("mfa_on", name, "", "")
        return codes

    def mfa_disable(self, name):
        """Switch two-step sign-in off and forget its secret and recovery codes."""
        self._set_fields(name, mfa={})
        self.auth.event("mfa_off", name, "", "")

    def mfa_new_recovery(self, name):
        """Replace the recovery codes with a new set (the old ones stop working). Returns the new plain codes, to show once."""
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
        # Rate limit (self.rl): after 10 wrong tries within 600 seconds, refuse everything for a while so codes cannot be guessed.
        if self.rl.blocked("mfa:" + name, 10, 600):
            return False
        rec = self.user_record(name)
        m = dict((rec or {}).get("mfa") or {})
        if not m.get("on"):
            return False
        # Try the authenticator code first. m["last"] is the newest time step already used, so the same code cannot be used twice.
        secret = self.secrets.decrypt(m.get("secret"))
        counter = accounts.check_totp(secret, code, m.get("last", 0)) if secret else None
        if counter is not None:
            m["last"] = counter
            self._set_fields(name, mfa=m)
            return True
        # Not a valid app code: maybe it is a one-time recovery code. use_recovery returns whether it matched and the codes still left.
        used, left = accounts.use_recovery(m.get("recovery") or [], code)
        if used:
            m["recovery"] = left
            self._set_fields(name, mfa=m)
            self.auth.event("mfa_recovery_used", name, "", f"{len(left)} left")
            return True
        # Wrong code: count it against the rate limit.
        self.rl.hit("mfa:" + name)
        return False

    def mfa_ticket(self, name, how):
        """A short-lived ticket that says 'the first step of signing in is done': the second step (a code) trades it for a session."""
        now = time.time()
        # Housekeeping: drop tickets that have expired, then, if there are still more than 500, drop the oldest (dicts remember insert order).
        for k in [k for k, v in self.mfa_tickets.items() if v["expires"] < now]:
            self.mfa_tickets.pop(k, None)
        while len(self.mfa_tickets) > 500:
            self.mfa_tickets.pop(next(iter(self.mfa_tickets)))
        # The ticket is random; we keep only its hash. It lasts 300 seconds (5 minutes) and allows a limited number of tries ("tries").
        ticket = secrets.token_urlsafe(24)
        self.mfa_tickets[auth.digest(ticket)] = {"user": name, "how": how, "expires": now + 300, "tries": 0}
        return ticket

    def mfa_finish(self, ticket, code):
        """(name, how) when the ticket is live and the code is right; otherwise None. A ticket allows 5 wrong codes."""
        t = self.mfa_tickets.get(auth.digest(ticket or ""))
        if not t or t["expires"] < time.time():
            return None
        # Right code: use up the ticket so it works once. Wrong code: count it, and kill the ticket after 5 misses.
        if self.mfa_check(t["user"], code):
            self.mfa_tickets.pop(auth.digest(ticket), None)
            return t["user"], t["how"]
        t["tries"] += 1
        if t["tries"] >= 5:
            self.mfa_tickets.pop(auth.digest(ticket), None)
        return None

    # ---- passkeys (WebAuthn): kept in the person's users.json entry as "passkeys": [{id, alg, pem, counter, name, created}]
    def passkey_list(self, name):
        """The person's passkeys, as safe summaries (id, label, created time); the public key and counter are not included."""
        return [{"id": p["id"], "name": p.get("name", "Passkey"), "created": p.get("created")} for p in (self.user_record(name) or {}).get("passkeys", [])]

    def passkey_challenge(self, kind, user=""):
        """Make a one-time random "challenge" the browser must sign to prove it holds the passkey. `kind` says why (e.g. register or sign in).

        Returns the challenge text; we remember only its hash, for 300 seconds, with the purpose and person it was made for.
        """
        now = time.time()
        for k in [k for k, v in self.pk_pending.items() if v["expires"] < now]:
            self.pk_pending.pop(k, None)
        while len(self.pk_pending) > 300:
            self.pk_pending.pop(next(iter(self.pk_pending)))
        # 32 random bytes, written in URL-safe base64 (a way to write bytes as plain text).
        challenge = passkeys.b64u(secrets.token_bytes(32))
        self.pk_pending[auth.digest(challenge)] = {"kind": kind, "user": user, "expires": now + 300}
        return challenge

    def passkey_take(self, challenge, kind, user=None):
        """Use up a challenge (each works once): True when it was issued by us, for this purpose (and this person)."""
        # pop removes it as it reads it, which is what makes a challenge work only once.
        p = self.pk_pending.pop(auth.digest(challenge or ""), None)
        return bool(p and p["kind"] == kind and p["expires"] >= time.time() and (user is None or p["user"] == user))

    def passkey_add(self, name, pk, label):
        """Save a new passkey `pk` (dict with id, alg, pem, counter) for the person under a label. Re-adding the same id replaces it; max 10 kept."""
        rec = self.user_record(name) or {}
        # Keep the other passkeys (not the same id), at most 9 of them, so with the new one there are at most 10.
        keep = [p for p in rec.get("passkeys", []) if p["id"] != pk["id"]][:9]
        self._set_fields(name, passkeys=keep + [dict(pk, name=str(label)[:40] or "Passkey", created=int(time.time()))])
        self.auth.event("passkey_added", name, "", str(label)[:40])

    def passkey_remove(self, name, cred_id):
        """Delete one passkey by its id. Returns False if the person had no such passkey, True if it was removed."""
        rec = self.user_record(name) or {}
        left = [p for p in rec.get("passkeys", []) if p["id"] != cred_id]
        if len(left) == len(rec.get("passkeys", [])):
            return False
        self._set_fields(name, passkeys=left)
        self.auth.event("passkey_removed", name, "", "")
        return True

    def passkey_find(self, cred_id):
        """Find which person owns the passkey with this id. Returns (user record, passkey) or (None, None)."""
        for u in self.users.values():
            for p in u.get("passkeys", []):
                if p["id"] == cred_id:
                    return u, p
        return None, None

    def google_on(self):
        """True when "Sign in with Google" is set up (both Google settings exist in the environment)."""
        return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))

    def signup_mode(self):
        """Who may create accounts: "closed", "invite" or "open". Anything else counts as "closed" (the safe choice)."""
        return self.security.get("signup_mode") if self.security.get("signup_mode") in ("closed", "invite", "open") else "closed"

    def save_security(self, **changes):
        """Change a setting in security.json (and keep it for the next start)."""
        # Accept only known setting names, apply them in memory, then also write them to security.json.
        clean = {k: v for k, v in changes.items() if k in SECURITY_DEFAULTS}
        self.security.update(clean)
        if self.data_dir:
            path = os.path.join(self.data_dir, "security.json")
            # Re-read the file so we only change what was asked and keep anything else saved in it.
            try:
                with open(path, encoding="utf-8") as f:
                    saved = json.load(f)
            except (OSError, ValueError):
                saved = {}
            saved.update(clean)
            # Private file (0o600), written to a temp name and swapped in, as in _save_users.
            fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(saved, f, indent=2)
            os.replace(path + ".tmp", path)

    def create_account(self, name, email, password, tier="free"):
        """A person who signed up with a name, an email and a password. Raises ValueError with a sentence the person can read."""
        # Validate everything before creating anything: name, email, password strength, then that neither name nor email is already used.
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
        # The email starts unverified; only a hash of the password is kept. "created" is the sign-up time in Unix seconds.
        entry = {"user": name, "tier": tier, "owner": False, "tz_minutes": 0, "email": email, "email_verified": False,
                 "pw": accounts.hash_password(password), "created": int(time.time())}
        self.users["e:" + name] = entry
        self._save_users()
        self._ensure_usage_user(entry)
        self.set_plan(name, tier)
        self.auth.event("signup", name, "", "password")
        return name

    def set_plan(self, name, tier):
        """Put a person on a plan (tier) in both the usage tracker and users.json. Raises ValueError for an unknown plan."""
        if tier not in self.cfg["tiers"]:
            raise ValueError("unknown plan")
        row = self.usage.get_user(name)
        self.usage.add_user(name, tier, row["tz_minutes"], row["owner"], row["overrides"])
        for u in self.users.values():
            if u["user"] == name:
                u["tier"] = tier
        self._save_users()
