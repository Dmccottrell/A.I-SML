"""
growth_test.py - Does growing a trained model save training compute? (an experiment, ~1 day)

THE QUESTION
    Growing a trained small model into a deeper one (see grow.py) should be cheaper than
    training the deeper model from scratch. This measures how much cheaper, on our own models,
    before we count on it for Yuvra Solstice -> Yuvra Apogee (which would save cloud money).

THE TEST (defaults: v2's 88M, 12 layers, grown to 24 layers)
    Two runs of the SAME 24-layer model, given the SAME total compute:

      grown     v2's trained weights, layers copied up to 24, then trained for --grown_steps
      scratch   24 layers from random numbers, trained for as many steps as the SAME total
                compute allows. The grown model's compute includes what v2's training already
                cost, counted at 12 layers (so half as expensive per token).

    Compute is measured in "layer-tokens" (tokens read x layers), so a 24-layer step counts double.
    At equal compute, whichever has the lower validation loss is the better use of the
    compute. The report also shows how much MORE compute the scratch run needs to reach the
    grown model's final loss.

RUN IT (about 20 hours on an RTX 4070; pausable: Ctrl+C, then run the same command again)
        python growth_test.py                       both runs, then the report
        python growth_test.py --report_only         just print the report again

TEST WITH v3 (the size that matters for v3.5): use a SNAPSHOT of v3 taken during its training.
    While v3 trains, the backup folder gets v3_latest.pt about once a day. Copy it to a name
    that won't be overwritten, e.g. C:\\ai-backups\\v3_growth_base.pt (a copy doesn't disturb
    the training). Later, with the GPU free:

        python growth_test.py --base_version v3 --from_ckpt C:\\ai-backups\\v3_growth_base.pt --new_layers 48 --batch_size 1 --grad_accum 32 --grad_checkpoint --warmup 500 --grown_steps 4000 --eval_iters 100

    v3 has 32 layers, so 48 is 1.5x deeper (~575M parameters). A mid-training snapshot is the
    right thing to grow from (the learning rate is still high, as in real growth). The step counter
    inside the snapshot tells the script how much reading it had done. About 2-3 days on the 4070
    for a snapshot from day one (estimate).
    Results: growth_test/<name>/grown.csv, scratch.csv (and the report).
    Do it when the GPU is free (not while v3 is training).

READING THE REPORT
    "growth dip": the loss right after growing vs before. Usually a small rise, then it recovers.
    "at equal compute": grown vs scratch loss. Lower is better. If the grown loss is clearly
    lower, growth pays off. If the gap is tiny, it doesn't.
"""
import argparse
import csv
import math
import os
import sys
import time

import numpy as np
import torch

from config import VERSIONS, get_version
from grow import grow_state_dict
from model import ModelConfig, TinyLM


# ------------------------------------------------------------------ data
class Data:
    """Random training batches from <data_dir>/train.bin, and fixed validation batches from val.bin."""

    def __init__(self, data_dir, seq_len, device):
        self.train = np.memmap(os.path.join(data_dir, "train.bin"), dtype=np.uint16, mode="r")
        self.val = np.memmap(os.path.join(data_dir, "val.bin"), dtype=np.uint16, mode="r")
        self.seq_len, self.device = seq_len, device

    def _batch(self, data, starts):
        x = torch.stack([torch.from_numpy(data[i:i + self.seq_len].astype(np.int64)) for i in starts])
        y = torch.stack([torch.from_numpy(data[i + 1:i + 1 + self.seq_len].astype(np.int64)) for i in starts])
        return x.to(self.device), y.to(self.device)

    def train_batch(self, batch_size, rng):
        starts = rng.integers(0, len(self.train) - self.seq_len - 1, batch_size)
        return self._batch(self.train, starts)

    def val_batches(self, batch_size, n):
        rng = np.random.default_rng(999)                       # the same validation text every time
        return [self._batch(self.val, rng.integers(0, len(self.val) - self.seq_len - 1, batch_size))
                for _ in range(n)]


