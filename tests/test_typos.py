"""Tests for the messy-typing lessons (typo_lessons.py). Run:  python -m unittest tests.test_typos -v"""
import os
import random
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import typo_lessons as T


class Messy(unittest.TestCase):
    def test_changes_ordinary_text_but_is_deterministic(self):
        text = "What is the capital of Illinois, and why is it famous?"
        a = [T.messy(text, random.Random(i)) for i in range(40)]
        self.assertGreater(sum(x != text for x in a), 30)
        self.assertEqual(T.messy(text, random.Random(5)), T.messy(text, random.Random(5)))

    def test_numbers_code_and_short_text_are_safe(self):
        rng = random.Random(0)
        for i in range(50):
            self.assertIn("3", T.messy("List 3 fruits that are red", rng))
            self.assertIn("`print(12)`", T.messy("Please run `print(12)` for me", rng))
            self.assertEqual(T.messy("```\nx = 1\n```", rng), "```\nx = 1\n```")
            self.assertEqual(T.messy("hi", rng).lower().strip("!?."), "hi")
            self.assertTrue(T.messy("Tell me about the moon", rng).strip())

    def test_slips_stay_close_to_the_original(self):
        rng = random.Random(1)
        for _ in range(200):
            w = T.slip("photosynthesis", rng)
            self.assertLessEqual(abs(len(w) - 14), 1)
            self.assertEqual(w[0], "p")                          # first letter kept, as real typos mostly do


class Copies(unittest.TestCase):
    EX = [{"kind": "general", "messages": [{"role": "user", "content": "How do plants make their own food?"},
                                           {"role": "assistant", "content": "Plants use photosynthesis."}]},
          {"kind": "lookup", "messages": [{"role": "user", "content": "What is the capital of Illinois?",
                                           "notes": [{"title": "Illinois", "text": "Springfield is the capital."}]},
                                          {"role": "assistant", "content": "Springfield (Source: Illinois)."}]},
          {"kind": "memory_save", "messages": [{"role": "user", "content": "My name is Samantha Jones."},
                                               {"role": "assistant", "content": "Nice to meet you!"}]},
          {"kind": "tool_use", "messages": [{"role": "user", "content": "Fix the bug in calc.py please", "tools": True},
                                            {"role": "assistant", "content": "ok", "tools": True}]}]

    def test_only_the_users_words_change(self):
        out = T.typo_copies(self.EX * 30, random.Random(2), share=1.0)
        self.assertGreater(len(out), 40)
        for e in out:
            self.assertEqual(e["kind"], "typo")
            a = e["messages"][-1]
            self.assertIn(a["content"], ("Plants use photosynthesis.", "Springfield (Source: Illinois)."))
        looked = [e for e in out if e["messages"][-1]["content"].startswith("Springfield")]
        self.assertTrue(looked)
        for e in looked:
            self.assertEqual(e["messages"][0]["notes"][0]["title"], "Illinois")     # the notes are untouched

    def test_memory_and_tool_lessons_are_never_copied(self):
        for e in T.typo_copies(self.EX * 50, random.Random(3), share=1.0):
            text = e["messages"][0]["content"]
            self.assertNotIn("Samantha", text)
            self.assertFalse(e["messages"][0].get("tools"))
            self.assertNotIn("calc.py", text)

    def test_the_v3_builder_adds_them(self):
        import make_chat_data_v3 as D
        a = types.SimpleNamespace(general=0, topic_switch=0, unknowable=300, identity=300, small_talk=0, stories=0,
                                  memory=0, web=0, other_ai=0, agent=0, typos=0.5)
        examples = D.build([], [], [], [], None, a)
        self.assertGreater(sum(e["kind"] == "typo" for e in examples), 100)
        a.typos = 0
        self.assertEqual(sum(e["kind"] == "typo" for e in D.build([], [], [], [], None, a)), 0)


if __name__ == "__main__":
    unittest.main()
