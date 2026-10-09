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

EVENTS_KEPT = 5000


def digest(secret):
    return hashlib.sha256(str(secret).encode()).hexdigest()


def norm_invite(code):
    """An invite code however it was typed or pasted (capitals, spaces, with or without dashes) in the form it is stored: xxxx-xxxx-xxxx."""
    raw = str(code or "").strip().lower()
    flat = re.sub(r"[^0-9a-z]", "", raw)
    return "-".join(flat[i:i + 4] for i in range(0, 12, 4)) if len(flat) == 12 else raw


def same(a, b):
    return hmac.compare_digest(str(a).encode(), str(b).encode())


def device_label(user_agent):
    """A short, human label for a browser: 'Chrome on Android'. Never the full user-agent string."""
    ua = str(user_agent or "")
    os_ = next((n for p, n in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"), ("Macintosh", "Mac"),
                               ("CrOS", "Chromebook"), ("Linux", "Linux")) if p in ua), "an unknown device")
    br = next((n for p, n in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari")) if p in ua), "A browser")
    return f"{br} on {os_}"


class RateLimiter:
    """A sliding window per name. `blocked` says how many seconds until the name may try again (0 = fine)."""

    def __init__(self):
        self.hits, self.lock = {}, threading.Lock()

    def hit(self, name, now=None):
        now = time.time() if now is None else now
        with self.lock:
            self.hits.setdefault(name, []).append(now)

    def blocked(self, name, limit, window, now=None):
        now = time.time() if now is None else now
        with self.lock:
            recent = [t for t in self.hits.get(name, []) if now - t < window]
            self.hits[name] = recent
            if len(recent) < limit:
                return 0
            return max(1, int(window - (now - recent[len(recent) - limit])) + 1)

    def clear(self, name):
        with self.lock:
            self.hits.pop(name, None)

    def trim(self, older_than=86400, now=None):
        now = time.time() if now is None else now
        with self.lock:
            for k in list(self.hits):
                self.hits[k] = [t for t in self.hits[k] if now - t < older_than]
                if not self.hits[k]:
                    del self.hits[k]


class AuthDB:
    """Sessions, pairing links, email codes and the audit log in one small SQLite file (auth.db), or in memory for tests."""

    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
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
        now = time.time() if now is None else now
        token, sid = secrets.token_urlsafe(32), secrets.token_hex(8)
        with self.lock:
            self.db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
                            (sid, digest(token), user, now, now, now + days * 86400, device_label(user_agent), self._ip_hint(ip)))
            self.db.commit()
        return sid, token

    @staticmethod
    def _ip_hint(ip):
        """Keep only a coarse part of the address (for 'where was I signed in'), not the whole thing."""
        ip = str(ip or "")
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
            row = self.db.execute("SELECT id, user, expires, revoked FROM sessions WHERE token_hash = ?", (digest(token),)).fetchone()
            if not row or row[3] or row[2] < now:
                return None
            self.db.execute("UPDATE sessions SET last_seen = ?, expires = ? WHERE id = ?", (now, now + days * 86400, row[0]))
            self.db.commit()
            return {"id": row[0], "user": row[1]}

    def sessions_for(self, user, now=None):
        now = time.time() if now is None else now
        with self.lock:
            rows = self.db.execute("SELECT id, created, last_seen, device, ip FROM sessions WHERE user = ? AND revoked = 0 AND expires > ? "
                                   "ORDER BY last_seen DESC", (user, now)).fetchall()
        return [{"id": r[0], "created": r[1], "last_seen": r[2], "device": r[3], "where": r[4]} for r in rows]

    def revoke(self, sid, user=None):
        with self.lock:
            cur = self.db.execute("UPDATE sessions SET revoked = 1 WHERE id = ? AND revoked = 0" + (" AND user = ?" if user else ""),
                                  (sid, user) if user else (sid,))
            self.db.commit()
            return cur.rowcount > 0

    def revoke_user(self, user, except_id=None):
        with self.lock:
            cur = self.db.execute("UPDATE sessions SET revoked = 1 WHERE user = ? AND revoked = 0 AND id != ?", (user, except_id or ""))
            self.db.commit()
            return cur.rowcount

    def prune(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            self.db.execute("DELETE FROM sessions WHERE revoked = 1 OR expires < ?", (now - 7 * 86400,))
            self.db.execute("DELETE FROM pairs WHERE used = 1 OR expires < ?", (now - 86400,))
            self.db.execute("DELETE FROM codes WHERE expires < ?", (now,))
            self.db.execute("DELETE FROM invites WHERE expires < ? OR uses_left <= 0", (now - 86400,))
            self.db.commit()

    # ---- one-time pairing links
    def new_pair(self, user, minutes=15, made_by="", now=None):
        now = time.time() if now is None else now
        token = secrets.token_urlsafe(24)
        with self.lock:
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
            if not row or row[2] or row[1] < now:
                return None
            cur = self.db.execute("UPDATE pairs SET used = 1 WHERE token_hash = ? AND used = 0", (digest(token),))
            self.db.commit()
            return row[0] if cur.rowcount else None

    # ---- email codes
    def put_code(self, email, code, minutes=10, now=None):
        now = time.time() if now is None else now
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO codes VALUES (?, ?, ?, 0)", (email.lower(), digest(code), now + minutes * 60))
            self.db.commit()

    def check_code(self, email, code, max_tries=5, now=None):
        now = time.time() if now is None else now
        email = email.lower()
        with self.lock:
            row = self.db.execute("SELECT code_hash, expires, tries FROM codes WHERE email = ?", (email,)).fetchone()
            if not row or row[1] < now or row[2] >= max_tries:
                return False
            if same(row[0], digest(str(code).strip())):
                self.db.execute("DELETE FROM codes WHERE email = ?", (email,))
                self.db.commit()
                return True
            self.db.execute("UPDATE codes SET tries = tries + 1 WHERE email = ?", (email,))
            self.db.commit()
            return False

    # ---- invite codes (for a closed sign-up: the owner makes a code, someone uses it once or a few times)
    def new_invite(self, tier="free", uses=1, days=14, note="", now=None):
        now = time.time() if now is None else now
        code = "-".join(secrets.token_hex(2) for _ in range(3))
        with self.lock:
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
        now = time.time() if now is None else now
        with self.lock:
            rows = self.db.execute("SELECT id, tier, uses_left, expires, note, hint FROM invites WHERE uses_left > 0 AND expires >= ? ORDER BY made DESC", (now,)).fetchall()
        return [{"id": r[0], "tier": r[1], "uses_left": r[2], "expires": r[3], "note": r[4], "ends_with": r[5]} for r in rows]

    def revoke_invite(self, invite_id):
        with self.lock:
            cur = self.db.execute("DELETE FROM invites WHERE id = ?", (str(invite_id),))
            self.db.commit()
            return cur.rowcount > 0

    # ---- the audit log
    def event(self, kind, user="", ip="", detail="", now=None):
        now = time.time() if now is None else now
        with self.lock:
            self.db.execute("INSERT INTO events (at, kind, user, ip, detail) VALUES (?, ?, ?, ?, ?)", (now, kind, str(user or ""), self._ip_hint(ip), str(detail)[:300]))
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
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM events WHERE kind = ? AND at >= ?", (kind, since)).fetchone()[0]

    def events(self, limit=100, kind=None, user=None):
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
        args.append(max(1, min(int(limit), 500)))
        with self.lock:
            rows = self.db.execute(q, args).fetchall()
        return [{"at": r[0], "kind": r[1], "user": r[2], "ip": r[3], "detail": r[4]} for r in rows]


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}")


def clean_email(text):
    """A lower-case address, or None if it does not look like one (no spaces, one @, a dot in the domain)."""
    text = str(text or "").strip()
    return text.lower() if len(text) <= 254 and EMAIL_RE.fullmatch(text) else None


def make_code():
    return f"{secrets.randbelow(10**6):06d}"
