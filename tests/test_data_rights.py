"""Download my data, delete my account, the privacy and terms pages, and backups."""
import io
import json
import os
import sqlite3
import stat
import tempfile
import time
import unittest
import zipfile

import backup_data as B
import data_tools
from tests.test_app_server import Base, Client
from tests.test_code_sessions import open_to_everyone

TOKEN = "ghp_" + "Qq1Ww2Ee3R" * 4


def fake_github(method, url, headers, body):
    return 200, {"login": "sam", "id": 7}


class Rights(Base):
    data_dir = True

    def setUp(self):
        super().setUp()
        self.state.github_http = fake_github
        open_to_everyone(self.state)

    def sam_data(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "remember the word pineapple")
        priv = self.new_chat(self.sam, private=True)
        self.ask(self.sam, priv, "my-private-secret-words")
        self.sam.call("POST", "/api/apps/github/connect", {"token": TOKEN})
        self.sam.call("POST", "/api/code/import", {"project": "app", "files": [{"path": "a.py", "b64": "cHJpbnQoMSk="}]})
        return cid

    def test_the_export_has_everything_in_plain_files_and_no_secrets(self):
        self.sam_data()
        st, h, data = self.sam.call("GET", "/api/export", raw=True)
        self.assertEqual(st, 200)
        self.assertEqual(h["Content-Type"], "application/zip")
        self.assertIn("attachment", h["Content-Disposition"])
        z = zipfile.ZipFile(io.BytesIO(data))
        names = set(z.namelist())
        for must in ("README.txt", "profile.json", "settings.json", "chats.json", "saved_notes.json", "devices.json", "github.json", "projects/app/a.py"):
            self.assertIn(must, names)
        chats = json.loads(z.read("chats.json"))
        self.assertIn("pineapple", json.dumps(chats))
        everything = b"".join(z.read(n) for n in names)
        self.assertNotIn(b"my-private-secret-words", everything)               # private chats were never saved
        self.assertNotIn(TOKEN.encode(), everything)                           # no token
        self.assertNotIn(self.sam_key.encode(), everything)                    # no key
        self.assertEqual(json.loads(z.read("profile.json"))["plan"], "free")
        self.assertEqual(z.read("projects/app/a.py"), b"print(1)")

    def test_the_export_is_only_your_own_and_needs_a_sign_in(self):
        self.sam_data()
        self.assertEqual(Client(self.port).call("GET", "/api/export")[0], 401)
        z = zipfile.ZipFile(io.BytesIO(self.owner.call("GET", "/api/export", raw=True)[2]))
        self.assertNotIn("pineapple", json.dumps(json.loads(z.read("chats.json"))))

    def test_deleting_an_account_removes_everything(self):
        self.sam_data()
        phone = Client(self.port)
        st, h, _ = phone.call("GET", "/pair/" + self.owner.call("POST", "/api/admin/pairing", {"user": "sam"})[1]["pair"], raw=True)
        phone.cookie = h["Set-Cookie"].split(";")[0]
        self.assertEqual(self.sam.call("POST", "/api/delete-account", {"confirm": "wrong"})[0], 400)
        self.assertEqual(self.sam.call("GET", "/api/state")[0], 200)               # nothing happened
        self.assertEqual(self.sam.call("POST", "/api/delete-account", {"confirm": "sam"})[0], 200)
        self.assertEqual(self.sam.call("GET", "/api/state")[0], 401)               # the key no longer works
        self.assertEqual(phone.call("GET", "/api/state")[0], 401)                  # nor the signed-in device
        d = self.tmp.name
        self.assertFalse(os.path.exists(os.path.join(d, "chats-sam.db")))
        self.assertFalse(os.path.exists(os.path.join(d, "code", "sam")))
        self.assertFalse(os.path.exists(self.state.github._path("sam")))
        self.assertNotIn("sam", open(os.path.join(d, "users.json")).read())
        with self.assertRaises(KeyError):
            self.state.usage.get_user("sam")
        events = self.state.auth.events(limit=200)
        self.assertNotIn("sam", {e["user"] for e in events})                       # their name left the security log
        self.assertIn("account_deleted", {e["kind"] for e in events})
        self.assertEqual(self.owner.call("GET", "/api/state")[0], 200)              # others are untouched

    def test_the_owner_account_cannot_be_deleted_this_way(self):
        st, j = self.owner.call("POST", "/api/delete-account", {"confirm": "owner"})
        self.assertEqual(st, 400)
        self.assertEqual(self.owner.call("GET", "/api/state")[0], 200)

    def test_a_deleted_name_can_start_fresh(self):
        self.sam_data()
        self.sam.call("POST", "/api/delete-account", {"confirm": "sam"})
        key = self.state.add_user("sam", "free")
        again = Client(self.port, key)
        self.assertEqual(again.call("GET", "/api/state")[1]["chats"], [])


