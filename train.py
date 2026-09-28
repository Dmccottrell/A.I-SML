"""
train.py - Pretrain the model on <data_dir>/train.bin.

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
    ckpt.pt whenever val loss improves. Settings come from config.py.

PAUSE AND RESUME
    Every `save_every` steps it also writes latest.pt (model + optimizer +
    step number). Press Ctrl+C to pause: it saves and exits. Run the same
    command again to continue where it stopped. This also recovers from a
    crash, restart or power cut (you lose at most `save_every` steps).
    Use --fresh to ignore latest.pt and start over.

v3+ EXTRAS (switched on in config.py)
    * "wsd" schedule: the learning rate holds steady, then fades over the last
      10% of steps while reading <data_dir>/anneal/train.bin, a higher-quality
      mix ("study the best material last"). pre_decay.pt is saved just before
      the fade, so the run can be continued later.
    * Mini-exam: every `exam_every` steps, 500 HellaSwag questions (see exam.py).
    * torch.compile: faster training when available (turns itself off if not).
    * metrics.csv (and TensorBoard graphs if installed) in the checkpoint folder:
          tensorboard --logdir checkpoints/dev/v3/tb
    * --backup_dir D:\ai-backups copies latest.pt there every 24 hours.

PILOT RUN (do this before any long run)
    --pilot trains just a few dozen steps into a separate folder and reports
    speed, GPU memory and the projected time for the full run. If it runs
    out of memory, lower batch_size (and raise grad_accum) or turn on
    grad_checkpoint in config.py, then pilot again. Nothing is saved.

Usage:  python train.py                    (v1: checkpoints/dev/)
        python train.py --version v2       (v2: checkpoints/dev/v2/)
        python train.py --version v2 --fresh
        python train.py --version v3 --pilot        (~60 steps, then a report)
        python train.py --version v3 --backup_dir D:\ai-backups

READING THE OUTPUT
    iter 100: loss 5.454  lr 6.06e-05  748ms/iter   <- every 50 iterations
    step 500: train 3.912  val 3.905                <- every eval_every iterations
    exam 2000: HellaSwag 31.4% (random = 25%)       <- every exam_every iterations (v3+)
    Lower is better. Train and val should stay close; if train drops far
    below val, the model is memorizing instead of learning.
"""
import argparse, csv, os, math, shutil, sys, time

import numpy as np
import torch

from config import add_version_arg, get_version
from model import TinyLM
from tokenizer import BPETokenizer

p = argparse.ArgumentParser()
add_version_arg(p)
p.add_argument("--fresh", action="store_true", help="ignore latest.pt and start from scratch")
p.add_argument("--pilot", type=int, nargs="?", const=60, default=0,
               help="trial run of N steps (default 60) that reports speed, memory and full-run time")
p.add_argument("--no_compile", action="store_true", help="don't try torch.compile")
p.add_argument("--backup_dir", default=None, help="also copy latest.pt to this folder (e.g. another drive)")
p.add_argument("--backup_every_hours", type=float, default=24)
args = p.parse_args()
V = get_version(args.version)
S = V.train                      # training settings for this version

# ---------------- settings ----------------
DATA_DIR = V.data_dir
OUT_DIR = V.ckpt_dir
if args.pilot:
    OUT_DIR = os.path.join(V.ckpt_dir, "pilot")   # never touches the real checkpoints
    args.fresh = True
BEST_PATH = os.path.join(OUT_DIR, "ckpt.pt")      # best val loss so far (use this one)
LATEST_PATH = os.path.join(OUT_DIR, "latest.pt")  # most recent state (for resuming)
PRE_DECAY_PATH = os.path.join(OUT_DIR, "pre_decay.pt")   # wsd: the state just before the fade
ANNEAL_DATA = os.path.join(DATA_DIR, "anneal", "train.bin")
# wsd schedule: the step where the learning rate starts to fade
DECAY_START = int(S.max_iters * (1 - S.decay_frac)) if S.schedule == "wsd" else S.max_iters + 1

