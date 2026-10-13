"""The verification report at the end of a VryxCode turn (coding/code_report.py)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import code_report as R


def step(tool, preview, result=""):
    out = [{"kind": "step", "tool": tool, "preview": preview}]
    if result:
        out.append({"kind": "result", "text": result})
    return out


def turn(*steps_, finished=True):
    ev = [{"kind": "start", "task": "make it"}]
    for s in steps_:
        ev += s
    return ev, {"finished": finished}


def build(pair):
    return R.build_report(pair[0], end=pair[1])


WRITE = step("write_file", "write app.py (12 lines)\n  + x = 1", "wrote app.py · checked ✓")
EDIT = step("edit_file", "edit app.py\n  - x = 1\n  + x = 2\n  + y = 3", "edited app.py · checked ✓")
PASS = step("run", 'run {"command": "python -m unittest"}', "exit code 0\nRan 3 tests in 0.01s\n\nOK")
FAIL = step("run", 'run {"command": "python -m unittest"}', "exit code 1\nRan 3 tests in 0.01s\n\nFAILED (failures=1)")


class Report(unittest.TestCase):
    def test_verified_when_tests_pass_after_the_last_change(self):
        r = build(turn(WRITE, EDIT, PASS))
        self.assertEqual(r["verdict"], "verified")
        f = r["files"][0]
        self.assertEqual((f["path"], f["edits"], f["added"], f["removed"], f["checked"]), ("app.py", 2, 14, 1, True))
        self.assertEqual(r["tests"][0]["line"], "3 tests, all passed")

    def test_a_change_after_the_last_pass_is_not_verified(self):
        r = build(turn(WRITE, PASS, EDIT))
        self.assertEqual(r["verdict"], "checked")
        self.assertTrue(any("Code changed after the last passing test run" in t for t in r["look_at"]))

    def test_a_failing_run_is_reported(self):
        r = build(turn(WRITE, FAIL))
        self.assertEqual(r["verdict"], "checked")
        self.assertFalse(r["tests"][0]["passed"])
        self.assertTrue(any("last test run failed" in t for t in r["look_at"]))

    def test_no_tests_and_no_check_is_not_verified(self):
        r = build(turn(step("write_file", "write notes.txt (2 lines)\n  + hi", "wrote notes.txt")))
        self.assertEqual(r["verdict"], "not_verified")
        self.assertTrue(any("No tests were run" in t for t in r["look_at"]))

    def test_errors_failed_commands_and_unfinished_work_are_listed(self):
        bad = step("edit_file", "edit app.py\n  - a\n  + b", "error: could not find the text")
        cmd = step("run", 'run {"command": "make"}', "exit code 2\nno rule")
        r = build(turn(WRITE, bad, cmd, finished=False))
        self.assertEqual(len(r["problems"]), 1)
        self.assertEqual(r["failed_commands"][0]["exit"], 2)
        self.assertTrue(any("did not say it was finished" in t for t in r["look_at"]))

    def test_web_pages_point_at_the_preview(self):
        r = build(turn(step("write_file", "write index.html (3 lines)\n  + <p>", "wrote index.html · checked ✓")))
        self.assertTrue(any("Preview" in t for t in r["look_at"]))

    def test_a_plain_answer_has_no_report_and_only_the_latest_turn_counts(self):
        self.assertIsNone(R.build_report([{"kind": "start", "task": "hi"}], end={"finished": False, "said": True}))
        ev = turn(WRITE, PASS)[0] + [{"kind": "end", "finished": True}, {"kind": "user", "text": "now another thing"}] + step("run", 'run {"command": "ls"}', "exit code 0\nx")
        r = R.build_report(ev, end={"finished": True})
        self.assertEqual(r["files"], [])
        self.assertEqual(r["verdict"], "no_changes")


if __name__ == "__main__":
    unittest.main()


class Compaction(unittest.TestCase):
    """A long conversation folds its old steps into a short list; the session says so (it used to be silent) and the report still sees every step."""

    def test_the_session_notes_when_old_steps_are_folded(self):
        import tempfile, shutil
        import code_sessions
        import vryxcode
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        replies = [vryxcode.harness_call("write_file", path=f"f{i}.py", content="x = %d\n" % i) for i in range(10)] + [vryxcode.harness_call("finish", summary="done")]
        s = code_sessions.Session("s1", "owner", "demo", "write ten files", "solstice-2", d, auto_edits=True)
        s.generate = vryxcode.ScriptedChat(replies)
        s.run(s.generate, 14, 120)                                                    # a tiny memory (120 tokens) so folding must happen
        kinds = [e["kind"] for e in s.events]
        self.assertIn("compacted", kinds)
        self.assertLess(kinds.index("compacted"), kinds.index("end"))
        report = s.events[-1].get("report")
        self.assertEqual(len(report["files"]), 10)                                    # the report is built from the events, so folding loses nothing from it
