"""
feedback.py - "That didn't work": what people say went wrong with an answer, kept for the owner so the next retrain fixes the real problems.

WHAT THIS FILE DOES
    Under each answer there is a "Report" button. The person picks what was wrong (wrong fact, too long, ignored my question, cut off, other) and may add a
    note. We keep, in a private database next to the other server files: who, which model, what was asked, what was answered, the notes the answer used, and the
    kind. Private chats can never be reported (nothing about them is saved). The owner sees counts by kind and by model, reads the reports, marks them handled,
    and exports them as a lessons file (`feedback_export.jsonl`, chat format) to correct the models on the next retrain.
    The page says plainly, before sending, that the question and answer go to the owner.
"""
import json
import sqlite3
import threading
import time

KINDS = {"wrong_fact": "Wrong fact", "ignored": "Ignored my question", "too_long": "Too long", "too_short": "Too short or vague", "cut_off": "Cut off", "unsafe": "Not appropriate",
         "other": "Something else"}


class Feedback:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript("""CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, user TEXT, model TEXT, kind TEXT, note TEXT,
                                     question TEXT, answer TEXT, notes_used TEXT, status TEXT DEFAULT 'new');""")
            self.db.commit()

    def add(self, user, model, kind, note, question, answer, notes_used=None):
        kind = kind if kind in KINDS else "other"
        with self.lock:
            cur = self.db.execute("INSERT INTO feedback (at, user, model, kind, note, question, answer, notes_used) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                  (time.time(), user, str(model)[:40], kind, str(note or "")[:500], str(question or "")[:4000], str(answer or "")[:8000], json.dumps(notes_used or [])[:4000]))
            self.db.commit()
            return cur.lastrowid

    def list(self, limit=50, status=None, kind=None, model=None):
        q, args, conds = "SELECT id, at, user, model, kind, note, question, answer, status FROM feedback", [], []
        for col, v in (("status", status), ("kind", kind), ("model", model)):
            if v:
                conds.append(f"{col} = ?")
                args.append(v)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(max(1, min(int(limit), 500)))
        with self.lock:
            rows = self.db.execute(q, args).fetchall()
        return [dict(zip(("id", "at", "user", "model", "kind", "note", "question", "answer", "status"), r)) for r in rows]

    def counts(self):
        with self.lock:
            by_kind = dict(self.db.execute("SELECT kind, COUNT(*) FROM feedback WHERE status = 'new' GROUP BY kind").fetchall())
            by_model = dict(self.db.execute("SELECT model, COUNT(*) FROM feedback WHERE status = 'new' GROUP BY model").fetchall())
            total = self.db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        return {"new": sum(by_kind.values()), "total": total, "by_kind": by_kind, "by_model": by_model}

    def set_status(self, fid, status):
        with self.lock:
            cur = self.db.execute("UPDATE feedback SET status = ? WHERE id = ?", (status if status in ("new", "handled") else "new", int(fid)))
            self.db.commit()
            return cur.rowcount > 0

    def export_lines(self, status="new"):
        """One JSON line per report, in the chat format the lesson builders read, plus the kind and what was wrong: a starting point for corrected answers (a person still writes the right answer)."""
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
        with self.lock:
            rows = self.db.execute("SELECT at, kind, note, question FROM feedback WHERE user = ? ORDER BY id", (user,)).fetchall()
        return [{"at": r[0], "kind": r[1], "note": r[2], "question": r[3]} for r in rows]
