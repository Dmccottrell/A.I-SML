"""
chat_memory.py - Let the AI remember earlier chats and facts about you (prototype).

WHAT THIS FILE DOES
    The model itself never remembers anything between chats: its weights don't change when you talk
    to it. Assistants that "remember you" do it around the model, and so does this:

      1. Past chats.  Every question and answer is saved on THIS computer (data/memory/memory.db).
                      When you ask something, the best-matching earlier exchanges are found (the
                      same keyword search as the Wikipedia lookup) and given to the model as notes:
                          [1] Earlier chat (Sep 29): User: my dog is called Biscuit ... AI: ...
      2. Saved memories.  Short facts you ask it to keep ("remember: I prefer Python"). They are
                      given as notes when they match what you ask, and you can list or delete them.

    The notes use the same format as the Wikipedia notes v3 is trained on (see chat.py), so the model
    reads them the same way: no extra training is needed to start. Nothing leaves this computer.

    In the chat (python generate.py --version v3 --chat --memory):
        remember: <fact>     save a fact            memories         list saved facts
        forget <number>      delete one fact        forget everything   delete all chats and facts
    --private  chat without saving anything (the chat can still read old memories).

    From the command line:
        python chat_memory.py memories              list saved facts
        python chat_memory.py remember "I live in Chicago"
        python chat_memory.py forget 3
        python chat_memory.py search "what is my dog called"
        python chat_memory.py chats                 list saved chats
        python chat_memory.py clear                 delete everything (asks first)
"""
import argparse
import os
import sqlite3
import sys
import time

from wiki_index import keywords

DEFAULT_DB = os.path.join("data", "memory", "memory.db")
NOTE_WORDS = 120          # an earlier exchange is cut to about this many words (like a Wikipedia passage)


def shorten(text, words=NOTE_WORDS):
    parts = text.split()
    return " ".join(parts) if len(parts) <= words else " ".join(parts[:words]) + " ..."


def day(timestamp):
    return time.strftime("%b %d", time.localtime(timestamp)).replace(" 0", " ")


