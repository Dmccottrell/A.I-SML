"""
classroom.py - What the Teacher assistant skill pack is asked for, and how its answers are checked.

WHAT THIS FILE DOES
    The Teacher assistant (Beta, docs/SKILLS.md) makes classroom materials for a teacher, starting with
    3rd grade: worksheets with answer keys, reading passages with questions, lesson plans, spelling lists,
    parent emails, report card comments, rubrics and quick activities. It answers in the layout
    export_doc.py turns into a PDF or Word file (# title, ## sections, numbered items).

    Shared by make_teacher_data.py (the teacher writes lessons; bad ones are thrown away), skill_test.py
    (scores our model) and the tests. The checks are the point: a worksheet with a wrong answer key is
    worse than none, so every simple sum in a key is recalculated, counts must match what was asked,
    and reading passages must really read at about a 3rd-grade level.
"""
import random
import re

from export_doc import parse

# ------------------------------------------------------------------ what teachers ask for (3rd grade first)
MATH = ["multiplication facts for 2s", "multiplication facts for 3s", "multiplication facts for 4s",
        "multiplication facts for 5s", "multiplication facts for 6s", "multiplication facts for 7s",
        "multiplication facts for 8s", "multiplication facts for 9s", "division facts within 100",
        "multiplication word problems", "division word problems", "fractions on a number line",
        "equivalent fractions", "comparing fractions with the same denominator", "area of rectangles",
        "perimeter of shapes", "rounding to the nearest 10", "rounding to the nearest 100",
        "adding three-digit numbers", "subtracting three-digit numbers", "telling time to the minute",
        "arrays and equal groups", "reading bar graphs", "place value to the thousands"]
ELA = ["nouns, verbs and adjectives", "past tense verbs", "finding the main idea", "context clues",
       "prefixes and suffixes", "synonyms and antonyms", "capital letters", "contractions",
       "plural nouns", "subject and predicate", "fact and opinion", "sequencing events in a story"]
SCIENCE = ["the life cycle of a butterfly", "the life cycle of a frog", "weather and climate", "magnets",
           "pushes and pulls (forces)", "the parts of a plant", "animal habitats", "fossils",
           "the water cycle", "inherited traits"]
SOCIAL = ["map skills", "needs and wants", "communities: urban, suburban and rural", "community helpers",
          "local government", "landforms"]
PASSAGES = ["honeybees", "the moon", "a class garden", "penguins", "how volcanoes form", "recycling",
            "a lost puppy who finds its way home", "the first airplane flight", "sea turtles",
            "a snow day", "how a seed becomes a plant", "a new student's first day", "thunderstorms"]
SPELLING = ["long a (a_e, ai, ay)", "long e (ee, ea)", "long i (i_e, igh)", "long o (o_e, oa, ow)",
            "r-controlled vowels (ar, or)", "words with -ed and -ing", "silent e", "the /ou/ sound (ou, ow)",
            "consonant blends (bl, st, tr)", "words ending in -le"]
EVENTS = ["an upcoming field trip to the science museum", "the class reading challenge this month",
          "picture day next week", "our class play", "parent-teacher conferences",
          "a reminder to send a water bottle every day", "the end of the school year",
          "what we are learning in math this month", "a class party next Friday"]
SITUATIONS = ["is improving in reading", "works hard in math but struggles with word problems",
              "is kind and helpful to classmates", "needs to work on staying focused",
              "is a strong writer", "is shy but participates more lately", "is ahead in math",
              "needs to turn in homework more often"]
RUBRIC_TASKS = ["a paragraph about their favorite animal", "a poster about the water cycle",
                "a short book report", "an oral presentation about a community helper",
                "a persuasive letter to the principal"]
ACTIVITIES = ["brain break ideas", "indoor recess ideas", "early finisher activities",
              "morning meeting questions", "quick review games for math facts"]


