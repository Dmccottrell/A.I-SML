"""
evaluate.py - Score a model on a fixed test sheet (eval/prompts.jsonl).

WHAT THIS FILE DOES
    Asks the model the same 20 questions every time (facts, explanations,
    advice, writing, stories, identity) and checks each answer for an
    expected keyword, e.g. "Paris" for "What is the capital of France?".
    It prints a score per category and saves every answer to a report, so
    you can compare versions and checkpoints side by side.

    Keyword checks are rough: a right answer worded differently can be
    marked wrong, and a lucky word can be marked right. Read the report too!

Usage:  python evaluate.py                        (v1 chat model)
        python evaluate.py --version v2
        python evaluate.py --version v2 --ckpt checkpoints/dev/v2/ckpt.pt

The report is saved next to the checkpoint: eval_<checkpoint name>.md
"""
import argparse, json, os
from collections import defaultdict

import torch

from chat import build_prompt, special_ids
from config import add_version_arg, get_version
from model import load_checkpoint
from tokenizer import BPETokenizer

p = argparse.ArgumentParser()
add_version_arg(p)
p.add_argument("--ckpt", default=None, help="default: chat.pt of the chosen version")
p.add_argument("--prompts", default="eval/prompts.jsonl")
p.add_argument("--tokens", type=int, default=150)
args = p.parse_args()
V = get_version(args.version)
ckpt_path = args.ckpt or os.path.join(V.ckpt_dir, "chat.pt")

device = "cuda" if torch.cuda.is_available() else "cpu"
model, _ = load_checkpoint(ckpt_path, device)
tok = BPETokenizer.load(os.path.join(V.data_dir, "tokenizer.json"))
_, _, eot = special_ids(tok)

with open(args.prompts, encoding="utf-8") as f:
    tests = [json.loads(line) for line in f if line.strip()]


def answer(question):
    """Ask one question in a fresh conversation. Fixed seed + low temperature = repeatable."""
    torch.manual_seed(0)
    ids = build_prompt(tok, [{"role": "user", "content": question}], model.cfg.max_seq_len - args.tokens)
    idx = torch.tensor([ids], device=device)
    out = model.generate(idx, args.tokens, temperature=0.5, top_k=40, stop_id=eot)
    return tok.decode(out[0, idx.size(1):].tolist()).replace("<|endoftext|>", "").strip()


passed = defaultdict(int)
total = defaultdict(int)
lines = [f"# Evaluation: {ckpt_path}\n"]
for t in tests:
    reply = answer(t["prompt"])
    ok = any(k.lower() in reply.lower() for k in t["expect"])
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

report = os.path.join(os.path.dirname(ckpt_path), f"eval_{os.path.splitext(os.path.basename(ckpt_path))[0]}.md")
with open(report, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("report saved to", report)
