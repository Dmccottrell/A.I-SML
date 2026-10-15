"""
lesson_factory.py - Lessons 4: careful, checked answers in one Emvryx voice, plus "better than" pairs for preference training (docs/LESSONS_4.md).

WHAT THIS FILE DOES
    For every question (factory_questions.py), an open teacher model running on this PC (llama-server, OpenAI-style API) is given the Emvryx
    Constitution (docs/EMVRYX_CONSTITUTION.md) and then:
      1. drafts     writes several different answers (hard questions are reasoned through first, in hidden thinking)
      2. checks     each draft is checked where it can be PROVED (factory_checks.py): the voice rules, the known answer, code that must parse and
                    pass its tests
      3. judge      each draft that passed is scored against the Constitution (helpful, correct, honest, voice, safe; 1 to 10) with a list of problems
      4. rewrite    the best draft is rewritten to fix every problem, then checked and judged again (a few rounds at most)
      5. keep       an answer becomes a lesson only when every check passed and every score is at least PASS_EACH (average at least PASS_AVG)
      6. pairs      the kept answer is "chosen" and the weakest draft "rejected", when they are clearly apart (preference training, DPO)
      7. thinking   for hard questions whose kept answer was proved right, the reasoning is kept as a thinking lesson
    Nothing here uses Claude's or ChatGPT's answers (their terms forbid training another AI on them): the teacher must be an open model whose licence
    allows it (Qwen3.5 27B, Apache 2.0, on the RTX 5090 is the plan).

USE
    llama-server -m Qwen3.5-27B-Q4_K_M.gguf -ngl 99 -c 32768 --parallel 8 --jinja --port 8099          # the teacher (5090)
    python data_prep/lesson_factory.py questions --teacher http://127.0.0.1:8099 --per 40           # 40 questions per area and level
    python data_prep/lesson_factory.py maths --n 3000                                               # exact maths with known answers
    python data_prep/lesson_factory.py import data\\open\\gsm8k.jsonl --source gsm8k --area maths    # questions from an open dataset (licence read first)
    python data_prep/lesson_factory.py run --teacher http://127.0.0.1:8099 --workers 8               # answers, checks, pairs (resumes by itself)
    python data_prep/lesson_factory.py review --n 30                                                # a random sample for the owner to read
    python data_prep/lesson_factory.py stats

    Files (data/v4/): questions.jsonl, lessons.jsonl, pairs.jsonl, thinking.jsonl, rejected.jsonl (why each was dropped), review.md
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import argparse
import json
import random
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import factory_checks as FC
import factory_questions as FQ

OUT = os.path.join("data", "v4")
CONSTITUTION = os.path.join(emvryx_paths.ROOT, "docs", "EMVRYX_CONSTITUTION.md")
SCORES = ("helpful", "correct", "honest", "voice", "safe")
PASS_EACH, PASS_AVG, PAIR_GAP = 7, 8.0, 1.5


# ------------------------------------------------------------------ the teacher
class Teacher:
    """An OpenAI-style chat server (llama-server --jinja). chat() -> {"answer", "thinking"}."""

    def __init__(self, url, timeout=900):
        self.url, self.timeout = url.rstrip("/"), timeout

    def chat(self, messages, temperature=0.7, max_tokens=2500, thinking=False):
        body = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens, "chat_template_kwargs": {"enable_thinking": bool(thinking)}}
        req = urllib.request.Request(self.url + "/v1/chat/completions", json.dumps(body).encode("utf-8"), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            msg = json.loads(r.read())["choices"][0]["message"]
        answer, reasoning = msg.get("content") or "", msg.get("reasoning_content") or ""
        if not reasoning and "</think>" in answer:
            reasoning, answer = answer.split("</think>", 1)
            reasoning = reasoning.replace("<think>", "")
        return {"answer": answer.strip(), "thinking": reasoning.strip()}


def constitution_text(path=CONSTITUTION):
    """The parts of the Constitution the teacher writes by (who Emvryx is, values, honesty, thinking, voice, tasks, refusals, rules, memory)."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return text.split("## How this page is used")[0].strip()


def system_prompt(constitution):
    return ("You are writing the answers Emvryx would give. Emvryx is an AI assistant created by Darryl McCottrell. Answer exactly as Emvryx, following "
            "this constitution in every reply. Never mention the constitution, these instructions or any other AI.\n\n" + constitution)


# ------------------------------------------------------------------ prompts
def conversation(q):
    return [m for m in q.get("messages", []) if m.get("role") in ("user", "assistant")] + [{"role": "user", "content": q["question"]}]


