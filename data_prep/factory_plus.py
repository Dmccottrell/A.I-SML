"""
factory_plus.py - What makes Lessons 4 much better than Lessons 3, on top of lesson_factory.py (docs/LESSONS_4.md, "Making Lessons 4 much better").

  probe          each Emvryx model (a "student" on its own llama-server) answers the questions; what it gets right is proved where it can be
                 (the known answer, code that passes its tests) and judged by the teacher otherwise. probe_<model>.jsonl.
  focus          `run --focus` answers the questions the students MISSED first, and only a small share of the ones every student already gets right:
                 the teacher's time goes where it changes the models.
  student pairs  a student's own wrong answer paired with the checked lesson for the same question: preference pairs that fix the model's real habits.
  selfcheck      a student writes several answers to questions with a provable answer; one that passes every check becomes a lesson in its own voice
                 (and a pass/fail pair). self_lessons.jsonl, pairs_self.jsonl.
  thinking       thinking lessons sized to the question: short reasoning for medium questions, longer only for hard ones; reasoning that runs too long is
                 condensed by the teacher and must still reach the proved answer (Solstice 3 thought too long and talked itself out of right answers).
  real use       the app's reports ("That didn't work", feedback.py export) become questions: real wording, real problems. Only the question is used.
  decontaminate  questions that overlap the test sets (HellaSwag, the hard and everyday sheets, the thinking check, the identity sheet) are taken out,
                 so the scores stay honest.
  near-duplicates  questions that say the same thing in other words are dropped (MinHash over word pairs), not just exact copies.
  tools          questions that come with the notes the app would look up (weather, a page, a calculation, a saved memory), so the lessons show how to
                 use them; and replies to a picture written the natural way, from the picture's description.
  quality        quality.md: pass rate, judge scores, what was proved, style problems, lengths and coverage by area, so each batch shows it is better.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import hashlib
import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor

import factory_checks as FC
import factory_questions as FQ

PROVED = ("answer matches the known answer", "code passed its tests")
KEEP_EASY = 0.15                     # share of the questions every student already gets right that are still answered (so nothing is forgotten)
THINK_BUDGET = {"medium": 1200, "hard": 4000}      # characters of reasoning a thinking lesson may keep, by level
EVAL_FILES = ("hard.jsonl", "everyday.jsonl", "identity_open.jsonl", "constraints.jsonl", "prompts_v3.jsonl", "web.jsonl")
NGRAM = 8                            # words in a row shared with a test question that make a question "seen in a test"


# ------------------------------------------------------------------ probe: what each model already gets right
def provable(q):
    return q.get("answer") not in (None, "") or bool(q.get("tests"))


def probe_one(q, student, judge_fn=None):
    """{"question_id", "ok", "how", "answer"} for one question: proved when it can be, else judged (ok = judge passes), else unknown (ok None)."""
    try:
        ans = student.chat(FQ_conversation(q), temperature=0.3, max_tokens=1500)["answer"]
    except Exception as e:                                         # noqa: BLE001 - a busy or crashed student: unknown, asked again next time
        return {"question_id": q["id"], "ok": None, "how": f"error: {e}"[:200], "answer": ""}
    c = FC.check(q, ans)
    if any(p in c["checked"] for p in PROVED) or (provable(q) and not c["ok"]):
        return {"question_id": q["id"], "ok": bool(c["ok"]), "how": "proved", "answer": ans}
    if judge_fn:
        s = judge_fn(q, ans)
        if s:
            return {"question_id": q["id"], "ok": bool(c["ok"]) and s["min"] >= 7 and s["avg"] >= 8.0, "how": f"judged {s['avg']}", "answer": ans}
    return {"question_id": q["id"], "ok": None, "how": "not checked", "answer": ans}


def FQ_conversation(q):
    """The question as a student or the teacher sees it (notes written into the message, as the app shows them)."""
    msgs = [m for m in q.get("messages", []) if m.get("role") in ("user", "assistant")]
    text = q["question"]
    if q.get("notes"):
        text = f"{text}\n\n[Notes the app found for this question]\n{q['notes']}"
    return msgs + [{"role": "user", "content": text}]


def probe(questions, student, out, name, judge_fn=None, workers=4, limit=None, log=print):
    """Each question once per student (resumes). Returns {"right", "wrong", "unknown"}."""
    path = f"probe_{safe(name)}.jsonl"
    done = {r["question_id"] for r in read(out.path(path)) if r.get("ok") is not None or r.get("how") == "not checked"}
    todo = [q for q in questions if q["id"] not in done][:limit or None]
    counts = {"right": 0, "wrong": 0, "unknown": 0}

    def one(q):
        r = probe_one(q, student, judge_fn)
        out.add(path, r)
        counts["right" if r["ok"] else "wrong" if r["ok"] is False else "unknown"] += 1
        n = sum(counts.values())
        if n % 50 == 0:
            log(f"  {name}: {n}/{len(todo)} probed, wrong {counts['wrong']}")
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(one, todo))
    return counts


def safe(name):
    return re.sub(r"[^\w.-]", "_", str(name))[:40]


def misses(out):
    """{question_id: how many students got it wrong} and {question_id: how many got it right}, over every probe file."""
    wrong, right = {}, {}
    for f in sorted(os.listdir(out.folder)) if os.path.isdir(out.folder) else []:
        if f.startswith("probe_") and f.endswith(".jsonl"):
            for r in read(os.path.join(out.folder, f)):
                d = wrong if r.get("ok") is False else right if r.get("ok") else None
                if d is not None:
                    d[r["question_id"]] = d.get(r["question_id"], 0) + 1
    return wrong, right


def focus_order(questions, out, keep_easy=KEEP_EASY, seed=7):
    """Questions in the order worth answering: missed by most students first, then never probed, then a small share of the ones all got right."""
    wrong, right = misses(out)
    rng = random.Random(seed)
    missed = sorted((q for q in questions if wrong.get(q["id"])), key=lambda q: -wrong[q["id"]])
    unknown = [q for q in questions if not wrong.get(q["id"]) and not right.get(q["id"])]
    easy = [q for q in questions if right.get(q["id"]) and not wrong.get(q["id"])]
    easy = rng.sample(easy, int(len(easy) * keep_easy))
    return missed + unknown + easy


# ------------------------------------------------------------------ the model's own mistakes, paired with the checked lesson
def student_pairs(out):
    """pairs_student.jsonl: for each question a student got wrong and the factory has a checked lesson for: chosen = the lesson, rejected = the student."""
    lessons = {l["question_id"]: l for l in read(out.path("lessons.jsonl"))}
    have = {(p["question_id"], p.get("model")) for p in read(out.path("pairs_student.jsonl"))}
    n = 0
    for f in sorted(os.listdir(out.folder)):
        if not (f.startswith("probe_") and f.endswith(".jsonl")):
            continue
        model = f[len("probe_"):-len(".jsonl")]
        for r in read(os.path.join(out.folder, f)):
            l = lessons.get(r["question_id"])
            if r.get("ok") is not False or not l or not r.get("answer") or (r["question_id"], model) in have:
                continue
            chosen = l["messages"][-1]["content"]
            if chosen.strip() == r["answer"].strip():
                continue
            out.add("pairs_student.jsonl", {"messages": l["messages"][:-1], "chosen": chosen, "rejected": r["answer"], "kind": l.get("kind"),
                                            "question_id": r["question_id"], "model": model, "why": f"{model} got this wrong ({r.get('how')})"})
            have.add((r["question_id"], model))
            n += 1
    return n


# ------------------------------------------------------------------ the model checks its own answers
def selfcheck(questions, student, out, name, samples=6, workers=4, limit=None, log=print):
    """For questions with a provable answer: `samples` tries by the student; one that passes every check becomes a lesson, and a pass/fail pair."""
    done = {r["question_id"] for r in read(out.path("self_done.jsonl")) if r.get("model") == safe(name)}
    todo = [q for q in questions if provable(q) and q["id"] not in done][:limit or None]
    counts = {"lessons": 0, "pairs": 0, "none_passed": 0}

    def one(q):
        tries = []
        for i in range(samples):
            try:
                a = student.chat(FQ_conversation(q), temperature=0.8, max_tokens=1500)["answer"]
            except Exception:                                      # noqa: BLE001
                continue
            tries.append((a, FC.check(q, a)))
        good = [t for t in tries if t[1]["ok"] and any(p in t[1]["checked"] for p in PROVED)]
        bad = [t for t in tries if not t[1]["ok"]]
        out.add("self_done.jsonl", {"question_id": q["id"], "model": safe(name), "passed": len(good), "tries": len(tries)})
        if not good:
            counts["none_passed"] += 1
            return
        best = min(good, key=lambda t: len(t[0]))                    # the shortest answer that is proved right
        convo = FQ_conversation(q)
        out.add("self_lessons.jsonl", {"messages": convo + [{"role": "assistant", "content": best[0]}], "kind": q.get("area", "general"), "level": q.get("level"),
                                       "source": f"self:{safe(name)}", "question_id": q["id"], "checked": best[1]["checked"]})
        counts["lessons"] += 1
        if bad:
            out.add("pairs_self.jsonl", {"messages": convo, "chosen": best[0], "rejected": bad[0][0], "kind": q.get("area", "general"), "question_id": q["id"],
                                         "model": safe(name), "why": "; ".join(bad[0][1]["problems"][:2])})
            counts["pairs"] += 1
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(one, todo))
    log(f"  {name}: self-checked {len(todo)}: {counts}")
    return counts


# ------------------------------------------------------------------ thinking sized to the question
def thinking_budget(level):
    return THINK_BUDGET.get(level)


def condense_prompt(q, thinking, answer, limit):
    return [{"role": "user", "content": f"Here is a question, a correct answer, and the reasoning that reached it. Rewrite the reasoning so it keeps only the "
             f"steps that matter, in under {limit} characters, plain and direct, still reaching exactly the same answer. Reply with the reasoning only.\n\n"
             f"QUESTION:\n{q['question']}\n\nREASONING:\n{thinking}\n\nANSWER:\n{answer}"}]


def sized_thinking(q, thinking, answer, teacher):
    """The reasoning to keep for a thinking lesson, within the level's budget (condensed by the teacher when too long), or None."""
    limit = thinking_budget(q.get("level"))
    thinking = (thinking or "").strip()
    if not limit or len(thinking) < 40:
        return None
    if len(thinking) <= limit:
        return thinking
    try:
        short = teacher.chat(condense_prompt(q, thinking, answer, limit), temperature=0.2, max_tokens=1500)["answer"].strip()
    except Exception:                                              # noqa: BLE001
        return None
    return short if 40 <= len(short) <= limit else None


