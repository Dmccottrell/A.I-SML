"""
evaluate_open.py - Run one of our test sheets (eval/*.jsonl) on an OPEN model (Qwen, with or without our LoRA add-on).

WHAT THIS FILE DOES
    evaluate.py only runs our own from-scratch checkpoints. This runs the same sheets and the same pass / fail rules (eval_checks.py) on a
    Hugging Face model, using the same chat format the app uses (chat.py with the ChatML tokenizer), so what it scores is what a person gets.
    A fixed seed and a low temperature make a run repeatable. It prints PASS / FAIL for every test and a score per category.

Usage:  python evaluation/evaluate_open.py --model flare-2.5 --tuned                               (base + our adapter, on eval/identity_open.jsonl)
        python evaluation/evaluate_open.py --model flare-2.5                                       (the plain base: what Qwen says without our lessons)
        python evaluation/evaluate_open.py --model flare-2.5 --tuned --prompts eval/constraints.jsonl     (the rules sheet)
        python evaluation/evaluate_open.py --model export/open/flare-2.5/my-ai --prompts eval/prompts_v3.jsonl
    Sheets whose tests carry "notes" (lookup tests) get them as the app would. There is no Wikipedia lookup here (--lookup is evaluate.py's).
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import argparse
import json
import os
import sys
from collections import defaultdict

import torch

from chat import build_prompt
from eval_checks import check
from open_tokenizer import OpenTokenizer


def reply_to(model, tok, hf_tok, history, max_new_tokens, temperature, device, window=8192):
    """The model's reply to the last message of `history`, built exactly as the chat app builds the prompt."""
    ids = build_prompt(tok, history, window - max_new_tokens)
    x = torch.tensor([ids], device=device)
    kw = dict(do_sample=temperature > 0, max_new_tokens=max_new_tokens, eos_token_id=tok.special["<|im_end|>"],
              pad_token_id=hf_tok.pad_token_id if hf_tok.pad_token_id is not None else tok.special["<|im_end|>"],
              attention_mask=torch.ones_like(x))
    if temperature > 0:
        kw.update(temperature=temperature, top_p=0.9)
    with torch.no_grad():
        out = model.generate(x, **kw)
    return hf_tok.decode(out[0, x.size(1):], skip_special_tokens=True).strip()


def run_sheet(model, tok, hf_tok, tests, max_new_tokens, temperature, device):
    """([(test, reply, ok)], {category: [passed, total]})."""
    results, tally = [], defaultdict(lambda: [0, 0])
    for t in tests:
        torch.manual_seed(0)
        message = {"role": "user", "content": t["prompt"]}
        if t.get("notes"):
            message["notes"] = t["notes"]
        reply = reply_to(model, tok, hf_tok, list(t.get("history", [])) + [message], max_new_tokens, temperature, device)
        ok = check(t, reply)
        results.append((t, reply, ok))
        tally[t["category"]][0] += int(ok)
        tally[t["category"]][1] += 1
    return results, tally


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default="flare-2.5", help="a preset, a Hugging Face id, or a local folder")
    p.add_argument("--adapter", default=None, help="our LoRA adapter folder")
    p.add_argument("--tuned", action="store_true", help="use our adapter (found from the preset name; the old folder name works too)")
    p.add_argument("--prompts", default="eval/identity_open.jsonl")
    p.add_argument("--tokens", type=int, default=256)
    p.add_argument("--temperature", type=float, default=0.3)
    p.add_argument("--report", default=None, help="also write a markdown report here")
    a = p.parse_args(argv)

    import open_models
    from exam_open import find_adapter, load_base, to_device
    preset, cfg = open_models.resolve(a.model)
    model_id = cfg["hf"] if preset and not os.path.isdir(a.model) else a.model
    name = preset or os.path.basename(model_id.rstrip("/\\")).lower()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    with open(a.prompts, encoding="utf-8") as f:
        tests = [json.loads(line) for line in f if line.strip()]

    model, hf_tok = load_base(model_id, device, cfg.get("quant4", False))
    adapter = a.adapter or (find_adapter(name, model_id) if a.tuned else None)
    if a.tuned and not adapter:
        sys.exit("--tuned needs our adapter: pass --adapter <folder> or train first")
    if adapter:
        from peft import PeftModel
        model = to_device(PeftModel.from_pretrained(model, adapter), device)
    model.eval()
    tok = OpenTokenizer(hf_tok.backend_tokenizer, think=cfg.get("think"))

    label = f"{model_id}" + (f" + adapter {adapter}" if adapter else " (plain base)")
    results, tally = run_sheet(model, tok, hf_tok, tests, a.tokens, a.temperature, device)
    lines = [f"# {a.prompts}: {label}\n"]
    for t, reply, ok in results:
        lines.append(f"{'PASS' if ok else 'FAIL'}  [{t['category']}] {t['prompt']}\n      -> {reply[:300]!r}")
    passed = sum(v[0] for v in tally.values())
    total = sum(v[1] for v in tally.values())
    lines.append("")
    for cat, (ok, n) in sorted(tally.items()):
        lines.append(f"{cat:16s} {ok}/{n}")
    lines.append(f"{'TOTAL':16s} {passed}/{total}")
    text = "\n".join(lines)
    print(text)
    if a.report:
        os.makedirs(os.path.dirname(a.report) or ".", exist_ok=True)
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
