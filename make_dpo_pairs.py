"""
make_dpo_pairs.py - Build "this answer is better than that one" pairs for preference training (dpo.py).

WHAT THIS FILE DOES
    The chat model (chat.pt) answers each practice question several times (a little randomness makes
    the answers differ). Each answer gets a score from rules we can CHECK, so no grader has to be
    trusted:

        lookup      notes that contain the answer -> how many of the answer's key facts (names,
                    numbers, rarer words from the teacher's answer) it uses; mentioning the known WRONG
                    answer costs a lot
        dont_know   notes that DON'T contain the answer -> it should say it doesn't know
        instruction "List 3 ...", "in 2 sentences" -> the count must match
        every kind  repeating itself, an empty answer, or never finishing (no end token) cost points

    The best and the worst answer to the same question become one pair, if their scores are clearly
    apart. Output: <data_dir>/dpo_pairs.jsonl, one pair per line:
        {"messages": [...the question, with its notes...], "chosen": "...", "rejected": "...", "kind": "lookup"}

    It uses the teacher's examples (make_teacher_data.py: lookup.jsonl, instructions.jsonl), so the
    questions come with known answers. A GPU helps: ~4 answers x 2,000 questions takes a few hours.

Usage:
    python make_dpo_pairs.py --version v3                  (2,000 questions, 4 answers each)
    python make_dpo_pairs.py --version v3 --n 500 --samples 6
"""
import argparse
import json
import os
import random
import re

import torch

STOP = set("the a an of in on at to for from by with and or is are was were be been it its this that "
           "which who whom what when where why how as into than then there their they he she his her".split())
UNSURE = ["don't know", "do not know", "not sure", "doesn't say", "don't mention", "doesn't mention",
          "couldn't find", "can't find", "no information", "not in my notes", "don't cover", "don't have"]
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10}
MARGIN = 0.3            # scores (0-1) must differ by at least this to make a pair


# ------------------------------------------------------------------ scoring rules
def key_terms(text):
    """The words that carry an answer's facts: numbers, capitalized names, and longer rarer words."""
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", text)
    keys = {w.lower() for w in words if any(c.isdigit() for c in w) or (w[0].isupper() and w.lower() not in STOP)}
    keys |= {w.lower() for w in words if len(w) >= 7 and w.lower() not in STOP}
    return keys


def repetition_penalty(text):
    """0 for varied text, up to 1 for text that keeps repeating the same 3-word phrases."""
    words = text.lower().split()
    grams = [tuple(words[i:i + 3]) for i in range(len(words) - 2)]
    if len(grams) < 6:
        return 0.0
    return max(0.0, 1.0 - len(set(grams)) / len(grams) - 0.1)


def base_penalty(text, finished):
    p = repetition_penalty(text)
    if not text.strip():
        p += 1.0
    if not finished:
        p += 0.3                              # ran out of room instead of ending the answer
    return p


def score_lookup(text, answer, wrong):
    keys = key_terms(answer)
    if not keys:
        return 0.0
    low = text.lower()
    s = sum(k in low for k in keys) / len(keys)
    wrong_keys = key_terms(wrong) - keys
    if wrong_keys and sum(k in low for k in wrong_keys) / len(wrong_keys) >= 0.5:
        s -= 0.7                              # it used the known wrong answer
    if any(u in low for u in UNSURE) and s < 0.5:
        s -= 0.2                              # "I don't know" when the notes DO have it
    return s


def score_dont_know(text):
    low = text.lower()
    return 1.0 if any(u in low for u in UNSURE) else 0.0


def wanted_count(prompt):
    """("items", 3) for "List 3 ...", ("sentences", 2) for "in two sentences", or None."""
    m = re.search(r"\b(\d+|" + "|".join(NUMBER_WORDS) + r")\s+(\w+\s+)?(sentences?)\b", prompt, re.I)
    if m:
        return "sentences", int(m.group(1)) if m.group(1).isdigit() else NUMBER_WORDS[m.group(1).lower()]
    m = re.search(r"\b(?:list|give|name|write)\s+(?:me\s+)?(\d+|" + "|".join(NUMBER_WORDS) + r")\b", prompt, re.I)
    if m:
        return "items", int(m.group(1)) if m.group(1).isdigit() else NUMBER_WORDS[m.group(1).lower()]
    return None


def score_instruction(text, prompt):
    want = wanted_count(prompt)
    if not want:
        return None                           # nothing we can check: no pair from this one
    kind, n = want
    if kind == "sentences":
        got = len(re.findall(r"[.!?](\s|$)", text.strip()))
    else:
        got = len([l for l in text.splitlines() if re.match(r"^\s*(\d+[.)]|[-*•])\s", l)])
    return 1.0 if got == n else max(0.0, 1.0 - abs(got - n) / max(n, 1))