class ChatMemory:
    """Saved chats and facts, with keyword search. Example:

        mem = ChatMemory()
        chat = mem.start_chat()
        mem.add_exchange(chat, "my dog is called Biscuit", "What a lovely name!")
        mem.notes("what's my dog's name?", exclude_chat=None)
            -> [{"title": "Earlier chat (Sep 29)", "text": "User: my dog is called Biscuit AI: What a lovely name!"}]
    """

    def __init__(self, path=DEFAULT_DB):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path)
        try:
            self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS exchanges_fts USING fts5("
                            "text, content='exchanges', content_rowid='id', tokenize='porter unicode61')")
            self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5("
                            "text, content='facts', content_rowid='id', tokenize='porter unicode61')")
        except sqlite3.OperationalError as e:
            if "fts5" in str(e).lower():
                raise SystemExit("Your Python's SQLite has no FTS5 full-text search. "
                                 "Install Python from python.org (it includes FTS5).")
            raise
        with self.db:
            self.db.execute("CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY, started REAL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS exchanges (id INTEGER PRIMARY KEY, chat INTEGER, "
                            "time REAL, user TEXT, ai TEXT, text TEXT)")
            self.db.execute("CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY, time REAL, text TEXT)")

    # ---- saving ----
    def start_chat(self):
        with self.db:
            return self.db.execute("INSERT INTO chats (started) VALUES (?)", (time.time(),)).lastrowid

    def add_exchange(self, chat, user, ai, when=None):
        """Save one question and its answer."""
        text = f"User: {user} AI: {ai}"
        with self.db:
            i = self.db.execute("INSERT INTO exchanges (chat, time, user, ai, text) VALUES (?, ?, ?, ?, ?)",
                                (chat, when or time.time(), user, ai, text)).lastrowid
            self.db.execute("INSERT INTO exchanges_fts (rowid, text) VALUES (?, ?)", (i, text))
        return i

    def remember(self, fact):
        fact = " ".join(fact.split())
        if not fact:
            raise ValueError("nothing to remember")
        with self.db:
            i = self.db.execute("INSERT INTO facts (time, text) VALUES (?, ?)", (time.time(), fact)).lastrowid
            self.db.execute("INSERT INTO facts_fts (rowid, text) VALUES (?, ?)", (i, fact))
        return i

    # ---- looking things up ----
    def _search(self, table, question, k, extra_where="", params=()):
        words = keywords(question)
        if not words:
            return []
        match = " OR ".join(f'"{w}"' for w in words)
        sql = (f"SELECT t.* FROM {table}_fts f JOIN {table} t ON t.id = f.rowid "
               f"WHERE {table}_fts MATCH ? {extra_where} ORDER BY bm25({table}_fts), t.time DESC LIMIT ?")
        cur = self.db.execute(sql, (match, *params, k))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur]

    def search_exchanges(self, question, k=2, exclude_chat=None):
        where, params = ("AND t.chat != ?", (exclude_chat,)) if exclude_chat is not None else ("", ())
        return self._search("exchanges", question, k, where, params)

    def search_facts(self, question, k=2):
        return self._search("facts", question, k)

    def notes(self, question, k_facts=2, k_chats=2, exclude_chat=None):
        """Notes for a question: matching saved facts first, then matching earlier exchanges.

        exclude_chat: the current chat, whose messages the model can already see.
        """
        out = [{"title": "Saved memory", "text": f["text"]} for f in self.search_facts(question, k_facts)]
        for e in self.search_exchanges(question, k_chats, exclude_chat):
            out.append({"title": f"Earlier chat ({day(e['time'])})", "text": shorten(e["text"])})
        return out

    # ---- seeing and deleting ----
    def facts(self):
        return [dict(zip(("id", "time", "text"), r)) for r in
                self.db.execute("SELECT id, time, text FROM facts ORDER BY id")]

    def forget(self, fact_id):
        """Delete one saved fact. Returns False if there was no such fact."""
        row = self.db.execute("SELECT text FROM facts WHERE id = ?", (fact_id,)).fetchone()
        if not row:
            return False
        with self.db:
            self.db.execute("INSERT INTO facts_fts (facts_fts, rowid, text) VALUES ('delete', ?, ?)", (fact_id, row[0]))
            self.db.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
        return True

    def chats(self):
        return [dict(zip(("id", "started", "exchanges", "first"), r)) for r in self.db.execute(
            "SELECT c.id, c.started, COUNT(e.id), (SELECT user FROM exchanges WHERE chat = c.id ORDER BY id LIMIT 1) "
            "FROM chats c LEFT JOIN exchanges e ON e.chat = c.id GROUP BY c.id ORDER BY c.id")]

    def clear(self):
        """Delete every saved chat and fact."""
        with self.db:
            for t in ("exchanges", "facts", "chats"):
                self.db.execute(f"DELETE FROM {t}")
            self.db.execute("INSERT INTO exchanges_fts (exchanges_fts) VALUES ('rebuild')")
            self.db.execute("INSERT INTO facts_fts (facts_fts) VALUES ('rebuild')")

    def close(self):
        self.db.close()


def handle_command(mem, msg):
    """Memory commands typed in the chat. Returns the text to show, or None if `msg` isn't one."""
    low = msg.strip().lower()
    if low.startswith("remember:"):
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
        n = low[len("forget "):].strip()
        if not n.isdigit():
            return "(type  forget <number>  - the number from 'memories' - or  forget everything)"
        return f"(forgot memory {n})" if mem.forget(int(n)) else f"(there is no memory {n})"
    return None


def main():
    p = argparse.ArgumentParser(description="See and manage what the AI remembers.")
    p.add_argument("command", choices=["memories", "remember", "forget", "search", "chats", "clear"])
    p.add_argument("text", nargs="?", default="")
    p.add_argument("--db", default=DEFAULT_DB)
    a = p.parse_args()
    mem = ChatMemory(a.db)
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


if __name__ == "__main__":
    sys.exit(main())
