"""
train.py - Pretrain the model on data/train.bin.

WHAT THIS FILE DOES
    Teaches the model to predict the next token. It runs this loop
    `max_iters` times:

        1. get_batch()        grab random chunks of text (x) and the same
                              chunks shifted by one token (y = the answers)
        2. model(x, y)        forward pass: guess the next token everywhere,
                              measure how wrong the guesses are (the loss)
        3. loss.backward()    compute how to nudge every weight to lower the loss
        4. optimizer.step()   apply the nudge

    Every `eval_every` steps it measures loss on train AND val data and saves
    checkpoints/dev/ckpt.pt whenever val loss improves (see stage.py).

Usage:  python train.py

READING THE OUTPUT
    iter 100: loss 5.454  lr 6.06e-05  748ms/iter   <- every 50 iterations
    step 500: train 3.912  val 3.905                <- every 500 iterations
    Lower is better. Train and val should stay close; if train drops far
    below val, the model is memorizing instead of learning.
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
max_iters = 20_000        # total optimizer steps
warmup_iters = 1_000      # steps spent slowly ramping the learning rate up
lr_max, lr_min = 6e-4, 6e-5   # peak and final learning rate
weight_decay = 0.1        # gentle pull of weights toward 0 (reduces memorizing)
eval_every, eval_iters = 500, 50   # evaluate every 500 steps, averaging 50 batches

# Use the GPU if there is one. bfloat16 = fast 16-bit numbers on modern GPUs
# (RTX 30/40/50); older GPUs fall back to float16; CPU uses normal float32.
device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = (torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16) if device == "cuda" else torch.float32

cfg = ModelConfig()
# Match the model's vocabulary to the tokenizer you actually trained
cfg.vocab_size = BPETokenizer.load(os.path.join(DATA_DIR, "tokenizer.json")).vocab_size
# -------------------------------------------------------------------------

os.makedirs(OUT_DIR, exist_ok=True)
torch.manual_seed(1337)   # same random choices every run, so results are repeatable


def get_batch(split):
    """Return one batch of training examples as (x, y), both (batch_size, max_seq_len).

    y is x shifted ONE token to the right, so y[b, t] is the correct next
    token after x[b, t]. That shift is the entire trick of language-model training.

        text:  Once upon a time there
        x:     Once upon a    time
        y:     upon a    time there

    Args:
        split: "train" or "val" (which .bin file to read)
    """
    # memmap = treat the file on disk like an array without loading it all into RAM
    data = np.memmap(os.path.join(DATA_DIR, f"{split}.bin"), dtype=np.uint16, mode="r")
    ix = torch.randint(len(data) - cfg.max_seq_len - 1, (batch_size,))   # random start positions
    x = torch.stack([torch.from_numpy(data[i:i+cfg.max_seq_len].astype(np.int64)) for i in ix])
    y = torch.stack([torch.from_numpy(data[i+1:i+1+cfg.max_seq_len].astype(np.int64)) for i in ix])
    if device == "cuda":
        # pin_memory + non_blocking lets the CPU->GPU copy overlap with GPU work
        return x.pin_memory().to(device, non_blocking=True), y.pin_memory().to(device, non_blocking=True)
    return x.to(device), y.to(device)


def get_lr(it):
    """Learning rate for iteration `it`: linear warmup, then cosine decay.

        lr
        6e-4 |    /‾‾‾‾\\
             |   /      ‾\\
             |  /         ‾\\_
        6e-5 | /             ‾‾‾
             +-------------------> it
             0  1k            20k

    Warmup avoids huge, destabilising updates while weights are still random;
    the slow decay lets the model settle into a good solution at the end.
    """
    if it < warmup_iters:
        return lr_max * (it + 1) / warmup_iters
    progress = min(1.0, (it - warmup_iters) / (max_iters - warmup_iters))   # 0 -> 1
    return lr_min + 0.5 * (1 + math.cos(math.pi * progress)) * (lr_max - lr_min)


model = TinyLM(cfg).to(device)
print(f"model: {model.num_params()/1e6:.1f}M parameters on {device}")

# Weight decay on matrices only (not norms)
decay = [p for n, p in model.named_parameters() if p.dim() >= 2]
no_decay = [p for n, p in model.named_parameters() if p.dim() < 2]
# AdamW: the optimizer (the rule for nudging weights). It keeps a running
# average of each weight's gradients so updates are smooth and well-scaled.
optimizer = torch.optim.AdamW(
    [{"params": decay, "weight_decay": weight_decay},
     {"params": no_decay, "weight_decay": 0.0}],
    lr=lr_max, betas=(0.9, 0.95), fused=(device == "cuda"))
# GradScaler only matters for float16 (stops tiny gradients rounding to zero);
# it is switched off automatically with bfloat16.
scaler = torch.amp.GradScaler(enabled=(dtype == torch.float16))
# autocast: run big matrix multiplies in 16-bit for speed, sensitive math in 32-bit
autocast = torch.autocast(device_type=device, dtype=dtype, enabled=(device == "cuda"))


@torch.no_grad()
def estimate_loss():
    """Average the loss over `eval_iters` batches from train and from val.

    model.eval() switches off training-only behaviour (like dropout);
    model.train() switches it back on afterwards.
    Returns {"train": float, "val": float}.
    """
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


# ============================== main training loop ==============================
best_val = float("inf")
t0 = time.time()
for it in range(max_iters + 1):
    # Set this iteration's learning rate
    for g in optimizer.param_groups:
        g["lr"] = get_lr(it)

    # Periodically evaluate, and save a checkpoint if val loss is the best so far
    if it % eval_every == 0:
        losses = estimate_loss()
        print(f"step {it}: train {losses['train']:.3f}  val {losses['val']:.3f}")
        if losses["val"] < best_val:
            best_val = losses["val"]
            torch.save({"model": model.state_dict(), "config": cfg.__dict__,
                        "iter": it, "val_loss": best_val},
                       os.path.join(OUT_DIR, "ckpt.pt"))

    # Gradient accumulation: run several small batches and add up their
    # gradients before one optimizer step. Acts like one big batch of
    # 32 * 4 = 128 sequences without needing the memory for it.
    for micro in range(grad_accum):
        x, y = get_batch("train")
        with autocast:
            _, loss = model(x, y)
        scaler.scale(loss / grad_accum).backward()   # gradients ADD UP across micro-batches
    scaler.unscale_(optimizer)
    # Gradient clipping: cap the total gradient size at 1.0 so one bad batch
    # can't throw the weights far off course.
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    scaler.step(optimizer)                  # apply the nudge
    scaler.update()
    optimizer.zero_grad(set_to_none=True)   # clear gradients for the next step

    if it % 50 == 0:
        dt = time.time() - t0; t0 = time.time()
        print(f"iter {it}: loss {loss.item():.3f}  lr {get_lr(it):.2e}  {dt*1000/50:.0f}ms/iter")
