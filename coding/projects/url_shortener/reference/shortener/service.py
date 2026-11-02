# The URL shortener itself (reference solution for the "url_shortener" exercise): stores links in SQLite,
# hands out short codes (or custom aliases), counts clicks and reports the most clicked. Codes come from shortener/codes.py.
import re
import sqlite3

from shortener.codes import encode

# A custom alias: 3 to 30 letters, digits, "_" or "-". Used with fullmatch so the WHOLE alias must fit.
ALIAS = re.compile(r"[A-Za-z0-9_-]{3,30}")


class Shortener:
    """Keeps a table of links: code (the short name), url, whether the code is a custom alias, and a click counter."""

    def __init__(self, db_path=":memory:"):
        """Open (or create) the database. ":memory:" is a temporary one; a file path keeps links between runs."""
        self.db = sqlite3.connect(db_path)
        # code is UNIQUE so two links can never share a short name. alias is 1 for custom names and 0 for generated ones.
        self.db.execute("CREATE TABLE IF NOT EXISTS links (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, url TEXT NOT NULL, alias INTEGER NOT NULL, clicks INTEGER NOT NULL DEFAULT 0)")

    def shorten(self, url, alias=None):
        """Return a short code for url. With alias, that exact name is used (and must be valid and free).

        Without alias, the same url always gets the same generated code back. Raises ValueError for a url that does not
        start with http:// or https://, a badly formed alias, or an alias that is already taken.
        """
        # Regex: "http", an optional "s", "://", then at least one more character. "url or ''" copes with None.
        if not re.match(r"https?://.+", url or ""):
            raise ValueError("the url must start with http:// or https://")
        if alias is not None:
            if not ALIAS.fullmatch(alias):
                raise ValueError("bad alias")
            if self.db.execute("SELECT 1 FROM links WHERE code = ?", (alias,)).fetchone():
                raise ValueError("alias taken")
            with self.db:
                self.db.execute("INSERT INTO links (code, url, alias) VALUES (?, ?, 1)", (alias, url))
            return alias
        # No alias: if this url already has a generated code, reuse it instead of making a duplicate.
        row = self.db.execute("SELECT code FROM links WHERE url = ? AND alias = 0", (url,)).fetchone()
        if row:
            return row[0]
        with self.db:
            # Insert first to get the row number, then derive the code from it. Adding 10000 makes codes start longer than one character.
            cur = self.db.execute("INSERT INTO links (url, alias) VALUES (?, 0)", (url,))
            code = encode(cur.lastrowid + 10000)
            self.db.execute("UPDATE links SET code = ? WHERE id = ?", (code, cur.lastrowid))
        return code

    def resolve(self, code):
        """Look up the url for a code and count one click. Returns None (and counts nothing) for an unknown code."""
        row = self.db.execute("SELECT url FROM links WHERE code = ?", (code,)).fetchone()
        if not row:
            return None
        with self.db:
            self.db.execute("UPDATE links SET clicks = clicks + 1 WHERE code = ?", (code,))
        return row[0]

    def stats(self, code):
        """Return {"url", "clicks"} for a code without counting a click, or None if the code is unknown."""
        row = self.db.execute("SELECT url, clicks FROM links WHERE code = ?", (code,)).fetchone()
        return {"url": row[0], "clicks": row[1]} if row else None

    def top(self, n=3):
        """The n most clicked links as (code, clicks) pairs, most clicks first; ties are ordered by code."""
        return [tuple(r) for r in self.db.execute("SELECT code, clicks FROM links ORDER BY clicks DESC, code LIMIT ?", (n,)).fetchall()]
