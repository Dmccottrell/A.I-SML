import json
import os
import random
import tempfile
import unittest

from quiz.bank import load_questions
from quiz.session import QuizSession

QS = [{"q": f"Q{i}", "choices": ["a", "b", "c"], "answer": i % 3, "topic": "maths" if i % 2 else "art"} for i in range(1, 7)]


def save(data):
    path = os.path.join(tempfile.mkdtemp(), "q.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


class Quiz(unittest.TestCase):
    def test_load_and_validate(self):
        self.assertEqual(load_questions(save(QS)), QS)
        bad = [dict(QS[0]), dict(QS[1], answer=5)]
        with self.assertRaises(ValueError) as e:
            load_questions(save(bad))
        self.assertIn("2", str(e.exception))
        with self.assertRaises(ValueError):
            load_questions(save([{"q": "x", "choices": ["only"], "answer": 0, "topic": "t"}]))
        with self.assertRaises(ValueError):
            load_questions(save([{"q": "x", "choices": ["a", "b"], "topic": "t"}]))

    def test_order_and_count(self):
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
        s = QuizSession(QS, seed=1)
        asked = []
        while not s.finished:
            q = s.current()
            asked.append(q)
            right = q["topic"] == "maths"
            self.assertEqual(s.answer(q["answer"] if right else (q["answer"] + 1) % 3), right)
        r = s.results()
        self.assertEqual((r["score"], r["total"], r["percent"]), (3, 6, 50.0))
        self.assertEqual(r["by_topic"], {"maths": [3, 3], "art": [0, 3]})
        self.assertEqual(r["missed"], [q["q"] for q in asked if q["topic"] == "art"])


if __name__ == "__main__":
    unittest.main()
