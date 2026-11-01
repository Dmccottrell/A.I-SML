"""
shares.py - Read-only links to a chat: "share this conversation".

WHAT THIS FILE DOES
    A person can make a link to a COPY of one of their chats (not private chats). The copy is taken when the link is made, so later messages and edits are not
    exposed, and it holds only the words (no pictures, files, notes or names of apps). The link is a long random address (/s/<token>); only its hash is stored.
    It expires (7 days by default, up to 30), the person can cancel it any time, and the owner has to switch sharing on first (Admin > Overview);
    switching it off stops every link at once. Anyone with the link can read it, so the page says so before it is made.
"""
import html
import json
import secrets
import sqlite3
import threading
import time

import auth

MAX_ACTIVE = 20         # most live links one person may have at once
MAX_BYTES = 250_000     # biggest chat copy we accept (the JSON text length, about 250 KB)


class Shares:
    """A small SQLite table of share links. Only a hash of each link's secret token is stored, so a leaked database cannot reveal working links."""

    def __init__(self, path=":memory:"):
        """Open (or create) the database at `path`; ":memory:" is a throwaway one for tests."""
        # check_same_thread=False lets request threads share this connection; self.lock keeps them from overlapping.
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        # One row per link: id (short public handle for cancelling), token_hash (hash of the secret), owner, source chat, title,
        # created/expires times (Unix seconds), a revoked flag (1 = cancelled) and snapshot (the JSON copy of the chat).
        with self.lock:
            self.db.executescript("""CREATE TABLE IF NOT EXISTS shares (id TEXT PRIMARY KEY, token_hash TEXT UNIQUE, user TEXT, chat_id INTEGER, title TEXT,
                                     created REAL, expires REAL, revoked INTEGER DEFAULT 0, snapshot TEXT);""")
            self.db.commit()

    def create(self, user, chat_id, title, messages, days=7, now=None):
        """The token (shown once) for a copy of `messages` ([{"role", "content", "model"}]). Raises ValueError with a sentence for the person."""
        # `now` can be passed in by tests so time is predictable; otherwise use the real clock.
        now = time.time() if now is None else now
        # Keep only the words of each message (role, text, model name) and skip empty ones: no pictures, files or app names are copied.
        msgs = [{"role": m["role"], "content": str(m["content"]), "model": str(m.get("model", ""))} for m in messages if m.get("content")]
        if not msgs:
            raise ValueError("There is nothing in this chat to share yet.")
        # The frozen copy, as JSON text. Refuse chats too big to store as one link.
        blob = json.dumps({"title": str(title)[:80], "messages": msgs})
        if len(blob) > MAX_BYTES:
            raise ValueError("This chat is too long to share as one link.")
        # Count and insert under one lock so two quick requests cannot both get past the limit.
        with self.lock:
            active = self.db.execute("SELECT COUNT(*) FROM shares WHERE user = ? AND revoked = 0 AND expires > ?", (user, now)).fetchone()[0]
            if active >= MAX_ACTIVE:
                raise ValueError(f"You already have {MAX_ACTIVE} links. Cancel one you no longer need.")
            # The token is 24 random bytes in URL-safe text: unguessable. Only its hash (auth.digest) is saved; the token itself is returned once.
            token = secrets.token_urlsafe(24)
            # Lifetime is `days` clamped to 1..30, times 86400 seconds per day. The 0 is the "revoked" flag (not cancelled yet).
            self.db.execute("INSERT INTO shares VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)", (secrets.token_hex(4), auth.digest(token), user, chat_id, str(title)[:80], now,
                                                                                         now + max(1, min(int(days), 30)) * 86400, blob))
            self.db.commit()
        return token

    def get(self, token, now=None):
        """{"title", "messages", "created", "expires"} for a live link, else None."""
        now = time.time() if now is None else now
        # Look the link up by the hash of the token it was given; cancelled or expired links match nothing.
        with self.lock:
            r = self.db.execute("SELECT title, snapshot, created, expires FROM shares WHERE token_hash = ? AND revoked = 0 AND expires > ?", (auth.digest(token or ""), now)).fetchone()
        if not r:
            return None
        data = json.loads(r[1])
        return {"title": r[0], "messages": data["messages"], "created": r[2], "expires": r[3]}

    def list(self, user, now=None):
        """This person's live (not cancelled, not expired) links, newest first, with no chat content: [{"id", "title", "created", "expires"}]."""
        now = time.time() if now is None else now
        with self.lock:
            rows = self.db.execute("SELECT id, title, created, expires FROM shares WHERE user = ? AND revoked = 0 AND expires > ? ORDER BY created DESC", (user, now)).fetchall()
        return [{"id": r[0], "title": r[1], "created": r[2], "expires": r[3]} for r in rows]

    def revoke(self, user, share_id):
        """Cancel one link. The `user` check stops anyone cancelling someone else's link. Returns True if a link was cancelled."""
        with self.lock:
            cur = self.db.execute("UPDATE shares SET revoked = 1 WHERE id = ? AND user = ?", (str(share_id), user))
            self.db.commit()
            return cur.rowcount > 0

    def forget_user(self, user):
        """Delete every link (and its chat copy) belonging to a person, for example when their account is removed."""
        with self.lock:
            self.db.execute("DELETE FROM shares WHERE user = ?", (user,))
            self.db.commit()

    def prune(self, now=None):
        """Clean up: delete cancelled links, and links that expired more than 7 days ago (kept briefly past expiry, then dropped)."""
        now = time.time() if now is None else now
        with self.lock:
            self.db.execute("DELETE FROM shares WHERE revoked = 1 OR expires < ?", (now - 7 * 86400,))
            self.db.commit()


