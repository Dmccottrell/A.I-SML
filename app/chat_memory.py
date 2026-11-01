"""
chat_memory.py - Let the AI remember earlier chats and facts about you (prototype).

WHAT THIS FILE DOES
    The model itself never remembers anything between chats: its weights don't change when you talk
    to it. Assistants that "remember you" do it around the model, and so does this:

      1. Past chats.  Every question and answer is saved on THIS computer (data/memory/memory.db).
                      When you ask something, the best-matching earlier exchanges are found (the
                      same keyword search as the Wikipedia lookup) and given to the model as notes:
                          [1] Earlier chat (Sep 29): User: my dog is called Biscuit ... AI: ...
      2. Saved memories.  Short facts about you. You can save one yourself ("remember: I prefer
                      Python"), and v3+ saves them on its own when you tell it something worth
                      keeping ("my name is Sam"): it writes a "remember" tool call, which the chat
                      saves and shows you as "(saved to memory: ...)". It is trained NOT to save
                      passwords, card numbers, moods or facts about other people. Saved facts are
                      given as notes when they match what you ask; list or delete them any time.

    SEARCH BY MEANING: with a small embedding model (all-MiniLM-L6-v2, Apache-2.0, ~90 MB, runs on
    the CPU) each saved exchange and fact also gets a list of numbers describing its MEANING, so "my
    pet" finds "my cat is called Pixel" even though no word matches. Results from both searches are
    combined (keywords are best for exact names and numbers). It needs `pip install
    sentence-transformers` once; without it, keyword search alone is used.

    The notes use the same format as the Wikipedia notes v3 is trained on (see chat.py), so the model
    reads them the same way: no extra training is needed to start. Nothing leaves this computer.

    In the chat (python tools/generate.py --version v3 --chat --memory):
        remember: <fact>     save a fact            memories         list saved facts
        forget <number>      delete one fact        forget everything   delete all chats and facts
    --private  chat without saving anything (the chat can still read old memories).

    From the command line:
        python app/chat_memory.py memories              list saved facts
        python app/chat_memory.py remember "I live in Chicago"
        python app/chat_memory.py forget 3
        python app/chat_memory.py search "what is my dog called"
        python app/chat_memory.py chats                 list saved chats
        python app/chat_memory.py clear                 delete everything (asks first)
"""
# Where it fits: the chat server and the command-line chat import ChatMemory from here to save and look up memories.
# The next line (kept as one line on purpose) adds the project's code folders to Python's import search path,
# so "from wiki_index import ..." below works wherever this file is started from.
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import argparse        # reads the words typed after the command name (the command line)
import os
import sqlite3         # SQLite: a database stored in one ordinary file; built into Python
import sys
import time

import numpy as np     # fast maths on lists of numbers (used to compare "meaning vectors")

from wiki_index import keywords

# Where the memory database file lives by default (relative to the folder the program is started in).
DEFAULT_DB = os.path.join("data", "memory", "memory.db")
NOTE_WORDS = 120          # an earlier exchange is cut to about this many words (like a Wikipedia passage)
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
MIN_SIMILARITY = 0.35     # meaning matches weaker than this are ignored (0 = unrelated, 1 = same meaning)
RRF_K = 60                # how keyword and meaning rankings are combined (reciprocal rank fusion)


class Embedder:
    """Turns texts into meaning vectors with a small open model (downloaded once, then offline).

    A "meaning vector" (an embedding) is a list of numbers; two texts that mean similar things get similar lists.
    """

    def __init__(self, name=EMBED_MODEL):
        """Load the model called `name` on the CPU (no graphics card needed)."""
        # Imported here, not at the top of the file, so the program still starts when this optional package is missing.
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(name, device="cpu")

    def __call__(self, texts):
        """Turn a list of texts into a 2-D array: one row of numbers (a vector) per text, in the same order."""
        # normalize_embeddings=True makes every vector length 1, so a plain dot product later equals cosine similarity.
        return np.asarray(self.model.encode(list(texts), normalize_embeddings=True), dtype=np.float32)


