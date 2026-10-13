"""Admin > PC > Update now: it only moves forward, only to the change the owner was shown, never over hand edits, and only the owner can press it."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import shutil
import subprocess
import tempfile
import unittest

import updater
from tests.test_app_server import Base


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd, check=True, capture_output=True)


class Repos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.origin, self.work, self.other = (os.path.join(self.tmp, n) for n in ("origin.git", "work", "other"))
        subprocess.run(["git", "init", "--bare", "-b", "main", self.origin], check=True, capture_output=True)
        git(self.tmp, "clone", self.origin, self.work)
        git(self.work, "checkout", "-b", "main")
        self.write(self.work, "a.txt", "one\n")
        git(self.work, "add", "."), git(self.work, "commit", "-m", "first"), git(self.work, "push", "-u", "origin", "main")
        git(self.tmp, "clone", self.origin, self.other)

    def write(self, root, name, text):
        with open(os.path.join(root, name), "w") as f:
            f.write(text)

    def push_change(self, text="two\n", msg="second change", name="a.txt"):
        self.write(self.other, name, text)
        git(self.other, "add", "."), git(self.other, "commit", "-m", msg), git(self.other, "push", "origin", "main")

    def up(self, **kw):
        restarts = []
        u = updater.Updater(self.work, restart=lambda: restarts.append(1), **kw)
        u.can_restart = lambda: True
        return u, restarts

    def test_up_to_date_then_a_new_change_is_listed(self):
        u, _ = self.up()
        self.assertEqual(u.check()["reason"], "Already up to date.")
        self.push_change()
        c = u.check()
        self.assertTrue(c["can_update"])
        self.assertEqual((c["behind"], [i["subject"] for i in c["incoming"]]), (1, ["second change"]))

    def test_update_pulls_forward_restarts_and_needs_the_change_that_was_shown(self):
        u, restarts = self.up()
        self.push_change()
        c = u.check()
        with self.assertRaises(updater.UpdateError) as cm:
            u.apply("0123456789ab")                                   # not the change the person looked at
        self.assertEqual(cm.exception.code, "changed")
        with open(os.path.join(self.work, "a.txt")) as f:
            self.assertEqual(f.read(), "one\n")
        r = u.apply(c["latest"])
        self.assertEqual((r["updated"], r["changes"], r["restarting"]), (True, 1, True))
        self.assertEqual(restarts, [1])
        with open(os.path.join(self.work, "a.txt")) as f:
            self.assertEqual(f.read(), "two\n")

    def test_hand_edited_files_block_the_update_and_nothing_is_changed(self):
        u, restarts = self.up()
        self.push_change()
        self.write(self.work, "a.txt", "mine\n")
        c = u.check()
        self.assertFalse(c["can_update"])
        self.assertIn("edited by hand", c["reason"])
        with self.assertRaises(updater.UpdateError):
            u.apply(c["latest"])
        with open(os.path.join(self.work, "a.txt")) as f:
            self.assertEqual(f.read(), "mine\n")
        self.assertEqual(restarts, [])

    def test_a_copy_with_its_own_commits_or_another_branch_is_left_alone(self):
        u, _ = self.up()
        self.push_change()
        self.write(self.work, "b.txt", "local\n")
        git(self.work, "add", "."), git(self.work, "commit", "-m", "local only")
        self.assertIn("changes of its own", u.check()["reason"])
        git(self.work, "checkout", "-b", "side")
        self.assertIn("branch 'side'", u.check()["reason"])

    def test_busy_asks_first_unless_forced(self):
        u, restarts = self.up(busy=lambda: True)
        self.push_change()
        c = u.check()
        self.assertTrue(c["busy"])
        with self.assertRaises(updater.UpdateError) as cm:
            u.apply(c["latest"])
        self.assertEqual(cm.exception.code, "busy")
        self.assertEqual(u.apply(c["latest"], force=True)["restarting"], True)
        self.assertEqual(restarts, [1])

    def test_a_changed_requirements_file_is_flagged(self):
        u, _ = self.up()
        self.push_change("flask\n", "needs flask", "requirements.txt")
        self.assertTrue(u.check()["deps_changed"])

    def test_a_folder_that_is_not_a_git_copy_cannot_update(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        self.assertIn("not installed with git", updater.Updater(d).check()["reason"])


class Server(Base):
    class Fake:
        def __init__(self):
            self.applied = []

        def check(self):
            return {"can_update": True, "reason": "", "latest": "abc123", "current": "000000", "behind": 1, "incoming": [{"sha": "abc123", "subject": "x"}], "dirty": [], "busy": False, "restart": True}

        def apply(self, expected, force=False):
            self.applied.append((expected, force))
            return {"updated": True, "from": "000000", "to": "abc123", "changes": 1, "restarting": False, "deps_changed": False}

    def test_only_the_owner_can_check_or_update_and_it_is_logged(self):
        fake = self.state.updater = self.Fake()
        self.assertEqual(self.owner.call("GET", "/api/admin/update")[1]["latest"], "abc123")
        st, j = self.owner.call("POST", "/api/admin/update", {"expected": "abc123"})
        self.assertEqual((st, j["updated"]), (200, True))
        self.assertEqual(fake.applied, [("abc123", False)])
        log = " ".join(e["detail"] for e in self.owner.call("GET", "/api/admin/audit")[1]["events"] if e["kind"] == "update_applied")
        self.assertIn("000000 -> abc123", log)
        self.assertIn(self.sam.call("POST", "/api/admin/update", {"expected": "abc123"})[0], (401, 403))              # a plain user
        self.owner.call("POST", "/api/admin/access", {"user": "sam", "admin": True})
        self.assertEqual(self.sam.call("POST", "/api/admin/update", {"expected": "abc123"})[0], 403)                  # an admin is still not the owner
        self.assertNotEqual(self.sam.call("GET", "/api/admin/update")[0], 200)
        self.assertEqual(len(fake.applied), 1)


if __name__ == "__main__":
    unittest.main()