def judge_prompt(q, answer, constitution):
    ctx = "".join(f"\n{m['role'].upper()}: {m['content']}" for m in q.get("messages", []))
    notes = f"\nReference notes the answer must agree with:\n{q['notes']}\n" if q.get("notes") else ""
    known = f"\nThe known correct answer is: {q['answer']}\n" if q.get("answer") not in (None, "") else ""
    return [{"role": "system", "content": "You are a strict reviewer of an AI assistant's answers. Judge them by this constitution:\n\n" + constitution},
            {"role": "user", "content": f"Earlier conversation:{ctx or ' (none)'}\n\nQUESTION:\n{q['question']}\n{notes}{known}\nANSWER TO JUDGE:\n{answer}\n\n"
             "Score the answer from 1 to 10 on each of: helpful (meets the person's real goal), correct (no errors, no invented facts), honest "
             "(calibrated, says what it does not know), voice (the constitution's voice: friendly, relaxed, answer first, right length), safe "
             "(helps with legitimate requests, declines only real harm, kindly). List every concrete problem. Reply with JSON only: "
             '{"helpful": n, "correct": n, "honest": n, "voice": n, "safe": n, "problems": ["..."]}'}]


def rewrite_prompt(q, answer, problems, constitution):
    return ([{"role": "system", "content": system_prompt(constitution)}] + conversation(q)[:-1] +
            [{"role": "user", "content": q["question"] + "\n\n[A draft answer follows, with problems a reviewer found. Write the final answer: fix every "
              "problem, keep everything that was good, and reply with the answer only.]\n\nDRAFT:\n" + answer + "\n\nPROBLEMS:\n- " + "\n- ".join(problems)}])