def teacher_request(rng):
    """(the teacher's message, spec for checking the answer). spec["type"] says what was asked for."""
    kind = rng.choice(["worksheet", "worksheet", "reading", "lesson_plan", "spelling", "parent_email",
                       "comments", "rubric", "activities"])
    n = rng.choice([5, 6, 8, 10])
    grade = "3rd grade" if rng.random() < 0.85 else rng.choice(["2nd grade", "4th grade"])
    if kind == "worksheet":
        topic = rng.choice(MATH + MATH + ELA + SCIENCE)
        msg = rng.choice([f"Make a {n}-question worksheet on {topic} for my {grade} class, with an answer key.",
                          f"Can you make me a worksheet on {topic} for {grade}? {n} questions and an answer key please.",
                          f"I need {n} practice problems on {topic} for {grade} students, with answers."])
        return msg, {"type": kind, "n": n, "key": True, "topic": topic, "grade": grade}
    if kind == "reading":
        n = rng.choice([3, 4, 5])
        topic = rng.choice(PASSAGES)
        msg = (f"Write a short reading passage about {topic} for {grade}, with {n} comprehension "
               f"questions and an answer key.")
        return msg, {"type": kind, "n": n, "key": True, "topic": topic, "grade": grade}
    if kind == "lesson_plan":
        topic = rng.choice(MATH + ELA + SCIENCE + SOCIAL)
        minutes = rng.choice([30, 45, 60])
        return (f"Write a {minutes}-minute lesson plan on {topic} for {grade}.",
                {"type": kind, "topic": topic, "grade": grade, "minutes": minutes})
    if kind == "spelling":
        pattern = rng.choice(SPELLING)
        return (f"Make a {grade} spelling list of {n} words with {pattern}, with a sentence for each word.",
                {"type": kind, "n": n, "topic": pattern, "grade": grade})
    if kind == "parent_email":
        event = rng.choice(EVENTS)
        return f"Write a short email to parents about {event}.", {"type": kind, "topic": event, "grade": grade}
    if kind == "comments":
        n = rng.choice([2, 3, 4])
        sit = rng.choice(SITUATIONS)
        return (f"Write {n} report card comments for a {grade} student who {sit}.",
                {"type": kind, "n": n, "topic": sit, "grade": grade})
    if kind == "rubric":
        task = rng.choice(RUBRIC_TASKS)
        return f"Make a simple rubric for {task} for {grade}.", {"type": kind, "topic": task, "grade": grade}
    what = rng.choice(ACTIVITIES)
    return f"Give me {n} {what} for my {grade} class.", {"type": kind, "n": n, "topic": what, "grade": grade}


# How each kind of answer is laid out (given to the teacher model, and learned by ours)
LAYOUT = {
    "worksheet": "# <title>\\nGrade <n> - <subject> - Worksheet\\nInstructions: <one line>\\n## Questions\\n1. ...\\n"
                 "(exactly {n} numbered questions; use ____ for blanks)\\n## Answer key\\n1. ...\\n(exactly {n} answers, "
                 "same order, short)",
    "reading": "# <title>\\nGrade <n> - Reading\\n<the passage: 150-300 words, short sentences, words a {grade} "
               "student can read>\\n## Questions\\n1. ...\\n(exactly {n})\\n## Answer key\\n1. ...\\n(exactly {n})",
    "lesson_plan": "# <title>\\nGrade <n> - <subject> - {minutes} minutes\\n## Objective\\n<one sentence: students "
                   "will be able to...>\\n## Materials\\n- ...\\n## Warm-up (<minutes>)\\n...\\n## Teaching (<minutes>)\\n"
                   "1. ...\\n## Practice (<minutes>)\\n...\\n## Exit ticket\\n<one or two quick questions>",
    "spelling": "# <title>\\nGrade <n> - Spelling\\n## Words\\n1. <word>: <a short sentence using it>\\n(exactly {n})\\n"
                "## Practice idea\\n<one short activity>",
    "parent_email": "# <subject line>\\nDear Families,\\n<2-3 short paragraphs, warm and clear, with any dates or "
                    "things to bring as - bullet points>\\nThank you,\\n[Teacher name]",
    "comments": "# Report card comments\\n1. ...\\n(exactly {n}, each 1-3 sentences, positive and specific, with a "
                "next step where it fits; use [Student] instead of a name)",
    "rubric": "# <title> rubric\\nGrade <n>\\n## Criteria\\n- <criterion>: 3 = ..., 2 = ..., 1 = ...\\n(3-5 criteria, "
              "in words a {grade} student understands)",
    "activities": "# <title>\\n1. <name>: <what to do, 1-2 sentences>\\n(exactly {n})",
}


def layout_for(spec):
    return LAYOUT[spec["type"]].format(n=spec.get("n", ""), grade=spec.get("grade", "3rd grade"),
                                       minutes=spec.get("minutes", "")).replace("\\n", "\n")


