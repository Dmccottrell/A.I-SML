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
    python exam.py --version v3 --n 1000         first 1,000 questions only
    python exam.py --version v2 --ckpt checkpoints/dev/v2/ckpt.pt
"""
import argparse
import os

import torch
import torch.nn.functional as F


@torch.no_grad()
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
    p.add_argument("--ckpt", default=None, help="default: final.pt, else ckpt.pt")
    p.add_argument("--n", type=int, default=0, help="only the first N questions (default: all)")
    a = p.parse_args()
    V = get_version(a.version)
    ckpt = a.ckpt
    if ckpt is None:
        final = os.path.join(V.ckpt_dir, "final.pt")
        ckpt = final if os.path.exists(final) else os.path.join(V.ckpt_dir, "ckpt.pt")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if device == "cuda" and torch.cuda.is_bf16_supported() else torch.float16
    autocast = torch.autocast(device_type=device, dtype=dtype) if device == "cuda" else None
    model, _ = load_checkpoint(ckpt, device)
    tok = BPETokenizer.load(os.path.join(V.data_dir, "tokenizer.json"))
    examples = load_hellaswag()
    if a.n:
        examples = examples[:a.n]
    print(f"HellaSwag: {len(examples):,} questions, model {ckpt}")
    acc = hellaswag_accuracy(model, tok, examples, device, autocast)
    print(f"accuracy: {acc*100:.1f}%  (random guessing = 25%)")


if __name__ == "__main__":
    main()
