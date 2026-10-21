"""
state_accounts.py - AppState's accounts part: users, keys, passwords, two-step sign-in, passkeys, plans and sign-up rules.
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
        return os.path.join(self.data_dir, "users.json") if self.data_dir else None

    def _load_security(self):
        sec = dict(SECURITY_DEFAULTS)
        if self.data_dir:
            try:
                with open(os.path.join(self.data_dir, "security.json"), encoding="utf-8") as f:
                    sec.update({k: v for k, v in json.load(f).items() if k in SECURITY_DEFAULTS})
            except (OSError, ValueError):
                pass
        return sec

    def _load_users(self):
        path, users = self._users_path(), {}
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                users = json.load(f)
        migrated = False
        for k in list(users):
            if not (k.startswith("h:") or k.startswith("e:")):           # an older file that kept the keys themselves: keep them working, store only the hash
                users["h:" + auth.digest(k)] = users.pop(k)
                migrated = True
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
        path = self._users_path()
        if path:
            tmp = path + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.users, f, indent=2)
            os.replace(tmp, path)
            try:
                os.chmod(path, 0o600)
                self._users_mtime = os.stat(path).st_mtime
            except OSError:
                pass

    def _reload_users_if_changed(self):
        """Another process (--rotate-key, --add-user) may have changed users.json while the server runs: read it again."""
        path = self._users_path()
        if not path:
            return
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
        try:
            self.usage.get_user(u["user"])
        except KeyError:
            self.usage.add_user(u["user"], u["tier"], u.get("tz_minutes", 0), owner=bool(u.get("owner") or u.get("unlimited")))

    def _entries(self, name):
        return [k for k, u in self.users.items() if u["user"] == name]

    def user_record(self, name):
        return next((u for u in self.users.values() if u["user"] == name), None)

    def add_user(self, name, tier, tz_minutes=0, email=None, key_prefix=""):
        """A new person: returns their key (shown once, never stored). For someone who already exists the plan is updated and None is returned:
        make them a pairing link instead (or rotate their key)."""
        if tier not in self.cfg["tiers"]:
            raise ValueError(f"plan must be one of {', '.join(self.cfg['tiers'])}")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name):
            raise ValueError("a name is letters, numbers, - and _ (up to 32)")
        rec = self.user_record(name)
        if rec is not None:
            if email:
                self.set_email(name, email)
            return None
        if email and not auth.clean_email(email):
            raise ValueError("that does not look like an email address")
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
        found = self._entries(name)
        if not found:
            raise ValueError(f"no one is called {name!r} (use owner, or a name you added with --add-user)")
        rec = dict(self.users[found[0]])
        key = (API_KEY_PREFIX if rec.get("app") else "") + secrets.token_urlsafe(24)
        new = "h:" + auth.digest(key)
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
        row = self.usage.get_user(entry["user"])
        admin = bool(row["owner"] or entry.get("admin"))
        granters = {auth.clean_email(e) for e in (self.security.get("grant_emails") or []) if auth.clean_email(e)}
        # who may give out plans, no-limits and admin rights: the PC owner, and an account that was made an admin by the PC owner AND has one of these emails
        granter = bool(entry.get("owner")) or bool(entry.get("admin") and auth.clean_email(entry.get("email") or "") in granters)
        owner = bool(row["owner"]) or granter                  # an admin the PC owner trusts (their email is in grant_emails) acts as the owner for everything
        admin = admin or owner
        return {"user": entry["user"], "owner": owner, "admin": admin, "founder": bool(entry.get("owner")), "granter": granter,
                "tier": row["tier"], "banned": bool(entry.get("banned")), "app": bool(entry.get("app")),
                "email": entry.get("email"), "has_password": bool(entry.get("pw")), "mfa": bool((entry.get("mfa") or {}).get("on"))}

    def who(self, key):
        """The person a key belongs to, or None."""
        if not key:
            return None
        self._reload_users_if_changed()
        entry = self.users.get("h:" + auth.digest(key))
        return self._who_of(entry) if entry else None

    def who_session(self, token):
        """The person a session cookie belongs to (the session is extended while it is used), or None."""
        self._reload_users_if_changed()
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
        rec = self.user_record(name)
        return self._who_of(rec) if rec else None

    def user_by_email(self, email):
        email = auth.clean_email(email)
        return next((u for u in self.users.values() if email and u.get("email") == email and u.get("email_verified") is not False), None)

    def set_access(self, name, plan=None, unlimited=None, admin=None):
        """Change one person's plan, whether they have no limits, and whether they have admin rights. The first owner account is never changed here."""
        rec = self.user_record(name)
        if not rec:
            raise ValueError("no one is called that")
        if rec.get("owner"):
            raise ValueError("the first owner account always has full rights; change another account")
        fields = {}
        if plan is not None:
            if plan not in self.cfg["tiers"]:
                raise ValueError("choose " + ", ".join(self.cfg["tiers"]))
            fields["tier"] = plan
        if unlimited is not None:
            fields["unlimited"] = bool(unlimited)
        if admin is not None:
            fields["admin"] = bool(admin)
        self._set_fields(name, **fields)
        row = self.usage.get_user(name)
        now = self.user_record(name)
        self.usage.add_user(name, now["tier"], row["tz_minutes"], bool(now.get("unlimited")), row["overrides"])
        self.auth.event("access_changed", name, "", f"plan={now['tier']} unlimited={bool(now.get('unlimited'))} admin={bool(now.get('admin'))}")
        return {"user": name, "plan": now["tier"], "unlimited": bool(now.get("unlimited")), "admin": bool(now.get("admin"))}

    def set_ban(self, name, banned):
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
        base = re.sub(r"[^A-Za-z0-9_-]", "", email.split("@")[0])[:24]
        if not accounts.clean_name(base):                       # too short, or a name nobody should be able to pick (admin, support...)
            base = (base + "user")[:24]
        name, n = base, 1
        while self.user_record(name):
            n += 1
            name = f"{base}{n}"
        entry = {"user": name, "tier": "free", "owner": False, "tz_minutes": 0, "email": email, "email_verified": True}
        self.users["e:" + name] = entry
        self._save_users()
        self._ensure_usage_user(entry)
        self.auth.event("signup", name, "", "email")
        return name

    def mark_email_verified(self, name):
        for k in self._entries(name):
            self.users[k]["email_verified"] = True
        self._save_users()

    # ---- passwords, MFA, sign-up
    # Kept in the person's users.json entry: "pw" (a scrypt hash) and "mfa" {"secret" (encrypted), "on", "last" (last time step used), "recovery" [hashes]}.
    def _set_fields(self, name, **fields):
        for k in self._entries(name):
            self.users[k].update(fields)
        self._save_users()

    def find_login(self, ident):
        """The account a sign-in name or email points to (a name, or a verified email), or None."""
        ident = str(ident or "").strip()
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
        if not rec and "@" in str(ident or ""):                              # an email that was never confirmed: still the account's own email, and the password is still needed
            em = auth.clean_email(ident)
            same = [u for u in self.users.values() if em and u.get("email") == em]
            rec = same[0] if len(same) == 1 else None
        if not rec or not rec.get("pw"):
            accounts.burn_time(password)
            return None
        return rec if accounts.verify_password(password, rec["pw"]) else None

    def set_password(self, name, password):
        problem = accounts.password_problem(password, name, (self.user_record(name) or {}).get("email", ""))
        if problem:
            raise ValueError(problem)
        self._set_fields(name, pw=accounts.hash_password(password))
        self.auth.event("password_set", name, "", "")

    def mfa_on(self, name):
        rec = self.user_record(name)
        return bool(rec and (rec.get("mfa") or {}).get("on"))

    def mfa_info(self, name):
        m = (self.user_record(name) or {}).get("mfa") or {}
        return {"on": bool(m.get("on")), "recovery_left": len(m.get("recovery") or [])}

    def mfa_begin(self, name):
        """A fresh secret for the person to add to their authenticator app. It is not active until a code from the app proves it works."""
        secret = accounts.new_secret()
        self._mfa_pending[name] = {"secret": secret, "expires": time.time() + 900}
        rec = self.user_record(name) or {}
        account = rec.get("email") or name
        return {"secret": accounts.group_secret(secret), "uri": accounts.otpauth_uri(account, secret)}

    def mfa_enable(self, name, code):
        """The 8 recovery codes (shown once) when `code` from the app matches the pending secret, else None."""
        pend = self._mfa_pending.get(name)
        if not pend or pend["expires"] < time.time():
            return None
        counter = accounts.check_totp(pend["secret"], code)
        if counter is None:
            return None
        codes = accounts.make_recovery_codes()
        self._set_fields(name, mfa={"secret": self.secrets.encrypt(pend["secret"]), "on": True, "last": counter,
                                    "recovery": [accounts.hash_recovery(c) for c in codes]})
        self._mfa_pending.pop(name, None)
        self.auth.event("mfa_on", name, "", "")
        return codes

    def mfa_disable(self, name):
        self._set_fields(name, mfa={})
        self.auth.event("mfa_off", name, "", "")

    def mfa_new_recovery(self, name):
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
        if self.rl.blocked("mfa:" + name, 10, 600):
            return False
        rec = self.user_record(name)
        m = dict((rec or {}).get("mfa") or {})
        if not m.get("on"):
            return False
        secret = self.secrets.decrypt(m.get("secret"))
        counter = accounts.check_totp(secret, code, m.get("last", 0)) if secret else None
        if counter is not None:
            m["last"] = counter
            self._set_fields(name, mfa=m)
            return True
        used, left = accounts.use_recovery(m.get("recovery") or [], code)
        if used:
            m["recovery"] = left
            self._set_fields(name, mfa=m)
            self.auth.event("mfa_recovery_used", name, "", f"{len(left)} left")
            return True
        self.rl.hit("mfa:" + name)
        return False

    def mfa_ticket(self, name, how):
        """A short-lived ticket that says 'the first step of signing in is done': the second step (a code) trades it for a session."""
        now = time.time()
        for k in [k for k, v in self.mfa_tickets.items() if v["expires"] < now]:
            self.mfa_tickets.pop(k, None)
        while len(self.mfa_tickets) > 500:
            self.mfa_tickets.pop(next(iter(self.mfa_tickets)))
        ticket = secrets.token_urlsafe(24)
        self.mfa_tickets[auth.digest(ticket)] = {"user": name, "how": how, "expires": now + 300, "tries": 0}
        return ticket

    def mfa_finish(self, ticket, code):
        """(name, how) when the ticket is live and the code is right; otherwise None. A ticket allows 5 wrong codes."""
        t = self.mfa_tickets.get(auth.digest(ticket or ""))
        if not t or t["expires"] < time.time():
            return None
        if self.mfa_check(t["user"], code):
            self.mfa_tickets.pop(auth.digest(ticket), None)
            return t["user"], t["how"]
        t["tries"] += 1
        if t["tries"] >= 5:
            self.mfa_tickets.pop(auth.digest(ticket), None)
        return None

    # ---- passkeys (WebAuthn): kept in the person's users.json entry as "passkeys": [{id, alg, pem, counter, name, created}]
    def passkey_list(self, name):
        return [{"id": p["id"], "name": p.get("name", "Passkey"), "created": p.get("created")} for p in (self.user_record(name) or {}).get("passkeys", [])]

    def passkey_challenge(self, kind, user=""):
        now = time.time()
        for k in [k for k, v in self.pk_pending.items() if v["expires"] < now]:
            self.pk_pending.pop(k, None)
        while len(self.pk_pending) > 300:
            self.pk_pending.pop(next(iter(self.pk_pending)))
        challenge = passkeys.b64u(secrets.token_bytes(32))
        self.pk_pending[auth.digest(challenge)] = {"kind": kind, "user": user, "expires": now + 300}
        return challenge

    def passkey_take(self, challenge, kind, user=None):
        """Use up a challenge (each works once): True when it was issued by us, for this purpose (and this person)."""
        p = self.pk_pending.pop(auth.digest(challenge or ""), None)
        return bool(p and p["kind"] == kind and p["expires"] >= time.time() and (user is None or p["user"] == user))

    def passkey_add(self, name, pk, label):
        rec = self.user_record(name) or {}
        keep = [p for p in rec.get("passkeys", []) if p["id"] != pk["id"]][:9]
        self._set_fields(name, passkeys=keep + [dict(pk, name=str(label)[:40] or "Passkey", created=int(time.time()))])
        self.auth.event("passkey_added", name, "", str(label)[:40])

    def passkey_remove(self, name, cred_id):
        rec = self.user_record(name) or {}
        left = [p for p in rec.get("passkeys", []) if p["id"] != cred_id]
        if len(left) == len(rec.get("passkeys", [])):
            return False
        self._set_fields(name, passkeys=left)
        self.auth.event("passkey_removed", name, "", "")
        return True

    def passkey_find(self, cred_id):
        for u in self.users.values():
            for p in u.get("passkeys", []):
                if p["id"] == cred_id:
                    return u, p
        return None, None

    def google_on(self):
        return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))

    def signup_mode(self):
        return self.security.get("signup_mode") if self.security.get("signup_mode") in ("closed", "invite", "open") else "closed"

    def save_security(self, **changes):
        """Change a setting in security.json (and keep it for the next start)."""
        clean = {k: v for k, v in changes.items() if k in SECURITY_DEFAULTS}
        self.security.update(clean)
        if self.data_dir:
            path = os.path.join(self.data_dir, "security.json")
            try:
                with open(path, encoding="utf-8") as f:
                    saved = json.load(f)
            except (OSError, ValueError):
                saved = {}
            saved.update(clean)
            fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(saved, f, indent=2)
            os.replace(path + ".tmp", path)

    def create_account(self, name, email, password, tier="free"):
        """A person who signed up with a name, an email and a password. Raises ValueError with a sentence the person can read."""
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
        entry = {"user": name, "tier": tier, "owner": False, "tz_minutes": 0, "email": email, "email_verified": False,
                 "pw": accounts.hash_password(password), "created": int(time.time())}
        self.users["e:" + name] = entry
        self._save_users()
        self._ensure_usage_user(entry)
        self.set_plan(name, tier)
        self.auth.event("signup", name, "", "password")
        return name

    def set_plan(self, name, tier):
        if tier not in self.cfg["tiers"]:
            raise ValueError("unknown plan")
        row = self.usage.get_user(name)
        self.usage.add_user(name, tier, row["tz_minutes"], row["owner"], row["overrides"])
        for u in self.users.values():
            if u["user"] == name:
                u["tier"] = tier
        self._save_users()
