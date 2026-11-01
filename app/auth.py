"""
auth.py - Sign-in for the Emvryx app: sessions you can revoke, one-time pairing links, email codes, rate limits and an audit log.

WHAT THIS FILE DOES
    A person proves who they are once (with a key, a one-time pairing link, or a code sent to their email) and gets a SESSION: a long random
    token kept in the browser's cookie. The server stores only a hash of it, so a stolen database cannot be used to sign in, and each session
    can be listed and revoked on its own ("sign out that phone"). The key itself is no longer the cookie.

    * Keys are random (192 bits). We keep only their SHA-256, never the key (a fast hash is right for a long random secret).
    * A pairing link (`/pair/<token>`) works once, for 15 minutes, and turns into a session: it replaces `/?key=...` links that sit in
      browser history.
    * Email codes: 6 digits, valid 10 minutes, 5 tries, one live code per address, stored hashed.
    * RateLimiter: a sliding window per key (an address, an email), used to slow down guessing and to lock an address out for a while.
    * The audit log keeps the last 5,000 security events (sign-ins, failures, pairing, revoking, bans) for the owner.

    Everything here is plain code with a clock you can fake, so it is tested without a server.
"""
import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time

# How many audit-log rows we keep. Older rows are deleted when a new one is added (see AuthDB.event), so the log cannot grow forever.
EVENTS_KEPT = 5000


def digest(secret):
    """One-way fingerprint (SHA-256, as hex text) of a secret. We store this instead of the secret itself, so a leaked database cannot be used to sign in.
    In: any secret (token, code, key). Out: a 64-character hex string.
    """
    # str() first so numbers work; .encode() turns text into bytes, which is what a hash function needs.
    return hashlib.sha256(str(secret).encode()).hexdigest()


def norm_invite(code):
    """An invite code however it was typed or pasted (capitals, spaces, with or without dashes) in the form it is stored: xxxx-xxxx-xxxx."""
    # str(code or "") turns None into an empty string; then trim spaces and lower-case it.
    raw = str(code or "").strip().lower()
    # A regex is a text pattern. [^0-9a-z] means 'any character that is NOT a digit or a letter'; re.sub removes all of those (spaces, dashes).
    flat = re.sub(r"[^0-9a-z]", "", raw)
    # A real code has 12 characters. Cut it into three groups of 4 (positions 0, 4, 8) and join with dashes. Anything else is returned as typed.
    return "-".join(flat[i:i + 4] for i in range(0, 12, 4)) if len(flat) == 12 else raw


def same(a, b):
    """True if two secrets are equal, compared in constant time.
    A plain == stops at the first different character, so how long it takes could leak how much matched (a 'timing attack'). hmac.compare_digest always takes the same time.
    """
    return hmac.compare_digest(str(a).encode(), str(b).encode())


def device_label(user_agent):
    """A short, human label for a browser: 'Chrome on Android'. Never the full user-agent string."""
    # The user-agent is the text a browser sends to say what it is, e.g. 'Mozilla/5.0 (Linux; Android 14) Chrome/120...'.
    ua = str(user_agent or "")
    # next(generator, default) gives the first match, or the default. Each pair is (text to look for, friendly name); the first name whose text appears in the user-agent wins.
    # Order matters: iPhone/iPad are checked before Mac, and Android before Linux, because those user-agents also contain the later words.
    os_ = next((n for p, n in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"), ("Macintosh", "Mac"),
                               ("CrOS", "Chromebook"), ("Linux", "Linux")) if p in ua), "an unknown device")
    # Same idea for the browser. Order matters again: Edge and Opera also say 'Chrome/' and 'Safari/', so they are checked first and Safari last.
    br = next((n for p, n in (("Emvryx-Android/", "The Emvryx app"), ("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari")) if p in ua), "A browser")
    return f"{br} on {os_}"