# ------------------------------------------------------------------ one training run ("arm")
def get_lr(step, total, warmup, lr_max, lr_min):
    if step < warmup:
        return lr_max * (step + 1) / warmup
    progress = min(1.0, (step - warmup) / max(1, total - warmup))
    return lr_min + 0.5 * (1 + math.cos(math.pi * progress)) * (lr_max - lr_min)


@torch.no_grad()
def val_loss(model, val_batches, autocast):
    model.eval()
    total = 0.0
    for x, y in val_batches:
        with autocast:
            _, loss = model(x, y)
        total += loss.item()
    model.train()
    return total / len(val_batches)


def read_log(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [{k: float(v) for k, v in row.items()} for row in csv.DictReader(f)]


def train_arm(name, model, cfg, data, a, total_steps, base_units, out_dir, device, autocast,
              make_opt=None, seed=None, lr=None):
    """Train `model` for total_steps, logging validation loss every --eval_every steps. Resumable.

    make_opt(model) -> optimizer (default AdamW); seed: the order of the training text (runs with the
    same seed read the same batches); lr: peak learning rate (default --lr). Used by muon_test.py too.
    """
    log_path = os.path.join(out_dir, f"{name}.csv")
    latest = os.path.join(out_dir, f"{name}_latest.pt")
    done_flag = os.path.join(out_dir, f"{name}.done")
    if os.path.exists(done_flag):
        print(f"[{name}] already finished, skipping")
        return
    lr_max = lr or a.lr
    opt = make_opt(model) if make_opt else torch.optim.AdamW(model.parameters(), lr=lr_max, betas=(0.9, 0.95),
                                                             weight_decay=0.1, fused=(device == "cuda"))
    rng = np.random.default_rng(seed if seed is not None else (1234 if name == "grown" else 4321))
    step = 0
    if os.path.exists(latest):
        state = torch.load(latest, map_location="cpu")   # not the GPU: a copy left there wastes memory
        model.load_state_dict(state["model"]); opt.load_state_dict(state["optimizer"])
        step = state["step"]; rng.bit_generator.state = state["rng"]
        print(f"[{name}] resuming at step {step:,} of {total_steps:,}")
    logged = {int(r["step"]) for r in read_log(log_path)}
    val = data.val_batches(a.batch_size, a.eval_iters)
    tokens_per_step = a.batch_size * a.grad_accum * cfg.max_seq_len
    t0, t_start_step = time.time(), step
    train_seconds = [0.0]           # time spent training (not evaluating), for per-step speed

    def log(step_now):
        if step_now in logged:
            return
        tokens = step_now * tokens_per_step
        row = {"step": step_now, "tokens": tokens,
               "units": base_units + tokens * cfg.n_layers, "val_loss": val_loss(model, val, autocast),
               "sec_per_step": train_seconds[0] / max(1, step_now - t_start_step)}
        new = not os.path.exists(log_path)
        with open(log_path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(row))
            if new:
                w.writeheader()
            w.writerow(row)
        logged.add(step_now)
        rate = (time.time() - t0) / max(1, step_now - t_start_step)
        print(f"[{name}] step {step_now:,}/{total_steps:,}  val loss {row['val_loss']:.4f}  "
              f"(~{rate * (total_steps - step_now) / 3600:.1f} h left)", flush=True)

    def save(step_now):
        tmp = latest + ".tmp"
        torch.save({"model": model.state_dict(), "optimizer": opt.state_dict(), "step": step_now,
                    "rng": rng.bit_generator.state}, tmp)
        os.replace(tmp, latest)

    model.train()
    try:
        while step < total_steps:
            if step % a.eval_every == 0:
                log(step)
            t_step = time.time()
            lr_now = get_lr(step, total_steps, a.warmup, lr_max, lr_max * 0.1)
            for g in opt.param_groups:
                g["lr"] = lr_now
            for _ in range(a.grad_accum):
                x, y = data.train_batch(a.batch_size, rng)
                with autocast:
                    _, loss = model(x, y)
                (loss / a.grad_accum).backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); opt.zero_grad(set_to_none=True)
            if device == "cuda":
                torch.cuda.synchronize()
            train_seconds[0] += time.time() - t_step
            step += 1
            if step % a.save_every == 0:
                save(step)
            if a.halt_after and step - t_start_step >= a.halt_after:     # for testing pause/resume
                save(step)
                raise SystemExit(f"[{name}] halted at step {step} (test)")
        log(total_steps)
        save(total_steps)
        open(done_flag, "w").close()
    except KeyboardInterrupt:
        save(step)
        print(f"\n[{name}] paused at step {step:,}. Run the same command again to resume.")
        sys.exit(0)


