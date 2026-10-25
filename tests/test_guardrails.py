"""VryxCode's guardrails (flag vryxcode_guardrails, coding/guardrails.py): no going in circles, progress or stop, smaller fixes, the tests locked
while fixing, a cap on fixes, and reviews that grade problems and can end on Approved."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import tempfile
import unittest

import code_review as R
import flags
import guardrails as G
import harness


def call(name, args):
    import json
    return "<|tool_call|>" + json.dumps({"name": name, "args": args}) + "<|end_tool_call|>"


def project(files):
    d = tempfile.mkdtemp()
    for p, text in files.items():
        os.makedirs(os.path.dirname(os.path.join(d, p)) or d, exist_ok=True)
        with open(os.path.join(d, p), "w") as f:
            f.write(text)
    return d


class Counting(unittest.TestCase):
    def test_the_flag_starts_with_the_owner_and_admins(self):
        self.assertEqual(flags.BY_ID["vryxcode_guardrails"]["default"], "admins")

    def test_failing_tests_are_counted_from_the_output(self):
        self.assertEqual(G.failing_count("exit code 0\nOK"), 0)
        self.assertEqual(G.failing_count("exit code 1\nFAILED (failures=2, errors=1)"), 3)
        self.assertEqual(G.failing_count("exit code 1\n==== 4 failed, 10 passed in 0.3s ===="), 4)
        self.assertEqual(G.failing_count("exit code 1\nTests:       2 failed, 5 passed"), 2)
        self.assertIsNone(G.failing_count("exit code 1\nsomething else went wrong"))

    def test_the_same_files_give_the_same_hash(self):
        d = project({"a.py": "x = 1\n"})
        h = G.state_hash(d)
        with open(os.path.join(d, "a.py"), "w") as f:
            f.write("x = 2\n")
        self.assertNotEqual(G.state_hash(d), h)
        with open(os.path.join(d, "a.py"), "w") as f:
            f.write("x = 1\n")
        self.assertEqual(G.state_hash(d), h)


class Guard(unittest.TestCase):
    def test_going_back_to_an_earlier_state_stops(self):
        d = project({"a.py": "try:\n    x()\nexcept Exception:\n    pass\n"})
        g = G.Guard(d)
        with open(os.path.join(d, "a.py"), "w") as f:
            f.write("x()\n")                          # pass 2 removes the try "for readability"
        g.after_change()
        with open(os.path.join(d, "a.py"), "w") as f:
            f.write("try:\n    x()\nexcept Exception:\n    pass\n")      # pass 3 adds it back "for safety"
        with self.assertRaises(G.Stop) as cm:
            g.after_change()
        self.assertIn("going round in circles", cm.exception.summary)

    def test_tests_that_do_not_get_better_switch_approach_then_stop(self):
        g = G.Guard(project({"a.py": "1\n"}))
        self.assertEqual(g.after_test("exit code 1\nFAILED (failures=2)"), "")      # the first failure starts the fix phase
        g.changed_since_test = True
        self.assertEqual(g.after_test("exit code 1\nFAILED (failures=2)"), "")      # flat once
        g.changed_since_test = True
        self.assertIn("different", g.after_test("exit code 1\nFAILED (failures=3)"))   # flat twice: change approach
        g.changed_since_test = True
        with self.assertRaises(G.Stop) as cm:
            g.after_test("exit code 1\nFAILED (failures=2)")
        self.assertIn("did not get better", cm.exception.summary)

    def test_progress_resets_and_passing_ends_the_fix_phase(self):
        g = G.Guard(project({"a.py": "1\n"}))
        g.after_test("exit code 1\nFAILED (failures=3)")
        for n in (2, 1):
            g.changed_since_test = True
            self.assertEqual(g.after_test(f"exit code 1\nFAILED (failures={n})"), "")
        self.assertEqual(g.after_test("exit code 0\nOK"), "")
        self.assertFalse(g.fixing)

    def test_fixes_get_smaller(self):
        d = project({"app.py": "".join(f"line{i}\n" for i in range(400))})
        g = G.Guard(d)
        big = {"path": "app.py", "old": "x\n" * 40, "new": "y\n" * 40}
        self.assertIsNone(g.before("edit_file", big))                    # not fixing yet: no limit
        g.after_test("exit code 1\nFAILED (failures=1)")
        self.assertIsNone(g.before("edit_file", big))                    # first fixes: up to 150 lines
        self.assertIn("150", g.before("write_file", {"path": "app.py", "content": "new\n" * 400}))
        g.fixes = 2
        self.assertIn("15 lines", g.before("edit_file", big))            # from the third fix: up to 15 lines
        self.assertIsNone(g.before("edit_file", {"path": "app.py", "old": "a\nb", "new": "a\nc"}))
        self.assertIsNone(g.before("write_file", {"path": "new_module.py", "content": "x\n" * 300}))   # a new file is not a fix to old code

    def test_the_tests_are_locked_while_fixing(self):
        d = project({"tests/test_app.py": "assert 1\n", "app.py": "x\n"})
        g = G.Guard(d)
        self.assertIsNone(g.before("edit_file", {"path": "tests/test_app.py", "old": "1", "new": "2"}))   # not fixing: tests may change
        g.after_test("exit code 1\nFAILED (failures=1)")
        self.assertIn("tests decide", g.before("edit_file", {"path": "tests/test_app.py", "old": "1", "new": "True"}))
        self.assertIn("tests decide", g.before("delete_file", {"path": "./tests/test_app.py"}))
        self.assertIsNone(g.before("write_file", {"path": "tests/test_bug.py", "content": "assert 0\n"}))   # a new test that shows the bug is welcome

    def test_five_fixes_that_do_not_work_stop(self):
        g = G.Guard(project({"a.py": "1\n"}))
        g.after_test("exit code 1\nFAILED (failures=5)")
        with self.assertRaises(G.Stop) as cm:
            for n in (4, 3, 2, 1, 1):
                g.changed_since_test = True
                g.after_test(f"exit code 1\nFAILED (failures={n})")
        self.assertIn("5 fixes", cm.exception.summary)


class InTheLoop(unittest.TestCase):
    def run_with(self, replies, guard_on, files):
        it = iter(replies)
        gen = lambda m: next(it)
        gen.guardrails = guard_on
        d = project(files)
        with harness.Sandbox(workspace=d) as box:
            r = harness.run_agent("fix it", gen, box, max_turns=len(replies) + 1, chat_mode=True)
            with open(os.path.join(box.root, "a.py")) as f:
                return r, f.read()

    def test_flip_flopping_is_stopped_only_with_the_flag(self):
        one, two = "x = 1\n", "x = 2\n"
        replies = [call("write_file", {"path": "a.py", "content": two}), call("write_file", {"path": "a.py", "content": one}),
                   call("write_file", {"path": "a.py", "content": two}), call("finish", {"summary": "done"})]
        r, _ = self.run_with(replies, True, {"a.py": one})
        self.assertEqual(r.get("stopped"), "guardrail")
        r, _ = self.run_with(replies, False, {"a.py": one})
        self.assertTrue(r["finished"])

    def test_editing_a_test_to_pass_is_refused_in_the_loop(self):
        replies = [call("run", {"command": "python -m unittest"}),
                   call("edit_file", {"path": "test_a.py", "old": "x == 2", "new": "x == 1"}),
                   "I could not change the test.", ]
        r, _ = self.run_with(replies, True, {"a.py": "x = 1\n", "test_a.py": "import unittest\nfrom a import x\n\nclass T(unittest.TestCase):\n    def test(self):\n        self.assertTrue(x == 2)\n"})
        sent = " ".join(m["content"] for m in r["messages"] if m["role"] == "user")
        self.assertIn("tests decide", sent)


class Reviews(unittest.TestCase):
    def test_the_strict_review_has_the_checklist_severities_and_the_request(self):
        p = R.strict(R.review_prompt("--- a\n+++ b\n+x\n", ["a.py"]), "Return 401 on a bad token")
        for word in ("CRITICAL", "MAJOR", "NITPICK", "APPROVED", "Return 401 on a bad token", "approving is the best outcome"):
            self.assertIn(word, p)
        self.assertNotIn("would you merge this", p)                 # the open-ended rules are gone

    def test_only_critical_and_major_block(self):
        nits = 'Fine.\n```json\n{"status": "CHANGES_NEEDED", "defects": [{"severity": "NITPICK", "problem": "rename x"}]}\n```'
        self.assertEqual(R.verdict(nits)["status"], "APPROVED")
        bad = 'Broken.\n```json\n{"status": "CHANGES_NEEDED", "defects": [{"severity": "MAJOR", "file": "auth.py", "problem": "200 on bad token", "test": "bad token gets 401"}, {"severity": "NITPICK", "problem": "x"}]}\n```'
        v = R.verdict(bad)
        self.assertEqual((v["status"], len(v["blocking"])), ("CHANGES_NEEDED", 1))
        fix = R.fix_request(v["blocking"])
        self.assertIn("first write a small test", fix)
        self.assertIn("passes on the first run, the problem is not real", fix)
        self.assertNotIn("rename x", fix)
        self.assertIsNone(R.verdict("no json here"))


if __name__ == "__main__":
    unittest.main()
