"""Many requests at once: the chat, document and usage databases are shared by the server's threads (safe_db.py)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import tempfile
import threading
import time
import unittest

import app_engine as E
import usage_limits as U
from safe_db import SafeDB
from tests.test_usage_limits import NOW, make


def together(n, fn):
    """Run fn(i) in n threads started at the same moment; the errors they raised."""
    gate, errors = threading.Barrier(n), []

    def run(i):
        gate.wait()
        try:
            fn(i)
        except Exception as e:                                         # noqa: BLE001
            errors.append(e)
    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


class Shared(unittest.TestCase):
    def test_results_read_like_a_cursor(self):
        db = SafeDB()
        db.execute("CREATE TABLE t (x)")
        cur = db.execute("INSERT INTO t VALUES (1)")
        self.assertEqual(cur.lastrowid, 1)
        db.executemany("INSERT INTO t VALUES (?)", [(2,), (3,)])
        r = db.execute("SELECT x FROM t ORDER BY x")
        self.assertEqual(r.fetchone(), (1,))
        self.assertEqual(r.fetchall(), [(2,), (3,)])
        self.assertIsNone(r.fetchone())
        self.assertEqual([row[0] for row in db.execute("SELECT x FROM t")], [1, 2, 3])
        self.assertEqual(db.execute("DELETE FROM t").rowcount, 3)

    def test_many_chats_written_at_once_are_all_kept(self):
        with tempfile.TemporaryDirectory() as d:
            store = E.ChatStore(os.path.join(d, "chats.db"))

            def chat(i):
                cid = store.new_chat(f"chat {i}")
                for j in range(20):
                    row = store.add(cid, "user", f"q{j}")
                    store.update(cid, row, f"q{j} edited", "done")
                store.list_chats()
            self.assertEqual(together(12, chat), [])
            self.assertEqual(len(store.list_chats(everything=True)), 12)
            store.db.close()

    def test_two_requests_at_once_cannot_both_spend_the_last_of_the_tank(self):
        store, L = make("free")
        u, t = L.effective("sam")
        level = L.level_of("sam", t, NOW)
        passed, plain = [], L.level_of

        def slow(*a, **k):                                                # a busy PC: time passes between reading the tank and spending from it
            v = plain(*a, **k)
            time.sleep(0.01)
            return v
        L.level_of = slow

        def ask(i):
            try:
                passed.append(L.reserve("sam", "flare", "balanced", level * 0.6, NOW))
            except U.LimitError:
                pass
        self.assertEqual(together(8, ask), [])
        self.assertEqual(len(passed), 1)                                 # 0.6 + 0.6 is more than the tank holds: only one may run
