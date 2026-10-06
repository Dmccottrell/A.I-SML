"""Tests for vryx_swe.py (patches for SWE-bench-style issues) and bench_exercises.py (Aider-style exercises), with scripted stand-in models."""
import json
import os
import subprocess
import tempfile
import unittest

import bench_exercises as X
import vryx_swe as S
import vryxcode as V
from vryxcode import harness_call


def git(args, cwd):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t"] + args, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class Swe(unittest.TestCase):
    def setUp(self):
        self.repos = tempfile.mkdtemp()
        self.src = os.path.join(self.repos, "owner__proj")
        os.makedirs(self.src)
        git(["init", "-q"], self.src)
        with open(os.path.join(self.src, "calc.py"), "w") as f:
            f.write("def add(a, b):\n    return a - b\n")
        git(["add", "-A"], self.src)
        git(["commit", "-q", "-m", "base"], self.src)
        self.base = git(["rev-parse", "HEAD"], self.src)
        with open(os.path.join(self.src, "calc.py"), "a") as f:
            f.write("\n# a later change that must not be seen\n")
        git(["commit", "-qam", "later"], self.src)
        self.inst = {"instance_id": "owner__proj-1", "repo": "owner/proj", "base_commit": self.base, "problem_statement": "add(1, 2) returns -1"}

    def test_the_agent_fixes_the_bug_and_the_patch_applies(self):
        fix = V.ScriptedChat([harness_call("edit_file", path="calc.py", old="return a - b", new="return a + b"),
                              harness_call("write_file", path="notes.txt", content="hello\n"),
                              harness_call("finish", summary="fixed add")])
        r = S.solve(self.inst, fix, self.repos, out=lambda *_: None)
        self.assertTrue(r["finished"])
        self.assertIn("+    return a + b", r["model_patch"])
        self.assertIn("notes.txt", r["model_patch"])                              # new files are in the patch
        self.assertNotIn("a later change", r["model_patch"])                      # it worked on the base commit
        # the original checkout is untouched
        self.assertIn("return a - b", open(os.path.join(self.src, "calc.py")).read())
        # the patch applies to a fresh copy of the base commit and fixes it
        work, fresh = S.prepare_repo(self.inst, self.repos)
        try:
            with open(os.path.join(work, "p.diff"), "w") as f:
                f.write(r["model_patch"])
            git(["apply", os.path.join(work, "p.diff")], fresh)
            self.assertIn("return a + b", open(os.path.join(fresh, "calc.py")).read())
        finally:
            import shutil
            shutil.rmtree(work, ignore_errors=True)

    def test_the_task_text_holds_the_issue_and_not_the_tests(self):
        model = V.ScriptedChat([harness_call("finish", summary="nothing")])
        S.solve(self.inst, model, self.repos, out=lambda *_: None)
        first = model.seen[0][-1]["content"]
        self.assertIn("add(1, 2) returns -1", first)
        self.assertIn("Do not edit tests", first)

    def test_no_change_means_an_empty_patch(self):
        r = S.solve(self.inst, V.ScriptedChat([harness_call("finish", summary="gave up")]), self.repos, out=lambda *_: None)
        self.assertEqual(r["model_patch"], "")

    def test_predictions_use_the_swe_bench_format(self):
        row = S.predictions_row({"instance_id": "x-1", "model_patch": "diff"}, "solstice-2")
        self.assertEqual(row, {"instance_id": "x-1", "model_name_or_path": "solstice-2", "model_patch": "diff"})

    def test_a_missing_checkout_is_a_clear_error(self):
        with self.assertRaises(FileNotFoundError) as c:
            S.prepare_repo({**self.inst, "repo": "other/thing"}, self.repos)
        self.assertIn("--clone", str(c.exception))

    def test_only_equinox_and_above(self):
        path = os.path.join(self.repos, "i.jsonl")
        open(path, "w").write(json.dumps(self.inst) + "\n")
        with self.assertRaises(SystemExit):
            S.main(["--instances", path, "--model", "flare-2.5"])


