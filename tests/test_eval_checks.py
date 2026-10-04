"""Tests for eval_checks.py (the test-sheet rules), the new eval/constraints.jsonl, and the chat-bleed guard."""
import json
import unittest

import app_engine as E
from eval_checks import check


class Rules(unittest.TestCase):
    def test_old_rules_still_work(self):
        self.assertTrue(check({"expect": ["paris"]}, "It is Paris."))
        self.assertFalse(check({"expect": ["paris"]}, "London"))
        self.assertFalse(check({"expect": ["springfield"], "not": ["chicago"]}, "Springfield, not Chicago"))
        self.assertTrue(check({"count": 3}, "1. a\n2. b\n3. c"))
        self.assertFalse(check({"count": 3}, "1. a\n2. b"))
        self.assertTrue(check({"sentences": 2}, "One. Two."))

    def test_word_limits(self):
        self.assertTrue(check({"max_words": 5}, "Blue sky, white clouds."))
        self.assertFalse(check({"max_words": 3}, "Blue sky, white clouds."))
        self.assertFalse(check({"max_words": 3}, ""))              # an empty reply is not "short", it's nothing
        self.assertTrue(check({"min_words": 3}, "one two three"))

    def test_forbidden_letter(self):
        self.assertTrue(check({"no_letter": "e"}, "A dog runs far."))
        self.assertFalse(check({"no_letter": "e"}, "The dog runs."))
        self.assertFalse(check({"no_letter": "e"}, ""))

    def test_form(self):
        self.assertTrue(check({"all_caps": True}, "THE SKY IS BLUE."))
        self.assertFalse(check({"all_caps": True}, "The sky is BLUE."))
        self.assertTrue(check({"lowercase": True}, "paris, of course"))
        self.assertTrue(check({"starts_with": "yes"}, "Yes, it is."))
        self.assertTrue(check({"ends_with": "goodbye"}, "Nice day. Goodbye"))
        self.assertFalse(check({"starts_with": "yes"}, "No."))

    def test_json(self):
        t = {"json": True, "json_keys": ["name", "age"]}
        self.assertTrue(check(t, '{"name": "Sam", "age": 10}'))
        self.assertTrue(check(t, '```json\n{"name": "Sam", "age": 10}\n```'))
        self.assertFalse(check(t, '{"name": "Sam"}'))
        self.assertFalse(check(t, "Sure! Here is the JSON: {...}"))

    def test_bleed_always_fails(self):
        self.assertFalse(check({"expect": ["paris"]}, "Paris.<|user|>and Spain?"))
        self.assertFalse(check({}, "Hello <|assistant|>"))


class Sheet(unittest.TestCase):
    def test_constraints_sheet_is_well_formed(self):
        with open("eval/constraints.jsonl", encoding="utf-8") as f:
            tests = [json.loads(l) for l in f if l.strip()]
        self.assertGreaterEqual(len(tests), 25)
        cats = {t["category"] for t in tests}
        self.assertTrue({"length", "lists", "form", "avoid", "structured", "multi_turn"} <= cats)
        for t in tests:
            self.assertTrue(t["prompt"])
            rules = set(t) - {"category", "prompt", "history"}
            self.assertTrue(rules, t["prompt"])                    # every test checks something
        for t in (x for x in tests if x["category"] == "multi_turn"):
            self.assertGreaterEqual(len(t["history"]), 2)
        for t in tests:
            self.assertFalse(check(t, ""), f"an empty reply must not pass: {t['prompt']}")


class Bleed(unittest.TestCase):
    def run_guard(self, pieces):
        g = E.Guard(iter(pieces))
        shown = "".join(g)
        return shown, g.text, g.reason

    def test_cuts_at_the_next_turn(self):
        shown, text, reason = self.run_guard(["Paris is the capital. ", "<|user|>", "And Spain?"])
        self.assertEqual((shown.strip(), text.strip(), reason), ("Paris is the capital.", "Paris is the capital.", "bleed"))

    def test_marker_split_across_pieces_is_not_shown(self):
        shown, text, reason = self.run_guard(["Yes. <|us", "er|>more"])
        self.assertEqual(reason, "bleed")
        self.assertNotIn("<|", text)
        self.assertEqual(text.strip(), "Yes.")

    def test_normal_reply_is_untouched(self):
        shown, text, reason = self.run_guard(["Hello ", "there, ", "friend."])
        self.assertEqual((shown, text, reason), ("Hello there, friend.", "Hello there, friend.", "done"))

    def test_cut_bleed_helper(self):
        self.assertEqual(E.cut_bleed("ok<|endoftext|>junk"), ("ok", True))
        self.assertEqual(E.cut_bleed("fine"), ("fine", False))


if __name__ == "__main__":
    unittest.main()
