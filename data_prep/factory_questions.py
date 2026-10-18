"""
factory_questions.py - The questions the lesson factory answers (docs/LESSONS_4.md).

WHAT THIS FILE DOES
    A question is a dict: {"id", "question", "area", "level"} plus anything that lets an answer be CHECKED:
        "answer"   the known answer (a number or a short text): maths and facts
        "tests"    Python assert lines or test code: the answer's code is run against them
        "messages" earlier turns, for a multi-turn question (the question is the last user turn)
        "notes"    reference text the answer must agree with (a judge reads it)
    Where questions come from:
      areas      AREAS below: about 20 areas, each with what good questions look like; the teacher writes new questions for an area and level
                 (questions_prompt / parse_questions), then they are de-duplicated
      import     JSONL files from open datasets (the owner reads each licence first): {"question","answer"} (GSM8K-style), {"prompt","tests"}
                 (MBPP/HumanEval-style), {"instruction","input"} (Alpaca-style) or {"messages"} (chat); only the QUESTIONS are used, answers are made here
      checked    exact maths problems from reasoning_problems.py, whose answers are known
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import hashlib
import json
import re

LEVELS = ("easy", "medium", "hard")

AREAS = {
    "everyday": "practical everyday questions: cooking, travel, home, shopping, time and planning",
    "explain": "explaining an idea clearly to a curious person: science, technology, history, how things work",
    "maths": "maths word problems and calculations with one exact numeric answer; state the numbers needed",
    "code_python": "Python programming tasks: write a function, fix a bug in given code, explain code; include the code to fix when asked",
    "code_web": "HTML, CSS and JavaScript tasks: a small page, a component, fixing a layout or script bug",
    "code_other": "programming in other languages (Java, C, C++, Go, Rust, SQL, shell): small tasks and debugging",
    "science": "physics, chemistry, biology and earth science questions, from homework level to university level",
    "writing": "writing help: emails, messages, cover letters, stories, poems, editing a given paragraph for tone or clarity",
    "advice": "personal and work decisions with trade-offs: careers, money basics, study plans, difficult conversations",
    "planning": "multi-step tasks: plan a project, a trip, a week of meals, a study schedule, a small event",
    "reasoning": "logic puzzles, estimation, comparing options, spotting a flaw in an argument",
    "health": "general health and wellbeing questions where good information helps and a professional may be needed",
    "money": "personal finance basics: budgeting, saving, interest, comparing offers (no specific investment picks)",
    "learning": "a student asking to understand a topic step by step, or checking their own answer",
    "tech_help": "computer and phone help: settings, errors, files, networks, troubleshooting step by step",
    "creative": "brainstorming names, ideas, gifts, games; light-hearted and fun requests",
    "feelings": "someone sharing stress, sadness, excitement or a problem with a friend, wanting to be heard and helped",
    "sensitive": "questions that sound risky but are legitimate (medicine doses, security concepts, history of violence, chemistry), "
                 "plus a few that ask for real harm, so the answer shows when to help fully and when to decline kindly",
    "ambiguous": "requests missing one key detail, where a good answer asks one short question or states a sensible assumption",
    "follow_up": "a short second message continuing an earlier exchange (give the earlier exchange as context)",
    "casual": "messages typed the way people really text: slang and fillers (ya know, ngl, lowkey, fr, idk, bruh), misspellings, voice-to-text "
              "mistakes, missing words, run-on sentences and half-finished thoughts, often a feeling or opinion rather than a question; a good "
              "reply works out what they mean, answers that naturally as \"you\", never corrects their spelling and never says it did not understand "
              "when the meaning can be guessed",
}


def qid(text):
    return hashlib.sha1(" ".join(str(text).lower().split()).encode("utf-8")).hexdigest()[:16]


def norm(text):
    return re.sub(r"[^a-z0-9 ]", "", " ".join(str(text).lower().split()))


def questions_prompt(area, level, n, avoid=()):
    """The message that asks the teacher for n new questions in an area."""
    lines = [f"Write {n} varied, realistic questions a person might ask an AI assistant.",
             f"Area: {area}: {AREAS[area]}.",
             f"Level: {level} ({'quick and simple' if level == 'easy' else 'needs some thought' if level == 'medium' else 'genuinely hard, multi-step or expert'}).",
             "Vary the wording, length and who is asking. Write each question exactly as the person would type it, with any code or numbers they would include.",
             "No answers. Return a JSON list of strings and nothing else."]
    if avoid:
        lines.append("Do not repeat these: " + " | ".join(list(avoid)[:20]))
    return "\n".join(lines)


def parse_questions(reply):
    """A list of question strings from the teacher's reply (a JSON list, or one question per line as a fallback)."""
    text = (reply or "").strip()
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        try:
            got = json.loads(m.group(0))
            return [str(q).strip() for q in got if str(q).strip()]
        except ValueError:
            pass
    return [re.sub(r"^\s*(?:\d+[.)]|[-*])\s*", "", line).strip() for line in text.splitlines() if len(line.strip()) > 8]


def from_row(row, source, area=None, level="medium"):
    """One question from a dataset row in any of the known shapes, or None."""
    q = {"source": source, "level": row.get("level", level), "area": row.get("area") or area or "imported"}
    if row.get("messages"):
        msgs = [m for m in row["messages"] if m.get("role") in ("user", "assistant")]
        while msgs and msgs[-1]["role"] != "user":
            msgs = msgs[:-1]                                             # the last USER turn is the question; the answer is made here
        if not msgs:
            return None
        q["question"], q["messages"] = msgs[-1]["content"], msgs[:-1]
    elif row.get("question"):
        q["question"] = row["question"]
        if row.get("answer") not in (None, ""):
            ans = str(row["answer"])
            q["answer"] = ans.split("####")[-1].strip() if "####" in ans else ans.strip()     # GSM8K puts the final answer after ####
    elif row.get("prompt"):
        q["question"] = row["prompt"]
        if row.get("tests") or row.get("test_list") or row.get("test"):
            q["tests"] = row.get("tests") or row.get("test_list") or row.get("test")
            q["area"] = area or "code_python"
    elif row.get("instruction"):
        q["question"] = row["instruction"] + (("\n\n" + row["input"]) if row.get("input") else "")
    else:
        return None
    for key in ("notes", "tol"):
        if row.get(key):
            q[key] = row[key]
    q["id"] = qid(q["question"] + json.dumps(q.get("messages", []), sort_keys=True))
    return q


def import_jsonl(path, source, area=None, level="medium", limit=None):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            q = from_row(json.loads(line), source, area, level)
            if q:
                out.append(q)
                if limit and len(out) >= limit:
                    break
    return out


def checked_maths(n, seed=11):
    """Exact maths problems with known answers (reasoning_problems.py)."""
    import reasoning_problems as RP
    return [{"id": qid(p["question"]), "question": p["question"], "answer": p["answer"], "tol": p.get("tol", 0), "area": "maths",
             "level": "medium", "source": "reasoning_problems"} for p in RP.make_problems(n, seed)]


def dedupe(questions, seen=()):
    """Drop repeats (same words, ignoring case and punctuation) and anything already in `seen` (ids)."""
    out, keys, ids = [], set(), set(seen)
    for q in questions:
        k = norm(q["question"])
        if k in keys or q["id"] in ids or len(k) < 6:
            continue
        keys.add(k)
        ids.add(q["id"])
        out.append(q)
    return out