def make_exercise(root, slug, module, stub, test):
    d = os.path.join(root, slug)
    os.makedirs(os.path.join(d, ".docs"))
    os.makedirs(os.path.join(d, ".meta"))
    open(os.path.join(d, ".docs", "instructions.md"), "w").write(f"# {slug}\nSee the tests.\n")
    open(os.path.join(d, f"{module}.py"), "w").write(stub)
    open(os.path.join(d, f"{module}_test.py"), "w").write(test)
    open(os.path.join(d, ".meta", "example.py"), "w").write("SECRET EXAMPLE SOLUTION\n")
    json.dump({"files": {"solution": [f"{module}.py"], "test": [f"{module}_test.py"], "example": [".meta/example.py"]}}, open(os.path.join(d, ".meta", "config.json"), "w"))


HELLO_TEST = "import unittest\nfrom a_hello import hello\n\n\nclass T(unittest.TestCase):\n    def test_it(self):\n        self.assertEqual(hello(), 'Hello, World!')\n\n\nif __name__ == '__main__':\n    unittest.main()\n"
ADD_TEST = "import unittest\nfrom b_add import add\n\n\nclass T(unittest.TestCase):\n    def test_it(self):\n        self.assertEqual(add(2, 3), 5)\n\n\nif __name__ == '__main__':\n    unittest.main()\n"
NOTHING_TEST = "import unittest\nfrom c_nothing import f\n\n\nclass T(unittest.TestCase):\n    def test_it(self):\n        self.assertEqual(f(), 1)\n"


class Exercises(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        make_exercise(self.root, "a-hello", "a_hello", "def hello():\n    pass\n", HELLO_TEST)
        make_exercise(self.root, "b-add", "b_add", "def add(a, b):\n    pass\n", ADD_TEST)
        make_exercise(self.root, "c-nothing", "c_nothing", "def f():\n    return 0\n", NOTHING_TEST)
        os.makedirs(os.path.join(self.root, "not-an-exercise"))

    def test_exercises_are_found_and_the_example_solution_is_hidden(self):
        items = X.find_exercises(self.root)
        self.assertEqual([ex["slug"] for _, ex in items], ["a-hello", "b-add", "c-nothing"])
        work, folder = X.stage(*items[0])
        try:
            self.assertFalse(os.path.exists(os.path.join(folder, ".meta")))
            self.assertTrue(os.path.exists(os.path.join(folder, "a_hello_test.py")))
        finally:
            import shutil
            shutil.rmtree(work, ignore_errors=True)

    def test_two_tries_and_the_summary(self):
        model = V.ScriptedChat([
            harness_call("write_file", path="a_hello.py", content="def hello():\n    return 'Hello, World!'\n"), harness_call("finish", summary="done"),
            harness_call("write_file", path="b_add.py", content="def add(a, b):\n    return a * b\n"), harness_call("finish", summary="done"),     # wrong
            harness_call("write_file", path="b_add.py", content="def add(a, b):\n    return a + b\n"), harness_call("finish", summary="done"),     # fixed on try 2
            harness_call("finish", summary="idk"), harness_call("finish", summary="idk")])                                                          # does nothing twice
        results = [X.run_exercise(path, ex, model) for path, ex in X.find_exercises(self.root)]
        self.assertEqual([(r["slug"], r["passed_first"], r["passed"], r["attempts"]) for r in results],
                         [("a-hello", True, True, 1), ("b-add", False, True, 2), ("c-nothing", False, False, 2)])
        s = X.summarize(results)
        self.assertEqual((s["exercises"], s["passed_first_try"], s["passed_after_second_try"]), (3, 1, 2))
        self.assertEqual((s["pct_first"], s["pct_after_second"]), (33.3, 66.7))
        self.assertEqual(s["attempts_with_no_change"], 2)                          # the model that wrote nothing is visible in the report
        retry = [m for m in model.seen if "tests still fail" in m[-1]["content"]]
        self.assertTrue(retry)                                                    # the second try saw the failing output
        self.assertIn("AssertionError", retry[0][-1]["content"])

    def test_a_folder_without_exercises_and_the_gate(self):
        with self.assertRaises(SystemExit):
            X.main(["--exercises", tempfile.mkdtemp(), "--model", "equinox-2", "--llama", "http://127.0.0.1:9"])
        with self.assertRaises(SystemExit):
            X.main(["--exercises", self.root, "--model", "flare-2.5"])


if __name__ == "__main__":
    unittest.main()
