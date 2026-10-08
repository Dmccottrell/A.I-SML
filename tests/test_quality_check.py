"""The quality check: the sheet is well formed, the run goes through the real app (private chats), and comparing two runs finds what got worse."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import tempfile
import unittest
from unittest import mock

import app_engine as E
import quality_check as Q
from tests.test_app_server import Base


class Sheet(unittest.TestCase):
    def test_the_sheet_is_well_formed_and_covers_what_matters(self):
        tests = Q.load_sheet(Q.SHEET)
        self.assertGreaterEqual(len(tests), 35)
        self.assertEqual(len({t["prompt"] for t in tests}), len(tests))                          # no duplicates: results are matched by prompt
        self.assertTrue({"facts", "maths", "format", "honesty", "identity", "code", "safety", "rewrite", "manners"} <= {t["category"] for t in tests})
        known = {"category", "prompt", "expect", "not", "count", "sentences", "max_words", "min_words", "no_letter", "starts_with", "ends_with", "all_caps", "lowercase", "json", "json_keys"}
        for t in tests:
            self.assertLessEqual(set(t), known, t["prompt"])
            self.assertTrue(len(t) > 2, t["prompt"])                                               # every test checks something

    def test_compare_finds_what_got_worse_and_what_got_better(self):
        old = [{"prompt": "a", "ok": True}, {"prompt": "b", "ok": False}, {"prompt": "c", "ok": True}]
        new = [{"prompt": "a", "ok": False, "reply": "x"}, {"prompt": "b", "ok": True, "reply": "y"}, {"prompt": "c", "ok": True, "reply": "z"}, {"prompt": "d", "ok": False, "reply": "w"}]
        reg, imp = Q.compare(old, new)
        self.assertEqual(([r["prompt"] for r in reg], [r["prompt"] for r in imp]), (["a"], ["b"]))     # a brand-new failing prompt is not a regression

    def test_totals_by_category(self):
        s = Q.totals([{"category": "x", "ok": True}, {"category": "x", "ok": False}, {"category": "y", "ok": True}])
        self.assertEqual((s["passed"], s["total"], s["by_category"]["x"]), (2, 3, [1, 2]))


class Run(Base):
    data_dir = True

    def setUp(self):
        replies = {"What is the capital of France?": "The capital of France is Paris.", "Reply with only the word YES.": "Probably not, but who knows!"}
        self.factory = lambda model, question: E.FakeBackend(replies.get(question, "Hello there."))
        super().setUp()

    def test_a_run_goes_through_private_chats_scores_each_answer_and_saves_nothing_in_the_app(self):
        tests = [{"category": "facts", "prompt": "What is the capital of France?", "expect": ["paris"]},
                 {"category": "format", "prompt": "Reply with only the word YES.", "expect": ["yes"], "max_words": 2}]
        client = Q.AppClient(f"http://127.0.0.1:{self.port}", self.sam_key)
        results = Q.run(tests, lambda p: client.ask("flare-2", p))
        self.assertEqual([r["ok"] for r in results], [True, False])
        self.assertIn("Paris", results[0]["reply"])
        self.assertEqual(self.sam.call("GET", "/api/state")[1]["chats"], [])                          # private chats: nothing was saved

    def test_main_saves_the_run_and_compares_with_the_last_one(self):
        with tempfile.TemporaryDirectory() as d:
            sheet = os.path.join(d, "sheet.jsonl")
            with open(sheet, "w") as f:
                f.write(json.dumps({"category": "facts", "prompt": "What is the capital of France?", "expect": ["paris"]}) + "\n")
            argv = ["--server", f"http://127.0.0.1:{self.port}", "--model", "flare-2", "--sheet", sheet, "--out-dir", os.path.join(d, "q")]
            with mock.patch.dict(os.environ, {"EMVRYX_KEY": self.sam_key}):
                self.assertEqual(Q.main(argv + ["--label", "before"]), 0)
                replies_now = {"What is the capital of France?": "Lyon, I think."}
                self.state.backend_factory = lambda model, question: E.FakeBackend(replies_now.get(question, "x"))
                self.assertEqual(Q.main(argv + ["--label", "after", "--strict"]), 1)                   # it got worse and --strict says so
            saved = json.load(open(os.path.join(d, "q", "flare-2-after.json")))
            self.assertEqual(saved["summary"]["passed"], 0)

    def test_a_missing_key_is_explained(self):
        with mock.patch.dict(os.environ, {"EMVRYX_KEY": ""}), self.assertRaises(SystemExit) as e:
            Q.main(["--model", "flare-2"])
        self.assertIn("EMVRYX_KEY", str(e.exception))


if __name__ == "__main__":
    unittest.main()
