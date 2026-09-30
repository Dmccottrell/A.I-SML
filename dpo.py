"""
dpo.py - Preference training (DPO): teach the chat model to PREFER the better of two answers.

WHAT THIS FILE DOES
    Chat fine-tuning (finetune.py) shows the model good answers. DPO shows it PAIRS: for the same
    question, a better answer ("chosen") and a worse one ("rejected"), from make_dpo_pairs.py. The
    model learns to make the chosen answer more likely and the rejected one less likely, RELATIVE to
    how it started (the "reference": the chat model before DPO), so it improves where the pairs point
    without drifting far from what it already does well.

        loss = -log sigmoid( beta * [ (log p(chosen) - log p_ref(chosen)) - (log p(rejected) - log p_ref(rejected)) ] )

    Only the ANSWER tokens count (not the question or notes). The reference's scores are computed once
    at the start with the same model (it IS the starting point), so no second copy of the model has to
    sit in GPU memory.

    Reads <data_dir>/dpo_pairs.jsonl and <ckpt_dir>/chat.pt; writes <ckpt_dir>/chat_dpo.pt. chat.pt is
    not changed: compare them first (evaluate.py / compare.py), then use the better one.

READING THE OUTPUT
    step 40/250: loss 0.612  accuracy 0.71  margin +0.35
    accuracy: how often the model now prefers the chosen answer (starts ~0.5; rising is good).
    margin: how much more it prefers it. Loss starts at ~0.693 (= no preference yet) and goes down.

Usage:
    python dpo.py --version v3                     one pass over the pairs
    python dpo.py --version v3 --epochs 2 --beta 0.1 --lr 2e-6
    Ctrl+C pauses (saves dpo_latest.pt); run the same command to resume. --fresh starts over.
"""
import argparse
import json
import os
import random
import sys
import time

import torch
import torch.nn.functional as F

from chat import _encode_message, normalize


def encode_pair(tok, pair, max_len):
    """(chosen ids, chosen mask, rejected ids, rejected mask): the conversation + each answer, with the
    mask on the final answer only. None if it doesn't fit in max_len tokens."""
    context = normalize({"messages": pair["messages"]})
    prefix = [t for m in context for t in _encode_message(tok, m)[0]]
    out = []
    for key in ("chosen", "rejected"):
        answer, _ = _encode_message(tok, {"role": "assistant", "content": pair[key]})
        ids = prefix + answer
        if len(ids) > max_len:
            return None
        out += [ids, [0] * len(prefix) + [1] * len(answer)]
    return tuple(out)


def sequence_logps(model, seqs, device, autocast):
    """Sum of log-probabilities of the masked (answer) tokens, one number per (ids, mask) in seqs."""
    T = max(len(ids) for ids, _ in seqs) - 1
    x = torch.zeros((len(seqs), T), dtype=torch.long)
    y = torch.zeros((len(seqs), T), dtype=torch.long)
    m = torch.zeros((len(seqs), T))
    for i, (ids, mask) in enumerate(seqs):
        n = len(ids) - 1
        x[i, :n] = torch.tensor(ids[:-1])
        y[i, :n] = torch.tensor(ids[1:])
        m[i, :n] = torch.tensor(mask[1:], dtype=torch.float)
    x, y, m = x.to(device), y.to(device), m.to(device)
    with autocast:
        logits, _ = model(x)
    logp = torch.gather(F.log_softmax(logits.float(), dim=-1), 2, y.unsqueeze(-1)).squeeze(-1)
    return (logp * m).sum(-1)


def dpo_loss(pc, pr, rc, rr, beta):
    """The DPO loss and two diagnostics, from policy (p) and reference (r) log-probs of chosen/rejected."""
    margin = beta * ((pc - rc) - (pr - rr))
    return -F.logsigmoid(margin).mean(), (margin > 0).float().mean(), margin.mean()