def base_tokens_from(ckpt, V, seq_len):
    """Tokens a base checkpoint has read, from its step counter ("iter") and its version's batch settings."""
    if "iter" not in ckpt:
        return None
    return float(ckpt["iter"] * V.train.batch_size * V.train.grad_accum * seq_len)


# ------------------------------------------------------------------ report
def report(out_dir, base_units, base_loss=None):
    grown, scratch = read_log(os.path.join(out_dir, "grown.csv")), read_log(os.path.join(out_dir, "scratch.csv"))
    if not grown or not scratch:
        print("report: needs both grown.csv and scratch.csv in", out_dir)
        return None
    su, sl = np.array([r["units"] for r in scratch]), np.array([r["val_loss"] for r in scratch])
    print("\n==================== GROWTH TEST REPORT ====================")
    if base_loss is not None:
        print(f"before growing: loss {base_loss:.4f}   right after growing: {grown[0]['val_loss']:.4f}   "
              f"(growth dip {grown[0]['val_loss'] - base_loss:+.4f})")
    print(f"{'compute (billion layer-tokens)':>32} {'grown':>9} {'scratch':>9} {'gap':>8}")
    shown = 0
    for r in grown:
        if r["units"] > su.max() or r["units"] < su.min():
            continue
        s_at = float(np.interp(r["units"], su, sl))
        if shown % 2 == 0 or r is grown[-1]:
            print(f"{r['units'] / 1e9:>32.1f} {r['val_loss']:>9.4f} {s_at:>9.4f} {r['val_loss'] - s_at:>+8.4f}")
        shown += 1
    final = grown[-1]
    s_final_at = float(np.interp(final["units"], su, sl))
    print(f"\nat equal compute ({final['units'] / 1e9:.1f}B layer-tokens):  grown {final['val_loss']:.4f}   "
          f"scratch {s_final_at:.4f}   gap {final['val_loss'] - s_final_at:+.4f}  (negative = growth is better)")
    if sl.min() > final["val_loss"]:
        print("the scratch run never reached the grown model's loss, even with the same total compute: growth wins")
    else:
        # the first point where the scratch curve is at or below the grown model's final loss
        target = final["val_loss"]
        idx = int(np.argmax(sl <= target))
        if idx == 0:
            u_need = float(su[0])
        else:                                   # a straight line between the two points either side of it
            u_need = float(su[idx - 1] + (target - sl[idx - 1]) * (su[idx] - su[idx - 1]) / (sl[idx] - sl[idx - 1]))
        print(f"scratch needed ~{u_need / 1e9:.1f}B layer-tokens to match the grown model's final loss: "
              f"{u_need / final['units']:.2f}x the grown model's compute")
    print("============================================================")
    return final["val_loss"] - s_final_at


