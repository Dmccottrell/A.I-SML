"""
user_memory.py - What the app remembers about a person, shared by EVERY model.

WHAT THIS FILE DOES
    A model's weights never change while you talk to it, and each model starts every chat knowing nothing about you. So the app keeps a short list of facts
    about each person ("The user's name is Darryl.") and gives it to whichever model answers, as a note. Tell Flare your name, switch to Solstice in a new
    chat, ask "what's my name?": Solstice reads the same list.

    How facts get in:  you say something worth keeping ("my name is Darryl", "I live in Austin", "my dog is called Biscuit", "remember that I prefer Python"),
    or you add one yourself on the Memory screen. The app spots these with plain rules (no model needed, so it works the same for every model).
    How they come out:  "forget that I live in Austin", "forget everything about me", or the Delete buttons on the Memory screen.
    Never saved: anything that looks like a password, a card or ID number, a key, an email address or a phone number. Private chats neither save nor read memory.
    One value per kind: a new name replaces the old name, a new city replaces the old city.
"""
import re
import sqlite3
import threading
import time

MAX_FACTS = 100
MAX_FACT_CHARS = 200
TITLE = "What you know about the user"

SENSITIVE = re.compile(r"\b(pass(word|code|phrase)|pin\b|credit card|debit card|card number|cvv|ssn|social security|api[ -]?key|secret|token|private key|"
                       r"bank account|routing number)\b|\d{6,}|[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s().-]{8,}\d", re.I)
NAME_STOP = {"not", "a", "an", "the", "here", "just", "going", "so", "very", "sorry", "back", "also", "and", "but", "in", "on", "at", "from", "is", "am",
             "who", "what", "your", "my", "me", "you", "it", "this", "that", "to", "of", "for", "with", "now", "today", "later", "tomorrow", "tonight",
             "maybe", "anything", "whatever", "sometime", "soon", "when", "if", "back", "again", "up", "out", "over", "something", "someone"}
WORD = r"[A-Za-z][A-Za-z'\-]{1,24}"


def _clean(text):
    return " ".join(str(text).split())[:MAX_FACT_CHARS].strip(" .,!?;:")


def _title(name):
    return " ".join(w[:1].upper() + w[1:] for w in name.split())


def extract(message):
    """[(slot, fact)] spotted in one message. slot is 'name', 'age', 'location', 'job' (one value each) or '' (many allowed)."""
    text = " ".join(str(message or "").split())
    if not text or len(text) > 600:
        return []
    found = []
    m = re.search(rf"\b(?:my name is|my name's|call me|i am called|i'm called|people call me|you can call me)\s+({WORD}(?:\s+{WORD})?)", text, re.I)
    if m:
        words = []
        for w in m.group(1).split():
            if w.lower() in NAME_STOP:
                break
            words.append(w)
        if words:
            found.append(("name", f"The user's name is {_title(' '.join(words))}."))
    m = re.search(r"\bi(?: am|'m) (\d{1,2}) years? old\b", text, re.I)
    if m and 3 <= int(m.group(1)) <= 110:
        found.append(("age", f"The user is {m.group(1)} years old."))
    m = re.search(r"\bi (?:live|am living|reside|'m living) in ([A-Za-z][^.,!?;\n]{1,40})", text, re.I) or re.search(r"\bi(?: am|'m) from ([A-Za-z][^.,!?;\n]{1,40})", text, re.I)
    if m:
        place = re.split(r"\b(?:and|but|because|so|where|which)\b", m.group(1), 1, flags=re.I)[0].strip()
        if place:
            found.append(("location", f"The user lives in or is from {_title(place)}."))
    m = re.search(r"\bi work (?:as (?:an? )?|at |for )([A-Za-z][^.,!?;\n]{2,40})", text, re.I)
    if m:
        what = re.split(r"\b(?:and|but|because|so|where|which)\b", m.group(1), 1, flags=re.I)[0].strip()
        if what:
            found.append(("job", f"The user works {'as' if 'work as' in m.group(0).lower() else 'at'} {what}."))
    for m in re.finditer(rf"\bmy (dog|cat|pet|puppy|kitten|son|daughter|wife|husband|partner|brother|sister|mom|mum|dad|boyfriend|girlfriend)(?:'s name)? (?:is|was)? ?(?:called|named|is) ({WORD})", text, re.I):
        found.append(("", f"The user's {m.group(1).lower()} is called {_title(m.group(2))}."))
    for m in re.finditer(r"\bmy fav(?:ou?rite) ([a-z ]{3,25}?) is ([^.,!?;\n]{2,40})", text, re.I):
        found.append(("", f"The user's favourite {m.group(1).strip().lower()} is {m.group(2).strip()}."))
    m = re.match(r"^(?:please )?remember(?: that)?[:,]? +(.{3,200})$", text, re.I)
    if m:
        found.append(("", f"The user asked to remember: {_clean(m.group(1))}."))
    return [(slot, fact) for slot, fact in found if not SENSITIVE.search(fact)]