# ------------------------------------------------------------------ questions from real use
def from_feedback(path):
    """Questions from the app's report export (feedback_export.jsonl): only the person's question, never the old answer or who sent it."""
    out = []
    for r in read(path):
        user = [m for m in r.get("messages", []) if m.get("role") == "user"]
        text = " ".join(str(user[-1].get("content", "")).split()) if user else ""
        if 8 <= len(text) <= 2000:
            out.append({"id": FQ.qid(text), "question": text, "area": "real_use", "level": "medium", "source": "feedback", "why_reported": r.get("kind")})
    return out


# ------------------------------------------------------------------ test sets kept out of the lessons
def words(text):
    return re.findall(r"[a-z0-9]+", str(text).lower())


def ngrams(text, n=NGRAM):
    w = words(text)
    return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def eval_texts(root=emvryx_paths.ROOT, hellaswag=True):
    """Every test question we score with: the sheets in eval/, the thinking check's problems and (when cached) HellaSwag."""
    texts = []
    for f in EVAL_FILES:
        for r in read(os.path.join(root, "eval", f)):
            texts.append(str(r.get("prompt") or r.get("question") or r.get("text") or ""))
    try:
        import reasoning_problems
        texts += [str(p.get("question", "")) for p in reasoning_problems.make_problems(140, 777)]     # what evaluation/thinking_check.py asks by default
    except Exception:                                              # noqa: BLE001 - the sheets are still covered
        pass
    if hellaswag:
        cached = os.path.join(root, "data", "benchmarks", "hellaswag_val.jsonl")
        for r in read(cached):
            texts.append(str(r.get("ctx", "")) + " " + " ".join(r.get("endings", [])[:1]))
    return [t for t in texts if t.strip()]


