"""Tests for effort_router.py: Auto decides Quick, Balanced or Deep from the message."""
import unittest

from effort_router import choose_effort as pick

ALL = ("quick", "balanced", "deep")


class Router(unittest.TestCase):
    def test_greetings_and_short_questions_are_quick(self):
        for t in ("hi", "Hello!", "thanks", "ok", "good morning", "What's up?", "capital of France?", "what is 5?"):
            self.assertEqual(pick(t)[0], "quick", t)

    def test_simple_lookups_are_quick(self):
        self.assertEqual(pick("What is the capital of Illinois")[0], "quick")
        self.assertEqual(pick("Who was the first president of the United States")[0], "quick")

    def test_normal_questions_are_balanced(self):
        for t in ("Can you give me three tips for studying for a science test this week",
                  "Write a friendly note to a parent about this week",
                  "Summarize why the sky looks blue during the day for my class"):
            self.assertEqual(pick(t)[0], "balanced", t)

    def test_hard_things_are_deep(self):
        for t in ("Explain step by step how to solve 3x + 7 = 22",
                  "Why does this fail?\n```python\ndef f(x):\n    return x/0\n```",
                  "Compare renting and buying a house, with the pros and cons of each",
                  "Write an essay about the causes of the French Revolution",
                  "What is the derivative of x^2 + 3x? And the integral? And why does it work?",
                  "word " * 150):
            self.assertEqual(pick(t)[0], "deep", t[:40])

    def test_brief_requests_win_over_wordy_ones(self):
        self.assertEqual(pick("Briefly, what are the main causes of the French Revolution and how did they connect to each other over time")[0], "quick")
        self.assertEqual(pick("tl;dr of how photosynthesis works for my class")[0], "quick")

    def test_code_stays_deep_even_if_brief(self):
        self.assertEqual(pick("briefly, why does this crash? def f(): return 1/0")[0], "deep")

    def test_models_without_deep_are_held_to_balanced(self):
        eff, why = pick("Explain step by step how to solve 3x + 7 = 22", allowed=("quick", "balanced"))
        self.assertEqual(eff, "balanced")
        self.assertIn("no Deep", why)

    def test_low_usage_makes_auto_think_less(self):
        text = "Explain step by step how to solve 3x + 7 = 22"
        self.assertEqual(pick(text, tank_pct=100)[0], "deep")
        self.assertEqual(pick(text, tank_pct=15)[0], "balanced")
        self.assertEqual(pick("Can you give me three tips for studying for a science test", tank_pct=3)[0], "quick")

    def test_always_gives_a_plain_reason_and_a_valid_level(self):
        for t in ("", "   ", "?", "a", "x" * 5000, "Hello there, how are you doing today my friend"):
            eff, why = pick(t)
            self.assertIn(eff, ALL)
            self.assertTrue(why)

    def test_empty_message_does_not_crash(self):
        self.assertEqual(pick("")[0], "quick")
        self.assertEqual(pick(None)[0], "quick")


if __name__ == "__main__":
    unittest.main()


class Temperature(unittest.TestCase):
    def test_exact_things_run_cool(self):
        from effort_router import choose_temperature as t
        for text in ("Reply with only valid JSON with the key name", "Solve 3x + 7 = 22", "List exactly 4 fruits",
                     "Why does this fail? def f(): return 1/0"):
            self.assertEqual(t(text)[0], 0.2, text)

    def test_creative_things_run_warm(self):
        from effort_router import choose_temperature as t
        for text in ("Write me a story about a fox", "Brainstorm names for my dog", "Write a poem about rain"):
            self.assertEqual(t(text)[0], 1.0, text)

    def test_normal_questions_keep_the_models_own_setting(self):
        from effort_router import choose_temperature as t
        self.assertEqual(t("What is the capital of France?")[0], 0.8)
        self.assertEqual(t("What is the capital of France?", base=0.45)[0], 0.45)

    def test_a_small_models_range_is_respected(self):
        from effort_router import choose_temperature as t
        self.assertEqual(t("Write a poem about rain", 0.45, (0.3, 0.6))[0], 0.6)
        self.assertEqual(t("List exactly 3 fruits", 0.45, (0.3, 0.6))[0], 0.3)

    def test_always_a_reason_and_odd_input_is_fine(self):
        from effort_router import choose_temperature as t
        for text in (None, "", "   ", "x" * 3000):
            temp, why = t(text)
            self.assertTrue(0.2 <= temp <= 1.0)
            self.assertTrue(why)
