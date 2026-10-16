import re
import sqlite3

from shortener.codes import encode

ALIAS = re.compile(r"[A-Za-z0-9_-]{3,30}")


class Shortener:
    def __init__(self, db_path=":memory:"):
        self.db = sqlite3.connect(db_path)
        self.db.execute("CREATE TABLE IF NOT EXISTS links (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, url TEXT NOT NULL, alias INTEGER NOT NULL, clicks INTEGER NOT NULL DEFAULT 0)")

    def shorten(self, url, alias=None):
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
        row = self.db.execute("SELECT code FROM links WHERE url = ? AND alias = 0", (url,)).fetchone()
        if row:
            return row[0]
        with self.db:
            cur = self.db.execute("INSERT INTO links (url, alias) VALUES (?, 0)", (url,))
            code = encode(cur.lastrowid + 10000)
            self.db.execute("UPDATE links SET code = ? WHERE id = ?", (code, cur.lastrowid))
        return code

    def resolve(self, code):
        row = self.db.execute("SELECT url FROM links WHERE code = ?", (code,)).fetchone()
        if not row:
            return None
        with self.db:
            self.db.execute("UPDATE links SET clicks = clicks + 1 WHERE code = ?", (code,))
        return row[0]

    def stats(self, code):
        row = self.db.execute("SELECT url, clicks FROM links WHERE code = ?", (code,)).fetchone()
        return {"url": row[0], "clicks": row[1]} if row else None

    def top(self, n=3):
        return [tuple(r) for r in self.db.execute("SELECT code, clicks FROM links ORDER BY clicks DESC, code LIMIT ?", (n,)).fetchall()]
