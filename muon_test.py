"""
muon_test.py - Does the Muon optimizer really need fewer steps than AdamW on OUR models? (~1-2 hours)

THE QUESTION
    Muon (muon.py) is reported to reach the same quality in roughly 30-50% fewer steps. If that holds
    for our models, v3.5's months of training get shorter (or it reads more in the same time). This
    measures it before we rely on it.

THE TEST
    The SAME small model (a ~46M-parameter v3-style model, v3's tokenizer), trained twice from the SAME
    random start on the SAME batches in the same order, with the same learning-rate schedule:
        adamw   what every version uses now
        muon    Muon for the weight matrices, AdamW for embeddings and norms
    (plus, with --muon_lr, a second Muon run at another learning rate, in case the first isn't its best).
    Validation loss is logged every --eval_every steps.

THE REPORT
    * final validation loss of each run (lower is better),
    * how many steps Muon needed to reach AdamW's FINAL loss -> "steps saved",
    * time per step (Muon's extra matrix work costs a little), so the saving in hours, not just steps.
    A saving under ~10% is within noise: not worth switching. Above ~20% on this test, the next step is a
    short check at v3.5's real size before switching its config.

RUN IT (on the PC while the cloud trains v3, or any free GPU; pausable: Ctrl+C, then the same command)
        python muon_test.py                       both runs, then the report (~1-2 hours on an RTX 4070)
        python muon_test.py --muon_lr 1.2e-3      also try Muon at twice the learning rate
        python muon_test.py --report_only
    It reads data/v3 (train.bin, val.bin, tokenizer.json); --data_dir to use another version's data.
    NOT while v3 is training on the same GPU.
"""
import argparse
import os

import numpy as np
import torch

from growth_test import Data, read_log, train_arm
from model import ModelConfig, TinyLM
from muon import Muon, muon_param_groups
from tokenizer import BPETokenizer

SEED = 1234   # the same random start and the same batches for every run


