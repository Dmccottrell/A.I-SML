"""
exam_open.py - Score an OPEN model (Qwen 2.5 / Qwen3, with or without our LoRA add-on) on HellaSwag.

WHAT THIS FILE DOES
    The same test and the same scoring as exam.py (each question is an everyday situation with 4 endings; the model "picks" the
    ending it finds least surprising, measured as the average loss of the ending's tokens), so the number is comparable with
    Ember 2 (28.4%) and Flare 2 / v3 (36.2%). exam.py only reads our own checkpoints; this one loads a Hugging Face model.

    The question it answers: did our fine-tune make the model better or worse at plain common sense? Fine-tuning can make a model
    forget things, so the plain base is scored first and the tuned model is compared against it.

Usage:  python exam_open.py --model flare-2.5 --compare              (plain base, then base + our adapter, and the difference)
        python exam_open.py --model flare-2.5                        (plain base only: the baseline)
        python exam_open.py --model flare-2.5 --adapter checkpoints/dev/open/flare-2.5/adapter
        python exam_open.py --model export/open/flare-2.5/my-ai      (a merged folder from finetune_open.py --merge)
        add  --n 1000 --spread   for a faster check that matches the full-test score (without --spread: the easier first N)
Needs:  pip install peft (for adapters). The model is a preset name (open_models.py), a Hugging Face id or a local folder.
"""
import argparse
import json
import os
import sys

import torch
import torch.nn.functional as F

from exam import pick_questions


def load_questions(path=None):
    """[{"ctx", "endings", "label"}]: the HellaSwag validation set, or a jsonl file of the same shape (for offline tests)."""
    if path:
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    from benchmarks import load_hellaswag
    return load_hellaswag()


def ending_scores(model, tok, ex, device, max_len=2048, pad_id=0):
    """The average loss of each of the 4 endings given the situation (lower = the model finds it more natural)."""
    ctx = tok.encode(ex["ctx"], add_special_tokens=False)
    rows, n_end = [], []
    for ending in ex["endings"]:
        end = tok.encode(" " + ending, add_special_tokens=False)
        ids = (ctx + end)[-max_len:]                       # if too long, drop the start of the situation
        rows.append(ids)
        n_end.append(min(len(end), len(ids) - 1))
    T = max(len(r) for r in rows)
    x = torch.full((len(rows), T), pad_id, dtype=torch.long)
    mask = torch.zeros((len(rows), T), dtype=torch.long)
    for i, ids in enumerate(rows):
        x[i, :len(ids)] = torch.tensor(ids)
        mask[i, :len(ids)] = 1
    x, mask = x.to(device), mask.to(device)
    logits = model(input_ids=x, attention_mask=mask).logits
    losses = F.cross_entropy(logits[:, :-1].float().transpose(1, 2), x[:, 1:], reduction="none")
    scores = []
    for i, ids in enumerate(rows):
        end_losses = losses[i, len(ids) - 1 - n_end[i]:len(ids) - 1]      # the ending's tokens only
        scores.append(end_losses.mean().item())
    return scores


@torch.no_grad()
def hellaswag_accuracy(model, tok, examples, device, max_len=2048, pad_id=0, progress=0):
    """Fraction of `examples` where the model prefers the correct ending."""
    was_training = model.training
    model.eval()
    correct = 0
    for k, ex in enumerate(examples, 1):
        scores = ending_scores(model, tok, ex, device, max_len, pad_id)
        correct += int(min(range(len(scores)), key=scores.__getitem__) == ex["label"])
        if progress and k % progress == 0:
            print(f"  {k:,}/{len(examples):,}  {correct / k * 100:.1f}%", flush=True)
    if was_training:
        model.train()
    return correct / len(examples)


def find_adapter(name, model_arg):
    """The saved LoRA adapter of a run, or None: checkpoints/dev/open/<preset or model name>/adapter (also the old folder name)."""
    import finetune_open
    candidates = [os.path.join("checkpoints", "dev", "open", name, "adapter"),
                  os.path.join("checkpoints", "dev", "open", finetune_open.short_name(model_arg), "adapter")]
    return next((c for c in candidates if os.path.isdir(c)), None)


def load_base(model_id, device):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    dtype = torch.bfloat16 if device == "cuda" else torch.float32
    tok = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(model_id, dtype=dtype).to(device)
    return model, tok


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default="flare-2.5", help="a preset (flare-2.5, equinox-2, ...), a Hugging Face id, or a local folder")
    p.add_argument("--adapter", default=None, help="our LoRA adapter folder (applied on top of --model)")
    p.add_argument("--compare", action="store_true", help="score the plain base first, then base + adapter, and print the difference")
    p.add_argument("--n", type=int, default=0, help="only N questions (default: all 10,042)")
    p.add_argument("--spread", action="store_true", help="with --n: spread them over the whole test (matches the full score)")
    p.add_argument("--questions", default=None, help="a jsonl file of {ctx, endings, label} instead of HellaSwag (offline tests)")
    p.add_argument("--max_len", type=int, default=2048)
    a = p.parse_args(argv)

    import open_models
    preset, cfg = open_models.resolve(a.model)
    model_id = cfg["hf"] if preset and not os.path.isdir(a.model) else a.model
    name = preset or os.path.basename(model_id.rstrip("/\\")).lower()
    device = "cuda" if torch.cuda.is_available() else "cpu"

    examples = pick_questions(load_questions(a.questions), a.n or 0, "spread" if a.spread else "first")
    print(f"HellaSwag: {len(examples):,} questions, model {model_id}, device {device}")
    results = []

    model, tok = load_base(model_id, device)
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else (tok.eos_token_id or 0)
    adapter = a.adapter or (find_adapter(name, model_id) if a.compare else None)
    if a.compare and not adapter:
        sys.exit("--compare needs our adapter: pass --adapter <folder> (the one finetune_open.py saved) or train first")

    if a.adapter is None or a.compare:
        acc = hellaswag_accuracy(model, tok, examples, device, a.max_len, pad_id, progress=500)
        print(f"plain base:        {acc * 100:.1f}%  (random guessing = 25%)")
        results.append(("base", acc))
    if adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, adapter).to(device)
        acc = hellaswag_accuracy(model, tok, examples, device, a.max_len, pad_id, progress=500)
        print(f"base + our adapter: {acc * 100:.1f}%  (adapter: {adapter})")
        results.append(("tuned", acc))
    if len(results) == 2:
        d = (results[1][1] - results[0][1]) * 100
        print(f"difference: {d:+.1f} points ({'better' if d > 0.5 else 'worse' if d < -0.5 else 'about the same'}). "
              f"Our own models: Ember 2 28.4%, Flare 2 (v3) 36.2%.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