# The HTML of the public read-only page. It is a template: {title}, {created}, {expires} and {body} are filled in by render().
# The doubled braces {{ }} are literal { } in the CSS (str.format treats single braces as slots). Light/dark colours follow the viewer's device.
# "noindex,nofollow" asks search engines not to list the page.
PAGE = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">'
        '<title>{title} - Emvryx</title><style>:root{{color-scheme:dark light;--bg:#07080D;--surface:#0F1119;--line:#232739;--text:#EEF0F6;--muted:#9AA3BC;--accent:#F5A524}}'
        '@media(prefers-color-scheme:light){{:root{{--bg:#F7F8FC;--surface:#fff;--line:#D8DCEA;--text:#0D0F1A;--muted:#4A526B;--accent:#B87400}}}}'
        'body{{margin:0;background:var(--bg);color:var(--text);font:17px/1.55 system-ui,sans-serif}}main{{max-width:720px;margin:0 auto;padding:20px 16px 60px}}'
        'h1{{font-size:22px;margin:8px 0 2px}}.note{{color:var(--muted);font-size:14px;margin-bottom:18px}}.m{{margin:14px 0;display:flex;flex-direction:column;gap:4px}}'
        '.who{{font-size:13px;color:var(--muted);font-weight:600}}.b{{white-space:pre-wrap;word-break:break-word;background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:12px 16px}}'
        '.u .b{{border-color:var(--accent)}}footer{{color:var(--muted);font-size:13px;margin-top:30px}}a{{color:var(--accent)}}</style></head><body><main>'
        '<h1>{title}</h1><div class="note">A read-only copy of a chat, shared with a link. It was copied on {created} and the link works until {expires}.</div>{body}'
        '<footer>Made with Emvryx. Answers can be wrong: check anything important.</footer></main></body></html>')


def render(share):
    """Build the full HTML page for a share dict from Shares.get. Every piece of text is HTML-escaped so a message cannot inject code into the page."""
    # esc: make text safe to put in HTML (< becomes &lt; and so on). day: Unix seconds -> "03 May 2026".
    esc = lambda s: html.escape(str(s), quote=True)
    day = lambda t: time.strftime("%d %b %Y", time.gmtime(t))
    # One block per message: a small label ("Asked" for the person, "Emvryx (model)" for the answer) and the text in a bubble.
    body = "".join(f'<div class="m {"u" if m["role"] == "user" else "a"}"><div class="who">{"Asked" if m["role"] == "user" else "Emvryx" + (" (" + esc(m["model"]) + ")" if m.get("model") else "")}</div>'
                   f'<div class="b">{esc(m["content"])}</div></div>' for m in share["messages"])
    return PAGE.format(title=esc(share["title"] or "A shared chat"), created=day(share["created"]), expires=day(share["expires"]), body=body)