# Use the GPU if there is one. bfloat16 = fast 16-bit numbers on modern GPUs
# (RTX 30/40/50); older GPUs fall back to float16; CPU uses normal float32.
device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = (torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16) if device == "cuda" else torch.float32

cfg = V.model
# Match the model's vocabulary to the tokenizer you actually trained
cfg.vocab_size = BPETokenizer.load(os.path.join(DATA_DIR, "tokenizer.json")).vocab_size
# ------------------------------------------

os.makedirs(OUT_DIR, exist_ok=True)
torch.manual_seed(1337)   # same random choices every run, so results are repeatable


def data_file(split, it=0):
    """Which .bin file to read: val.bin, train.bin, or (wsd, while fading) the anneal set."""
    if split == "train" and it >= DECAY_START and os.path.exists(ANNEAL_DATA):
        return ANNEAL_DATA
    return os.path.join(DATA_DIR, f"{split}.bin")


def get_batch(split, it=0):
    """Return one batch of training examples as (x, y), both (batch_size, max_seq_len).

    y is x shifted ONE token to the right, so y[b, t] is the correct next
    token after x[b, t]. That shift is the entire trick of language-model training.

        text:  Once upon a time there
        x:     Once upon a    time
        y:     upon a    time there

    Args:
        split: "train" or "val" (which .bin file to read)
        it:    the training step (decides when the wsd schedule switches to the anneal set)
    """
    # memmap = treat the file on disk like an array without loading it all into RAM
    data = np.memmap(data_file(split, it), dtype=np.uint16, mode="r")
    ix = torch.randint(len(data) - cfg.max_seq_len - 1, (S.batch_size,))   # random start positions
    x = torch.stack([torch.from_numpy(data[i:i+cfg.max_seq_len].astype(np.int64)) for i in ix])
    y = torch.stack([torch.from_numpy(data[i+1:i+1+cfg.max_seq_len].astype(np.int64)) for i in ix])
    if device == "cuda":
        # pin_memory + non_blocking lets the CPU->GPU copy overlap with GPU work
        return x.pin_memory().to(device, non_blocking=True), y.pin_memory().to(device, non_blocking=True)
    return x.to(device), y.to(device)


def get_lr(it):
    """Learning rate for iteration `it`: linear warmup, then cosine decay.

        lr
        max  |    /‾‾‾‾\\
             |   /      ‾\\
             |  /         ‾\\_
        min  | /             ‾‾‾
             +-------------------> it
             0  warmup      max_iters

    Warmup avoids huge, destabilising updates while weights are still random;
    the slow decay lets the model settle into a good solution at the end.

    With schedule="wsd" (warmup-stable-decay) it holds lr_max instead, then
    fades in a straight line over the last decay_frac of steps:

        max  |    /‾‾‾‾‾‾‾‾‾‾‾‾‾\
        min  | /                 \
             +-------------------> it
             0  warmup   DECAY_START  max_iters
    """
    if it < S.warmup_iters:
        return S.lr_max * (it + 1) / S.warmup_iters
    if S.schedule == "wsd":
        if it < DECAY_START:
            return S.lr_max
        progress = min(1.0, (it - DECAY_START) / max(1, S.max_iters - DECAY_START))   # 0 -> 1
        return S.lr_max + progress * (S.lr_min - S.lr_max)
    progress = min(1.0, (it - S.warmup_iters) / (S.max_iters - S.warmup_iters))   # 0 -> 1
    return S.lr_min + 0.5 * (1 + math.cos(math.pi * progress)) * (S.lr_max - S.lr_min)


model = TinyLM(cfg).to(device)
model.grad_checkpoint = S.grad_checkpoint
print(f"{V.name}: {model.num_params()/1e6:.1f}M parameters on {device}"
      + ("  (gradient checkpointing on)" if S.grad_checkpoint else ""))

