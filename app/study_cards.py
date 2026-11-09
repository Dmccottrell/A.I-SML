"""
study_cards.py - Flashcards you can practise (feature flag study_cards), with a review of the ones you got wrong.

WHAT THIS FILE DOES
    A reply that holds flashcards ("1. Term: meaning" lines, as the Flashcards tool in Teacher mode writes them, or a two-column table)
    can be saved as a deck. The person then flips through the cards and says "Got it" or "Not yet" for each; the answers are kept, so
    the deck knows which cards were missed and can show just those again. To make cards from your own document, attach it to the chat
    and use the Flashcards tool: the cards then come from that document.

    Nothing here calls a model. Every person has their own decks (a small SQLite file), and can delete any of them.

    parse_cards(text)                       -> [{"term", "meaning"}]
    Decks(path).add(title, cards, now)      -> the deck's id
    Decks.list() / get(id) / mark(id, card, right, now) / delete(id)
"""
import json
import re
import sqlite3
import threading

MIN_CARDS = 3                 # fewer than this is not a deck (an ordinary sentence with a colon in it must not look like flashcards)
MAX_CARDS = 100               # per deck
MAX_DECKS = 60                # per person: the oldest go when there are more
MAX_TERM, MAX_MEANING = 200, 600

# "1. Term: meaning", "- Term: meaning", "**Term**: meaning", "Term - meaning" after a number. The term may be wrapped in ** or `.
LINE = re.compile(r"^\s*(?:\d{1,3}[.)]|[-*•])\s+(?:\*\*|`)?(?P<term>[^:\n*`]{1,200}?)(?:\*\*|`)?\s*(?::|—| - )\s*(?:\*\*)?\s*(?P<meaning>\S.*)$")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{2,}")


def _tidy(text, limit):
    """One line of plain text: Markdown marks at the ends removed, spaces squeezed, cut to `limit`."""
    return " ".join(str(text).replace("**", "").strip().strip("`").split())[:limit]


def parse_cards(text):
    """The flashcards in a reply, in order, without repeats of the same term. Returns [] when there are fewer than MIN_CARDS."""
    cards, seen = [], set()

    def add(term, meaning):
        term, meaning = _tidy(term, MAX_TERM), _tidy(meaning, MAX_MEANING)
        if term and meaning and term.lower() not in seen and len(cards) < MAX_CARDS:
            seen.add(term.lower())
            cards.append({"term": term, "meaning": meaning})

    lines = str(text or "").split("\n")
    for i, line in enumerate(lines):
        m = LINE.match(line)
        if m:
            add(m.group("term"), m.group("meaning"))
        elif line.count("|") >= 2 and not TABLE_RULE.match(line):             # a table row: | Term | Meaning |
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            header = i + 1 < len(lines) and TABLE_RULE.match(lines[i + 1])    # the row above the dashes is the heading, not a card
            if len(cells) >= 2 and not header:
                add(cells[0], cells[1])
    return cards if len(cards) >= MIN_CARDS else []


class Decks:
    """One person's flashcard decks. Each card remembers how often it was right and wrong, and how the last try went."""

    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.db.execute("CREATE TABLE IF NOT EXISTS decks (id INTEGER PRIMARY KEY, title TEXT, cards TEXT, made REAL, practised REAL)")
        self.db.commit()

    def add(self, title, cards, now):
        """Save a deck. `cards` is parse_cards' list. Raises ValueError when there are too few cards."""
        if len(cards) < MIN_CARDS:
            raise ValueError("There are no flashcards in that answer.")
        rows = [{"term": c["term"], "meaning": c["meaning"], "right": 0, "wrong": 0, "last": None} for c in cards[:MAX_CARDS]]
        title = " ".join(str(title or "").split())[:80] or "Flashcards"
        with self.lock:
            cur = self.db.execute("INSERT INTO decks (title, cards, made, practised) VALUES (?, ?, ?, 0)", (title, json.dumps(rows), now))
            # keep only the newest MAX_DECKS
            self.db.execute("DELETE FROM decks WHERE id NOT IN (SELECT id FROM decks ORDER BY id DESC LIMIT ?)", (MAX_DECKS,))
            self.db.commit()
            return cur.lastrowid

    @staticmethod
    def _shape(row, with_cards=True):
        cards = json.loads(row[2])
        out = {"id": row[0], "title": row[1], "made": row[3], "practised": row[4], "count": len(cards),
               "missed": sum(1 for c in cards if c["last"] is False), "known": sum(1 for c in cards if c["last"] is True)}
        if with_cards:
            out["cards"] = cards
        return out

    def list(self):
        """Every deck, newest first, without the cards themselves (count, how many are known and how many were missed last time)."""
        with self.lock:
            rows = self.db.execute("SELECT id, title, cards, made, practised FROM decks ORDER BY id DESC").fetchall()
        return [self._shape(r, with_cards=False) for r in rows]

    def get(self, deck_id):
        with self.lock:
            row = self.db.execute("SELECT id, title, cards, made, practised FROM decks WHERE id = ?", (deck_id,)).fetchone()
        return self._shape(row) if row else None

    def mark(self, deck_id, card, right, now):
        """Record one answer: card number `card` (from 0) was right or wrong. Returns the deck, or None when the deck or card is not there."""
        with self.lock:
            row = self.db.execute("SELECT id, title, cards, made, practised FROM decks WHERE id = ?", (deck_id,)).fetchone()
            if not row:
                return None
            cards = json.loads(row[2])
            if not (isinstance(card, int) and not isinstance(card, bool) and 0 <= card < len(cards)):
                return None
            cards[card]["right" if right else "wrong"] += 1
            cards[card]["last"] = bool(right)
            self.db.execute("UPDATE decks SET cards = ?, practised = ? WHERE id = ?", (json.dumps(cards), now, deck_id))
            self.db.commit()
            return self._shape((row[0], row[1], json.dumps(cards), row[3], now))

    def delete(self, deck_id):
        with self.lock:
            n = self.db.execute("DELETE FROM decks WHERE id = ?", (deck_id,)).rowcount
            self.db.commit()
        return bool(n)
