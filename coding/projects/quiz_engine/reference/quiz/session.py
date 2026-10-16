import random


class QuizSession:
    def __init__(self, questions, seed=0, count=None):
        qs = list(questions)
        random.Random(seed).shuffle(qs)
        self.questions = qs if count is None else qs[:count]
        self.i, self.score = 0, 0
        self.log = []

    @property
    def finished(self):
        return self.i >= len(self.questions)

    def current(self):
        return None if self.finished else self.questions[self.i]

    def answer(self, index):
        if self.finished:
            raise RuntimeError("the quiz is finished")
        q = self.questions[self.i]
        right = index == q["answer"]
        self.score += right
        self.log.append((q, right))
        self.i += 1
        return right

    def results(self):
        by_topic = {}
        for q, right in self.log:
            t = by_topic.setdefault(q["topic"], [0, 0])
            t[0] += right
            t[1] += 1
        total = len(self.questions)
        return {"score": self.score, "total": total, "percent": round(100 * self.score / total, 1) if total else 0.0,
                "by_topic": by_topic, "missed": [q["q"] for q, right in self.log if not right]}