# ------------------------------------------------------------------ questions
def build_questions(lookup, instructions, wiki, rng, n):
    """[(kind, messages, check)] mixed from the teacher's examples."""
    import make_chat_data_v3 as D
    out = []
    for rec in lookup:
        if rng.random() < 0.7:
            out.append(("lookup", [D.user(rec["question"], D.notes_for(rec, wiki, rng))],
                        {"answer": rec["answer"], "wrong": rec.get("wrong_answer", "")}))
        else:
            notes = D.unrelated_notes(rec, lookup, wiki, rng)
            if notes:
                out.append(("dont_know", [D.user(rec["question"], notes)], {}))
    for rec in instructions:
        if wanted_count(rec["prompt"]):
            out.append(("instruction", [D.user(rec["prompt"])], {"prompt": rec["prompt"]}))
    rng.shuffle(out)
    return out[:n]


def score(kind, text, finished, check):
    if kind == "lookup":
        s = score_lookup(text, check["answer"], check["wrong"])
    elif kind == "dont_know":
        s = score_dont_know(text)
    else:
        s = score_instruction(text, check["prompt"])
        if s is None:
            return None
    return s - base_penalty(text, finished)


def pick_pair(scored, margin=MARGIN):
    """(chosen, rejected) from [(score, text)], or None if the best and worst aren't clearly apart."""
    scored = [x for x in scored if x[0] is not None]
    if len(scored) < 2:
        return None
    best, worst = max(scored), min(scored)
    if best[0] - worst[0] < margin or best[1].strip() == worst[1].strip():
        return None
    return best[1], worst[1]


def main():
    from chat import build_prompt, special_ids, split_memory_calls
    from config import add_version_arg, get_version
    from model import load_checkpoint
    from tokenizer import BPETokenizer
    p = argparse.ArgumentParser()
    add_version_arg(p)
    p.add_argument("--ckpt", default=None, help="the chat model (default: <ckpt_dir>/chat.pt)")
    p.add_argument("--n", type=int, default=2000, help="questions")
    p.add_argument("--samples", type=int, default=4, help="answers per question")
    p.add_argument("--tokens", type=int, default=200)
    p.add_argument("--temperature", type=float, default=0.9)
    p.add_argument("--db", default=os.path.join("data", "wiki", "wiki.db"))
    p.add_argument("--teacher_dir", default=None, help="default: <data_dir>/teacher, else v3's")
    p.add_argument("--seed", type=int, default=7)
    a = p.parse_args()
    V = get_version(a.version)
    tdir = a.teacher_dir or os.path.join(V.data_dir, "teacher")
    if not os.path.isdir(tdir):
        tdir = os.path.join(get_version("v3").data_dir, "teacher")     # later versions reuse v3's examples

    def read(name):
        path = os.path.join(tdir, name)
        if not os.path.exists(path):
            print(f"(no {path}: skipping those questions)")
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]

    wiki = None
    if os.path.exists(a.db):
        from wiki_index import WikiIndex
        wiki = WikiIndex(a.db)
    rng = random.Random(a.seed)
    questions = build_questions(read("lookup.jsonl"), read("instructions.jsonl"), wiki, rng, a.n)
    if not questions:
        raise SystemExit("no questions: run make_teacher_data.py first (lookup and instructions tasks)")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, _ = load_checkpoint(a.ckpt or os.path.join(V.ckpt_dir, "chat.pt"), device)
    tok = BPETokenizer.load(os.path.join(V.data_dir, "tokenizer.json"))
    _, _, eot = special_ids(tok)
    out_path = os.path.join(V.data_dir, "dpo_pairs.jsonl")
    prog_path = out_path + ".progress"                 # resumable: the next question to do
    done = 0
    if os.path.exists(prog_path) and os.path.exists(out_path):
        with open(prog_path) as f:
            done = int(f.read().strip() or 0)
        print(f"resuming at question {done:,}")
    made = 0
    counts = {}
    with open(out_path, "a", encoding="utf-8") as f:
        for qi in range(done, len(questions)):
            kind, messages, check = questions[qi]
            ids = build_prompt(tok, messages, model.cfg.max_seq_len - a.tokens)
            scored = []
            for s in range(a.samples):
                torch.manual_seed(a.seed * 100_003 + qi * 17 + s)
                idx = torch.tensor([ids], device=device)
                out = model.generate(idx, a.tokens, a.temperature, 50, stop_id=eot, repetition_penalty=1.1)
                new = out[0, idx.size(1):].tolist()
                finished = bool(new) and new[-1] == eot
                text, _ = split_memory_calls(tok.decode(new).replace("<|endoftext|>", ""))
                scored.append((score(kind, text, finished, check), text.strip()))
            pair = pick_pair(scored)
            if pair:
                f.write(json.dumps({"q": qi, "kind": kind, "messages": messages, "chosen": pair[0],
                                    "rejected": pair[1]}, ensure_ascii=False) + "\n")
                f.flush()
                made += 1
                counts[kind] = counts.get(kind, 0) + 1
            with open(prog_path, "w") as pf:
                pf.write(str(qi + 1))
            if qi % 50 == 0:
                print(f"question {qi:,}/{len(questions):,}: {made:,} pairs so far {counts}", flush=True)
    print(f"done: {made:,} new pairs in {out_path} {counts}")


if __name__ == "__main__":
    main()