def decontaminate(questions, tests, n=NGRAM):
    """(kept, dropped): a question sharing n words in a row with any test question, or equal to one, is dropped."""
    grams, whole = set(), set()
    for t in tests:
        grams |= ngrams(t, n)
        whole.add(" ".join(words(t)))
    kept, dropped = [], []
    for q in questions:
        text = q["question"]
        (dropped if " ".join(words(text)) in whole or ngrams(text, n) & grams else kept).append(q)
    return kept, dropped


# ------------------------------------------------------------------ near-duplicates (the same question in other words)
def minhash(text, k=64):
    w = [x for x in words(text) if len(x) > 2]
    shingles = {" ".join(w[i:i + 2]) for i in range(max(1, len(w) - 1))} or {""}
    return [min(int(hashlib.md5(f"{i}|{s}".encode()).hexdigest()[:12], 16) for s in shingles) for i in range(k)]


def near_dupes(questions, threshold=0.6, k=64, bands=16):
    """(kept, dropped): a question whose MinHash agrees with an earlier one on at least `threshold` of the k values is dropped."""
    rows = k // bands
    buckets, sigs, kept, dropped = {}, [], [], []
    for q in questions:
        sig = minhash(q["question"], k)
        cands = set()
        for b in range(bands):
            cands |= buckets.get((b, tuple(sig[b * rows:(b + 1) * rows])), set())
        if any(sum(x == y for x, y in zip(sig, sigs[j])) / k >= threshold for j in cands):
            dropped.append(q)
            continue
        idx = len(sigs)
        sigs.append(sig)
        kept.append(q)
        for b in range(bands):
            buckets.setdefault((b, tuple(sig[b * rows:(b + 1) * rows])), set()).add(idx)
    return kept, dropped


