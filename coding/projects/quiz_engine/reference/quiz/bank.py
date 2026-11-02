# Question loading for the quiz reference solution ("quiz_engine" exercise): reads a JSON file of questions
# and checks each one is well formed. quiz/session.py then runs a quiz from the checked list.
import json


def check(questions):
    """Make sure every question has the keys q, choices, answer, topic, at least 2 choices, and an answer that is a valid choice number.

    Returns the same list if all is well; otherwise raises ValueError naming the first bad question (counting from 1).
    """
    for n, q in enumerate(questions, 1):
        if not all(k in q for k in ("q", "choices", "answer", "topic")):
            raise ValueError(f"question {n} is missing a key")
        if len(q["choices"]) < 2:
            raise ValueError(f"question {n} needs at least 2 choices")
        # answer is the position (0, 1, 2 ...) of the right choice, so it must be a whole number inside the list.
        if not isinstance(q["answer"], int) or not 0 <= q["answer"] < len(q["choices"]):
            raise ValueError(f"question {n} has an answer out of range")
    return questions


def load_questions(path):
    """Read the JSON file at path (a list of question dicts), validate it with check(), and return it."""
    with open(path, encoding="utf-8") as f:
        return check(json.load(f))
