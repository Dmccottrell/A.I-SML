def letter(percent):
    for cut, grade in ((90, "A"), (80, "B"), (70, "C"), (60, "D")):
        if percent >= cut:
            return grade
    return "F"


class Gradebook:
    def __init__(self, weights):
        if abs(sum(weights.values()) - 100) > 1e-9:
            raise ValueError("weights must add up to 100")
        self.weights = dict(weights)
        self.scores = {}

    def add_score(self, student, category, score, out_of):
        if category not in self.weights:
            raise ValueError(f"unknown category {category}")
        if out_of <= 0 or not 0 <= score <= out_of:
            raise ValueError("bad score")
        cat = self.scores.setdefault(student, {}).setdefault(category, [0, 0])
        cat[0] += score
        cat[1] += out_of

    def average(self, student):
        if student not in self.scores:
            raise KeyError(student)
        cats = self.scores[student]
        total_w = sum(self.weights[c] for c in cats)
        return round(sum(self.weights[c] * (s / o * 100) for c, (s, o) in cats.items()) / total_w, 2)

    def students(self):
        return sorted(self.scores)

    def ranking(self):
        return sorted(((s, self.average(s)) for s in self.scores), key=lambda p: (-p[1], p[0]))
