"""Tests for stretch_ladder.py (the hands-off long-context ladder). No GPU needed: the commands are faked.
Run:  python -m unittest tests.test_stretch_ladder -v"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import stretch_ladder as L


class FakeRunner:
    """Pretends to run the commands. `fail_gate` / `fail_train`: step names that fail."""

    def __init__(self, fail_gate=(), fail_train=(), crash_gate=()):
        self.calls, self.fail_gate, self.fail_train, self.crash_gate = [], set(fail_gate), set(fail_train), set(crash_gate)

    def __call__(self, cmd):
        kind = "train" if "run_training.py" in cmd[1] else "gate"
        step = cmd[cmd.index("--version") + 1]
        self.calls.append((kind, step))
        if kind == "train" and step in self.fail_train:
            return 1
        if kind == "gate" and step in self.crash_gate:
            return 137
        if kind == "gate" and step in self.fail_gate:
            return 1
        return 0


class Ladder(unittest.TestCase):
    def setUp(self):
        self.state = os.path.join(tempfile.mkdtemp(), "ladder.json")

    def run_it(self, runner, **kw):
        return L.run_ladder(runner=runner, state_path=self.state, say=lambda *a: None, **kw)

    def test_every_rung_is_a_real_version_and_they_climb(self):
        prev = 0
        for step in L.LADDER:
            n = config.VERSIONS[step].model.max_seq_len
            self.assertGreater(n, prev)
            prev = n
        self.assertEqual(prev, 262_144)

    def test_goes_all_the_way_when_everything_passes(self):
        r = FakeRunner()
        st = self.run_it(r)
        self.assertEqual(st["passed"], L.LADDER)
        self.assertIsNone(st["failed"])
        self.assertEqual(len(r.calls), 2 * len(L.LADDER))

    def test_stops_at_the_first_failed_gate_and_trains_nothing_after_it(self):
        r = FakeRunner(fail_gate=["v3-long-64k"])
        st = self.run_it(r)
        self.assertEqual(st["passed"], ["v3-long-8k", "v3-long-16k", "v3-long-32k"])
        self.assertEqual(st["failed"]["step"], "v3-long-64k")
        self.assertNotIn(("train", "v3-long-128k"), r.calls)
        self.assertIn("tests", st["failed"]["why"])
        self.assertIn("v3-long-32k", L.summary(st))
        self.assertIn("32,768", L.summary(st))

    def test_a_training_crash_stops_the_ladder_too(self):
        st = self.run_it(FakeRunner(fail_train=["v3-long-128k"]))
        self.assertEqual(st["passed"][-1], "v3-long-64k")
        self.assertEqual(st["failed"]["step"], "v3-long-128k")
        self.assertIn("memory", st["failed"]["why"])

    def test_a_crashed_test_run_is_not_called_a_failed_test(self):
        st = self.run_it(FakeRunner(crash_gate=["v3-long-8k"]))
        self.assertIn("crashed", st["failed"]["why"])
        self.assertEqual(st["passed"], [])

    def test_resumes_where_it_stopped(self):
        self.run_it(FakeRunner(fail_gate=["v3-long-64k"]))
        r = FakeRunner()
        st = self.run_it(r)                                   # rerun (say, after more long data was added)
        self.assertEqual(r.calls[0], ("train", "v3-long-64k"))
        self.assertEqual(st["passed"], L.LADDER)

    def test_stop_after_and_existing_weights(self):
        r = FakeRunner()
        st = self.run_it(r, stop_after="v3-long-16k", final_exists=lambda s: s == "v3-long-8k")
        self.assertEqual(st["passed"], ["v3-long-8k", "v3-long-16k"])
        self.assertNotIn(("train", "v3-long-8k"), r.calls)    # already trained: only its gate ran
        self.assertIn(("gate", "v3-long-8k"), r.calls)

    def test_summary_when_nothing_passed(self):
        self.assertIn("2,048", L.summary({"passed": [], "failed": None}))


if __name__ == "__main__":
    unittest.main()
