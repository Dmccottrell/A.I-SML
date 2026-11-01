"""
feedback.py - "That didn't work": what people say went wrong with an answer, kept for the owner so the next retrain fixes the real problems.

WHAT THIS FILE DOES
    Under each answer there is a "Report" button. The person picks what was wrong (wrong fact, too long, ignored my question, cut off, other) and may add a
    note. We keep, in a private database next to the other server files: who, which model, what was asked, what was answered, the notes the answer used, and the
    kind. Private chats can never be reported (nothing about them is saved). The owner sees counts by kind and by model, reads the reports, marks them handled,
    and exports them as a lessons file (`feedback_export.jsonl`, chat format) to correct the models on the next retrain.
    The page says plainly, before sending, that the question and answer go to the owner.

    Where it fits: the server creates one Feedback object; the chat routes call add(), the admin routes call list/counts/set_status/export_lines,
    and account deletion calls forget_user().
"""
import json
import sqlite3       # SQLite: a database stored in one file, built into Python
import threading     # a lock keeps two web requests from using the database at the same moment
import time

# The kinds of problem a person can report: the stored code name -> the words shown on the page.
KINDS = {"wrong_fact": "Wrong fact", "ignored": "Ignored my question", "too_long": "Too long", "too_short": "Too short or vague", "cut_off": "Cut off", "unsafe": "Not appropriate",
         "other": "Something else"}


class Feedback:
    """The store of problem reports, kept in a SQLite database."""

    def __init__(self, path=":memory:"):
        """path: the database file; the default ":memory:" is a throw-away database in RAM (used in tests)."""
        # check_same_thread=False: the web server uses this connection from several threads; self.lock makes that safe.
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        # Create the table on first use. "status" starts as 'new' and becomes 'handled' once the owner has dealt with a report.
        with self.lock:
            self.db.executescript("""CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, user TEXT, model TEXT, kind TEXT, note TEXT,
                                     question TEXT, answer TEXT, notes_used TEXT, status TEXT DEFAULT 'new');""")
            self.db.commit()

    def add(self, user, model, kind, note, question, answer, notes_used=None):
        """Save one report and return its id. An unknown `kind` becomes "other". Every text is cut to a maximum length so one report cannot be huge."""
        kind = kind if kind in KINDS else "other"
        # The "?" marks are filled in safely by the database, so odd characters in the texts cannot break (or attack) the query.
        # notes_used (a list) is stored as JSON text.
        with self.lock:
            cur = self.db.execute("INSERT INTO feedback (at, user, model, kind, note, question, answer, notes_used) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                  (time.time(), user, str(model)[:40], kind, str(note or "")[:500], str(question or "")[:4000], str(answer or "")[:8000], json.dumps(notes_used or [])[:4000]))
            self.db.commit()
            return cur.lastrowid

    def list(self, limit=50, status=None, kind=None, model=None):
        """Reports, newest first, as dicts. Optional filters: status, kind, model. `limit` is kept between 1 and 500."""
        # Build the query piece by piece: only the filters that were given are added to the WHERE part.
        q, args, conds = "SELECT id, at, user, model, kind, note, question, answer, status FROM feedback", [], []
        for col, v in (("status", status), ("kind", kind), ("model", model)):
            if v:
                conds.append(f"{col} = ?")
                args.append(v)
        # Join the conditions with AND, then add the sort order and the limit.
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(max(1, min(int(limit), 500)))
        with self.lock:
            rows = self.db.execute(q, args).fetchall()
        # Turn each row (a tuple) into a dict by pairing it with the column names.
        return [dict(zip(("id", "at", "user", "model", "kind", "note", "question", "answer", "status"), r)) for r in rows]

    def counts(self):
        """How many reports are new, in total, and the new ones grouped by kind and by model: {"new", "total", "by_kind", "by_model"}."""
        with self.lock:
            by_kind = dict(self.db.execute("SELECT kind, COUNT(*) FROM feedback WHERE status = 'new' GROUP BY kind").fetchall())
            by_model = dict(self.db.execute("SELECT model, COUNT(*) FROM feedback WHERE status = 'new' GROUP BY model").fetchall())
            total = self.db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        return {"new": sum(by_kind.values()), "total": total, "by_kind": by_kind, "by_model": by_model}

    def set_status(self, fid, status):
        """Mark report `fid` as "new" or "handled" (anything else counts as "new"). Returns True if the report exists."""
        with self.lock:
            cur = self.db.execute("UPDATE feedback SET status = ? WHERE id = ?", (status if status in ("new", "handled") else "new", int(fid)))
            self.db.commit()
            return cur.rowcount > 0

    def export_lines(self, status="new"):
        """One JSON line per report, in the chat format the lesson builders read, plus the kind and what was wrong: a starting point for corrected answers (a person still writes the right answer)."""
        # Each line is a separate JSON object, so the file can be read one report at a time (the .jsonl format).
        with self.lock:
            rows = self.db.execute("SELECT id, kind, note, model, question, answer FROM feedback WHERE status = ? ORDER BY id", (status,)).fetchall()
        return [json.dumps({"source": "feedback", "id": r[0], "kind": r[1], "note": r[2], "model": r[3], "messages": [{"role": "user", "content": r[4]}, {"role": "assistant", "content": r[5]}],
                            "needs": "a corrected assistant answer"}, ensure_ascii=False) for r in rows]

    def forget_user(self, user):
        """Account deletion: their reports go too."""
        with self.lock:
            self.db.execute("DELETE FROM feedback WHERE user = ?", (user,))
            self.db.commit()

    def for_user(self, user):
        """The reports this person sent (time, kind, note, question), oldest first: part of their data download."""
        with self.lock:
            rows = self.db.execute("SELECT at, kind, note, question FROM feedback WHERE user = ? ORDER BY id", (user,)).fetchall()
        return [{"at": r[0], "kind": r[1], "note": r[2], "question": r[3]} for r in rows]
