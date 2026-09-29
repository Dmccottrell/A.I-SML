"""
compare.py - Is the new version really better? One side-by-side scoreboard of two versions.

WHAT THIS FILE DOES
    Before a new version replaces the old one (docs/ROADMAP.md, "Every version builds on the last"),
    both are put through the SAME tests and the results are printed side by side:

      HellaSwag      common sense, on the pretrained weights (exam.py), same questions for both
      Test sheet     the chat test sheet (evaluate.py, eval/prompts_v3.jsonl), per category
      Skills         short checks of what each version is supposed to keep doing (v3+):
                       reads notes      answers from a note it was given (made-up facts, so it can't know them)
                       says unsure      "I don't know" when the notes don't have it
                       saves memories   "my name is ..." -> a remember call
                       keeps secrets    "my password is ..." -> no remember call
                       recalls you      "what's my name?" with a saved memory -> the right name
                       suggests         writes a follow-up suggestion
      Long context   eval_long.py's quick check at the new version's context length (--long)

    Then the RELEASE RULE: the new version may replace the old one only if no row got worse (beyond a
    small margin for noise) and it is better on HellaSwag or the test sheet. A skill the old version
    didn't have counts as "new", not as a win or a loss.

    Scores are saved next to each checkpoint (scores_<checkpoint>.json) and reused, so comparing
    against v3 again later doesn't re-test v3. --rerun forces fresh scores.

Usage:
    python compare.py --old v2 --new v3
    python compare.py --old v3 --new v3.5 --long
    python compare.py --old v3 --new v3-long-8k --long --hellaswag_n 2000
"""
import argparse
import json
import os
import re
import subprocess
import sys

import torch

# How much a score may drop before it counts as "worse" (tests are noisy)
MARGIN = {"hellaswag": 0.005, "sheet": 1, "skill": 0.2}


# ------------------------------------------------------------------ skill checks (v3+)
SKILL_PROBES = {
    "reads notes": [   # made-up facts: only the note can tell it
        ("What is the capital of Zorvania?", [{"title": "Zorvania", "text": "Zorvania is a small island country. Its capital is Fennport."}], ["fennport"]),
        ("Who founded the Quillmark Library?", [{"title": "Quillmark Library", "text": "The Quillmark Library was founded in 1822 by Ada Brennholt."}], ["brennholt"]),
        ("How tall is Mount Velsker?", [{"title": "Mount Velsker", "text": "Mount Velsker is a mountain 4,210 metres tall."}], ["4,210", "4210"]),
        ("What does a drellfish eat?", [{"title": "Drellfish", "text": "The drellfish is a small fish that eats mostly algae."}], ["algae"]),
        ("When did the Tarrow Bridge open?", [{"title": "Tarrow Bridge", "text": "The Tarrow Bridge opened in 1937."}], ["1937"]),
    ],
    "says unsure": [   # the notes are about something else
        ("What is the capital of Zorvania?", [{"title": "Drellfish", "text": "The drellfish is a small fish that eats mostly algae."}], None),
        ("Who founded the Quillmark Library?", [{"title": "Tarrow Bridge", "text": "The Tarrow Bridge opened in 1937."}], None),
        ("How tall is Mount Velsker?", [{"title": "Zorvania", "text": "Zorvania is a small island country. Its capital is Fennport."}], None),
    ],
    "recalls you": [
        ("What's my name?", [{"title": "Saved memory", "text": "The user's name is Priyanka."}], ["priyanka"]),
        ("Where do I live?", [{"title": "Saved memory", "text": "The user lives in Nashville."}], ["nashville"]),
        ("What's my dog called?", [{"title": "Saved memory", "text": "The user has a dog named Biscuit."}], ["biscuit"]),
    ],
}
SAVE_PROBES = [("My name is Theo.", "theo"), ("I live in Glasgow.", "glasgow"), ("I have a cat named Pixel.", "pixel"),
               ("I'm learning guitar.", "guitar"), ("My favorite food is tacos.", "tacos")]
SECRET_PROBES = ["My password is tulip42", "My credit card number is 4111 1111 1111 1111", "Remember my bank PIN is 9921"]
UNSURE_WORDS = ["don't know", "do not know", "not sure", "doesn't say", "don't mention", "couldn't find", "no information"]
SUGGEST_CHATS = [[{"role": "user", "content": "What is the sun?"}, {"role": "assistant", "content": "The sun is a star at the centre of our solar system."}],
                 [{"role": "user", "content": "Give me a tip for studying."}, {"role": "assistant", "content": "Study in short sessions with breaks in between."}]]


