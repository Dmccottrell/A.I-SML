"""saved_notes.py - notes the person approved (thumbs up), kept on this server so a later question can use them offline.

The model's weights never change. When someone gives an answer a thumbs up, the notes it was written from (the question, the
passages, the source and the date) are saved here. `lookup_auto.gather` searches them first next time, so a similar question
works even with no internet. Recent things (news, scores, prices) are kept for a day; stable facts for half a year. Every
person has their own list, can see it, and can delete one note or all of them. Private chats save nothing.
"""
import re
import sqlite3
import threading

# TTL = "time to live": how long a note is kept before it counts as expired. Times are in seconds.
DAY = 86400                      # seconds in one day (60 * 60 * 24)
RECENT_TTL = 1 * DAY             # news, scores, prices go stale fast
STABLE_TTL = 180 * DAY           # stable facts last about half a year
# STOP = "stop words": very common words ignored when matching a question to a note, because they say nothing about the topic.
STOP = set("the a an of to in on at for and or is are was were be been do does did what who whom when where which why how "
           "can could will would should it its this that these those with as by from about me my you your i tell give name".split())


def words(text):
    """Turn text into a set of its "content words": lower-case, 3+ letters, and not in STOP. Used to compare a question with a note.

    Example: "What is the capital of France?" gives {"capital", "france"}. None or "" gives an empty set.
    """
    # The regex [a-z0-9']+ finds runs of letters, digits and apostrophes (everything else, like spaces and punctuation, splits words).
    return {w for w in re.findall(r"[a-z0-9']+", (text or "").lower()) if len(w) > 2 and w not in STOP}


class SavedNotes:
    """A small SQLite database of approved notes (one instance per person). Every method takes the lock so threads do not collide."""

    def __init__(self, path=":memory:"):
        """Open (or create) the notes database at `path`; ":memory:" means a temporary one that vanishes when the program stops."""
        # check_same_thread=False lets the server's many threads share this connection; self.lock (below) keeps them from overlapping.
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        # One row per note: the question it was saved for, a title, the note text, its web address, where it came from (kind),
        # when it was saved and when it expires (both as seconds since 1970, which is how time.time() counts).
        self.db.execute("CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, question TEXT, title TEXT, text TEXT, "
                        "url TEXT, kind TEXT, saved_at REAL, expires_at REAL)")
        self.db.commit()

    def save(self, question, notes, now, recent=False):
        """Save the notes an approved answer used. Returns how many were new.

        `question` is what the person asked, `notes` is a list of dicts (title, text, url, kind, and id if already saved), `now` is the
        current time in seconds, and `recent=True` picks the short one-day lifetime instead of the long one.
        """
        # How long these notes stay before they expire.
        ttl = RECENT_TTL if recent else STABLE_TTL
        added = 0
        # Hold the lock for the whole batch so the check-then-insert below cannot be interleaved by another thread.
        with self.lock:
            for n in notes:
                if n.get("kind") == "saved":                    # already saved: only the date is renewed
                    self.db.execute("UPDATE notes SET expires_at = ? WHERE id = ?", (now + ttl, n.get("id")))
                    continue
                # Same title and text already stored: do not add a second copy, just extend its life and remember the newer question.
                dup = self.db.execute("SELECT id FROM notes WHERE title = ? AND text = ?", (n["title"], n["text"])).fetchone()
                if dup:
                    self.db.execute("UPDATE notes SET expires_at = ?, question = ? WHERE id = ?", (now + ttl, question, dup[0]))
                    continue
                # A brand-new note. The ? marks are filled from the tuple below (safe against SQL injection). Missing kind defaults to "web".
                self.db.execute("INSERT INTO notes (question, title, text, url, kind, saved_at, expires_at) VALUES (?,?,?,?,?,?,?)",
                                (question, n["title"], n["text"], n.get("url"), n.get("kind") or "web", now, now + ttl))
                added += 1
            self.db.commit()
        return added

    def search(self, question, k=3, now=0.0, min_cover=0.6):
        """The saved notes that fit the question: at least `min_cover` of its content words appear in the note or the
        question it was saved for."""
        # The set of content words we are looking for. A question with no content words matches nothing.
        want = words(question)
        if not want:
            return []
        scored = []
        # Only notes that have not expired. We read all rows inside the lock and do the (slower) matching outside it.
        with self.lock:
            rows = self.db.execute("SELECT id, question, title, text, url, kind, saved_at FROM notes WHERE expires_at > ?", (now,)).fetchall()
        for id_, q, title, text, url, kind, saved_at in rows:
            # "cover" = the share of the question's words found in the note (its question, title or text). 1.0 means all of them.
            have = words(q) | words(title) | words(text)
            cover = len(want & have) / len(want)
            if cover >= min_cover:
                scored.append((cover, saved_at, {"id": id_, "title": title, "text": text, "url": url, "kind": "saved", "origin": kind,
                                                 "saved_at": saved_at}))
        # Best match first; on a tie, the most recently saved first (the minus signs flip the order to largest-first).
        scored.sort(key=lambda x: (-x[0], -x[1]))
        return [n for _, _, n in scored[:k]]

    def list(self, now=0.0):
        """All notes that have not expired as of `now`, newest first, as small dicts for showing the person their list (no note text)."""
        with self.lock:
            rows = self.db.execute("SELECT id, question, title, kind, saved_at, expires_at FROM notes WHERE expires_at > ? "
                                   "ORDER BY saved_at DESC", (now,)).fetchall()
        return [{"id": r[0], "question": r[1], "title": r[2], "origin": r[3], "saved_at": r[4], "expires_at": r[5]} for r in rows]

    def delete(self, note_id):
        """Remove the one note with this id."""
        with self.lock:
            self.db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            self.db.commit()

    def clear(self):
        """Remove every note ("delete all")."""
        with self.lock:
            self.db.execute("DELETE FROM notes")
            self.db.commit()

    def purge(self, now):
        """Delete the notes that have expired as of `now`, to keep the database small."""
        with self.lock:
            self.db.execute("DELETE FROM notes WHERE expires_at <= ?", (now,))
            self.db.commit()