PERSONAL = re.compile(r"\b(my|me|mine|myself|i|i'm|i've|i'd|i'll|we|our|ours|us|remember|know about)\b", re.I)
FORGET = re.compile(r"^(?:please )?(?:forget|delete|remove)(?: that| about| what you know about)? +(.{2,120})$", re.I)
FORGET_ALL = re.compile(r"^(?:please )?(?:forget|delete|erase|clear) (?:everything|all|all of it|everything you know)(?: about me| you know about me)?[.!]?$", re.I)


class Memory:
    """One person's facts, in a small SQLite file (or in memory for tests)."""

    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.execute("CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, slot TEXT, created REAL)")
            self.db.commit()

    def add(self, text, slot="", now=None):
        """Save a fact. False when it is empty, looks sensitive, or is already there. A new value for a slot replaces the old one."""
        text = _clean(text)
        if not text or SENSITIVE.search(text):
            return False
        text += "."
        now = time.time() if now is None else now
        with self.lock:
            if self.db.execute("SELECT 1 FROM facts WHERE lower(text) = lower(?)", (text,)).fetchone():
                return False
            if slot:
                self.db.execute("DELETE FROM facts WHERE slot = ?", (slot,))
            self.db.execute("INSERT INTO facts (text, slot, created) VALUES (?, ?, ?)", (text, slot, now))
            self.db.execute("DELETE FROM facts WHERE id NOT IN (SELECT id FROM facts ORDER BY id DESC LIMIT ?)", (MAX_FACTS,))
            self.db.commit()
        return True

    def list(self):
        with self.lock:
            rows = self.db.execute("SELECT id, text, created FROM facts ORDER BY id").fetchall()
        return [{"id": r[0], "text": r[1], "created": r[2]} for r in rows]

    def delete(self, fact_id):
        with self.lock:
            cur = self.db.execute("DELETE FROM facts WHERE id = ?", (int(fact_id),))
            self.db.commit()
            return cur.rowcount > 0

    def clear(self):
        with self.lock:
            n = self.db.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            self.db.execute("DELETE FROM facts")
            self.db.commit()
            return n

    def forget_matching(self, phrase):
        """Delete the facts that mention every important word of `phrase`. How many went."""
        words = [w for w in re.findall(r"[a-z0-9']+", phrase.lower()) if len(w) > 2 and w not in ("that", "the", "about", "and", "i", "my", "you", "know")]
        if not words:
            return 0
        gone = 0
        for f in self.list():
            low = f["text"].lower()
            if all(w in low or w.rstrip("s") in low for w in words):
                gone += self.delete(f["id"])
        return gone

    def learn(self, message, now=None):
        """Read one message from the person: save what is worth keeping, obey "forget ...". {"saved": [...], "forgot": n}"""
        text = " ".join(str(message or "").split())
        out = {"saved": [], "forgot": 0}
        if FORGET_ALL.match(text):
            out["forgot"] = self.clear()
            return out
        m = FORGET.match(text)
        if m:
            out["forgot"] = self.forget_matching(m.group(1))
            return out
        for slot, fact in extract(text):
            if self.add(fact, slot, now):
                out["saved"].append(fact)
        return out

    def note(self, question=None, max_chars=700):
        """The note the model reads, or None when nothing is remembered. With a `question`, only when it is about the person (my, me, I...): a note on
        every message would make the models, which were taught to answer from their notes, say "the notes don't mention that" about ordinary questions."""
        if question is not None and not PERSONAL.search(question):
            return None
        text = ""
        for f in reversed(self.list()):                     # the newest facts first, as many as fit
            if len(text) + len(f["text"]) + 1 > max_chars:
                break
            text = f["text"] + (" " + text if text else "")
        return {"title": TITLE, "text": text} if text else None

    def close(self):
        try:
            self.db.close()
        except sqlite3.Error:
            pass