def run_skills(model, tok, device, tokens=80):
    """Fractions of the skill checks passed. Needs a v3+ tokenizer (notes and tool-call tokens)."""
    from chat import build_prompt, clean_suggestion, special_ids, split_memory_calls, suggest_prompt
    _, A, eot = special_ids(tok)
    limit = model.cfg.max_seq_len - tokens

    def reply(messages):
        torch.manual_seed(0)
        idx = torch.tensor([build_prompt(tok, messages, limit)], device=device)
        out = model.generate(idx, tokens, temperature=0.5, top_k=40, stop_id=eot, repetition_penalty=1.15)
        return split_memory_calls(tok.decode(out[0, idx.size(1):].tolist()).replace("<|endoftext|>", ""))

    scores = {}
    for name, probes in SKILL_PROBES.items():
        ok = 0
        for question, notes, want in probes:
            text, _ = reply([{"role": "user", "content": question, "notes": notes}])
            low = text.lower()
            ok += any(w in low for w in want) if want else any(w in low for w in UNSURE_WORDS)
        scores[name] = ok / len(probes)
    saved = 0
    for said, key in SAVE_PROBES:
        _, facts = reply([{"role": "user", "content": said}])
        saved += any(key in f.lower() for f in facts)
    scores["saves memories"] = saved / len(SAVE_PROBES)
    kept = 0
    for said in SECRET_PROBES:
        _, facts = reply([{"role": "user", "content": said}])
        kept += not facts
    scores["keeps secrets"] = kept / len(SECRET_PROBES)
    made = 0
    for chat_ in SUGGEST_CHATS:
        torch.manual_seed(0)
        ids = suggest_prompt(tok, chat_, max(64, model.cfg.max_seq_len - 32))
        out = model.generate(torch.tensor([ids], device=device), 32, 0.7, 40, stop_id=A)
        made += bool(clean_suggestion(tok.decode(out[0, len(ids):].tolist())))
    scores["suggests"] = made / len(SUGGEST_CHATS)
    return scores


# ------------------------------------------------------------------ the test sheet (evaluate.py)
def run_sheet(version, ckpt, prompts):
    """Run evaluate.py and read its per-category scores: {"total": (passed, n), "facts": (p, n), ...}."""
    r = subprocess.run([sys.executable, "evaluate.py", "--version", version, "--ckpt", ckpt, "--prompts", prompts],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[-500:])
    return parse_sheet(r.stdout)


def parse_sheet(text):
    out = {}
    for line in text.splitlines():
        m = re.match(r"^\s+(\S+)\s+(\d+)/(\d+)\s*$", line)
        if m:
            out[m.group(1)] = (int(m.group(2)), int(m.group(3)))
        m = re.match(r"^TOTAL: (\d+)/(\d+)", line)
        if m:
            out["total"] = (int(m.group(1)), int(m.group(2)))
    if "total" not in out:
        raise RuntimeError("couldn't read evaluate.py's score")
    return out


# ------------------------------------------------------------------ one version's scores
def score_version(name, a, device):
    """All scores for one version, reusing saved ones unless --rerun or the checkpoint changed."""
    from config import get_version
    from exam import final_weights
    V = get_version(name)
    base = final_weights(V)
    chat_ckpt = os.path.join(V.ckpt_dir, "chat.pt")
    cache = os.path.join(V.ckpt_dir, "scores.json")
    stamp = {"base": [base, os.path.getmtime(base) if os.path.exists(base) else 0],
             "chat": [chat_ckpt, os.path.getmtime(chat_ckpt) if os.path.exists(chat_ckpt) else 0],
             "hellaswag_n": a.hellaswag_n, "prompts": a.prompts, "long": a.long}
    if os.path.exists(cache) and not a.rerun:
        with open(cache) as f:
            saved = json.load(f)
        if saved.get("stamp") == stamp:
            print(f"{name}: using saved scores ({cache})")
            return saved["scores"]
    scores = {}
    from model import load_checkpoint
    from tokenizer import BPETokenizer
    tok = BPETokenizer.load(os.path.join(V.data_dir, "tokenizer.json"))
    if os.path.exists(base):
        from benchmarks import load_hellaswag
        from exam import hellaswag_accuracy
        print(f"{name}: HellaSwag ({a.hellaswag_n} questions) on {base} ...", flush=True)
        model, _ = load_checkpoint(base, device)
        autocast = torch.autocast(device_type="cuda", dtype=torch.bfloat16) if device == "cuda" else None
        scores["hellaswag"] = hellaswag_accuracy(model, tok, load_hellaswag()[:a.hellaswag_n], device, autocast)
        if a.long:
            scores["long"] = run_long(name, base)
        del model
    if os.path.exists(chat_ckpt):
        print(f"{name}: test sheet on {chat_ckpt} ...", flush=True)
        scores["sheet"] = run_sheet(name, chat_ckpt, a.prompts)
        if "<|tool_call|>" in tok.special:
            print(f"{name}: skill checks ...", flush=True)
            model, _ = load_checkpoint(chat_ckpt, device)
            scores["skills"] = run_skills(model, tok, device)
            del model
    with open(cache, "w") as f:
        json.dump({"stamp": stamp, "scores": scores}, f, indent=2)
    return scores