# Weight decay on matrices only (not norms)
decay = [p for n, p in model.named_parameters() if p.dim() >= 2]
no_decay = [p for n, p in model.named_parameters() if p.dim() < 2]
# AdamW: the optimizer (the rule for nudging weights). It keeps a running
# average of each weight's gradients so updates are smooth and well-scaled.
optimizer = torch.optim.AdamW(
    [{"params": decay, "weight_decay": S.weight_decay},
     {"params": no_decay, "weight_decay": 0.0}],
    lr=S.lr_max, betas=(0.9, 0.95), fused=(device == "cuda"))
# GradScaler only matters for float16 (stops tiny gradients rounding to zero);
# it is switched off automatically with bfloat16.
scaler = torch.amp.GradScaler(enabled=(dtype == torch.float16))
# autocast: run big matrix multiplies in 16-bit for speed, sensitive math in 32-bit
autocast = torch.autocast(device_type=device, dtype=dtype, enabled=(device == "cuda"))


def save_atomic(obj, path):
    """torch.save to a temporary file, then rename it into place.

    If the PC loses power mid-save, the previous file is still intact
    (a half-written checkpoint would be unusable).
    """
    tmp = path + ".tmp"
    torch.save(obj, tmp)
    os.replace(tmp, path)


def save_latest(next_iter, path=LATEST_PATH):
    """Save everything needed to resume training at iteration `next_iter`."""
    save_atomic({"model": model.state_dict(), "optimizer": optimizer.state_dict(),
                 "scaler": scaler.state_dict(), "config": cfg.__dict__,
                 "iter": next_iter, "best_val": best_val,
                 "rng": torch.get_rng_state()}, path)


last_backup = time.time()


def maybe_backup():
    """Copy latest.pt to --backup_dir every --backup_every_hours (e.g. to another drive)."""
    global last_backup
    if not args.backup_dir or time.time() - last_backup < args.backup_every_hours * 3600:
        return
    os.makedirs(args.backup_dir, exist_ok=True)
    dest = os.path.join(args.backup_dir, f"{V.name}_latest.pt")
    shutil.copyfile(LATEST_PATH, dest + ".tmp")
    os.replace(dest + ".tmp", dest)
    last_backup = time.time()
    print(f"backed up latest.pt to {dest}")


# ---- progress log: metrics.csv always, TensorBoard graphs if it's installed ----
tb = None
if not args.pilot:
    try:
        from torch.utils.tensorboard import SummaryWriter
        tb = SummaryWriter(os.path.join(OUT_DIR, "tb"))
    except Exception:
        pass                          # optional: pip install tensorboard


def log_metric(it, name, value):
    """Append one number to metrics.csv (and TensorBoard): e.g. (2000, "val_loss", 3.1)."""
    if args.pilot:
        return
    path = os.path.join(OUT_DIR, "metrics.csv")
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "iter", "metric", "value"])
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), it, name, f"{value:.5g}"])
    if tb is not None:
        tb.add_scalar(name, value, it)
        tb.flush()


# ---- mini-exam: 500 HellaSwag questions (see exam.py) ----
exam_questions = None
if S.exam_every and not args.pilot:
    try:
        from benchmarks import load_hellaswag
        exam_questions = load_hellaswag()[:500]
        exam_tok = BPETokenizer.load(os.path.join(DATA_DIR, "tokenizer.json"))
    except Exception as e:
        print(f"mini-exam off: couldn't load HellaSwag ({e})")


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
        losses = torch.zeros(S.eval_iters)
        for k in range(S.eval_iters):
            x, y = get_batch(split)
            with autocast:
                _, loss = train_model(x, y)
            losses[k] = loss.item()
        out[split] = losses.mean().item()
    model.train()
    return out