def main():
    p = argparse.ArgumentParser(description="Measure how much compute growing a trained model saves.")
    p.add_argument("--base_version", default="v2", choices=list(VERSIONS), help="the trained small model")
    p.add_argument("--from_ckpt", default=None, help="its checkpoint (default: <ckpt_dir>/final.pt, else ckpt.pt)")
    p.add_argument("--data_dir", default=None, help="folder with train.bin and val.bin (default: the base version's)")
    p.add_argument("--new_layers", type=int, default=24)
    p.add_argument("--style", default="stack", choices=["stack", "interleave"])
    p.add_argument("--grown_steps", type=int, default=4000, help="steps to train the grown model")
    p.add_argument("--batch_size", type=int, default=8)
    p.add_argument("--grad_accum", type=int, default=4, help="8 x 4 x 1024 = ~32k tokens per step")
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--warmup", type=int, default=200)
    p.add_argument("--eval_every", type=int, default=250)
    p.add_argument("--eval_iters", type=int, default=40)
    p.add_argument("--save_every", type=int, default=500)
    p.add_argument("--base_tokens", type=float, default=None, help="tokens the base model read (default: from its config)")
    p.add_argument("--out", default=None, help="results folder (default: growth_test/<base>-<style>-<layers>)")
    p.add_argument("--grad_checkpoint", action="store_true",
                   help="save GPU memory (30%% slower); needed for v3-size models on a 12 GB card")
    p.add_argument("--report_only", action="store_true")
    p.add_argument("--halt_after", type=int, default=0, help=argparse.SUPPRESS)      # for testing
    a = p.parse_args()

    V = get_version(a.base_version)
    ckpt_path = a.from_ckpt
    if not ckpt_path:
        for name in ("final.pt", "ckpt.pt"):
            if os.path.exists(os.path.join(V.ckpt_dir, name)):
                ckpt_path = os.path.join(V.ckpt_dir, name)
                break
    if not ckpt_path or not os.path.exists(ckpt_path):
        raise SystemExit(f"can't find the trained {a.base_version} model in {V.ckpt_dir} (final.pt or ckpt.pt). Use --from_ckpt.")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if device == "cuda" and torch.cuda.is_bf16_supported() else torch.float32
    autocast = torch.autocast(device_type=device, dtype=dtype, enabled=(device == "cuda"))
    out_dir = a.out or os.path.join("growth_test", f"{a.base_version}-{a.style}-{a.new_layers}")
    os.makedirs(out_dir, exist_ok=True)

    ckpt = torch.load(ckpt_path, map_location="cpu")
    base_cfg = ckpt["config"]
    base_layers = base_cfg["n_layers"]
    base_tokens = a.base_tokens or base_tokens_from(ckpt, V, base_cfg["max_seq_len"]) \
        or float(V.train.batch_size * V.train.grad_accum * base_cfg["max_seq_len"] * V.train.max_iters)
    base_units = base_tokens * base_layers
    cfg = ModelConfig(**dict(base_cfg, n_layers=a.new_layers))
    tokens_per_step = a.batch_size * a.grad_accum * cfg.max_seq_len
    grown_tokens = a.grown_steps * tokens_per_step
    # the SAME total compute for the scratch run: the base model's training (at 12 layers) counts too
    scratch_tokens = base_units / a.new_layers + grown_tokens
    scratch_steps = math.ceil(scratch_tokens / tokens_per_step)

    # the base model's own loss on the same validation text, to show the growth dip
    data = Data(a.data_dir or V.data_dir, cfg.max_seq_len, device)
    val = data.val_batches(a.batch_size, a.eval_iters)
    base = TinyLM(ModelConfig(**base_cfg)).to(device)
    base.load_state_dict(ckpt["model"])
    base_loss = val_loss(base, val, autocast)
    del base

    print(f"base: {ckpt_path} ({base_layers} layers, read ~{base_tokens / 1e9:.2f}B tokens, val loss {base_loss:.4f})")
    print(f"grown : {a.new_layers} layers ({a.style}), {a.grown_steps:,} steps = {grown_tokens / 1e6:.0f}M tokens")
    print(f"scratch: {a.new_layers} layers, {scratch_steps:,} steps = {scratch_tokens / 1e9:.2f}B tokens "
          f"(the same total compute)")
    print(f"results in {out_dir}\n")
    if a.report_only:
        report(out_dir, base_units, base_loss)
        return

    # --- run 1: grown
    new_state, new_cfg = grow_state_dict(ckpt["model"], base_cfg, a.new_layers, a.style)
    grown = TinyLM(ModelConfig(**new_cfg)).to(device)
    grown.load_state_dict(new_state)
    grown.grad_checkpoint = a.grad_checkpoint
    torch.manual_seed(1)
    train_arm("grown", grown, cfg, data, a, a.grown_steps, base_units, out_dir, device, autocast)
    del grown
    # --- run 2: from scratch, same total compute
    torch.manual_seed(2)
    scratch = TinyLM(cfg).to(device)
    scratch.grad_checkpoint = a.grad_checkpoint
    train_arm("scratch", scratch, cfg, data, a, scratch_steps, 0, out_dir, device, autocast)
    report(out_dir, base_units, base_loss)


if __name__ == "__main__":
    main()
