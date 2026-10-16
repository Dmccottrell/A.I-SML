import json


def check(questions):
    for n, q in enumerate(questions, 1):
        if not all(k in q for k in ("q", "choices", "answer", "topic")):
            raise ValueError(f"question {n} is missing a key")
        if len(q["choices"]) < 2:
            raise ValueError(f"question {n} needs at least 2 choices")
        if not isinstance(q["answer"], int) or not 0 <= q["answer"] < len(q["choices"]):
            raise ValueError(f"question {n} has an answer out of range")
    return questions


def load_questions(path):
    with open(path, encoding="utf-8") as f:
        return check(json.load(f))
