"""vryxcode_dbview: a SQLite file in a project shown as tables, read-only."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import hashlib
import os
import sqlite3
import tempfile
import unittest

import code_db
from tests.test_app_server import Base


def make_db(path):
    con = sqlite3.connect(path)
    con.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT, note BLOB); CREATE TABLE \"odd \"\"name\"(x);"
                      "INSERT INTO users(name, note) VALUES ('Ada', x'0102'), ('Grace', NULL), ('Alan', NULL);")
    con.executemany("INSERT INTO \"odd \"\"name\" VALUES (?)", [(i,) for i in range(300)])
    con.commit()
    con.close()


def digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class View(unittest.TestCase):
    def test_tables_rows_search_and_nothing_written(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "app.db")
            make_db(db)
            before = digest(db)
            v = code_db.view(d, "app.db")
            self.assertEqual([(t["name"], t["rows"]) for t in v["tables"]], [('odd "name', 300), ("users", 3)])
            self.assertEqual((v["table"], len(v["rows"])), ('odd "name', 200))                     # the first rows only
            v = code_db.view(d, "app.db", "users", "a")
            self.assertEqual((v["columns"], [r[1] for r in v["rows"]]), (["id", "name", "note"], ["Ada", "Grace", "Alan"]))
            self.assertEqual(v["rows"][0][2], "[2 bytes]")
            self.assertEqual([r[1] for r in code_db.view(d, "app.db", "users", "gra")["rows"]], ["Grace"])
            self.assertEqual(code_db.view(d, "app.db", "users; DROP TABLE users")["table"], 'odd "name')  # only real table names are used
            self.assertEqual(digest(db), before)
            self.assertFalse(os.path.exists(db + "-journal"))

    def test_only_database_files_inside_the_project(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "notes.db"), "w") as f:
                f.write("not a database")
            for rel in ("../x.db", "missing.db", "notes.txt"):
                with self.assertRaises(code_db.DbError, msg=rel):
                    code_db.view(d, rel)
            with self.assertRaises(code_db.DbError):
                code_db.view(d, "notes.db")


class Server(Base):
    def test_the_files_panel_gets_the_tables(self):
        self.state.flags.data["audiences"]["vryxcode_dbview"] = "admins"
        folder = self.state.code.project_path("owner", "shop")
        os.makedirs(folder)
        make_db(os.path.join(folder, "shop.db"))
        st, j = self.owner.call("GET", "/api/code/db?project=shop&path=shop.db&table=users")
        self.assertEqual((st, [r[1] for r in j["rows"]]), (200, ["Ada", "Grace", "Alan"]))
        self.assertEqual(self.owner.call("GET", "/api/code/db?project=shop&path=../x.db")[0], 400)


if __name__ == "__main__":
    unittest.main()
