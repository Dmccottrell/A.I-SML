"""The project's own guardrails (tools/guard_repo.py): existing tests cannot be deleted or weakened, no new unconditional skips, a fix comes with
a test, and no secrets in the code."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import subprocess
import tempfile
import unittest

import guard_repo as G

TEST = "import unittest\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertEqual(1, 1)\n\n    def test_b(self):\n        self.assertTrue(True)\n"


class Repo(unittest.TestCase):
    def setUp(self):
        self.root, self.saved = tempfile.mkdtemp(), G.ROOT
        G.ROOT = self.root
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.write("app/thing.py", "x = 1\n")
        self.write("tests/test_thing.py", TEST)
        self.commit("start")
        self.git("checkout", "-q", "-b", "work")

    def tearDown(self):
        G.ROOT = self.saved

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def write(self, path, text):
        os.makedirs(os.path.dirname(os.path.join(self.root, path)), exist_ok=True)
        with open(os.path.join(self.root, path), "w") as f:
            f.write(text)

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)

    def problems(self, title=""):
        return " ".join(G.check("main", title))

    def test_a_clean_change_passes(self):
        self.write("app/thing.py", "x = 2\n")
        self.commit("Make x bigger")
        self.assertEqual(self.problems(), "")

    def test_deleting_a_test_file_fails_unless_it_is_retired_in_the_open(self):
        os.remove(os.path.join(self.root, "tests/test_thing.py"))
        self.commit("tidy")
        self.assertIn("was deleted", self.problems())
        self.write("tests/RETIRED.md", "- tests/test_thing.py: the feature it tested was removed\n")
        self.commit("retire")
        self.assertEqual(self.problems(), "")

    def test_removing_tests_or_asserts_fails(self):
        self.write("tests/test_thing.py", TEST.split("    def test_b")[0])
        self.commit("smaller")
        self.assertIn("lost tests (2 -> 1)", self.problems())

    def test_weakening_a_check_fails(self):
        self.write("tests/test_thing.py", TEST.replace("        self.assertTrue(True)\n", "        pass\n"))
        self.commit("weaker")
        self.assertIn("lost checks", self.problems())

    def test_a_new_unconditional_skip_fails_and_a_machine_skip_is_fine(self):
        self.write("tests/test_thing.py", TEST.replace("    def test_b", "    @unittest.skip('flaky')\n    def test_b"))  # guard: allowed (the input of this test)
        self.commit("skip")
        self.assertIn("a new skip", self.problems())
        self.write("tests/test_thing.py", TEST.replace("    def test_b", "    @unittest.skipUnless(os.name == 'nt', 'Windows only')\n    def test_b"))
        self.commit("machine skip")
        self.assertEqual(self.problems(), "")

    def test_a_fix_needs_a_test(self):
        self.write("app/thing.py", "x = 3\n")
        self.commit("Fix the crash when x is empty")
        self.assertIn("adds or changes no test", self.problems())
        self.write("tests/test_empty.py", "import unittest\n\nclass E(unittest.TestCase):\n    def test_empty(self):\n        self.assertEqual(3, 3)\n")
        self.commit("the test")
        self.assertEqual(self.problems(), "")

    def test_the_title_counts_too(self):
        self.write("app/thing.py", "x = 4\n")
        self.commit("change x")
        self.assertIn("adds or changes no test", self.problems("Fix the login loop"))

    def test_a_secret_fails(self):
        self.write("app/thing.py", "TOKEN = 'ghp_" + "a" * 36 + "'\n")
        self.commit("add token")
        self.assertIn("looks like a secret", self.problems())


if __name__ == "__main__":
    unittest.main()
