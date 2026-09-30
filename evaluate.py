"""
evaluate.py - Score a model on a fixed test sheet (eval/prompts.jsonl).

WHAT THIS FILE DOES
    Asks the model the same 20 questions every time (facts, explanations,
    advice, writing, stories, identity) and checks each answer for an
    expected keyword, e.g. "Paris" for "What is the capital of France?".
    It prints a score per category and saves every answer to a report, so
    you can compare versions and checkpoints side by side.

    v3+ use a bigger sheet, eval/prompts_v3.jsonl: the original 20 questions
    plus the mistakes found by testing v2 on a phone. Extra fields a test can have:
      "not":     words that make the answer WRONG ("chicago" for Illinois's capital)
      "history": earlier messages in the chat (topic switches, corrections)
      "count":   the answer must be a list of exactly this many items
      "sentences": the answer must have exactly this many sentences
    --lookup gives the model Wikipedia notes for each question (v3+).

    Keyword checks are rough: a right answer worded differently can be
    marked wrong, and a lucky word can be marked right. Read the report too!

Usage:  python evaluate.py                        (v1 chat model)
        python evaluate.py --version v2
        python evaluate.py --version v2 --ckpt checkpoints/dev/v2/ckpt.pt
        python evaluate.py --version v3 --lookup
        python evaluate.py --version v2 --prompts eval/prompts_v3.jsonl   (v2 on v3's sheet)
        python evaluate.py --version v3 --skill study     (with a skill pack on: did everyday answers get worse?)

The report is saved next to the checkpoint: eval_<checkpoint name>.md
"""
import argparse, json, os, re
from collections import defaultdict

import torch

from chat import build_prompt, special_ids
from config import add_version_arg, get_version
from model import load_checkpoint
from tokenizer import BPETokenizer

p = argparse.ArgumentParser()
add_version_arg(p)
p.add_argument("--ckpt", default=None, help="default: chat.pt of the chosen version")
p.add_argument("--prompts", default=None, help="default: prompts.jsonl (v1, v2), prompts_v3.jsonl (v3+)")
p.add_argument("--lookup", action="store_true", help="give the model Wikipedia notes (v3+)")
p.add_argument("--db", default=os.path.join("data", "wiki", "wiki.db"))
p.add_argument("--tokens", type=int, default=150)
p.add_argument("--repetition_penalty", type=float, default=1.15)
p.add_argument("--skill", default=None, help="switch on this skill pack (skills.py) for every question")
args = p.parse_args()
V = get_version(args.version)
ckpt_path = args.ckpt or os.path.join(V.ckpt_dir, "chat.pt")
if args.prompts is None:
    args.prompts = "eval/prompts.jsonl" if V.name in ("v1", "v2") else "eval/prompts_v3.jsonl"
wiki = None
if args.lookup:
    from wiki_index import WikiIndex
    wiki = WikiIndex(args.db)

device = "cuda" if torch.cuda.is_available() else "cpu"
model, _ = load_checkpoint(ckpt_path, device)
tok = BPETokenizer.load(os.path.join(V.data_dir, "tokenizer.json"))
_, _, eot = special_ids(tok)
if args.skill:
    from skills import load_pack, pack_path
    load_pack(model, pack_path(V.ckpt_dir, args.skill))

with open(args.prompts, encoding="utf-8") as f:
    tests = [json.loads(line) for line in f if line.strip()]


def answer(question, history=()):
    """Ask one question in a fresh conversation (after `history`, if any).

    Fixed seed + low temperature = repeatable.
    """
    torch.manual_seed(0)
    message = {"role": "user", "content": question}
    if wiki:
        notes = wiki.search(question, 3)
        if notes:
            message["notes"] = [{"title": n["title"], "text": n["text"]} for n in notes]
    ids = build_prompt(tok, list(history) + [message], model.cfg.max_seq_len - args.tokens)
    idx = torch.tensor([ids], device=device)
    out = model.generate(idx, args.tokens, temperature=0.5, top_k=40, stop_id=eot,
                         repetition_penalty=args.repetition_penalty)
    return tok.decode(out[0, idx.size(1):].tolist()).replace("<|endoftext|>", "").strip()


passed = defaultdict(int)
total = defaultdict(int)
lines = [f"# Evaluation: {ckpt_path}" + (f" + skill pack {args.skill}" if args.skill else "") + "\n"]
def check(t, reply):
    """True if `reply` passes test `t` (see the extra fields at the top of this file)."""
    low = reply.lower()
    ok = not t.get("expect") or any(k.lower() in low for k in t["expect"])
    ok = ok and not any(k.lower() in low for k in t.get("not", []))
    if "count" in t:
        lines = [l.strip() for l in reply.splitlines() if l.strip()]
        items = [l for l in lines if re.match(r"^(\d+[.)]|[-*•])\s", l)]
        ok = ok and len(items) == t["count"]
    if "sentences" in t:
        ok = ok and len(re.findall(r"[.!?](\s|$)", reply.strip())) == t["sentences"]
    return ok


for t in tests:
    reply = answer(t["prompt"], t.get("history", []))
    ok = check(t, reply)
    passed[t["category"]] += ok
    total[t["category"]] += 1
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {t['prompt']}\n       {reply[:150]!r}")
    lines.append(f"## [{mark}] {t['prompt']}\n\n{reply}\n")

print("\nscore by category:")
summary = []
for cat in total:
    summary.append(f"- {cat}: {passed[cat]}/{total[cat]}")
    print(f"  {cat:10s} {passed[cat]}/{total[cat]}")
score = f"TOTAL: {sum(passed.values())}/{sum(total.values())}"
print(score)
lines[1:1] = ["\n".join(summary) + f"\n\n**{score}**\n"]

report = os.path.join(os.path.dirname(ckpt_path), f"eval_{os.path.splitext(os.path.basename(ckpt_path))[0]}"
                      + (f"_{args.skill}" if args.skill else "") + ".md")
with open(report, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("report saved to", report)