class Pages(Base):
    def test_privacy_and_terms_are_public_and_carry_the_owners_details(self):
        self.state.security["contact_email"] = "help@example.com"
        self.state.security["operator_name"] = "Sam Example"
        for path in ("/privacy", "/terms"):
            st, h, body = Client(self.port).call("GET", path, raw=True)
            self.assertEqual(st, 200, path)
            text = body.decode()
            self.assertIn("mailto:help@example.com", text)
            self.assertIn("Sam Example", text)
            self.assertNotIn("{{", text)
            self.assertIn("style-src 'unsafe-inline'", h["Content-Security-Policy"])
            self.assertNotIn("script", h["Content-Security-Policy"].replace("default-src 'none'", ""))

    def test_without_details_the_pages_say_so_plainly(self):
        text = Client(self.port).call("GET", "/privacy", raw=True)[2].decode()
        self.assertIn("the person who runs this server", text)
        self.assertNotIn("{{", text)

    def test_the_contact_goes_to_the_page(self):
        self.assertIsNone(self.sam.call("GET", "/api/state")[1]["contact"])
        self.state.security["contact_email"] = "help@example.com"
        self.assertEqual(self.sam.call("GET", "/api/state")[1]["contact"], "help@example.com")

    def test_the_policy_says_what_the_app_really_does(self):
        text = Client(self.port).call("GET", "/privacy", raw=True)[2].decode()
        for fact in ("Private chats are never saved", "never stored", "Download my data", "Delete my account", "5,000", "not used to train"):
            self.assertIn(fact, text)


class Backups(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = os.path.join(self.tmp.name, "data")
        os.makedirs(os.path.join(self.data, "code", "sam", "app"))
        open(os.path.join(self.data, "users.json"), "w").write('{"h:abc": {"user": "sam"}}')
        open(os.path.join(self.data, "secret.key"), "w").write("THE-KEY")
        open(os.path.join(self.data, "code", "sam", "app", "a.py"), "w").write("print(1)")
        db = sqlite3.connect(os.path.join(self.data, "chats-sam.db"))
        db.execute("CREATE TABLE t (x)")
        db.execute("INSERT INTO t VALUES ('hello')")
        db.commit()
        self.db = db                                                          # left open: a running app
        self.out = os.path.join(self.tmp.name, "backups")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_a_backup_is_consistent_private_and_leaves_the_key_out(self):
        target, count, removed = B.make_backup(self.data, self.out)
        self.assertEqual(stat.S_IMODE(os.stat(target).st_mode) & 0o077, 0)
        z = zipfile.ZipFile(target)
        names = set(z.namelist())
        self.assertIn("users.json", names)
        self.assertIn("code/sam/app/a.py", names)
        self.assertNotIn("secret.key", names)
        out = os.path.join(self.tmp.name, "x.db")
        open(out, "wb").write(z.read("chats-sam.db"))
        self.assertEqual(sqlite3.connect(out).execute("SELECT x FROM t").fetchone()[0], "hello")

    def test_options_for_the_key_and_projects(self):
        names = set(zipfile.ZipFile(B.make_backup(self.data, self.out, with_key=True, projects=False)[0]).namelist())
        self.assertIn("secret.key", names)
        self.assertFalse(any(n.startswith("code/") for n in names))

    def test_only_the_newest_are_kept(self):
        for i in range(5):
            B.make_backup(self.data, self.out, keep=3, now=1_700_000_000 + i * 86400)
        kept = sorted(os.listdir(self.out))
        self.assertEqual(len(kept), 3)
        self.assertTrue(kept[-1] > kept[0])
        self.assertEqual(B.make_backup(self.data, self.out, keep=0, now=1_800_000_000)[2], [])           # 0 keeps all

    def test_restore_works_into_an_empty_folder_only_and_refuses_unsafe_paths(self):
        target = B.make_backup(self.data, self.out)[0]
        dest = os.path.join(self.tmp.name, "restored")
        self.assertGreater(B.restore(target, dest), 2)
        self.assertEqual(open(os.path.join(dest, "code", "sam", "app", "a.py")).read(), "print(1)")
        with self.assertRaises(SystemExit):
            B.restore(target, dest)                                           # not empty any more
        evil = os.path.join(self.tmp.name, "evil.zip")
        with zipfile.ZipFile(evil, "w") as z:
            z.writestr("../escape.txt", "x")
        with self.assertRaises(SystemExit):
            B.restore(evil, os.path.join(self.tmp.name, "r2"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "escape.txt")))

    def test_command_line(self):
        self.assertEqual(B.main(["--data", self.data, "--out", self.out, "--keep", "2"]), 0)
        self.assertEqual(len(os.listdir(self.out)), 1)


if __name__ == "__main__":
    unittest.main()