# ---- torch.compile: turns the model into faster GPU code (optional) ----
# The first steps are slow while it compiles. If it isn't available (on
# Windows it needs: pip install triton-windows), training continues without it.
train_model = model
if S.compile and not args.no_compile and device == "cuda":
    try:
        train_model = torch.compile(model)
        x, y = get_batch("train")
        with autocast:
            _, loss = train_model(x, y)        # compiles now, so errors show up here
        loss.backward()
        optimizer.zero_grad(set_to_none=True)
        print("torch.compile: on")
    except Exception as e:
        train_model = model
        optimizer.zero_grad(set_to_none=True)
        print(f"torch.compile: off ({type(e).__name__}). Training without it; "
              "on Windows, `pip install triton-windows` can enable it.")
        why = " ".join(str(e).split())[:500]          # the reason, on one line
        print(f"  reason: {why}")
        low = why.lower()
        if "triton" in low:
            print("  hint: pip install -U triton-windows")
        if "cl.exe" in low or "compiler" in low or "visual studio" in low:
            print("  hint: install Visual Studio Build Tools (Desktop development with C++), then run "
                  "from the 'x64 Native Tools Command Prompt for VS'")

# ---- resume from latest.pt if there is one ----
start_iter, best_val = 0, float("inf")
if os.path.exists(LATEST_PATH) and not args.fresh:
    state = torch.load(LATEST_PATH, map_location=device)
    model.load_state_dict(state["model"])
    optimizer.load_state_dict(state["optimizer"])
    if state["scaler"]:
        # Only float16 GPUs use the scaler. A run saved on a bfloat16 GPU (RTX 30/40/50)
        # has an empty one, so a float16 GPU (e.g. Kaggle's T4) just starts it fresh.
        scaler.load_state_dict(state["scaler"])
    torch.set_rng_state(state["rng"].cpu())
    start_iter, best_val = state["iter"], state["best_val"]
    if start_iter > S.max_iters:
        sys.exit(f"training already finished ({LATEST_PATH}); use --fresh to start over")
    print(f"resuming from iteration {start_iter} (best val so far {best_val:.3f})")

# ============================== main training loop ==============================
t0 = time.time()
it = start_iter
pilot_times = []                 # seconds per iteration, for the pilot report
try:
    for it in range(start_iter, S.max_iters + 1):
        # Save a resume point regularly (the state BEFORE doing iteration `it`)
        if it > start_iter and it % S.save_every == 0 and not args.pilot:
            save_latest(it)
            maybe_backup()
        if it == DECAY_START and not args.pilot:
            save_latest(it, PRE_DECAY_PATH)      # can be trained further later
            print(f"step {it}: learning rate starts to fade"
                  + (f"; now reading the anneal set ({ANNEAL_DATA})" if os.path.exists(ANNEAL_DATA) else ""))

        # Set this iteration's learning rate
        for g in optimizer.param_groups:
            g["lr"] = get_lr(it)

        # Periodically evaluate, and save a checkpoint if val loss is the best so far
        if it % S.eval_every == 0:
            losses = estimate_loss()
            print(f"step {it}: train {losses['train']:.3f}  val {losses['val']:.3f}")
            log_metric(it, "train_loss", losses["train"])
            log_metric(it, "val_loss", losses["val"])
            if losses["val"] < best_val and not args.pilot:
                best_val = losses["val"]
                save_atomic({"model": model.state_dict(), "config": cfg.__dict__,
                             "iter": it, "val_loss": best_val}, BEST_PATH)

        if exam_questions and it % S.exam_every == 0 and it > 0:
            from exam import hellaswag_accuracy
            acc = hellaswag_accuracy(model, exam_tok, exam_questions, device, autocast)
            print(f"exam {it}: HellaSwag {acc*100:.1f}% (random = 25%)")
            log_metric(it, "hellaswag_500", acc)

        # Gradient accumulation: run several small batches and add up their
        # gradients before one optimizer step. Acts like one big batch
        # without needing the memory for it.
        t_iter = time.time()
        for micro in range(S.grad_accum):
            x, y = get_batch("train", it)
            with autocast:
                _, loss = train_model(x, y)
            scaler.scale(loss / S.grad_accum).backward()   # gradients ADD UP across micro-batches
        if args.pilot and it == start_iter:
            pilot_first_loss = loss.item()
        scaler.unscale_(optimizer)
        # Gradient clipping: cap the total gradient size at 1.0 so one bad batch
        # can't throw the weights far off course.
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        scaler.step(optimizer)                  # apply the nudge
        scaler.update()
        optimizer.zero_grad(set_to_none=True)   # clear gradients for the next step

        if args.pilot:
            if device == "cuda":
                torch.cuda.synchronize()
            pilot_times.append(time.time() - t_iter)
            if it % 10 == 0:
                print(f"pilot iter {it}: loss {loss.item():.3f}  {pilot_times[-1]*1000:.0f}ms/iter")
            if it + 1 >= args.pilot:
                break
        elif it % 50 == 0:
            dt = time.time() - t0; t0 = time.time()
            print(f"iter {it}: loss {loss.item():.3f}  lr {get_lr(it):.2e}  {dt*1000/50:.0f}ms/iter")
            log_metric(it, "loss", loss.item())
            log_metric(it, "lr", get_lr(it))