# ------------------------------------------------------------------ checks
EXPR = re.compile(r"(\d+)\s*([×x*÷/+\-−])\s*(\d+)")


def arithmetic_answer(question):
    """The exact answer to a plain sum like "6 × 4 = ____" or "What is 56 ÷ 8?", or None if it isn't one."""
    found = EXPR.findall(question)
    if len(found) != 1 or len(re.findall(r"\d+", question)) != 2:
        return None                                   # word problems and mixed questions aren't recalculated
    a, op, b = int(found[0][0]), found[0][1], int(found[0][2])
    if op in "×x*":
        return a * b
    if op in "÷/":
        return a // b if b and a % b == 0 else None
    return a + b if op == "+" else a - b


def wrong_key_items(questions, answers):
    """Indexes (from 1) of answer-key items that don't match the recalculated sum."""
    bad = []
    for i, (q, a) in enumerate(zip(questions, answers), 1):
        want = arithmetic_answer(q)
        if want is None:
            continue
        got = re.findall(r"-?\d+", a.replace(",", ""))
        if not got or int(got[0]) != want:
            bad.append(i)
    return bad


def syllables(word):
    w = word.lower().strip(".,!?;:'\"()")
    if not w:
        return 0
    n = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and not w.endswith(("le", "ee")) and n > 1:
        n -= 1
    return max(1, n)


def reading_grade(text):
    """Flesch-Kincaid grade level (about: which school grade can read this)."""
    words = re.findall(r"[A-Za-z']+", text)
    sentences = max(1, len(re.findall(r"[.!?]+", text)))
    if not words:
        return 0.0
    return 0.39 * len(words) / sentences + 11.8 * sum(syllables(w) for w in words) / len(words) - 15.59


def _words(text):
    return len(text.split())


def check_teacher_answer(text, spec):
    """{rule: passed} for one Teacher assistant answer (the same rules for the teacher's lessons and ours)."""
    doc = parse(text)
    body_words = _words(text)
    r = {"layout": text.lstrip().startswith("# ") and bool(doc.sections)}
    t, n = spec["type"], spec.get("n")
    heads = " | ".join(s.heading.lower() for s in doc.sections)
    if t in ("worksheet", "reading"):
        qs, keys = doc.items("questions"), doc.items("key")
        r["count"] = len(qs) == n
        r["answer key"] = len(keys) == len(qs) and len(qs) > 0
        r["key is right"] = r["answer key"] and not wrong_key_items(qs, keys)
        if t == "reading":
            passage = " ".join(v for s in doc.sections if not s.is_questions and not s.is_key
                               for kind, v in s.blocks if kind == "para" and not re.match(r"^grade\b", v, re.I))
            r["reading level"] = 80 <= _words(passage) <= 400 and reading_grade(passage) <= 5.0
    elif t == "lesson_plan":
        r["parts"] = all(re.search(p, heads) for p in (r"objective|goal", r"material", r"practice|activit",
                                                        r"exit ticket|assessment|check"))
        r["length"] = 120 <= body_words <= 600
    elif t in ("spelling", "activities", "comments"):
        first = next((v for s in doc.sections for kind, v in s.blocks if kind == "numbered"), [])
        r["count"] = len(first) == n
        if t == "comments":
            r["no names"] = bool(first) and all("[student]" in it.lower() or "your child" in it.lower() for it in first)
            r["length"] = bool(first) and all(8 <= _words(it) <= 70 for it in first)
    elif t == "parent_email":
        low = text.lower()
        r["greeting"] = bool(re.search(r"^\s*dear\b", low, re.M))
        r["sign-off"] = bool(re.search(r"thank you|sincerely|best|warmly|kind regards", low))
        r["length"] = 50 <= body_words <= 260
    elif t == "rubric":
        crit = [it for s in doc.sections for kind, v in s.blocks if kind in ("bullets", "numbered") for it in v]
        r["criteria"] = 3 <= len(crit) <= 6
        r["score levels"] = bool(crit) and all(re.search(r"\b3\s*[=:-]", c) and re.search(r"\b1\s*[=:-]", c) for c in crit)
    r["no ai talk"] = not re.search(r"\bas an ai\b|language model", text, re.I)
    return r


def passes(checks):
    return all(checks.values())


if __name__ == "__main__":
    rng = random.Random(0)
    for _ in range(5):
        msg, spec = teacher_request(rng)
        print(spec["type"], "|", msg)