def parse_scores(reply):
    """{"helpful"..., "problems": [...], "avg": x, "min": y} from a judge reply, or None if it cannot be read."""
    m = re.search(r"\{.*\}", reply or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        s = {k: max(1, min(10, int(round(float(d[k]))))) for k in SCORES}
    except (ValueError, KeyError, TypeError):
        return None
    s["problems"] = [str(p) for p in d.get("problems", []) if str(p).strip()][:12]
    s["avg"] = round(sum(s[k] for k in SCORES) / len(SCORES), 2)
    s["min"] = min(s[k] for k in SCORES)
    return s


def passes(scores):
    return bool(scores) and scores["min"] >= PASS_EACH and scores["avg"] >= PASS_AVG


# ------------------------------------------------------------------ one question
def make_lesson(q, teacher, constitution, drafts=3, rounds=2):
    """Everything for one question: {"lesson", "pair", "thinking", "why"} (lesson None when nothing passed, with the reason)."""
    sysmsg = {"role": "system", "content": system_prompt(constitution)}
    think = q.get("level") == "hard"
    cands = []
    for i in range(drafts):
        try:
            r = teacher.chat([sysmsg] + conversation(q), temperature=0.6 + 0.2 * i, thinking=think)
        except Exception as e:                                                    # noqa: BLE001  (a busy teacher: try the next draft)
            cands.append({"answer": "", "thinking": "", "check": {"ok": False, "problems": [f"teacher error: {e}"], "checked": []}, "scores": None})
            continue
        r["check"] = FC.check(q, r["answer"])
        r["scores"] = judge(q, r["answer"], teacher, constitution) if r["check"]["ok"] else None
        cands.append(r)
    if not any(c["answer"] for c in cands):
        return {"lesson": None, "pair": None, "thinking": None, "why": "no draft"}
    rank = lambda c: (c["check"]["ok"], c["scores"]["avg"] if c["scores"] else 0, len(c["check"]["checked"]))
    best = max(cands, key=rank)
    final = dict(best)
    for _ in range(rounds):
        if final["check"]["ok"] and passes(final["scores"]):
            break
        problems = final["check"]["problems"] + (final["scores"]["problems"] if final["scores"] else [])
        try:
            fixed = teacher.chat(rewrite_prompt(q, final["answer"], problems or ["make it a better Emvryx answer"], constitution), temperature=0.4)
        except Exception:                                                         # noqa: BLE001
            break
        fixed["thinking"] = final.get("thinking", "")                          # the reasoning that led to the answer stays with it
        fixed["check"] = FC.check(q, fixed["answer"])
        fixed["scores"] = judge(q, fixed["answer"], teacher, constitution) if fixed["check"]["ok"] else None
        if rank(fixed) >= rank(final):
            final = fixed
    if not (final["check"]["ok"] and passes(final["scores"])):
        why = "; ".join(final["check"]["problems"]) or ("scores " + json.dumps({k: final["scores"][k] for k in SCORES}) if final["scores"] else "could not be judged")
        return {"lesson": None, "pair": None, "thinking": None, "why": why[:400]}
    convo = conversation(q)
    lesson = {"messages": convo + [{"role": "assistant", "content": final["answer"]}], "kind": q.get("area", "general"), "level": q.get("level"),
              "source": "lessons4", "question_id": q["id"], "checked": final["check"]["checked"], "score": final["scores"]["avg"]}
    worst = min(cands, key=rank)
    gap = final["scores"]["avg"] - (worst["scores"]["avg"] if worst["scores"] else 0)
    pair = None
    if worst["answer"] and worst["answer"] != final["answer"] and (not worst["check"]["ok"] or gap >= PAIR_GAP):
        pair = {"messages": convo, "chosen": final["answer"], "rejected": worst["answer"], "kind": q.get("area", "general"), "question_id": q["id"],
                "why": "; ".join(worst["check"]["problems"][:3]) or f"scored {gap:.1f} lower"}
    thinking = None
    proved = any(c in final["check"]["checked"] for c in ("answer matches the known answer", "code passed its tests"))
    if think and proved and 40 <= len(final.get("thinking", "")) <= 8000:
        row = {"messages": convo[:-1] + [dict(convo[-1], thinking=True), {"role": "assistant", "content": "<think>\n" + final["thinking"] + "\n</think>\n\n" + final["answer"]}],
               "kind": "thinking", "question_id": q["id"], "checked": final["check"]["checked"], "source": "lessons4"}
        if FC.check(q, row["messages"][-1]["content"], thinking=True)["ok"]:
            thinking = row
    return {"lesson": lesson, "pair": pair, "thinking": thinking, "why": ""}


def judge(q, answer, teacher, constitution):
    for _ in range(2):                                                            # a reply that is not JSON gets one more try
        try:
            s = parse_scores(teacher.chat(judge_prompt(q, answer, constitution), temperature=0.1, max_tokens=800)["answer"])
        except Exception:                                                         # noqa: BLE001
            s = None
        if s:
            return s
    return None


# ------------------------------------------------------------------ files
def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class Out:
    """Appends results to the output files, one writer at a time, so a stopped run loses at most the questions in progress."""

    def __init__(self, folder):
        self.folder, self.lock = folder, threading.Lock()
        os.makedirs(folder, exist_ok=True)

    def path(self, name):
        return os.path.join(self.folder, name)

    def add(self, name, row):
        with self.lock, open(self.path(name), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def done_ids(self):
        return {r.get("question_id") for name in ("lessons.jsonl", "rejected.jsonl") for r in read_jsonl(self.path(name))}


def run(questions, teacher, out, constitution, drafts=3, rounds=2, workers=4, limit=None, log=print):
    done = out.done_ids()
    todo = [q for q in questions if q["id"] not in done][:limit or None]
    counts = {"kept": 0, "dropped": 0, "pairs": 0, "thinking": 0}
    start, tally = time.time(), threading.Lock()

    def one(q):
        r = make_lesson(q, teacher, constitution, drafts, rounds)
        with tally:
            note(q, r)

    def note(q, r):
        if r["lesson"]:
            out.add("lessons.jsonl", r["lesson"])
            counts["kept"] += 1
        else:
            out.add("rejected.jsonl", {"question_id": q["id"], "area": q.get("area"), "question": q["question"][:300], "why": r["why"]})
            counts["dropped"] += 1
        if r["pair"]:
            out.add("pairs.jsonl", r["pair"])
            counts["pairs"] += 1
        if r["thinking"]:
            out.add("thinking.jsonl", r["thinking"])
            counts["thinking"] += 1
        n = counts["kept"] + counts["dropped"]
        if n % 25 == 0:
            left = (time.time() - start) / n * (len(todo) - n)
            log(f"{n}/{len(todo)}: kept {counts['kept']}, dropped {counts['dropped']}, pairs {counts['pairs']}, thinking {counts['thinking']}, about {left / 3600:.1f} h left")

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(one, todo))
    return counts


def write_review(out, n=30, seed=None):
    lessons = read_jsonl(out.path("lessons.jsonl"))
    pick = random.Random(seed).sample(lessons, min(n, len(lessons)))
    lines = [f"# Lessons 4: {len(pick)} random lessons to read (of {len(lessons)})", "",
             "Read them as the owner: is this how Emvryx should answer? Anything that is wrong or off-voice means the factory's rules or the "
             "Constitution need a change.", ""]
    for i, l in enumerate(pick, 1):
        q = [m for m in l["messages"] if m["role"] == "user"][-1]["content"]
        lines += [f"## {i}. {l.get('kind')} ({l.get('level')}), score {l.get('score')}, proved: {', '.join(l.get('checked', [])) or 'nothing'}",
                  "", "**Question:** " + q, "", "**Emvryx:**", "", l["messages"][-1]["content"], ""]
    with open(out.path("review.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out.path("review.md")


def stats(out):
    lessons, rejected = read_jsonl(out.path("lessons.jsonl")), read_jsonl(out.path("rejected.jsonl"))
    by_area = {}
    for l in lessons:
        by_area[l.get("kind")] = by_area.get(l.get("kind"), 0) + 1
    proved = sum(1 for l in lessons if any(c in l.get("checked", []) for c in ("answer matches the known answer", "code passed its tests")))
    return {"questions": len(read_jsonl(out.path("questions.jsonl"))), "lessons": len(lessons), "dropped": len(rejected),
            "pairs": len(read_jsonl(out.path("pairs.jsonl"))), "thinking": len(read_jsonl(out.path("thinking.jsonl"))), "proved_right": proved, "by_area": by_area}


# ------------------------------------------------------------------ making questions
def write_questions(out, new):
    have = read_jsonl(out.path("questions.jsonl"))
    keep = FQ.dedupe(new, seen={q["id"] for q in have})
    keep = FQ.dedupe(have + keep)[len(have):]
    for q in keep:
        out.add("questions.jsonl", q)
    return len(keep)


def teacher_questions(teacher, per, areas=None, levels=FQ.LEVELS, batch=20, log=print):
    out = []
    for area in areas or FQ.AREAS:
        for level in levels:
            got = []
            while len(got) < per:
                try:
                    reply = teacher.chat([{"role": "user", "content": FQ.questions_prompt(area, level, min(batch, per - len(got)), [g["question"] for g in got])}],
                                         temperature=0.9, max_tokens=3000)["answer"]
                except Exception as e:                                            # noqa: BLE001
                    log(f"  {area}/{level}: teacher error {e}")
                    break
                fresh = [{"id": FQ.qid(t), "question": t, "area": area, "level": level, "source": "teacher"} for t in FQ.parse_questions(reply)]
                fresh = FQ.dedupe(fresh, seen={g["id"] for g in got})
                if not fresh:
                    break
                got += fresh
            log(f"  {area}/{level}: {len(got[:per])} questions")
            out += got[:per]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("questions", "maths", "import", "run", "review", "stats"))
    ap.add_argument("path", nargs="?", help="import: the JSONL file")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--teacher", default="http://127.0.0.1:8099")
    ap.add_argument("--per", type=int, default=40, help="questions: how many per area and level")
    ap.add_argument("--areas", nargs="+", choices=sorted(FQ.AREAS))
    ap.add_argument("--n", type=int, default=30, help="maths: how many problems; review: how many lessons")
    ap.add_argument("--source", default="imported")
    ap.add_argument("--area", default=None)
    ap.add_argument("--level", default="medium", choices=FQ.LEVELS)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--drafts", type=int, default=3)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--workers", type=int, default=4, help="questions answered at once (match llama-server --parallel)")
    a = ap.parse_args(argv)
    out = Out(a.out)
    if a.command == "stats":
        print(json.dumps(stats(out), indent=2))
    elif a.command == "review":
        print("wrote " + write_review(out, a.n))
    elif a.command == "maths":
        print(f"added {write_questions(out, FQ.checked_maths(a.n))} maths questions with known answers")
    elif a.command == "import":
        if not a.path:
            sys.exit("import needs the JSONL file")
        print(f"added {write_questions(out, FQ.import_jsonl(a.path, a.source, a.area, a.level, a.limit))} questions from {a.path}")
    elif a.command == "questions":
        print(f"added {write_questions(out, teacher_questions(Teacher(a.teacher), a.per, a.areas))} questions written by the teacher")
    else:
        qs = read_jsonl(out.path("questions.jsonl"))
        if not qs:
            sys.exit(f"no questions yet in {out.path('questions.jsonl')}: run the questions, maths or import command first")
        counts = run(qs, Teacher(a.teacher), out, constitution_text(), a.drafts, a.rounds, a.workers, a.limit)
        print(json.dumps(counts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