def load_embedder(quiet=False):
    """The embedding model, or None (keyword search only) if it isn't installed or can't load."""
    try:
        return Embedder()
    # Catch everything on purpose: any failure here must only switch the feature off, never crash the chat.
    except Exception as e:                 # not installed, or no internet for the first download
        if not quiet:
            print(f"(memory: search by meaning is off ({type(e).__name__}); keyword search only. "
                  "To turn it on: pip install sentence-transformers)")
        return None


def shorten(text, words=NOTE_WORDS):
    """Cut `text` to at most `words` words (adds " ..." if cut); also squeezes runs of spaces/newlines into single spaces."""
    # split() with no argument breaks on any whitespace, so joining with one space tidies the text too.
    parts = text.split()
    return " ".join(parts) if len(parts) <= words else " ".join(parts[:words]) + " ..."


def day(timestamp):
    """A Unix timestamp (seconds since 1970) as a short local date such as "Sep 29" (no zero padding: "Sep 9")."""
    # %b = short month name, %d = day number with a leading zero; replacing " 0" with " " removes that zero.
    return time.strftime("%b %d", time.localtime(timestamp)).replace(" 0", " ")


class ChatMemory:
    """Saved chats and facts, with keyword search (plus search by meaning if given an embedder). Example:

        mem = ChatMemory()
        chat = mem.start_chat()
        mem.add_exchange(chat, "my dog is called Biscuit", "What a lovely name!")
        mem.notes("what's my dog's name?", exclude_chat=None)
            -> [{"title": "Earlier chat (Sep 29)", "text": "User: my dog is called Biscuit AI: What a lovely name!"}]
    """

    def __init__(self, path=DEFAULT_DB, embedder=None):
        """embedder: turns texts into meaning vectors (Embedder, or any function with the same
        behaviour). None = keyword search only."""
        self.embedder = embedder
        # A speed-up: the vectors of a table are loaded from disk once and kept here until something changes them.
        self._cache = {}                   # kind -> (ids, matrix of vectors), rebuilt after changes
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        # Make sure the folder for the database file exists (path may have no folder at all, hence "or '.'").
        # Connecting creates the file if it isn't there yet.
        self.db = sqlite3.connect(path)
        # FTS5 = SQLite's built-in full-text search. "content='exchanges'" means the search index points at the
        # real table instead of keeping its own copy of the text; "porter" reduces words to their stems
        # (running -> run) so word forms match.
        try:
            self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS exchanges_fts USING fts5("
                            "text, content='exchanges', content_rowid='id', tokenize='porter unicode61')")
            self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5("
                            "text, content='facts', content_rowid='id', tokenize='porter unicode61')")
        except sqlite3.OperationalError as e:
            # Some Python builds ship SQLite without FTS5: give a clear message instead of a cryptic database error.
            if "fts5" in str(e).lower():
                raise SystemExit("Your Python's SQLite has no FTS5 full-text search. "
                                 "Install Python from python.org (it includes FTS5).")
            raise
        # "with self.db" is a transaction: all the statements inside are saved together, or none if one fails.
        # The four tables: chats (one row per conversation), exchanges (each question + answer), facts (saved
        # memories) and vectors (the meaning numbers of an exchange or fact, stored as raw bytes in a BLOB).
        with self.db:
            self.db.execute("CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY, started REAL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS exchanges (id INTEGER PRIMARY KEY, chat INTEGER, "
                            "time REAL, user TEXT, ai TEXT, text TEXT)")
            self.db.execute("CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY, time REAL, text TEXT)")
            self.db.execute("CREATE TABLE IF NOT EXISTS vectors (kind TEXT, id INTEGER, vec BLOB, PRIMARY KEY (kind, id))")
        # If meaning search is on, give vectors to anything saved earlier without it.
        if self.embedder:
            self.embed_missing()

    # ---- meaning vectors ----
    def _store_vectors(self, kind, rows):
        """rows: [(id, text)]. Computes and saves their vectors."""
        if not rows or not self.embedder:
            return
        # Long texts are shortened first: the model only reads a limited amount, and it keeps this fast.
        vecs = self.embedder([shorten(t) for _, t in rows])
        # INSERT OR REPLACE overwrites an existing vector for the same (kind, id). The vector is stored as raw
        # float32 bytes so it fits in one database column.
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO vectors VALUES (?, ?, ?)",
                                [(kind, i, v.astype(np.float32).tobytes()) for (i, _), v in zip(rows, vecs)])
        # The cached copy is now out of date: drop it so the next search reloads from the database.
        self._cache.pop(kind, None)

    def embed_missing(self):
        """Give a vector to everything saved before search by meaning was turned on."""
        for kind in ("exchanges", "facts"):
            # Rows that have no entry yet in the vectors table.
            rows = self.db.execute(f"SELECT id, text FROM {kind} WHERE id NOT IN "
                                   "(SELECT id FROM vectors WHERE kind = ?)", (kind,)).fetchall()
            # Work in batches of 256 texts so the model never gets a huge list at once.
            for i in range(0, len(rows), 256):
                self._store_vectors(kind, rows[i:i + 256])

    def _vectors(self, kind):
        """Return (ids, matrix) for a kind: row j of the matrix is the vector of ids[j]. matrix is None if there are none."""
        if kind not in self._cache:
            rows = self.db.execute("SELECT id, vec FROM vectors WHERE kind = ?", (kind,)).fetchall()
            ids = [i for i, _ in rows]
            # Turn each stored byte string back into float numbers and stack them into one 2-D array.
            mat = np.stack([np.frombuffer(v, dtype=np.float32) for _, v in rows]) if rows else None
            self._cache[kind] = (ids, mat)
        return self._cache[kind]

    # ---- saving ----
    def start_chat(self):
        """Begin a new conversation: add a row to `chats` and return its id."""
        with self.db:
            return self.db.execute("INSERT INTO chats (started) VALUES (?)", (time.time(),)).lastrowid

    def add_exchange(self, chat, user, ai, when=None):
        """Save one question and its answer in chat number `chat`. `when` is a timestamp (default: now). Returns the new row id."""
        # One searchable string holding both sides of the exchange.
        text = f"User: {user} AI: {ai}"
        with self.db:
            i = self.db.execute("INSERT INTO exchanges (chat, time, user, ai, text) VALUES (?, ?, ?, ?, ?)",
                                (chat, when or time.time(), user, ai, text)).lastrowid
            # Also add it to the full-text index, using the same id so a search hit maps back to this row.
            self.db.execute("INSERT INTO exchanges_fts (rowid, text) VALUES (?, ?)", (i, text))
        self._store_vectors("exchanges", [(i, text)])
        return i

    def remember(self, fact):
        """Save a short fact about the user and return its id (the old id if the same fact is already saved)."""
        # Tidy the spaces so "I  like   tea" and "I like tea" count as the same fact.
        fact = " ".join(fact.split())
        if not fact:
            raise ValueError("nothing to remember")
        # Case-insensitive duplicate check.
        same = self.db.execute("SELECT id FROM facts WHERE lower(text) = lower(?)", (fact,)).fetchone()
        if same:
            return same[0]                 # already saved: don't keep duplicates
        with self.db:
            i = self.db.execute("INSERT INTO facts (time, text) VALUES (?, ?)", (time.time(), fact)).lastrowid
            self.db.execute("INSERT INTO facts_fts (rowid, text) VALUES (?, ?)", (i, fact))
        self._store_vectors("facts", [(i, fact)])
        return i

    # ---- looking things up ----
    def _keyword_ids(self, table, question, n):
        """Ids of the best keyword matches (BM25), best first.

        BM25 is a standard scoring formula: rarer words and more matches score higher.
        """
        # keywords() drops filler words like "the" and "is" and keeps the useful ones.
        words = keywords(question)
        if not words:
            return []
        # An FTS5 query: each word in double quotes (so odd characters can't break the syntax), joined by OR.
        match = " OR ".join(f'"{w}"' for w in words)
        # Join the search index to the real table; bm25() is lower for better matches, so ascending order is best first;
        # ties go to the newest. "?" marks are filled in safely by the database (this avoids SQL injection).
        sql = (f"SELECT t.id FROM {table}_fts f JOIN {table} t ON t.id = f.rowid "
               f"WHERE {table}_fts MATCH ? ORDER BY bm25({table}_fts), t.time DESC LIMIT ?")
        return [r[0] for r in self.db.execute(sql, (match, n))]

    def _meaning_ids(self, table, question, n):
        """Ids of the closest meanings (cosine similarity above MIN_SIMILARITY), best first."""
        if not self.embedder:
            return []
        ids, mat = self._vectors(table)
        if mat is None:
            return []
        # Vectors have length 1, so matrix @ vector (dot products) gives the cosine similarity of the question
        # to every saved row at once: 1 = same meaning, 0 = unrelated.
        sims = mat @ self.embedder([question])[0]
        # argsort of the negated scores = indexes from highest score to lowest; keep the top n.
        order = np.argsort(-sims)[:n]
        return [ids[j] for j in order if sims[j] >= MIN_SIMILARITY]

    def _search(self, table, question, k, exclude_chat=None):
        """Keyword and meaning results combined (reciprocal rank fusion), as row dicts."""
        # Fetch more candidates than needed (at least 20): some get dropped below (missing rows, current chat).
        n = max(k * 5, 20)
        score = {}
        # Reciprocal rank fusion: every list gives a row 1/(RRF_K + rank) points, so rows ranked high in either
        # list (or in both) win. This merges two rankings without having to compare their different score scales.
        for ranking in (self._keyword_ids(table, question, n), self._meaning_ids(table, question, n)):
            for rank, i in enumerate(ranking):
                score[i] = score.get(i, 0.0) + 1.0 / (RRF_K + rank)
        out = []
        # Highest total score first.
        for i in sorted(score, key=lambda i: -score[i]):
            cur = self.db.execute(f"SELECT * FROM {table} WHERE id = ?", (i,))
            row = cur.fetchone()
            if row is None:
                continue
            # Turn the database row (a tuple) into a dict keyed by column name.
            row = dict(zip([c[0] for c in cur.description], row))
            if exclude_chat is not None and row.get("chat") == exclude_chat:
                continue                   # the current chat: the model can already see it
            out.append(row)
            if len(out) == k:
                break
        return out

    def search_exchanges(self, question, k=2, exclude_chat=None):
        """The best `k` earlier question+answer rows for `question`, skipping chat `exclude_chat`."""
        return self._search("exchanges", question, k, exclude_chat)

    def search_facts(self, question, k=2):
        """The best `k` saved facts for `question`."""
        return self._search("facts", question, k)

    def notes(self, question, k_facts=2, k_chats=2, exclude_chat=None):
        """Notes for a question: matching saved facts first, then matching earlier exchanges.

        exclude_chat: the current chat, whose messages the model can already see.
        """
        # Facts first (they are short and more reliable), shaped like the Wikipedia notes: a title and a text.
        out = [{"title": "Saved memory", "text": f["text"]} for f in self.search_facts(question, k_facts)]
        for e in self.search_exchanges(question, k_chats, exclude_chat):
            out.append({"title": f"Earlier chat ({day(e['time'])})", "text": shorten(e["text"])})
        return out

    # ---- seeing and deleting ----
    def facts(self):
        """All saved facts, oldest first, as dicts with id, time and text."""
        return [dict(zip(("id", "time", "text"), r)) for r in
                self.db.execute("SELECT id, time, text FROM facts ORDER BY id")]

    def forget(self, fact_id):
        """Delete one saved fact. Returns False if there was no such fact."""
        row = self.db.execute("SELECT text FROM facts WHERE id = ?", (fact_id,)).fetchone()
        if not row:
            return False
        with self.db:
            # An FTS5 "external content" index must be told what text to remove: the special 'delete' command
            # does that (deleting only from the facts table would leave the word index stale).
            self.db.execute("INSERT INTO facts_fts (facts_fts, rowid, text) VALUES ('delete', ?, ?)", (fact_id, row[0]))
            self.db.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
            self.db.execute("DELETE FROM vectors WHERE kind = 'facts' AND id = ?", (fact_id,))
        self._cache.pop("facts", None)
        return True

    def chats(self):
        """Every saved chat as a dict: id, start time, number of exchanges, and the first thing the user said (or None)."""
        # LEFT JOIN keeps chats that have no exchanges yet (their count is 0); the sub-select picks the first message.
        return [dict(zip(("id", "started", "exchanges", "first"), r)) for r in self.db.execute(
            "SELECT c.id, c.started, COUNT(e.id), (SELECT user FROM exchanges WHERE chat = c.id ORDER BY id LIMIT 1) "
            "FROM chats c LEFT JOIN exchanges e ON e.chat = c.id GROUP BY c.id ORDER BY c.id")]

    def clear(self):
        """Delete every saved chat and fact."""
        with self.db:
            for t in ("exchanges", "facts", "chats", "vectors"):
                self.db.execute(f"DELETE FROM {t}")
            # 'rebuild' tells the search index to re-read its (now empty) tables.
            self.db.execute("INSERT INTO exchanges_fts (exchanges_fts) VALUES ('rebuild')")
            self.db.execute("INSERT INTO facts_fts (facts_fts) VALUES ('rebuild')")
        self._cache.clear()

    def close(self):
        """Close the database file."""
        self.db.close()


