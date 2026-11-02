# Hidden checks for the "quiz_engine" coding exercise. The agent never sees this file; it is run afterwards to decide
# whether the agent's quiz/ package really works (loading questions, ordering, scoring).
import json
import os
import random
import tempfile
import unittest

from quiz.bank import load_questions
from quiz.session import QuizSession

# Six sample questions Q1..Q6, each with 3 choices; the right answer rotates (i % 3) and the topic alternates maths/art.
QS = [{"q": f"Q{i}", "choices": ["a", "b", "c"], "answer": i % 3, "topic": "maths" if i % 2 else "art"} for i in range(1, 7)]


def save(data):
    """Write data as JSON to a new file in a fresh temporary folder and return the file's path."""
    path = os.path.join(tempfile.mkdtemp(), "q.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


class Quiz(unittest.TestCase):
    """Checks for load_questions and QuizSession."""

    def test_load_and_validate(self):
        """Proves good data loads unchanged, and each kind of bad question raises ValueError (one message names question 2)."""
        self.assertEqual(load_questions(save(QS)), QS)
        # The second question has answer 5, but it only has 3 choices.
        bad = [dict(QS[0]), dict(QS[1], answer=5)]
        with self.assertRaises(ValueError) as e:
            load_questions(save(bad))
        self.assertIn("2", str(e.exception))
        # Only one choice: not allowed.
        with self.assertRaises(ValueError):
            load_questions(save([{"q": "x", "choices": ["only"], "answer": 0, "topic": "t"}]))
        # No "answer" key at all: not allowed.
        with self.assertRaises(ValueError):
            load_questions(save([{"q": "x", "choices": ["a", "b"], "topic": "t"}]))

    def test_order_and_count(self):
        """Proves the shuffle is seeded (same as Random(7).shuffle), count limits the quiz to 4 questions, and answering after the end raises."""
        expect = list(QS)
        random.Random(7).shuffle(expect)
        s = QuizSession(QS, seed=7, count=4)
        seen = []
        while not s.finished:
            seen.append(s.current()["q"])
            s.answer(0)
        self.assertEqual(seen, [q["q"] for q in expect[:4]])
        self.assertIsNone(s.current())
        with self.assertRaises(RuntimeError):
            s.answer(0)

    def test_results(self):
        """Proves scoring: answer maths questions right and art questions wrong, then check score, percent, per-topic counts and missed list."""
        s = QuizSession(QS, seed=1)
        asked = []
        while not s.finished:
            q = s.current()
            asked.append(q)
            right = q["topic"] == "maths"
            # For art questions send a deliberately wrong choice ((answer + 1) % 3); answer() must report right/wrong correctly.
            self.assertEqual(s.answer(q["answer"] if right else (q["answer"] + 1) % 3), right)
        r = s.results()
        self.assertEqual((r["score"], r["total"], r["percent"]), (3, 6, 50.0))
        self.assertEqual(r["by_topic"], {"maths": [3, 3], "art": [0, 3]})
        # Missed questions are listed in the order they were asked.
        self.assertEqual(r["missed"], [q["q"] for q in asked if q["topic"] == "art"])


if __name__ == "__main__":
    unittest.main()
