"""The restore drill (tools/restore_drill.py): a good backup passes; an empty, damaged or old one is reported, and the real data folder is never touched."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import sqlite3
import tempfile
import time
import unittest
import zipfile

import backup_data
import restore_drill


class Drill(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = os.path.join(self.tmp.name, "data")
        os.makedirs(self.data)
        db = sqlite3.connect(os.path.join(self.data, "chats.db"))
        db.execute("CREATE TABLE chats (id INTEGER PRIMARY KEY, title TEXT)")
        db.executemany("INSERT INTO chats (title) VALUES (?)", [("one",), ("two",), ("three",)])
        db.commit()
        db.close()
        self.out = os.path.join(self.tmp.name, "backups")

    def backup(self):
        return backup_data.make_backup(self.data, self.out)[0]

    def test_a_good_backup_passes_and_reports_the_rows(self):
        zip_path = self.backup()
        problems, report = restore_drill.drill(zip_path)
        self.assertEqual(problems, [])
        self.assertTrue(any("chats 3" in line for line in report), report)

    def test_the_newest_zip_is_found_and_the_main_command_passes(self):
        self.backup()
        self.assertTrue(restore_drill.newest_zip(self.out).endswith(".zip"))
        self.assertEqual(restore_drill.main(["--out", self.out]), 0)

    def test_a_damaged_zip_is_reported(self):
        bad = os.path.join(self.tmp.name, "emvryx-2026-01-01-0000.zip")
        with open(bad, "wb") as f:
            f.write(b"this is not a zip")
        problems, _ = restore_drill.drill(bad)
        self.assertTrue(problems and "could not be unpacked" in problems[0], problems)

    def test_a_backup_with_a_damaged_database_is_reported(self):
        bad = os.path.join(self.tmp.name, "emvryx-2026-01-01-0000.zip")
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("chats.db", b"SQLite format 3\x00" + b"garbage" * 200)
        problems, _ = restore_drill.drill(bad)
        self.assertTrue(problems, "a database that is not a real one must be reported")

    def test_an_empty_backup_and_an_old_one_are_reported(self):
        empty = os.path.join(self.tmp.name, "emvryx-2026-01-01-0000.zip")
        with zipfile.ZipFile(empty, "w"):
            pass
        self.assertTrue(any("empty" in p for p in restore_drill.drill(empty)[0]))
        old = self.backup()
        week_ago = time.time() - 8 * 86400
        os.utime(old, (week_ago, week_ago))
        self.assertEqual(restore_drill.main(["--zip", old]), 1)

    def test_no_backup_is_a_problem(self):
        self.assertEqual(restore_drill.main(["--out", os.path.join(self.tmp.name, "nothing")]), 1)


if __name__ == "__main__":
    unittest.main()
