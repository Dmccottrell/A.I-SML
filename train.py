"""
train.py - Pretrain the model on data/train.bin.

Usage:  python train.py

Watch the val loss go down. Checkpoints are saved to checkpoints/dev/ (see stage.py).
"""
import os, math, time

import numpy as np
import torch

from model import TinyLM, ModelConfig
from stage import CKPT_DIR
from tokenizer import BPETokenizer

# ---------------- settings (sized for an 8GB NVIDIA GPU) ----------------
DATA_DIR = "data"
OUT_DIR = CKPT_DIR
batch_size = 32           # sequences per step (lower if you run out of memory)
grad_accum = 4            # effective batch = 32 * 4 = 128 sequences
max_iters = 20_000
warmup_iters = 1_000
lr_max, lr_min = 6e-4, 6e-5
weight_decay = 0.1
eval_every, eval_iters = 500, 50

device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = (torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16) if device == "cuda" else torch.float32

cfg = ModelConfig()
# Match the model's vocabulary to the tokenizer you actually trained
cfg.vocab_size = BPETokenizer.load(os.path.join(DATA_DIR, "tokenizer.json")).vocab_size
# -------------------------------------------------------------------------

os.makedirs(OUT_DIR, exist_ok=True)
torch.manual_seed(1337)


def get_batch(split):
    data = np.memmap(os.path.join(DATA_DIR, f"{split}.bin"), dtype=np.uint16, mode="r")
    ix = torch.randint(len(data) - cfg.max_seq_len - 1, (batch_size,))
    x = torch.stack([torch.from_numpy(data[i:i+cfg.max_seq_len].astype(np.int64)) for i in ix])
    y = torch.stack([torch.from_numpy(data[i+1:i+1+cfg.max_seq_len].astype(np.int64)) for i in ix])
    if device == "cuda":
        return x.pin_memory().to(device, non_blocking=True), y.pin_memory().to(device, non_blocking=True)
    return x.to(device), y.to(device)


def get_lr(it):
    """Linear warmup, then cosine decay."""
    if it < warmup_iters:
        return lr_max * (it + 1) / warmup_iters
    progress = min(1.0, (it - warmup_iters) / (max_iters - warmup_iters))
    return lr_min + 0.5 * (1 + math.cos(math.pi * progress)) * (lr_max - lr_min)


model = TinyLM(cfg).to(device)
print(f"model: {model.num_params()/1e6:.1f}M parameters on {device}")

# Weight decay on matrices only (not norms)
decay = [p for n, p in model.named_parameters() if p.dim() >= 2]
no_decay = [p for n, p in model.named_parameters() if p.dim() < 2]
optimizer = torch.optim.AdamW(
    [{"params": decay, "weight_decay": weight_decay},
     {"params": no_decay, "weight_decay": 0.0}],
    lr=lr_max, betas=(0.9, 0.95), fused=(device == "cuda"))
scaler = torch.amp.GradScaler(enabled=(dtype == torch.float16))
autocast = torch.autocast(device_type=device, dtype=dtype, enabled=(device == "cuda"))


@torch.no_grad()
def estimate_loss():
    model.eval()
    out = {}
    for split in ("train", "val"):
        losses = torch.zeros(eval_iters)
        for k in range(eval_iters):
            x, y = get_batch(split)
            with autocast:
                _, loss = model(x, y)
            losses[k] = loss.item()
        out[split] = losses.mean().item()
    model.train()
    return out


best_val = float("inf")
t0 = time.time()
for it in range(max_iters + 1):
    for g in optimizer.param_groups:
        g["lr"] = get_lr(it)

    if it % eval_every == 0:
        losses = estimate_loss()
        print(f"step {it}: train {losses['train']:.3f}  val {losses['val']:.3f}")
        if losses["val"] < best_val:
            best_val = losses["val"]
            torch.save({"model": model.state_dict(), "config": cfg.__dict__,
                        "iter": it, "val_loss": best_val},
                       os.path.join(OUT_DIR, "ckpt.pt"))

    for micro in range(grad_accum):
        x, y = get_batch("train")
        with autocast:
            _, loss = model(x, y)
        scaler.scale(loss / grad_accum).backward()
    scaler.unscale_(optimizer)
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    scaler.step(optimizer)
    scaler.update()
    optimizer.zero_grad(set_to_none=True)

    if it % 50 == 0:
        dt = time.time() - t0; t0 = time.time()
        print(f"iter {it}: loss {loss.item():.3f}  lr {get_lr(it):.2e}  {dt*1000/50:.0f}ms/iter")
