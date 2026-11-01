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
    """What execute returns: the rows (already read), lastrowid and rowcount, like a cursor that has been read to the end.

    A "cursor" is sqlite3's handle for walking through query results. Reading every row up front (while the lock is held) means the caller
    can use the result later without touching the shared connection again.
    """

    def __init__(self, cur):
        """Copy everything we need out of the sqlite cursor `cur` right away, so the cursor is not needed afterwards."""
        # cur.description is None for statements that return no rows (INSERT, UPDATE...), so only read rows for queries.
        self.rows = cur.fetchall() if cur.description else []
        self.lastrowid, self.rowcount, self.description = cur.lastrowid, cur.rowcount, cur.description
        # _at is how many rows have been handed out already (the "reading position").
        self._at = 0

    def fetchone(self):
        """Give the next unread row (a tuple), or None when all rows have been read. Same name and behaviour as a sqlite3 cursor."""
        if self._at >= len(self.rows):
            return None
        self._at += 1
        return self.rows[self._at - 1]

    def fetchall(self):
        """Give every row not yet read, as a list, and move the position to the end."""
        rest, self._at = self.rows[self._at:], len(self.rows)
        return rest

    def __iter__(self):
        """Lets callers write `for row in db.execute(...)`; it yields the rows not yet read."""
        return iter(self.fetchall())


class SafeDB:
    """A thin wrapper around one sqlite3 connection that takes a lock around every call, so many threads can share it without clashing."""

    def __init__(self, path=":memory:"):
        """Open the database file at `path` (the default ":memory:" means a throwaway database kept in RAM, handy for tests)."""
        # check_same_thread=False turns off sqlite3's "only the thread that made me may use me" rule; the lock below replaces that protection.
        self.conn = sqlite3.connect(path, check_same_thread=False)
        # RLock = re-entrant lock: the thread that already holds it may take it again without freezing (see the file notes above).
        self.lock = threading.RLock()

    def execute(self, sql, params=()):
        """Run one SQL statement with `params` filled into the ? marks (never paste values into `sql` yourself: that invites SQL injection).
        Returns a Result holding the rows."""
        with self.lock:
            return Result(self.conn.execute(sql, params))

    def executemany(self, sql, rows):
        """Run the same statement once for every item in `rows` (a list of parameter tuples). Returns a Result."""
        with self.lock:
            return Result(self.conn.executemany(sql, rows))

    def executescript(self, script):
        """Run several SQL statements written as one block of text (used to create tables). Returns sqlite3's own cursor."""
        with self.lock:
            return self.conn.executescript(script)

    def commit(self):
        """Make all changes since the last commit permanent on disk."""
        with self.lock:
            self.conn.commit()

    def close(self):
        """Close the database connection. Do not use this SafeDB afterwards."""
        with self.lock:
            self.conn.close()
