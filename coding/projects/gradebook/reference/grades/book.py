# The gradebook itself (reference solution for the "gradebook" coding exercise).
# It stores scores per student and category, works out weighted averages, letter grades and a ranking.
# grades/export.py uses it to write a CSV file.


def letter(percent):
    """Turn a percentage into a letter grade: 90+ A, 80+ B, 70+ C, 60+ D, anything lower F."""
    # Check from the highest cut-off down; the first one the score reaches wins.
    for cut, grade in ((90, "A"), (80, "B"), (70, "C"), (60, "D")):
        if percent >= cut:
            return grade
    return "F"


class Gradebook:
    """Holds scores for many students, grouped by category (for example "homework", "exams").

    weights says how much each category counts, as numbers that add up to 100.
    self.scores looks like {student: {category: [points_earned, points_possible]}}.
    """

    def __init__(self, weights):
        # Compare with a tiny tolerance (1e-9) because decimal sums can be off by a hair (0.1 + 0.2 != 0.3 exactly).
        if abs(sum(weights.values()) - 100) > 1e-9:
            raise ValueError("weights must add up to 100")
        # Copy the dict so later changes by the caller do not change our weights.
        self.weights = dict(weights)
        self.scores = {}

    def add_score(self, student, category, score, out_of):
        """Record one assignment, for example 8 out of 10. Can be called many times for the same category.

        Raises ValueError for an unknown category, an out_of that is not positive, or a score outside 0..out_of.
        """
        if category not in self.weights:
            raise ValueError(f"unknown category {category}")
        if out_of <= 0 or not 0 <= score <= out_of:
            raise ValueError("bad score")
        # setdefault creates the student's dict and the category's [0, 0] pair the first time, then returns it.
        cat = self.scores.setdefault(student, {}).setdefault(category, [0, 0])
        # Totals are added up, so a category's percentage is (all points earned) / (all points possible).
        cat[0] += score
        cat[1] += out_of

    def average(self, student):
        """The student's weighted average as a percentage, rounded to 2 decimals. Unknown student raises KeyError."""
        if student not in self.scores:
            raise KeyError(student)
        cats = self.scores[student]
        # Only categories the student has scores in count; total_w is their combined weight. Dividing by it
        # scales the result back up, so a student with only exams is not punished for missing homework.
        total_w = sum(self.weights[c] for c in cats)
        return round(sum(self.weights[c] * (s / o * 100) for c, (s, o) in cats.items()) / total_w, 2)

    def students(self):
        """Student names in alphabetical order."""
        return sorted(self.scores)

    def ranking(self):
        """List of (student, average) pairs, best first. Ties are broken alphabetically by name."""
        # The key (-average, name): the minus sign sorts higher averages first while names still sort A to Z.
        return sorted(((s, self.average(s)) for s in self.scores), key=lambda p: (-p[1], p[0]))
