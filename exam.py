"""
exam.py - Score a model on HellaSwag, a public common-sense test.

WHAT THIS FILE DOES
    Each HellaSwag question is an everyday situation with 4 possible endings:

        "A man is standing on a ladder next to a house. He..."
          0) ...eats the ladder.
          1) ...cleans the gutters with his hands.      <- correct
          2) ...flies into the sky.
          3) ...turns into a cat.

    The model doesn't write an answer. Instead we measure how "natural" each
    ending looks to it: the average loss on the ending's tokens (lower loss =
    the model finds it more likely). The ending with the lowest loss is the
    model's pick. Random guessing scores 25%.

    This works on PRETRAINED models (no chat fine-tuning needed), so it can
    compare v2 and v3 fairly, and train.py runs a short version of it during
    training (the "mini-exam") to show the model really is getting smarter.

    Rough reference points: GPT-2 (124M) ~29-31%, GPT-2 Medium (350M) ~37%.

Usage:
    python exam.py --version v2                  full test (10,042 questions)
    python exam.py --version v3 --n 1000         first 1,000 questions only (easier than the whole test)
    python exam.py --version v3 --n 1000 --spread   1,000 spread over the whole test (matches the full score)
    Compare versions on the FULL test only: the first questions of the file are the easier kind.
    python exam.py --version v2 --ckpt checkpoints/dev/v2/ckpt.pt
"""
import argparse
import os

import torch
import torch.nn.functional as F


def final_weights(V):
    """The finished pretraining run's final weights (same choice as finetune.py).

      1. final.pt
      2. latest.pt, if its run finished (runs from before final.pt existed)
      3. ckpt.pt (the best val score)
    """
    final = os.path.join(V.ckpt_dir, "final.pt")
    if os.path.exists(final):
        return final
    latest = os.path.join(V.ckpt_dir, "latest.pt")
    if os.path.exists(latest) and torch.load(latest, map_location="cpu")["iter"] > V.train.max_iters:
        return latest
    return os.path.join(V.ckpt_dir, "ckpt.pt")


@torch.no_grad()
def pick_questions(examples, n=0, how="first"):
    """n questions from the test (0 = all). how="first": the first n (v3's mini-exam; the file starts with
    the easier video-caption questions, so these score ~5 points HIGHER than the whole test);
    how="spread": n evenly spaced over the whole test, so the score matches the full test."""
    if not n or n >= len(examples):
        return list(examples)
    if how == "spread":
        return [examples[i * len(examples) // n] for i in range(n)]
    return list(examples[:n])


def hellaswag_accuracy(model, tok, examples, device, autocast=None):
    """Fraction of `examples` where the model prefers the correct ending.

    Args:
        model:    a TinyLM (any version)
        tok:      the model's BPETokenizer
        examples: list of {"ctx", "endings", "label"} (see benchmarks.load_hellaswag)
        device:   "cuda" or "cpu"
        autocast: optional torch.autocast context for 16-bit speed
    """
    was_training = model.training
    model.eval()
    max_len = model.cfg.max_seq_len
    correct = 0
    for ex in examples:
        ctx = tok.encode(ex["ctx"], allow_special=False)
        rows, n_end = [], []
        for ending in ex["endings"]:
            end = tok.encode(" " + ending, allow_special=False)
            ids = (ctx + end)[-max_len:]           # if too long, drop the start of the context
            rows.append(ids)
            n_end.append(min(len(end), len(ids) - 1))
        T = max(len(r) for r in rows)
        x = torch.zeros((len(rows), T), dtype=torch.long)
        for i, ids in enumerate(rows):
            x[i, :len(ids)] = torch.tensor(ids)
        x = x.to(device)
        if autocast is not None:
            with autocast:
                logits, _ = model(x)
        else:
            logits, _ = model(x)
        # Loss of every token given the ones before it: logits[t] predicts x[t+1]
        losses = F.cross_entropy(logits[:, :-1].float().transpose(1, 2), x[:, 1:], reduction="none")
        scores = []
        for i, ids in enumerate(rows):
            end_losses = losses[i, len(ids) - 1 - n_end[i]:len(ids) - 1]   # the ending's tokens only
            scores.append(end_losses.mean().item())
        correct += int(min(range(len(scores)), key=scores.__getitem__) == ex["label"])
    if was_training:
        model.train()
    return correct / len(examples)


def main():
    from benchmarks import load_hellaswag
    from config import add_version_arg, get_version
    from model import load_checkpoint
    from tokenizer import BPETokenizer

    p = argparse.ArgumentParser()
    add_version_arg(p)
    p.add_argument("--ckpt", default=None,
                   help="default: the finished run's final weights (final.pt or a finished latest.pt), else ckpt.pt")
    p.add_argument("--n", type=int, default=0, help="only N questions (default: all)")
    p.add_argument("--spread", action="store_true", help="with --n: spread the N over the whole test (matches "
                   "the full score); without it, the first N (v3's mini-exam set, ~5 points easier)")
    a = p.parse_args()
    V = get_version(a.version)
    ckpt = a.ckpt or final_weights(V)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if device == "cuda" and torch.cuda.is_bf16_supported() else torch.float16
    autocast = torch.autocast(device_type=device, dtype=dtype) if device == "cuda" else None
    model, _ = load_checkpoint(ckpt, device)
    tok = BPETokenizer.load(os.path.join(V.data_dir, "tokenizer.json"))
    examples = load_hellaswag()
    examples = pick_questions(examples, a.n or 0, "spread" if a.spread else "first")
    print(f"HellaSwag: {len(examples):,} questions, model {ckpt}")
    acc = hellaswag_accuracy(model, tok, examples, device, autocast)
    print(f"accuracy: {acc*100:.1f}%  (random guessing = 25%)")


if __name__ == "__main__":
    main()