def build_model(a, vocab, device):
    torch.manual_seed(SEED)
    cfg = ModelConfig(vocab_size=vocab, dim=a.dim, n_layers=a.layers, n_heads=a.dim // 64,
                      n_kv_heads=max(1, a.dim // 256), hidden_dim=a.hidden, max_seq_len=a.seq_len,
                      rope_theta=500_000.0)
    return TinyLM(cfg).to(device), cfg


def steps_to_reach(log, target):
    """First step (interpolated) at which a run's validation loss is at or below `target`, or None."""
    for prev, row in zip(log, log[1:]):
        if row["val_loss"] <= target:
            if prev["val_loss"] <= target:
                return prev["step"]
            f = (prev["val_loss"] - target) / (prev["val_loss"] - row["val_loss"])
            return prev["step"] + f * (row["step"] - prev["step"])
    return None


def report(out_dir, arms):
    logs = {n: read_log(os.path.join(out_dir, f"{n}.csv")) for n in arms}
    if not logs.get("adamw") or not any(logs.get(n) for n in arms if n != "adamw"):
        print("report: needs adamw.csv and at least one muon run in", out_dir)
        return None
    base = logs["adamw"]
    target, total = base[-1]["val_loss"], base[-1]["step"]
    base_sec = base[-1].get("sec_per_step", 0) or 0
    print("\n==================== MUON TEST REPORT ====================")
    print(f"{'step':>8}" + "".join(f"{n:>12}" for n in arms if logs.get(n)))
    for i, row in enumerate(base):
        if i % 2 == 0 or row is base[-1]:
            line = f"{int(row['step']):>8}"
            for n in arms:
                if logs.get(n):
                    same = [r["val_loss"] for r in logs[n] if r["step"] == row["step"]]
                    line += f"{same[0]:>12.4f}" if same else f"{'':>12}"
            print(line)
    results = {}
    print(f"\nAdamW's final validation loss: {target:.4f} after {int(total):,} steps "
          f"({base_sec:.2f} s/step)")
    for n in arms:
        if n == "adamw" or not logs.get(n):
            continue
        log = logs[n]
        sec = log[-1].get("sec_per_step", 0) or 0
        need = steps_to_reach(log, target)
        line = f"{n}: final loss {log[-1]['val_loss']:.4f} ({log[-1]['val_loss'] - target:+.4f} vs AdamW), {sec:.2f} s/step"
        if need is None:
            line += "; never reached AdamW's final loss: no saving"
            saved = time_saved = None
        else:
            saved = 1 - need / total
            time_saved = 1 - (need * sec) / (total * base_sec) if base_sec and sec else None
            line += f"; reached AdamW's final loss at step {need:,.0f}: {saved * 100:.0f}% fewer steps"
            if time_saved is not None:
                line += (f", {time_saved * 100:.0f}% less time" if time_saved >= 0 else
                         f", but {-time_saved * 100:.0f}% MORE time (each step is slower)")
        print(line)
        results[n] = {"final_loss": log[-1]["val_loss"], "steps_saved": saved, "time_saved": time_saved}
    best = max((r["time_saved"] if r["time_saved"] is not None else r["steps_saved"] or -1
                for r in results.values()), default=-1)
    if best is None or best < 0.10:
        verdict = "no real saving (under 10%): keep AdamW"
    elif best < 0.20:
        verdict = "a small saving (10-20%): worth a longer test before switching"
    else:
        verdict = "a clear saving (20%+): check it once at v3.5's real size, then switch its config to muon"
    print(f"\nVERDICT: {verdict}")
    print("============================================================")
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data_dir", default=os.path.join("data", "v3"))
    p.add_argument("--steps", type=int, default=4000)
    p.add_argument("--dim", type=int, default=512)
    p.add_argument("--layers", type=int, default=8)
    p.add_argument("--hidden", type=int, default=1408)
    p.add_argument("--seq_len", type=int, default=1024)
    p.add_argument("--batch_size", type=int, default=16)
    p.add_argument("--grad_accum", type=int, default=2, help="16 x 2 x 1024 = ~32k tokens per step")
    p.add_argument("--lr", type=float, default=6e-4, help="peak learning rate for both (Muon is scaled to match AdamW)")
    p.add_argument("--muon_lr", type=float, default=None, help="also run Muon at this learning rate")
    p.add_argument("--warmup", type=int, default=200)
    p.add_argument("--eval_every", type=int, default=250)
    p.add_argument("--eval_iters", type=int, default=40)
    p.add_argument("--save_every", type=int, default=500)
    p.add_argument("--out", default=os.path.join("muon_test", "run"))
    p.add_argument("--report_only", action="store_true")
    p.add_argument("--halt_after", type=int, default=0, help=argparse.SUPPRESS)      # for testing
    a = p.parse_args()
    arms = ["adamw", "muon"] + (["muon_lr2"] if a.muon_lr else [])
    os.makedirs(a.out, exist_ok=True)
    if a.report_only:
        report(a.out, arms)
        return
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda":
        autocast = torch.autocast(device_type="cuda", dtype=torch.bfloat16)
    else:
        autocast = torch.autocast(device_type="cpu", enabled=False)
    vocab = BPETokenizer.load(os.path.join(a.data_dir, "tokenizer.json")).vocab_size
    data = Data(a.data_dir, a.seq_len, device)
    for name in arms:
        model, cfg = build_model(a, vocab, device)
        if name == "adamw":
            make_opt, lr = None, a.lr
        else:
            lr = a.muon_lr if name == "muon_lr2" else a.lr
            make_opt = lambda m, lr=lr: Muon(muon_param_groups(m, 0.1), lr=lr)
        print(f"\n=== {name}: {model.num_params() / 1e6:.1f}M parameters, lr {lr:g}, {a.steps:,} steps ===")
        train_arm(name, model, cfg, data, a, a.steps, 0, a.out, device, autocast,
                  make_opt=make_opt, seed=SEED, lr=lr)
        del model
        if device == "cuda":
            torch.cuda.empty_cache()
    report(a.out, arms)


if __name__ == "__main__":
    main()
