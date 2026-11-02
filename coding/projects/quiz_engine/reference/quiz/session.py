# Running one quiz, for the "quiz_engine" reference solution: ask questions in a (repeatable) random order,
# take answers, and report a score. Questions come from quiz/bank.py.
import random


class QuizSession:
    """One play-through of a quiz. Call current() to see the question, answer(i) to answer it, until finished is True."""

    def __init__(self, questions, seed=0, count=None):
        """questions: list of question dicts. seed: makes the shuffle repeatable (same seed, same order). count: ask only this many."""
        # Copy the list first so shuffling does not reorder the caller's list.
        qs = list(questions)
        random.Random(seed).shuffle(qs)
        self.questions = qs if count is None else qs[:count]
        # i: position of the current question. score: right answers so far. log: (question, was_right) for each answer given.
        self.i, self.score = 0, 0
        self.log = []

    @property
    def finished(self):
        """True once every question has been answered. (A property is read like a value: session.finished, no brackets.)"""
        return self.i >= len(self.questions)

    def current(self):
        """The question being asked now, or None when the quiz is over."""
        return None if self.finished else self.questions[self.i]

    def answer(self, index):
        """Answer the current question with the choice number `index`. Returns True if right. Raises RuntimeError if already finished."""
        if self.finished:
            raise RuntimeError("the quiz is finished")
        q = self.questions[self.i]
        right = index == q["answer"]
        # True counts as 1 and False as 0 when added, so this adds one point only for a right answer.
        self.score += right
        self.log.append((q, right))
        self.i += 1
        return right

    def results(self):
        """Summary dict: score, total, percent (1 decimal; 0.0 for an empty quiz), by_topic {topic: [right, asked]}, missed (texts of wrong questions)."""
        by_topic = {}
        for q, right in self.log:
            # Each topic keeps a [right, asked] pair, created as [0, 0] the first time the topic is seen.
            t = by_topic.setdefault(q["topic"], [0, 0])
            t[0] += right
            t[1] += 1
        total = len(self.questions)
        return {"score": self.score, "total": total, "percent": round(100 * self.score / total, 1) if total else 0.0,
                "by_topic": by_topic, "missed": [q["q"] for q, right in self.log if not right]}