class RateLimiter:
    """A sliding window per name. `blocked` says how many seconds until the name may try again (0 = fine)."""

    def __init__(self):
        """Start with no recorded attempts. `hits` maps a name to a list of timestamps; `lock` stops two threads changing it at the same time."""
        # A threading.Lock makes sure only one thread at a time touches the dict (the server handles several requests in parallel).
        self.hits, self.lock = {}, threading.Lock()

    def hit(self, name, now=None):
        """Record one attempt for `name` right now. `now` lets tests pass a fake clock (seconds since 1970); None means use the real time."""
        now = time.time() if now is None else now
        with self.lock:
            # setdefault makes the list the first time, then appends this attempt's timestamp.
            self.hits.setdefault(name, []).append(now)

    def blocked(self, name, limit, window, now=None):
        """How many seconds `name` must wait before trying again; 0 means it is allowed.
        In: the name, `limit` (attempts allowed) and `window` (seconds the attempts count for). It blocks when `limit` attempts happened in the last `window` seconds.
        """
        now = time.time() if now is None else now
        with self.lock:
            # Keep only attempts still inside the window, and save the shortened list back so old ones do not pile up.
            recent = [t for t in self.hits.get(name, []) if now - t < window]
            self.hits[name] = recent
            if len(recent) < limit:
                return 0
            # Wait until the oldest attempt that still counts falls out of the window (+1 to round up). Never report less than 1 second while blocked.
            return max(1, int(window - (now - recent[len(recent) - limit])) + 1)

    def clear(self, name):
        """Forget all attempts for `name` (used after a successful sign-in so the person starts fresh)."""
        with self.lock:
            self.hits.pop(name, None)

    def trim(self, older_than=86400, now=None):
        """Housekeeping: drop attempts older than `older_than` seconds (default one day) and remove names left with none, so memory stays small."""
        now = time.time() if now is None else now
        with self.lock:
            # list(...) copies the keys first, because we delete from the dict while looping.
            for k in list(self.hits):
                self.hits[k] = [t for t in self.hits[k] if now - t < older_than]
                if not self.hits[k]:
                    del self.hits[k]