def handle_command(mem, msg):
    """Memory commands typed in the chat. Returns the text to show, or None if `msg` isn't one."""
    # Lower-case copy used only to recognise the command; the original `msg` keeps the user's capital letters for saving.
    low = msg.strip().lower()
    if low.startswith("remember:"):
        # Everything after the first colon is the fact.
        fact = msg.split(":", 1)[1].strip()
        if not fact:
            return "(nothing to remember: type  remember: <fact>)"
        mem.remember(fact)
        return f"(saved: {fact})"
    if low == "memories":
        facts = mem.facts()
        return "\n".join(f"  {f['id']}. {f['text']}" for f in facts) if facts else "(no saved memories)"
    if low == "forget everything":
        mem.clear()
        return "(all saved chats and memories deleted)"
    if low.startswith("forget "):
        # What follows "forget " should be the fact number shown by "memories".
        n = low[len("forget "):].strip()
        if not n.isdigit():
            return "(type  forget <number>  - the number from 'memories' - or  forget everything)"
        return f"(forgot memory {n})" if mem.forget(int(n)) else f"(there is no memory {n})"
    return None


def main():
    """Command-line entry point: run one of the memory commands listed at the top of this file."""
    p = argparse.ArgumentParser(description="See and manage what the AI remembers.")
    p.add_argument("command", choices=["memories", "remember", "forget", "search", "chats", "clear"])
    p.add_argument("text", nargs="?", default="")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--no_meaning", action="store_true", help="keyword search only")
    a = p.parse_args()
    # The (slow-to-load) meaning model is only needed for "search".
    mem = ChatMemory(a.db, None if a.no_meaning or a.command != "search" else load_embedder())
    if a.command == "memories":
        print(handle_command(mem, "memories"))
    elif a.command == "remember":
        print(handle_command(mem, "remember: " + a.text))
    elif a.command == "forget":
        print(handle_command(mem, "forget " + a.text))
    elif a.command == "search":
        for n in mem.notes(a.text):
            print(f"[{n['title']}] {n['text']}")
    elif a.command == "chats":
        for c in mem.chats():
            print(f"  chat {c['id']} ({day(c['started'])}): {c['exchanges']} exchanges, starts: {c['first'] or ''}")
    elif a.command == "clear":
        if input("Delete ALL saved chats and memories? Type yes: ").strip().lower() == "yes":
            mem.clear()
            print("deleted")
        else:
            print("nothing deleted")
    mem.close()


# Runs main() only when the file is started directly (python app/chat_memory.py ...), not when imported.
if __name__ == "__main__":
    sys.exit(main())
