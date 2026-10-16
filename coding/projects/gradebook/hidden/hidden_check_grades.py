import os
import tempfile
import unittest

from grades.book import Gradebook, letter
from grades.export import to_csv


class Grades(unittest.TestCase):
    def book(self):
        b = Gradebook({"homework": 40, "exams": 60})
        b.add_score("Zed", "homework", 8, 10)
        b.add_score("Zed", "homework", 10, 10)
        b.add_score("Zed", "exams", 45, 50)
        b.add_score("Amy", "exams", 35, 50)
        return b

    def test_letter(self):
        self.assertEqual([letter(p) for p in (95, 90, 89.99, 80, 75, 60, 59.9)], ["A", "A", "B", "B", "C", "D", "F"])

    def test_weights_and_errors(self):
        with self.assertRaises(ValueError):
            Gradebook({"a": 50, "b": 40})
        b = self.book()
        for args in (("x", "quiz", 1, 2), ("x", "exams", 3, 2), ("x", "exams", 1, 0), ("x", "exams", -1, 5)):
            with self.assertRaises(ValueError):
                b.add_score(*args)
        with self.assertRaises(KeyError):
            b.average("Nobody")

    def test_average_and_rank(self):
        b = self.book()
        self.assertEqual(b.average("Zed"), 90.0)          # homework 90% * 0.4 + exams 90% * 0.6
        self.assertEqual(b.average("Amy"), 70.0)          # only exams: scaled up
        b.add_score("Bea", "homework", 7, 10)
        self.assertEqual(b.students(), ["Amy", "Bea", "Zed"])
        self.assertEqual(b.ranking(), [("Zed", 90.0), ("Amy", 70.0), ("Bea", 70.0)])

    def test_rounding(self):
        b = Gradebook({"a": 100})
        b.add_score("x", "a", 2, 3)
        self.assertEqual(b.average("x"), 66.67)

    def test_csv(self):
        path = os.path.join(tempfile.mkdtemp(), "g.csv")
        b = self.book()
        to_csv(b, path)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read().strip().splitlines(), ["student,average,letter", "Amy,70.00,C", "Zed,90.00,A"])


if __name__ == "__main__":
    unittest.main()
