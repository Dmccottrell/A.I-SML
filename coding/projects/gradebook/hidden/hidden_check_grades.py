# Hidden checks for the "gradebook" coding exercise. The agent never sees this file; it is run afterwards to decide
# whether the agent's grades/ package really works. It uses Python's built-in unittest tools.
import os
import tempfile
import unittest

from grades.book import Gradebook, letter
from grades.export import to_csv


class Grades(unittest.TestCase):
    """Checks for letter grades, weights, averages, ranking, rounding and CSV export."""

    def book(self):
        """Helper (not a test): builds a small gradebook, 40% homework and 60% exams, with scores for Zed and Amy."""
        b = Gradebook({"homework": 40, "exams": 60})
        b.add_score("Zed", "homework", 8, 10)
        b.add_score("Zed", "homework", 10, 10)
        b.add_score("Zed", "exams", 45, 50)
        b.add_score("Amy", "exams", 35, 50)
        return b

    def test_letter(self):
        """Proves the letter cut-offs: exactly on a cut-off earns the higher letter, just below drops one."""
        self.assertEqual([letter(p) for p in (95, 90, 89.99, 80, 75, 60, 59.9)], ["A", "A", "B", "B", "C", "D", "F"])

    def test_weights_and_errors(self):
        """Proves bad input is refused: weights not adding to 100, unknown category, score above max, zero max, negative score."""
        # Weights 50 + 40 = 90, not 100, so creating the book must fail.
        with self.assertRaises(ValueError):
            Gradebook({"a": 50, "b": 40})
        b = self.book()
        # Each tuple is a bad add_score call: unknown category, 3 out of 2, out of 0, and a negative score.
        for args in (("x", "quiz", 1, 2), ("x", "exams", 3, 2), ("x", "exams", 1, 0), ("x", "exams", -1, 5)):
            with self.assertRaises(ValueError):
                b.add_score(*args)
        # Asking for the average of a student who has no scores is a KeyError, not a ValueError.
        with self.assertRaises(KeyError):
            b.average("Nobody")

    def test_average_and_rank(self):
        """Proves weighted averages, the sorted student list, and ranking order including the tie-break by name."""
        b = self.book()
        self.assertEqual(b.average("Zed"), 90.0)          # homework 90% * 0.4 + exams 90% * 0.6
        self.assertEqual(b.average("Amy"), 70.0)          # only exams: scaled up
        b.add_score("Bea", "homework", 7, 10)
        self.assertEqual(b.students(), ["Amy", "Bea", "Zed"])
        # Amy and Bea both average 70.0, so the tie is broken alphabetically (Amy first).
        self.assertEqual(b.ranking(), [("Zed", 90.0), ("Amy", 70.0), ("Bea", 70.0)])

    def test_rounding(self):
        """Proves averages are rounded to 2 decimals: 2 out of 3 is 66.666..., which must come back as 66.67."""
        b = Gradebook({"a": 100})
        b.add_score("x", "a", 2, 3)
        self.assertEqual(b.average("x"), 66.67)

    def test_csv(self):
        """Proves to_csv writes a header and one row per student, sorted by name, with 2-decimal averages and letters."""
        # mkdtemp makes a fresh empty temporary folder so the test never touches real files.
        path = os.path.join(tempfile.mkdtemp(), "g.csv")
        b = self.book()
        to_csv(b, path)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read().strip().splitlines(), ["student,average,letter", "Amy,70.00,C", "Zed,90.00,A"])


if __name__ == "__main__":
    unittest.main()