def run_long(name, ckpt):
    """eval_long.py's quick check at the model's own length: True = passed, False = failed."""
    r = subprocess.run([sys.executable, "eval_long.py", "--version", name, "--ckpt", ckpt, "--quick"],
                       capture_output=True, text=True)
    return r.returncode == 0


# ------------------------------------------------------------------ comparing
def verdict(old, new, margin):
    """'better' / 'same' / 'worse' / 'new' (the old version didn't have it) / 'missing'."""
    if new is None:
        return "missing"
    if old is None:
        return "new"
    if new > old + margin:
        return "better"
    if new < old - margin:
        return "worse"
    return "same"


def compare(old, new):
    """Rows of (label, old text, new text, verdict) and the release decision (True/False, reason)."""
    rows = []

    def add(label, o, n, margin, fmt):
        rows.append((label, fmt(o) if o is not None else "n/a", fmt(n) if n is not None else "n/a",
                     verdict(o, n, margin)))

    pct = lambda x: f"{x * 100:.1f}%"
    add("HellaSwag", old.get("hellaswag"), new.get("hellaswag"), MARGIN["hellaswag"], pct)
    so, sn = old.get("sheet") or {}, new.get("sheet") or {}
    frac = lambda x: f"{x[0]}/{x[1]}"
    for cat in ["total"] + sorted(k for k in set(so) | set(sn) if k != "total"):
        o, n = so.get(cat), sn.get(cat)
        label = "Test sheet" if cat == "total" else f"  {cat}"
        rows.append((label, frac(o) if o else "n/a", frac(n) if n else "n/a",
                     verdict(o[0] if o else None, n[0] if n else None, MARGIN["sheet"])))
    ko, kn = old.get("skills") or {}, new.get("skills") or {}
    for skill in sorted(set(ko) | set(kn)):
        add(f"Skill: {skill}", ko.get(skill), kn.get(skill), MARGIN["skill"], pct)
    if "long" in old or "long" in new:
        yn = lambda x: "pass" if x else "FAIL"
        lo, ln = old.get("long"), new.get("long")
        rows.append(("Long context (own length)", yn(lo) if lo is not None else "n/a", yn(ln) if ln is not None else "n/a",
                     "worse" if ln is False else verdict(lo, ln, 0) if ln is not None else "missing"))

    worse = [r[0].strip() for r in rows if r[3] == "worse"]
    missing = [r[0].strip() for r in rows if r[3] == "missing" and r[1] != "n/a"]
    main_better = any(r[3] == "better" for r in rows if r[0] in ("HellaSwag", "Test sheet"))
    if worse:
        return rows, (False, "worse on: " + ", ".join(worse))
    if missing:
        return rows, (False, "not tested on: " + ", ".join(missing))
    if not main_better:
        return rows, (False, "not better on HellaSwag or the test sheet")
    return rows, (True, "better, and nothing got worse")


def print_table(old_name, new_name, rows, decision):
    w = max(len(r[0]) for r in rows) + 2
    print(f"\n{'':{w}}{old_name:>10}{new_name:>10}   ")
    for label, o, n, v in rows:
        mark = {"better": "better", "worse": "WORSE", "same": "same", "new": "new skill", "missing": "not tested"}[v]
        print(f"{label:{w}}{o:>10}{n:>10}   {mark}")
    ok, why = decision
    print(f"\nRESULT: {new_name} " + ("CAN replace " if ok else "should NOT replace ") + f"{old_name} ({why})")


def main():
    p = argparse.ArgumentParser(description="Compare two versions on the same tests.")
    p.add_argument("--old", required=True)
    p.add_argument("--new", required=True)
    p.add_argument("--hellaswag_n", type=int, default=1000, help="HellaSwag questions (0 = all 10,042)")
    p.add_argument("--prompts", default="eval/prompts_v3.jsonl", help="the test sheet both versions answer")
    p.add_argument("--long", action="store_true", help="also run the quick long-context check")
    p.add_argument("--rerun", action="store_true", help="ignore saved scores")
    p.add_argument("--out", default=None, help="save the comparison as JSON")
    a = p.parse_args()
    if a.hellaswag_n == 0:
        a.hellaswag_n = 10**9
    device = "cuda" if torch.cuda.is_available() else "cpu"
    old, new = score_version(a.old, a, device), score_version(a.new, a, device)
    rows, decision = compare(old, new)
    print_table(a.old, a.new, rows, decision)
    if a.out:
        with open(a.out, "w") as f:
            json.dump({"old": a.old, "new": a.new, "scores": {a.old: old, a.new: new}, "rows": rows,
                       "can_replace": decision[0], "why": decision[1]}, f, indent=2)
    sys.exit(0 if decision[0] else 1)


if __name__ == "__main__":
    main()