def clean_questions(out, hellaswag=True, log=print):
    """Rewrite questions.jsonl without test questions and near-duplicates (the dropped ones go to questions_dropped.jsonl with the reason)."""
    qs = read(out.path("questions.jsonl"))
    kept, seen_in_test = decontaminate(qs, eval_texts(hellaswag=hellaswag))
    kept, dupes = near_dupes(kept)
    for q in seen_in_test:
        out.add("questions_dropped.jsonl", dict(q, dropped="overlaps a test question"))
    for q in dupes:
        out.add("questions_dropped.jsonl", dict(q, dropped="near-duplicate"))
    tmp = out.path("questions.jsonl.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(q, ensure_ascii=False) + "\n" for q in kept)
    os.replace(tmp, out.path("questions.jsonl"))
    log(f"questions: kept {len(kept)}, dropped {len(seen_in_test)} seen in tests and {len(dupes)} near-duplicates")
    return {"kept": len(kept), "tests": len(seen_in_test), "near_duplicates": len(dupes)}


# ------------------------------------------------------------------ questions with tool notes, and replies to pictures
TOOL_KINDS = {"weather": "a weather forecast for a named place and day", "web": "a short passage from a web page with its title and address",
              "calculator": "an exact calculation result", "memory": "facts the person asked Emvryx to remember earlier",
              "picture": "a description of a picture the person sent (what it shows and any words in it), with no question or only a short one"}


def tool_prompt(kind, n):
    return (f"Write {n} realistic situations for an AI assistant app. In each, the person sends a message and the app has already looked something up: "
            f"{TOOL_KINDS[kind]}. Write the person's message exactly as they would type it, and the notes the app found (plain text, realistic, specific). "
            "Return a JSON list of objects {\"question\": \"...\", \"notes\": \"...\"} and nothing else.")


def tool_questions(teacher, per=20, kinds=TOOL_KINDS, log=print):
    out = []
    for kind in kinds:
        try:
            reply = teacher.chat([{"role": "user", "content": tool_prompt(kind, per)}], temperature=0.9, max_tokens=4000)["answer"]
            rows = json.loads(re.search(r"\[.*\]", reply, re.S).group(0))
        except Exception as e:                                     # noqa: BLE001
            log(f"  tools/{kind}: {e}")
            continue
        got = [{"id": FQ.qid(r["question"] + "|" + r["notes"]), "question": str(r["question"]), "notes": str(r["notes"]),
                "area": "pictures" if kind == "picture" else "tools", "tool": kind, "level": "medium", "source": "teacher"}
               for r in rows if isinstance(r, dict) and str(r.get("question", "")).strip() and str(r.get("notes", "")).strip()]
        log(f"  tools/{kind}: {len(got)}")
        out += got
    return out


# ------------------------------------------------------------------ the files training reads
def export(out):
    """train.jsonl (the teacher's checked lessons, the models' own proved answers, the thinking lessons) and pairs_all.jsonl (every kind of pair),
    each question once per file kind. Returns the counts."""
    seen, rows = set(), []
    for name in ("lessons.jsonl", "self_lessons.jsonl", "thinking.jsonl"):
        for r in read(out.path(name)):
            key = (r.get("question_id"), r.get("kind") == "thinking", r.get("source", "")[:4])
            if key not in seen:
                seen.add(key)
                rows.append(r)
    pairs, pseen = [], set()
    for name in ("pairs.jsonl", "pairs_student.jsonl", "pairs_self.jsonl"):
        for r in read(out.path(name)):
            key = (r.get("question_id"), r.get("rejected", "")[:200])
            if key not in pseen:
                pseen.add(key)
                pairs.append(r)
    for name, data in (("train.jsonl", rows), ("pairs_all.jsonl", pairs)):
        with open(out.path(name), "w", encoding="utf-8") as f:
            f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in data)
    return {"train": len(rows), "pairs": len(pairs)}


