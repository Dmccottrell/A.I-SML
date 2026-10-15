"""
safe_db.py - One SQLite connection that the server's threads can share safely.

WHAT THIS FILE DOES
    The app answers many requests at once (one thread each). Python's sqlite3 allows one connection to be used from several threads
    (check_same_thread=False) but says the caller must keep them from overlapping, or writes can interleave: a reply being saved while another request
    commits, or "Recursive use of cursors". SafeDB holds a lock around every statement and reads the rows while it holds it, so callers keep writing
    `db.execute(...).fetchone()` exactly as before. The lock is re-entrant: a method can hold `db.lock` around several statements that must happen
    together (check-then-insert) and still call execute inside.
"""
import sqlite3
import threading


class Result:
    """What execute returns: the rows (already read), lastrowid and rowcount, like a cursor that has been read to the end."""

    def __init__(self, cur):
        self.rows = cur.fetchall() if cur.description else []
        self.lastrowid, self.rowcount, self.description = cur.lastrowid, cur.rowcount, cur.description
        self._at = 0

    def fetchone(self):
        if self._at >= len(self.rows):
            return None
        self._at += 1
        return self.rows[self._at - 1]

    def fetchall(self):
        rest, self._at = self.rows[self._at:], len(self.rows)
        return rest

    def __iter__(self):
        return iter(self.fetchall())


class SafeDB:
    def __init__(self, path=":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.RLock()

    def execute(self, sql, params=()):
        with self.lock:
            return Result(self.conn.execute(sql, params))

    def executemany(self, sql, rows):
        with self.lock:
            return Result(self.conn.executemany(sql, rows))

    def executescript(self, script):
        with self.lock:
            return self.conn.executescript(script)

    def commit(self):
        with self.lock:
            self.conn.commit()

    def close(self):
        with self.lock:
            self.conn.close()
