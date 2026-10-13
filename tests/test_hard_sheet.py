"""eval/hard.jsonl: the harder sheet is self-consistent (every reference answer passes its own check; no expected word is already in the question)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import unittest

from eval_checks import check

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "eval")


def rows():
    with open(os.path.join(HERE, "hard.jsonl"), encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


class Hard(unittest.TestCase):
    def test_every_reference_answer_passes_its_own_check(self):
        for t in rows():
            self.assertTrue(check(t, t["gold"]), t["prompt"][:70])

    def test_no_expected_word_is_already_in_the_question_and_questions_are_unique(self):
        prompts = [t["prompt"] for t in rows()]
        self.assertEqual(len(prompts), len(set(prompts)))
        for t in rows():
            for k in t.get("expect", []):
                short = t.get("max_words", 99) <= 5                      # "reply with one name" style: the answer is a name from the question, and a long reply fails the check anyway
                if len(k) > 2 and t["category"] not in ("constraints", "comprehension") and not short:
                    self.assertNotIn(k.lower(), t["prompt"].lower(), (k, t["prompt"][:60]))

    def test_wrong_and_empty_answers_fail(self):
        by = {t["prompt"][:30]: t for t in rows()}
        shirt = next(t for t in rows() if t["prompt"].startswith("A shirt"))
        for wrong in ("$30", "I don't know", "", "$36.30"):
            self.assertFalse(check(shirt, wrong), wrong)
        dan = next(t for t in rows() if "shortest" in t["prompt"])
        self.assertFalse(check(dan, "Carol"))
        self.assertTrue(check(dan, "Dan"))
        letter = next(t for t in rows() if "letter e" in t["prompt"])
        self.assertFalse(check(letter, "The dog ran home."))
        self.assertTrue(by)

    def test_it_has_the_right_shape_for_the_bake_off(self):
        from collections import Counter
        cats = Counter(t["category"] for t in rows())
        self.assertEqual(sum(cats.values()), 52)
        self.assertEqual(set(cats), {"maths_hard", "reasoning", "code_reasoning", "constraints", "comprehension", "knowledge_hard", "honesty_hard"})
        import quality_check
        self.assertEqual(len(quality_check.load_sheet(os.path.join(HERE, "hard.jsonl"))), 52)


if __name__ == "__main__":
    unittest.main()