class AuthDB:
    """Sessions, pairing links, email codes and the audit log in one small SQLite file (auth.db), or in memory for tests."""

    def __init__(self, path=":memory:"):
        """Open (or create) the SQLite database at `path` and make the tables if they are missing. ":memory:" is a throw-away database that lives only in RAM, used by tests."""
        # check_same_thread=False lets several server threads share this one connection; self.lock (below) keeps them from colliding.
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            # Tables: sessions (signed-in devices), pairs (one-time links), codes (email codes), invites (sign-up codes), events (audit log).
            # Only hashes of tokens and codes are stored, never the secrets. IF NOT EXISTS makes this safe to run on every start.
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, token_hash TEXT UNIQUE, user TEXT, created REAL, last_seen REAL,
                                                     expires REAL, device TEXT, ip TEXT, revoked INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS pairs (token_hash TEXT PRIMARY KEY, user TEXT, expires REAL, used INTEGER DEFAULT 0, made_by TEXT);
                CREATE TABLE IF NOT EXISTS codes (email TEXT PRIMARY KEY, code_hash TEXT, expires REAL, tries INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS invites (id TEXT PRIMARY KEY, code_hash TEXT UNIQUE, tier TEXT, uses_left INTEGER, expires REAL, note TEXT, made REAL, hint TEXT);
                CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, kind TEXT, user TEXT, ip TEXT, detail TEXT);
            """)
            self.db.commit()

    # ---- sessions
    def new_session(self, user, user_agent="", ip="", days=90, now=None):
        """Create a sign-in session for `user` that lasts `days` days.
        Out: (session id, token). The id is safe to show in a list; the token goes into the browser cookie and only its hash is stored.
        """
        now = time.time() if now is None else now
        # `secrets` makes cryptographically strong random values (unlike `random`). token: ~43 URL-safe characters (256 bits). sid: 16 hex characters, just a label.
        token, sid = secrets.token_urlsafe(32), secrets.token_hex(8)
        with self.lock:
            # The ? marks are placeholders filled from the tuple: this stops SQL injection (a person's text being run as SQL). 86400 = seconds in a day. The 0 in the SQL is 'revoked = no'.
            self.db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
                            (sid, digest(token), user, now, now, now + days * 86400, device_label(user_agent), self._ip_hint(ip)))
            self.db.commit()
        return sid, token

    # staticmethod: this function does not use `self`, so it can be called as AuthDB._ip_hint(ip).
    @staticmethod
    def _ip_hint(ip):
        """Keep only a coarse part of the address (for 'where was I signed in'), not the whole thing."""
        ip = str(ip or "")
        # A colon means an IPv6 address: keep the first three groups. Otherwise it should be IPv4 (four numbers split by dots): keep the first two.
        if ":" in ip:
            return ":".join(ip.split(":")[:3]) + "::"
        parts = ip.split(".")
        return ".".join(parts[:2]) + ".x.x" if len(parts) == 4 else ""

    def session(self, token, days=90, now=None):
        """{'id', 'user'} for a live session, else None. A live session is extended (rolling) up to `days` from now."""
        if not token:
            return None
        now = time.time() if now is None else now
        with self.lock:
            # Look the session up by the HASH of the token. row = (id, user, expires, revoked) or None.
            row = self.db.execute("SELECT id, user, expires, revoked FROM sessions WHERE token_hash = ?", (digest(token),)).fetchone()
            # Reject if unknown, revoked (row[3]), or already expired (row[2]).
            if not row or row[3] or row[2] < now:
                return None
            # Still valid: note that it was just used and push the expiry forward (the 'rolling' part).
            self.db.execute("UPDATE sessions SET last_seen = ?, expires = ? WHERE id = ?", (now, now + days * 86400, row[0]))
            self.db.commit()
            return {"id": row[0], "user": row[1]}

    def last_seen_map(self):
        """{user: the last time any of their devices used the app}, for the owner's People list."""
        with self.lock:
            rows = self.db.execute("SELECT user, MAX(last_seen) FROM sessions GROUP BY user").fetchall()
        return {r[0]: r[1] for r in rows}

    def sessions_for(self, user, now=None):
        """List one person's live (not revoked, not expired) sessions, most recently used first, for the 'your devices' screen.
        Out: a list of dicts with id, created, last_seen, device label and a coarse 'where'.
        """
        now = time.time() if now is None else now
        with self.lock:
            rows = self.db.execute("SELECT id, created, last_seen, device, ip FROM sessions WHERE user = ? AND revoked = 0 AND expires > ? "
                                   "ORDER BY last_seen DESC", (user, now)).fetchall()
        return [{"id": r[0], "created": r[1], "last_seen": r[2], "device": r[3], "where": r[4]} for r in rows]

    def revoke(self, sid, user=None):
        """Sign out one session by id. If `user` is given it must be that person's session (so nobody can revoke someone else's).
        Out: True if a session was really revoked.
        """
        with self.lock:
            # Build the SQL: add ' AND user = ?' only when a user was given, and pass matching values. rowcount (rows changed) tells us if anything matched.
            cur = self.db.execute("UPDATE sessions SET revoked = 1 WHERE id = ? AND revoked = 0" + (" AND user = ?" if user else ""),
                                  (sid, user) if user else (sid,))
            self.db.commit()
            return cur.rowcount > 0

    def revoke_user(self, user, except_id=None):
        """Sign a person out everywhere, optionally keeping the session `except_id` (the device they are using now).
        Out: how many sessions were revoked.
        """
        with self.lock:
            cur = self.db.execute("UPDATE sessions SET revoked = 1 WHERE user = ? AND revoked = 0 AND id != ?", (user, except_id or ""))
            self.db.commit()
            return cur.rowcount

    def prune(self, now=None):
        """Housekeeping: delete old rows so the database stays small. Called now and then by the server.
        Revoked or long-expired sessions, used or old pairing links, expired email codes and spent or expired invites all go. The extra days (7 * 86400, 86400) keep recent rows around a little while.
        """
        now = time.time() if now is None else now
        with self.lock:
            self.db.execute("DELETE FROM sessions WHERE revoked = 1 OR expires < ?", (now - 7 * 86400,))
            self.db.execute("DELETE FROM pairs WHERE used = 1 OR expires < ?", (now - 86400,))
            self.db.execute("DELETE FROM codes WHERE expires < ?", (now,))
            self.db.execute("DELETE FROM invites WHERE expires < ? OR uses_left <= 0", (now - 86400,))
            self.db.commit()

    # ---- one-time pairing links
    def new_pair(self, user, minutes=15, made_by="", now=None):
        """Make a one-time pairing link token for `user` (valid `minutes` minutes). `made_by` records who asked for it. Out: the token (only its hash is stored)."""
        now = time.time() if now is None else now
        token = secrets.token_urlsafe(24)
        with self.lock:
            # The last 0 is 'used = no'. The link stops working at now + minutes * 60 seconds.
            self.db.execute("INSERT INTO pairs VALUES (?, ?, ?, 0, ?)", (digest(token), user, now + minutes * 60, made_by))
            self.db.commit()
        return token

    def peek_pair(self, token, now=None):
        """The person a pairing link is for, WITHOUT using it up (so a chat app's link preview cannot burn it): None if it is unknown, used or late."""
        if not token:
            return None
        now = time.time() if now is None else now
        with self.lock:
            row = self.db.execute("SELECT user, expires, used FROM pairs WHERE token_hash = ?", (digest(token),)).fetchone()
        return row[0] if row and not row[2] and row[1] >= now else None

    def use_pair(self, token, now=None):
        """The person a pairing link is for, once. A second use, or a late one, gets None."""
        if not token:
            return None
        now = time.time() if now is None else now
        with self.lock:
            row = self.db.execute("SELECT user, expires, used FROM pairs WHERE token_hash = ?", (digest(token),)).fetchone()
            # Unknown, already used (row[2]) or expired (row[1]): refuse.
            if not row or row[2] or row[1] < now:
                return None
            # Mark it used. The 'AND used = 0' makes this atomic: if two requests race, only one gets rowcount 1 and the other gets None.
            cur = self.db.execute("UPDATE pairs SET used = 1 WHERE token_hash = ? AND used = 0", (digest(token),))
            self.db.commit()
            return row[0] if cur.rowcount else None

    # ---- email codes
    def put_code(self, email, code, minutes=10, now=None):
        """Save an email sign-in code (hashed) for an address, valid `minutes` minutes. INSERT OR REPLACE means a new code replaces the old one, so only one is live per address, and tries restart at 0."""
        now = time.time() if now is None else now
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO codes VALUES (?, ?, ?, 0)", (email.lower(), digest(code), now + minutes * 60))
            self.db.commit()

    def check_code(self, email, code, max_tries=5, now=None):
        """Is `code` the right live code for this address? True (and the code is used up) or False.
        Wrong guesses are counted; after `max_tries` the code is dead, so the 6 digits cannot be brute-forced.
        """
        now = time.time() if now is None else now
        email = email.lower()
        with self.lock:
            row = self.db.execute("SELECT code_hash, expires, tries FROM codes WHERE email = ?", (email,)).fetchone()
            # No code, expired, or too many wrong tries already: fail without even looking at the guess.
            if not row or row[1] < now or row[2] >= max_tries:
                return False
            # Compare hashes in constant time. Right: delete the code so it works only once.
            if same(row[0], digest(str(code).strip())):
                self.db.execute("DELETE FROM codes WHERE email = ?", (email,))
                self.db.commit()
                return True
            # Wrong: count this try.
            self.db.execute("UPDATE codes SET tries = tries + 1 WHERE email = ?", (email,))
            self.db.commit()
            return False

    # ---- invite codes (for a closed sign-up: the owner makes a code, someone uses it once or a few times)
    def new_invite(self, tier="free", uses=1, days=14, note="", now=None):
        """Make an invite code (format xxxx-xxxx-xxxx) that gives plan `tier`, can be used `uses` times and lasts `days` days. `note` is a label for the owner (cut to 60 characters).
        Out: the code itself - the only time it is visible; only its hash and last 4 characters (`hint`) are stored.
        """
        now = time.time() if now is None else now
        # Three groups of 4 random hex characters (token_hex(2) = 2 bytes = 4 characters).
        code = "-".join(secrets.token_hex(2) for _ in range(3))
        with self.lock:
            # max(1, int(uses)) makes sure there is at least one use. code[-4:] is the last 4 characters, kept so the owner can recognise which invite is which.
            self.db.execute("INSERT INTO invites VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (secrets.token_hex(4), digest(code), tier, max(1, int(uses)),
                                                                                   now + days * 86400, str(note)[:60], now, code[-4:]))
            self.db.commit()
        return code

    def peek_invite(self, code, now=None):
        """The plan an invite code gives, WITHOUT using it, or None."""
        now = time.time() if now is None else now
        with self.lock:
            row = self.db.execute("SELECT tier FROM invites WHERE code_hash = ? AND uses_left > 0 AND expires >= ?", (digest(norm_invite(code)), now)).fetchone()
        return row[0] if row else None

    def use_invite(self, code, now=None):
        now = time.time() if now is None else now
        with self.lock:
            cur = self.db.execute("UPDATE invites SET uses_left = uses_left - 1 WHERE code_hash = ? AND uses_left > 0 AND expires >= ?",
                                  (digest(norm_invite(code)), now))
            self.db.commit()
            if not cur.rowcount:
                return None
            return self.db.execute("SELECT tier FROM invites WHERE code_hash = ?", (digest(norm_invite(code)),)).fetchone()[0]

    def invites(self, now=None):
        """The invites still usable (uses left and not expired), newest first, for the owner's list. The code is never returned, only `ends_with`."""
        now = time.time() if now is None else now
        with self.lock:
            rows = self.db.execute("SELECT id, tier, uses_left, expires, note, hint FROM invites WHERE uses_left > 0 AND expires >= ? ORDER BY made DESC", (now,)).fetchall()
        return [{"id": r[0], "tier": r[1], "uses_left": r[2], "expires": r[3], "note": r[4], "ends_with": r[5]} for r in rows]

    def revoke_invite(self, invite_id):
        """Delete an invite by its id so it can no longer be used. Out: True if one was deleted."""
        with self.lock:
            cur = self.db.execute("DELETE FROM invites WHERE id = ?", (str(invite_id),))
            self.db.commit()
            return cur.rowcount > 0

    # ---- the audit log
    def event(self, kind, user="", ip="", detail="", now=None):
        """Add one row to the audit log (kind = what happened, e.g. a failed sign-in). The IP is shortened, `detail` is cut to 300 characters, and the log is trimmed to the newest EVENTS_KEPT rows."""
        now = time.time() if now is None else now
        with self.lock:
            self.db.execute("INSERT INTO events (at, kind, user, ip, detail) VALUES (?, ?, ?, ?, ?)", (now, kind, str(user or ""), self._ip_hint(ip), str(detail)[:300]))
            # Ids only go up, so deleting everything more than EVENTS_KEPT below the newest id keeps the last EVENTS_KEPT rows.
            self.db.execute("DELETE FROM events WHERE id <= (SELECT MAX(id) FROM events) - ?", (EVENTS_KEPT,))
            self.db.commit()

    def scrub_user(self, user):
        """After an account is deleted: their name leaves the security log (the events stay, as '(deleted)') and their sessions are removed."""
        with self.lock:
            self.db.execute("UPDATE events SET user = '(deleted)' WHERE user = ?", (user,))
            self.db.execute("DELETE FROM sessions WHERE user = ?", (user,))
            self.db.execute("DELETE FROM pairs WHERE user = ?", (user,))
            self.db.commit()

    def count(self, kind, since=0):
        """How many audit events of this `kind` happened since the time `since` (seconds since 1970)."""
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM events WHERE kind = ? AND at >= ?", (kind, since)).fetchone()[0]

    def events(self, limit=100, kind=None, user=None):
        """Read the audit log, newest first, optionally only one `kind` and/or one `user`. `limit` is forced into 1..500.
        Out: a list of dicts (at, kind, user, ip, detail).
        """
        # Build the query piece by piece: start with the base, then add WHERE filters only for the options that were given. Values go in `args` (never pasted into the SQL text) to stay safe from SQL injection.
        q, args = "SELECT at, kind, user, ip, detail FROM events", []
        conds = []
        if kind:
            conds.append("kind = ?")
            args.append(kind)
        if user:
            conds.append("user = ?")
            args.append(user)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY id DESC LIMIT ?"
        # Clamp the limit between 1 and 500 so a caller cannot ask for the whole table.
        args.append(max(1, min(int(limit), 500)))
        with self.lock:
            rows = self.db.execute(q, args).fetchall()
        return [{"at": r[0], "kind": r[1], "user": r[2], "ip": r[3], "detail": r[4]} for r in rows]


# A pattern for an email address: name part (letters, digits and . _ % + -, up to 64) then @, then a domain (up to 190 characters), then a dot and a 2-24 letter ending like 'com'.
# It is a sanity check, not a full standard check.
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}")


def clean_email(text):
    """A lower-case address, or None if it does not look like one (no spaces, one @, a dot in the domain)."""
    text = str(text or "").strip()
    # 254 is the longest email address allowed. fullmatch means the WHOLE text must fit the pattern, not just a part of it.
    return text.lower() if len(text) <= 254 and EMAIL_RE.fullmatch(text) else None


def make_code():
    """A new 6-digit email sign-in code as text, e.g. '048213'. randbelow(10**6) picks 0..999999 securely; :06d pads with leading zeros to 6 digits."""
    return f"{secrets.randbelow(10**6):06d}"