# ------------------------------------------------------------------ quality report
def quality(out):
    """The numbers that show a batch is better: written to quality.md and returned."""
    import style_check
    lessons, rejected = read(out.path("lessons.jsonl")), read(out.path("rejected.jsonl"))
    selfl = read(out.path("self_lessons.jsonl"))
    total = len(lessons) + len(rejected)
    scores = [l.get("score") for l in lessons if isinstance(l.get("score"), (int, float))]
    lengths = sorted(len(l["messages"][-1]["content"]) for l in lessons) or [0]
    style = sum(1 for l in lessons for _rid, sev in style_check.check_lesson(l) if sev == "hard")
    by_area = {}
    for l in lessons:
        by_area[l.get("kind")] = by_area.get(l.get("kind"), 0) + 1
    thinking = read(out.path("thinking.jsonl"))
    think_len = sorted(len(t["messages"][-1]["content"].split("</think>")[0]) for t in thinking) or [0]
    wrong, right = misses(out)
    q = {"answered": total, "kept": len(lessons), "pass_rate": round(len(lessons) / total, 3) if total else 0,
         "avg_score": round(sum(scores) / len(scores), 2) if scores else 0, "proved_right": sum(1 for l in lessons if any(p in l.get("checked", []) for p in PROVED)),
         "style_problems": style, "median_chars": lengths[len(lengths) // 2], "self_checked_lessons": len(selfl),
         "pairs": len(read(out.path("pairs.jsonl"))), "student_pairs": len(read(out.path("pairs_student.jsonl"))), "self_pairs": len(read(out.path("pairs_self.jsonl"))),
         "thinking": len(thinking), "median_thinking_chars": think_len[len(think_len) // 2], "questions_missed_by_a_student": len(wrong),
         "by_area": dict(sorted(by_area.items(), key=lambda kv: -kv[1]))}
    lines = [f"# Lessons 4 quality ({time.strftime('%Y-%m-%d %H:%M')})", "",
             "| | |", "|---|---|"] + [f"| {k.replace('_', ' ')} | {v} |" for k, v in q.items() if k != "by_area"] + \
            ["", "## By area", "", "| area | lessons |", "|---|---|"] + [f"| {a} | {n} |" for a, n in q["by_area"].items()]
    with open(out.path("quality.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return q


def read(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
