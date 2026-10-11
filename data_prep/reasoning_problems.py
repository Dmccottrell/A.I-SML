"""
reasoning_problems.py - Reasoning problems whose answers can be checked by code. Used to make thinking lessons (make_thinking_lessons.py) and to test
that a tuned model still thinks as well as the plain base (evaluation/thinking_check.py).

    make_problems(n, seed)       -> [{"id", "kind", "question", "answer", "tol"}]  (the same seed always gives the same problems)
    check_answer(problem, text)  -> True if the last number in the model's final answer matches the problem's answer
    ask(server, question, thinking) -> {"thinking": str, "answer": str, "tokens": int}   (any OpenAI-style server, such as llama-server)
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import random
import re
import urllib.request

import thinking as think_mod

NAMES = ["Maria", "Tom", "Aisha", "Liam", "Sofia", "Noah", "Priya", "Ethan", "Mei", "Carlos"]
ITEMS = [("notebooks", 2.5), ("pens", 1.2), ("apples", 0.8), ("sandwiches", 4.5), ("tickets", 12.0), ("stickers", 0.35)]


def _num(x):
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def _arith(rng, i):
    a, b, c = rng.randint(12, 99), rng.randint(3, 30), rng.randint(2, 9)
    ops = rng.choice([("({a} + {b}) * {c}", (a + b) * c), ("{a} * {c} - {b}", a * c - b), ("({a} - {b}) * {c} + {c}", (a - b) * c + c)])
    return dict(question=f"What is {ops[0].format(a=a, b=b, c=c)}?", answer=ops[1], tol=0)


def _percent(rng, i):
    p, n = rng.choice([5, 10, 12, 15, 20, 25, 30, 40, 60, 75]), rng.choice([40, 60, 80, 120, 150, 240, 360, 500])
    if rng.random() < 0.5:
        return dict(question=f"What is {p}% of {n}?", answer=n * p / 100, tol=0.01)
    return dict(question=f"A jacket costs ${n}. It is on sale for {p}% off. What is the sale price in dollars?", answer=n - n * p / 100, tol=0.01)


def _rate(rng, i):
    speed, hours = rng.choice([40, 45, 55, 60, 65, 80]), rng.choice([1.5, 2, 2.5, 3, 4])
    if rng.random() < 0.5:
        return dict(question=f"A train travels at {speed} km/h for {_num(hours)} hours. How far does it go, in km?", answer=speed * hours, tol=0.01)
    return dict(question=f"A cyclist rides {_num(speed * hours)} km in {_num(hours)} hours at a steady speed. What is the speed in km/h?", answer=speed, tol=0.01)


def _shopping(rng, i):
    (n1, p1), (n2, p2) = rng.sample(ITEMS, 2)
    q1, q2 = rng.randint(2, 6), rng.randint(2, 6)
    who = rng.choice(NAMES)
    return dict(question=f"{who} buys {q1} {n1} at ${p1:.2f} each and {q2} {n2} at ${p2:.2f} each. How much does {who} spend in total, in dollars?", answer=round(q1 * p1 + q2 * p2, 2), tol=0.01)


def _algebra(rng, i):
    a, x, b = rng.randint(2, 9), rng.randint(2, 15), rng.randint(1, 20)
    return dict(question=f"Solve for x: {a}x + {b} = {a * x + b}", answer=x, tol=0)


def _sequence(rng, i):
    start, step = rng.randint(2, 20), rng.randint(2, 9)
    if rng.random() < 0.5:
        seq = [start + step * k for k in range(5)]
        return dict(question=f"What is the next number in the sequence {', '.join(map(str, seq))}, ...?", answer=start + step * 5, tol=0)
    ratio = rng.choice([2, 3])
    seq = [start * ratio ** k for k in range(4)]
    return dict(question=f"What is the next number in the sequence {', '.join(map(str, seq))}, ...?", answer=start * ratio ** 4, tol=0)


def _units(rng, i):
    m = rng.choice([90, 150, 210, 270, 330, 450])
    return dict(question=f"A film is {m} minutes long. How many hours is that? Give a decimal number.", answer=m / 60, tol=0.01)


GENERATORS = [("arithmetic", _arith), ("percent", _percent), ("rate", _rate), ("shopping", _shopping), ("algebra", _algebra), ("sequence", _sequence), ("units", _units)]


def make_problems(n, seed=1):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        kind, gen = GENERATORS[i % len(GENERATORS)]
        p = gen(rng, i)
        p.update(id=f"{kind}-{seed}-{i}", kind=kind)
        out.append(p)
    return out


NUMBER = re.compile(r"-?\$?\d[\d,]*(?:\.\d+)?")


def last_number(text):
    found = NUMBER.findall(text or "")
    if not found:
        return None
    try:
        return float(found[-1].replace("$", "").replace(",", ""))
    except ValueError:
        return None


def check_answer(problem, text):
    got = last_number(text)
    return got is not None and abs(got - float(problem["answer"])) <= max(problem.get("tol", 0), 1e-9)


def ask(server, question, thinking=True, temperature=0.6, max_tokens=3000, timeout=600):
    """One question to an OpenAI-style server. Thinking is switched with the template option (llama-server --jinja takes it)."""
    body = {"messages": [{"role": "user", "content": question}], "temperature": temperature, "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": bool(thinking)}}
    req = urllib.request.Request(server.rstrip("/") + "/v1/chat/completions", json.dumps(body).encode("utf-8"), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    msg = data["choices"][0]["message"]
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or ""
    if not reasoning:
        reasoning, content = think_mod.split_thinking(content)
    return {"thinking": reasoning.strip(), "answer": content.strip(), "tokens": (data.get("usage") or {}).get("completion_tokens", 0)}