except KeyboardInterrupt:
    if args.pilot:
        sys.exit("\npilot stopped")
    # Ctrl+C: iteration `it` didn't finish, so resume will redo it
    optimizer.zero_grad(set_to_none=True)
    save_latest(it)
    print(f"\npaused at iteration {it}. Run the same command again to resume.")
    sys.exit(0)
except torch.cuda.OutOfMemoryError:
    sys.exit(f"\nOUT OF GPU MEMORY at iteration {it}. In config.py ({V.name}): halve batch_size and "
             "double grad_accum, or set grad_checkpoint=True, then try --pilot again.")

if args.pilot:
    steady = pilot_times[5:] or pilot_times       # skip the slow first few steps
    sec = sum(steady) / len(steady)
    tokens = S.batch_size * S.grad_accum * cfg.max_seq_len
    evals = (S.max_iters // S.eval_every + 1) * 2 * S.eval_iters * sec / S.grad_accum
    total_h = (sec * S.max_iters + evals) / 3600
    print("\n==================== PILOT REPORT ====================")
    print(f"model:          {V.name}, {model.num_params()/1e6:.1f}M parameters, "
          f"grad_checkpoint={S.grad_checkpoint}, compile={'on' if train_model is not model else 'off'}")
    print(f"speed:          {sec:.2f} s/iter = {tokens/sec/1e3:.1f}k tokens/s")
    if device == "cuda":
        print(f"GPU memory:     {torch.cuda.max_memory_reserved()/2**30:.1f} GB peak "
              f"of {torch.cuda.get_device_properties(0).total_memory/2**30:.1f} GB")
    print(f"loss:           {pilot_first_loss:.3f} -> {loss.item():.3f} (should be going down)")
    print(f"full run:       {S.max_iters:,} iters ~ {total_h:.0f} hours ({total_h/24:.1f} days)")
    print("=======================================================")
    sys.exit(0)

save_latest(S.max_iters + 1)   # marks training as finished
# The FINAL weights: usually the best model, since the learning rate ends small.
# (ckpt.pt keeps the best val score, but val scores are noisy by about +-0.05.)
FINAL_PATH = os.path.join(OUT_DIR, "final.pt")
save_atomic({"model": model.state_dict(), "config": cfg.__dict__,
             "iter": S.max_iters, "val_loss": best_val}, FINAL_PATH)
if args.backup_dir:
    os.makedirs(args.backup_dir, exist_ok=True)
    shutil.copyfile(FINAL_PATH, os.path.join(args.backup_dir, f"{V.name}_final.pt"))
print(f"done. best val loss {best_val:.3f} (ckpt.pt); final weights saved in {FINAL_PATH}")