def main():
    from config import add_version_arg, get_version
    from model import load_checkpoint
    from tokenizer import BPETokenizer
    p = argparse.ArgumentParser()
    add_version_arg(p)
    p.add_argument("--pairs", default=None, help="default: <data_dir>/dpo_pairs.jsonl")
    p.add_argument("--ckpt", default=None, help="the chat model to improve (default: <ckpt_dir>/chat.pt)")
    p.add_argument("--beta", type=float, default=None, help="default: config.py dpo_beta (0.1)")
    p.add_argument("--lr", type=float, default=None, help="default: config.py dpo_lr (2e-6)")
    p.add_argument("--epochs", type=int, default=1)
    p.add_argument("--batch_pairs", type=int, default=8, help="pairs per step")
    p.add_argument("--micro_pairs", type=int, default=2, help="pairs per forward pass (lower if out of memory)")
    p.add_argument("--fresh", action="store_true")
    a = p.parse_args()
    V = get_version(a.version)
    beta = a.beta if a.beta is not None else V.finetune.dpo_beta
    lr = a.lr if a.lr is not None else V.finetune.dpo_lr
    pairs_path = a.pairs or os.path.join(V.data_dir, "dpo_pairs.jsonl")
    base = a.ckpt or os.path.join(V.ckpt_dir, "chat.pt")
    out_path = os.path.join(V.ckpt_dir, "chat_dpo.pt")
    latest = os.path.join(V.ckpt_dir, "dpo_latest.pt")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if device == "cuda" and torch.cuda.is_bf16_supported() else torch.float32
    autocast = torch.autocast(device_type=device, dtype=dtype, enabled=(device == "cuda"))
    tok = BPETokenizer.load(os.path.join(V.data_dir, "tokenizer.json"))
    model, _ = load_checkpoint(base, device)
    cfg = model.cfg
    with open(pairs_path, encoding="utf-8") as f:
        raw = [json.loads(l) for l in f if l.strip()]
    pairs = [e for e in (encode_pair(tok, r, cfg.max_seq_len + 1) for r in raw) if e]
    print(f"{len(pairs):,} pairs ({len(raw) - len(pairs)} too long, skipped); beta {beta}, lr {lr:g}")
    if not pairs:
        raise SystemExit("no pairs to train on")

    # The reference: the starting model's scores, computed once
    ref_path = os.path.join(V.ckpt_dir, "dpo_ref.pt")
    ref = None
    if os.path.exists(ref_path) and not a.fresh:
        ref = torch.load(ref_path)
        if ref.get("n") != len(pairs) or ref.get("base") != base:
            ref = None
    if ref is None:
        model.eval()
        rc, rr = [], []
        with torch.no_grad():
            for i in range(0, len(pairs), a.micro_pairs):
                chunk = pairs[i:i + a.micro_pairs]
                seqs = [(c, cm) for c, cm, _, _ in chunk] + [(r, rm) for _, _, r, rm in chunk]
                lp = sequence_logps(model, seqs, device, autocast).cpu()
                rc += lp[:len(chunk)].tolist(); rr += lp[len(chunk):].tolist()
        ref = {"n": len(pairs), "base": base, "chosen": rc, "rejected": rr}
        torch.save(ref, ref_path)
        print("reference scores computed")

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, betas=(0.9, 0.95), weight_decay=0.0)
    steps_per_epoch = (len(pairs) + a.batch_pairs - 1) // a.batch_pairs
    total = steps_per_epoch * a.epochs
    step = 0
    if os.path.exists(latest) and not a.fresh:
        st = torch.load(latest, map_location="cpu")
        if st.get("n") == len(pairs):
            model.load_state_dict(st["model"]); optimizer.load_state_dict(st["optimizer"]); step = st["step"]
            print(f"resuming at step {step}/{total}")

    def save_latest():
        torch.save({"model": model.state_dict(), "optimizer": optimizer.state_dict(), "step": step,
                    "n": len(pairs)}, latest + ".tmp")
        os.replace(latest + ".tmp", latest)

    model.train()
    t_save = time.time()
    try:
        while step < total:
            epoch, i = divmod(step, steps_per_epoch)
            order = list(range(len(pairs)))
            random.Random(1000 + epoch).shuffle(order)
            idx = order[i * a.batch_pairs:(i + 1) * a.batch_pairs]
            for g in optimizer.param_groups:                     # short warm-up, then constant
                g["lr"] = lr * min(1.0, (step + 1) / 10)
            stats = []
            for j in range(0, len(idx), a.micro_pairs):
                chunk = idx[j:j + a.micro_pairs]
                seqs = [pairs[k][:2] for k in chunk] + [pairs[k][2:] for k in chunk]
                lp = sequence_logps(model, seqs, device, autocast)
                pc, pr = lp[:len(chunk)], lp[len(chunk):]
                rc = torch.tensor([ref["chosen"][k] for k in chunk], device=device)
                rr = torch.tensor([ref["rejected"][k] for k in chunk], device=device)
                loss, acc, margin = dpo_loss(pc, pr, rc, rr, beta)
                (loss * len(chunk) / len(idx)).backward()
                stats.append((loss.item(), acc.item(), margin.item(), len(chunk)))
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            step += 1
            n = sum(s[3] for s in stats)
            if step % 10 == 0 or step == total:
                l, ac, mg = (sum(s[k] * s[3] for s in stats) / n for k in range(3))
                print(f"step {step}/{total}: loss {l:.3f}  accuracy {ac:.2f}  margin {mg:+.2f}", flush=True)
            if time.time() - t_save > 600:
                save_latest(); t_save = time.time()
    except KeyboardInterrupt:
        optimizer.zero_grad(set_to_none=True)
        save_latest()
        print(f"\npaused at step {step}. Run the same command again to resume.")
        sys.exit(0)
    torch.save({"model": model.state_dict(), "config": cfg.__dict__, "dpo": {"beta": beta, "lr": lr,
                "pairs": len(pairs), "epochs": a.epochs, "from": base}}, out_path + ".tmp")
    os.replace(out_path + ".tmp", out_path)
    for f in (latest, ref_path):
        if os.path.exists(f):
            os.remove(f)
    print(f"saved {out_path}. Compare it with chat.pt before using it, e.g.\n"
          f"  python evaluate.py --version {V.name} --ckpt {out_path}")


if __name__ == "__main__":
    main()
