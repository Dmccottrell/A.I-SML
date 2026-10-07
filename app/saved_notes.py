"""saved_notes.py - notes the person approved (thumbs up), kept on this server so a later question can use them offline.

The model's weights never change. When someone gives an answer a thumbs up, the notes it was written from (the question, the
passages, the source and the date) are saved here. `lookup_auto.gather` searches them first next time, so a similar question
works even with no internet. Recent things (news, scores, prices) are kept for a day; stable facts for half a year. Every
person has their own list, can see it, and can delete one note or all of them. Private chats save nothing.
"""
import re
import sqlite3
import threading

DAY = 86400
RECENT_TTL = 1 * DAY
STABLE_TTL = 180 * DAY
STOP = set("the a an of to in on at for and or is are was were be been do does did what who whom when where which why how "
           "can could will would should it its this that these those with as by from about me my you your i tell give name".split())


def words(text):
    return {w for w in re.findall(r"[a-z0-9']+", (text or "").lower()) if len(w) > 2 and w not in STOP}


class SavedNotes:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.db.execute("CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, question TEXT, title TEXT, text TEXT, "
                        "url TEXT, kind TEXT, saved_at REAL, expires_at REAL)")
        self.db.commit()

    def save(self, question, notes, now, recent=False):
        """Save the notes an approved answer used. Returns how many were new."""
        ttl = RECENT_TTL if recent else STABLE_TTL
        added = 0
        with self.lock:
            for n in notes:
                if n.get("kind") == "saved":                    # already saved: only the date is renewed
                    self.db.execute("UPDATE notes SET expires_at = ? WHERE id = ?", (now + ttl, n.get("id")))
                    continue
                dup = self.db.execute("SELECT id FROM notes WHERE title = ? AND text = ?", (n["title"], n["text"])).fetchone()
                if dup:
                    self.db.execute("UPDATE notes SET expires_at = ?, question = ? WHERE id = ?", (now + ttl, question, dup[0]))
                    continue
                self.db.execute("INSERT INTO notes (question, title, text, url, kind, saved_at, expires_at) VALUES (?,?,?,?,?,?,?)",
                                (question, n["title"], n["text"], n.get("url"), n.get("kind") or "web", now, now + ttl))
                added += 1
            self.db.commit()
        return added

    def search(self, question, k=3, now=0.0, min_cover=0.6):
        """The saved notes that fit the question: at least `min_cover` of its content words appear in the note or the
        question it was saved for."""
        want = words(question)
        if not want:
            return []
        scored = []
        with self.lock:
            rows = self.db.execute("SELECT id, question, title, text, url, kind, saved_at FROM notes WHERE expires_at > ?", (now,)).fetchall()
        for id_, q, title, text, url, kind, saved_at in rows:
            have = words(q) | words(title) | words(text)
            cover = len(want & have) / len(want)
            if cover >= min_cover:
                scored.append((cover, saved_at, {"id": id_, "title": title, "text": text, "url": url, "kind": "saved", "origin": kind,
                                                 "saved_at": saved_at}))
        scored.sort(key=lambda x: (-x[0], -x[1]))
        return [n for _, _, n in scored[:k]]

    def list(self, now=0.0):
        with self.lock:
            rows = self.db.execute("SELECT id, question, title, kind, saved_at, expires_at FROM notes WHERE expires_at > ? "
                                   "ORDER BY saved_at DESC", (now,)).fetchall()
        return [{"id": r[0], "question": r[1], "title": r[2], "origin": r[3], "saved_at": r[4], "expires_at": r[5]} for r in rows]

    def delete(self, note_id):
        with self.lock:
            self.db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            self.db.commit()

    def clear(self):
        with self.lock:
            self.db.execute("DELETE FROM notes")
            self.db.commit()

    def purge(self, now):
        with self.lock:
            self.db.execute("DELETE FROM notes WHERE expires_at <= ?", (now,))
            self.db.commit()
