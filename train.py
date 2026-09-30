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

MORE THAN ONE GPU (DDP; a rented machine with 2 or more GPUs, e.g. 2 x RTX 3090)
    Start it with torchrun (or run_training.py --gpus 2, which does that for you):
        torchrun --standalone --nproc_per_node=2 train.py --version v3
    Every GPU holds a full copy of the model and reads DIFFERENT text; their gradients are
    averaged once per step. The settings don't change: grad_accum is the TOTAL number of
    micro-batches per step, shared between the GPUs (so it must divide evenly), which keeps
    every step the same size as on one GPU. Only the first process prints, evaluates and saves.
    A checkpoint saved on 1 GPU resumes on 2, and the other way round.
    Needs a GPU with room for the whole model + optimizer (v3.5: 24 GB is enough with
    gradient checkpointing; use optimizer="adamw", not "adamw_cpu", which would need each GPU's
    own copy of ~17 GB of RAM).

Usage:  python train.py                    (v1: checkpoints/dev/)
        python train.py --version v2       (v2: checkpoints/dev/v2/)
        python train.py --version v2 --fresh
        python train.py --version v3 --pilot        (~60 steps, then a report)
        python train.py --version v3 --backup_dir D:\ai-backups
        python train.py --version v3-long-8k --pilot   (after v3 finishes: the first stretch, docs/LONG_CONTEXT.md)

READING THE OUTPUT
    iter 100: loss 5.454  lr 6.06e-05  748ms/iter   <- every 50 iterations
    step 500: train 3.912  val 3.905                <- every eval_every iterations
    exam 2000: HellaSwag 31.4% (random = 25%)       <- every exam_every iterations (v3+)
    Lower is better. Train and val should stay close; if train drops far
    below val, the model is memorizing instead of learning.
"""
import argparse, csv, os, math, shutil, sys, time

# Windows only: torch.compile keeps its cache in a long folder path under %TEMP%, and file paths
# over 260 characters fail there ("FileNotFoundError ... triton ... .json"). A short folder avoids it.
if os.name == "nt" and "TORCHINDUCTOR_CACHE_DIR" not in os.environ:
    for _base in (os.environ.get("SystemDrive", "C:") + os.sep, os.path.expanduser("~")):
        try:
            os.makedirs(os.path.join(_base, "ti"), exist_ok=True)
            os.environ["TORCHINDUCTOR_CACHE_DIR"] = os.path.join(_base, "ti")
            break
        except OSError:
            continue

import contextlib

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
p.add_argument("--hub_backup", default=os.environ.get("HUB_BACKUP"),
               help="private Hugging Face repo (e.g. yourname/aisml-checkpoints): keep a copy of latest.pt OFF "
                    "this machine, uploaded every --hub_every_hours and when training stops (see hub_backup.py)")
p.add_argument("--hub_every_hours", type=float, default=2)
p.add_argument("--notify", default=os.environ.get("NTFY_TOPIC"),
               help="ntfy.sh topic: send progress messages to your phone (see notify.py)")
p.add_argument("--notify_every", type=int, default=250, help="steps between progress messages")
p.add_argument("--stop_at", type=float, default=0,
               help="(used by run_training.py --window) save and stop after the step that ends past this time")
args = p.parse_args()
if args.backup_dir and not args.pilot:
    # Check the backup folder NOW, so a typo or a missing drive stops the run in seconds,
    # not after 24 hours of training.
    try:
        os.makedirs(args.backup_dir, exist_ok=True)
    except OSError as e:
        sys.exit(f"can't use --backup_dir {args.backup_dir!r}: {e}\n"
                 "Pick a folder on a drive that exists (e.g. C:\\ai-backups), or leave --backup_dir out.")
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

# ---------------- several GPUs (DDP), started by torchrun ----------------
WORLD = int(os.environ.get("WORLD_SIZE", "1"))      # how many processes (GPUs) are training together
RANK = int(os.environ.get("RANK", "0"))
LOCAL_RANK = int(os.environ.get("LOCAL_RANK", "0"))
DIST = WORLD > 1
IS_MAIN = RANK == 0                                   # only the first process prints, evaluates and saves
if DIST:
    import datetime
    import signal
    import torch.distributed as dist
    # a long timeout: the other GPUs wait while the first one evaluates or saves a big checkpoint
    dist.init_process_group(backend="nccl" if torch.cuda.is_available() else "gloo",
                            timeout=datetime.timedelta(minutes=60))
    if torch.cuda.is_available():
        torch.cuda.set_device(LOCAL_RANK)
    if hasattr(signal, "SIGTERM"):                    # torchrun stops its workers with SIGTERM: treat it like Ctrl+C
        def _stop(*_):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, _stop)


def phone(text, title="v3"):
    """Push a short message to the phone (only from the first process; never stops training)."""
    if IS_MAIN and args.notify and not args.pilot:
        from notify import send
        send(args.notify, text, title=f"{title} {V.name}")


def mprint(*a, **k):
    """print, but only from the first process"""
    if IS_MAIN:
        print(*a, **k)


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
ACCUM = S.grad_accum      # micro-batches THIS process runs per step
if DIST:
    if S.grad_accum % WORLD:
        sys.exit(f"grad_accum ({S.grad_accum}) must divide evenly between {WORLD} GPUs. "
                 "Change grad_accum in config.py or use a different number of GPUs.")
    ACCUM = S.grad_accum // WORLD
PAUSE_MARKER = os.path.join(OUT_DIR, "paused_on_schedule")   # tells run_training.py "stopped on schedule"


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
model.checkpoint_every = S.checkpoint_every
model.loss_chunk = S.loss_chunk
if S.init_from and (args.fresh or not os.path.exists(LATEST_PATH)):
    # Long-context stretching: start from a trained model's weights (not its optimizer or step count).
    # Its context length and RoPE base may differ from cfg; everything else must match.
    if not os.path.exists(S.init_from):
        if not args.pilot:
            sys.exit(f"{V.name} starts from {S.init_from}, which doesn't exist yet. Finish that run first "
                     "(or copy its final.pt there).")
        mprint(f"(pilot: {S.init_from} not found, so the pilot uses random weights; speed and memory are the same)")
    else:
        src = torch.load(S.init_from, map_location="cpu")
        mine = {k: v for k, v in cfg.__dict__.items() if k not in ("max_seq_len", "rope_theta", "dropout")}
        theirs = {k: src["config"].get(k) for k in mine}
        if mine != theirs:
            sys.exit(f"{S.init_from} is a different model: " + ", ".join(
                f"{k} {theirs[k]} vs {mine[k]}" for k in mine if mine[k] != theirs[k]))
        model.load_state_dict(src["model"])
        mprint(f"starting from {S.init_from} (context {src['config']['max_seq_len']:,} -> {cfg.max_seq_len:,}, "
               f"RoPE base {src['config']['rope_theta']:,.0f} -> {cfg.rope_theta:,.0f})")
        del src
mprint(f"{V.name}: {model.num_params()/1e6:.1f}M parameters on {device}"
       + (f" x {WORLD} GPUs (DDP)" if DIST else "")
       + (f"  (gradient checkpointing on, every {S.checkpoint_every} block)" if S.grad_checkpoint else "")
       + (f"  (context {cfg.max_seq_len:,}, loss in chunks of {S.loss_chunk:,})" if S.loss_chunk else ""))
# With several GPUs the model is wrapped so gradients are averaged across them. `model` stays the plain
# model (for saving, loading and evaluating); `wrapped` is what training runs through.
wrapped = model
if DIST:
    from torch.nn.parallel import DistributedDataParallel as DDP
    wrapped = DDP(model, device_ids=[LOCAL_RANK] if device == "cuda" else None, broadcast_buffers=False)
    torch.manual_seed(1337 + RANK)      # the same weights everywhere (DDP copied them), but different text per GPU

# Weight decay on matrices only (not norms)
decay = [p for n, p in model.named_parameters() if p.dim() >= 2]
no_decay = [p for n, p in model.named_parameters() if p.dim() < 2]
# AdamW: the optimizer (the rule for nudging weights). It keeps a running
# average of each weight's gradients so updates are smooth and well-scaled.
groups = [{"params": decay, "weight_decay": S.weight_decay},
          {"params": no_decay, "weight_decay": 0.0}]
if S.optimizer == "muon":
    # Muon for the blocks' weight matrices, AdamW for embeddings and norms (see muon.py and muon_test.py)
    from muon import Muon, muon_param_groups
    optimizer = Muon(muon_param_groups(model, S.weight_decay), lr=S.lr_max)
elif S.optimizer == "adamw_cpu":
    # Its memory lives in system RAM (see offload_optim.py): for models too big for the GPU
    from offload_optim import CPUOffloadAdamW
    optimizer = CPUOffloadAdamW(groups, lr=S.lr_max, betas=(0.9, 0.95))
elif S.optimizer == "adamw8bit":
    try:
        import bitsandbytes as bnb
    except ImportError:
        sys.exit("optimizer 'adamw8bit' needs:  pip install bitsandbytes")
    optimizer = bnb.optim.AdamW8bit(groups, lr=S.lr_max, betas=(0.9, 0.95))
else:
    optimizer = torch.optim.AdamW(groups, lr=S.lr_max, betas=(0.9, 0.95), fused=(device == "cuda"))
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
    if not IS_MAIN:
        return
    save_atomic({"model": model.state_dict(), "optimizer": optimizer.state_dict(),
                 "scaler": scaler.state_dict(), "config": cfg.__dict__,
                 "iter": next_iter, "best_val": best_val,
                 "rng": torch.get_rng_state()}, path)


last_backup = time.time()


def maybe_backup():
    """Copy latest.pt to --backup_dir every --backup_every_hours (e.g. to another drive)."""
    global last_backup
    if not IS_MAIN or not args.backup_dir or time.time() - last_backup < args.backup_every_hours * 3600:
        return
    last_backup = time.time()          # on failure, try again at the next interval
    try:
        os.makedirs(args.backup_dir, exist_ok=True)
        dest = os.path.join(args.backup_dir, f"{V.name}_latest.pt")
        shutil.copyfile(LATEST_PATH, dest + ".tmp")
        os.replace(dest + ".tmp", dest)
        print(f"backed up latest.pt to {dest}")
    except OSError as e:               # never let a backup problem stop the training
        print(f"WARNING: backup to {args.backup_dir} failed ({e}). Training continues.")


# ---- off-machine backup (a private Hugging Face repo), so a machine that dies doesn't take the run with it ----
hub = None
if args.hub_backup and IS_MAIN and not args.pilot:
    from hub_backup import HubBackup
    def _hub_tell(message):
        print(message, flush=True)
        if "FAILED" in message or "can't" in message:      # only problems go to the phone
            phone(message, "backup")
    hub = HubBackup(args.hub_backup, V.name, tell=_hub_tell)
    if hub.check():
        hub.last_upload = time.time()          # the first upload comes after --hub_every_hours
        print(f"hub backup: latest.pt goes to {args.hub_backup} every {args.hub_every_hours:g} h and when training stops")
    else:
        hub = None


def hub_upload(next_iter, wait=False, name="latest.pt", path=None):
    """Upload the newest checkpoint to the hub backup (in the background, or now and wait)."""
    if hub is None:
        return
    path = path or LATEST_PATH
    if wait:
        print("uploading the off-machine backup before stopping (Ctrl+C again to skip it)...", flush=True)
        try:
            hub.upload(path, next_iter, name)
        except KeyboardInterrupt:
            print("backup upload skipped")
    else:
        hub.upload_in_background(path, next_iter, name)


# ---- progress log: metrics.csv always, TensorBoard graphs if it's installed ----
tb = None
if not args.pilot and IS_MAIN:
    try:
        from torch.utils.tensorboard import SummaryWriter
        tb = SummaryWriter(os.path.join(OUT_DIR, "tb"))
    except Exception:
        pass                          # optional: pip install tensorboard


def log_metric(it, name, value):
    """Append one number to metrics.csv (and TensorBoard): e.g. (2000, "val_loss", 3.1)."""
    if args.pilot or not IS_MAIN:
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
if S.exam_every and not args.pilot and IS_MAIN:
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
                _, loss = (model if DIST else train_model)(x, y)     # not the DDP wrapper: only one GPU evaluates
            losses[k] = loss.item()
        out[split] = losses.mean().item()
    model.train()
    return out


# ---- torch.compile: turns the model into faster GPU code (optional) ----
# The first steps are slow while it compiles. If it isn't available (on
# Windows it needs: pip install triton-windows), training continues without it.
train_model = wrapped
if S.compile and not args.no_compile and device == "cuda":
    try:
        train_model = torch.compile(wrapped)
        x, y = get_batch("train")
        with autocast:
            _, loss = train_model(x, y)        # compiles now, so errors show up here
        loss.backward()
        optimizer.zero_grad(set_to_none=True)
        mprint("torch.compile: on")
    except Exception as e:
        train_model = wrapped
        optimizer.zero_grad(set_to_none=True)
        mprint(f"torch.compile: off ({type(e).__name__}). Training without it; "
               "on Windows, `pip install triton-windows` can enable it.")
        why = " ".join(str(e).split())[:500]          # the reason, on one line
        mprint(f"  reason: {why}")
        low = why.lower()
        if "triton" in low:
            mprint("  hint: pip install -U triton-windows")
        if "cl.exe" in low or "compiler" in low or "visual studio" in low:
            mprint("  hint: install Visual Studio Build Tools (Desktop development with C++), then run "
                   "from the 'x64 Native Tools Command Prompt for VS'")

# ---- resume from latest.pt if there is one ----
start_iter, best_val = 0, float("inf")
if os.path.exists(LATEST_PATH) and not args.fresh:
    # Load onto the CPU, NOT the GPU: a checkpoint is ~5 GB (v3) and a copy left on the GPU pushed a 12 GB
    # card over its limit, so Windows spilled into slow system memory and training ran ~5x slower.
    # load_state_dict copies the values to wherever the model and optimizer live.
    state = torch.load(LATEST_PATH, map_location="cpu")
    model.load_state_dict(state["model"])
    optimizer.load_state_dict(state["optimizer"])
    if state["scaler"]:
        # Only float16 GPUs use the scaler. A run saved on a bfloat16 GPU (RTX 30/40/50)
        # has an empty one, so a float16 GPU (e.g. Kaggle's T4) just starts it fresh.
        scaler.load_state_dict(state["scaler"])
    start_iter, best_val = state["iter"], state["best_val"]
    if DIST:      # every GPU must read DIFFERENT text, so don't all restore the same random state
        torch.manual_seed(1337 + RANK + 100_003 * start_iter)
    else:
        torch.set_rng_state(state["rng"].cpu())
    if start_iter > S.max_iters:
        sys.exit(f"training already finished ({LATEST_PATH}); use --fresh to start over")
    del state                                     # free the CPU copy too
    if device == "cuda":
        torch.cuda.empty_cache()
    mprint(f"resuming from iteration {start_iter} (best val so far {best_val:.3f})")
    phone(f"resumed at step {start_iter:,} of {S.max_iters:,}", "resumed")

# ============================== main training loop ==============================
t0 = time.time()
it = start_iter
last_printed = start_iter - 1     # the iteration of the last "iter N" line (for the time per iteration)
pilot_times = []                 # seconds per iteration, for the pilot report
try:
    for it in range(start_iter, S.max_iters + 1):
        # Save a resume point regularly (the state BEFORE doing iteration `it`)
        if it > start_iter and it % S.save_every == 0 and not args.pilot:
            save_latest(it)
            maybe_backup()
            if hub is not None and hub.due(args.hub_every_hours):
                hub_upload(it)
        if it == DECAY_START and not args.pilot:
            save_latest(it, PRE_DECAY_PATH)      # can be trained further later
            mprint(f"step {it}: learning rate starts to fade"
                   + (f"; now reading the anneal set ({ANNEAL_DATA})" if os.path.exists(ANNEAL_DATA) else ""))

        # Set this iteration's learning rate
        for g in optimizer.param_groups:
            g["lr"] = get_lr(it)

        # Periodically evaluate, and save a checkpoint if val loss is the best so far
        if it % S.eval_every == 0 and IS_MAIN:
            losses = estimate_loss()
            print(f"step {it}: train {losses['train']:.3f}  val {losses['val']:.3f}")
            phone(f"step {it:,}: train {losses['train']:.3f}, val {losses['val']:.3f}", "val")
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
            phone(f"step {it:,}: HellaSwag {acc*100:.1f}% (random is 25%)", "exam")
            log_metric(it, "hellaswag_500", acc)

        # Gradient accumulation: run several small batches and add up their
        # gradients before one optimizer step. Acts like one big batch
        # without needing the memory for it.
        t_iter = time.time()
        for micro in range(ACCUM):
            x, y = get_batch("train", it)
            # With several GPUs, gradients are shared between them only after the LAST micro-batch
            sync = wrapped.no_sync() if (DIST and micro < ACCUM - 1) else contextlib.nullcontext()
            with sync:
                with autocast:
                    _, loss = train_model(x, y)
                scaler.scale(loss / ACCUM).backward()      # gradients ADD UP across micro-batches
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
                mprint(f"pilot iter {it}: loss {loss.item():.3f}  {pilot_times[-1]*1000:.0f}ms/iter")
            if it + 1 >= args.pilot:
                break
        elif it % 50 == 0:
            # Divide by the iterations actually run since the last line: after a resume (e.g. at 1383)
            # the first line (1400) covers only 18 of them, not 50, and dividing by 50 showed ~3x too fast.
            dt = time.time() - t0; t0 = time.time()
            per_it = dt / max(1, it - last_printed)
            last_printed = it
            mprint(f"iter {it}: loss {loss.item():.3f}  lr {get_lr(it):.2e}  {per_it*1000:.0f}ms/iter")
            log_metric(it, "loss", loss.item())
            log_metric(it, "lr", get_lr(it))
            if it > start_iter and it % args.notify_every == 0:
                left_h = (S.max_iters - it) * per_it / 3600
                phone(f"step {it:,}/{S.max_iters:,} ({100 * it / S.max_iters:.1f}%)  loss {loss.item():.2f}  "
                      f"{per_it:.1f} s/step  ~{left_h / 24:.1f} days left", "progress")

        if args.stop_at and it < S.max_iters:
            stop = time.time() >= args.stop_at
            if DIST:                              # every GPU must stop on the SAME step, so the first one decides
                flag = torch.tensor([1.0 if stop else 0.0], device=device)
                dist.broadcast(flag, src=0)
                stop = flag.item() > 0.5
            if stop:
                # The run window is over: iteration `it` is done, so save and stop (resume starts at it + 1)
                save_latest(it + 1)
                if IS_MAIN:
                    print(f"\nrun window over: saved at iteration {it + 1}. Training resumes at the next window.")
                    hub_upload(it + 1, wait=True)
                    phone(f"window over: saved at step {it + 1:,}" + (" (backed up)" if hub else ""), "paused")
                    open(PAUSE_MARKER, "w").close()     # torchrun can't pass on an exit code, so leave a note
                if DIST:
                    dist.barrier()                # let the first GPU finish saving before anyone exits
                sys.exit(0 if DIST else 75)       # 75 = "paused on schedule" (run_training.py waits, then restarts)
except KeyboardInterrupt:
    if args.pilot:
        sys.exit("\npilot stopped")
    # Ctrl+C: iteration `it` didn't finish, so resume will redo it
    optimizer.zero_grad(set_to_none=True)
    save_latest(it)
    if IS_MAIN:
        hub_upload(it, wait=True)
    mprint(f"\npaused at iteration {it}. Run the same command again to resume.")
    phone(f"paused at step {it:,} (stopped by you)", "paused")
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
    if IS_MAIN:
        print("\n==================== PILOT REPORT ====================")
        print(f"model:          {V.name}, {model.num_params()/1e6:.1f}M parameters, "
              f"grad_checkpoint={S.grad_checkpoint}, optimizer={S.optimizer}, "
              f"compile={'on' if train_model is not wrapped else 'off'}"
              + (f", {WORLD} GPUs (DDP)" if DIST else ""))
        print(f"speed:          {sec:.2f} s/iter = {tokens/sec/1e3:.1f}k tokens/s")
        if device == "cuda":
            print(f"GPU memory:     {torch.cuda.max_memory_reserved()/2**30:.1f} GB peak "
                  f"of {torch.cuda.get_device_properties(0).total_memory/2**30:.1f} GB (per GPU)")
        print(f"loss:           {pilot_first_loss:.3f} -> {loss.item():.3f} (should be going down)")
        print(f"full run:       {S.max_iters:,} iters ~ {total_h:.0f} hours ({total_h/24:.1f} days)")
        print("=======================================================")
    if DIST:
        dist.barrier()
        dist.destroy_process_group()
    sys.exit(0)

if DIST and os.environ.get("DDP_SELFCHECK"):
    # Debug aid: after training, every GPU's weights must be identical (they should be, by design)
    total = sum(p.double().sum().item() for p in model.parameters())
    sums = [None] * WORLD
    dist.all_gather_object(sums, total)
    mprint(f"ddp check: parameter sums per GPU {sums} -> " + ("all GPUs identical" if len(set(sums)) == 1 else "MISMATCH"))

save_latest(S.max_iters + 1)   # marks training as finished
# The FINAL weights: usually the best model, since the learning rate ends small.
# (ckpt.pt keeps the best val score, but val scores are noisy by about +-0.05.)
FINAL_PATH = os.path.join(OUT_DIR, "final.pt")
if IS_MAIN:
    save_atomic({"model": model.state_dict(), "config": cfg.__dict__,
                 "iter": S.max_iters, "val_loss": best_val}, FINAL_PATH)
    if args.backup_dir:
        try:
            os.makedirs(args.backup_dir, exist_ok=True)
            shutil.copyfile(FINAL_PATH, os.path.join(args.backup_dir, f"{V.name}_final.pt"))
        except OSError as e:
            print(f"WARNING: couldn't copy final.pt to {args.backup_dir} ({e}). It is safe in {FINAL_PATH}.")
    hub_upload(S.max_iters + 1, wait=True)
    hub_upload(S.max_iters, wait=True, name="final.pt", path=FINAL_PATH)
    print(f"done. best val loss {best_val:.3f} (ckpt.pt); final weights saved in {FINAL_PATH}")
    phone(f"FINISHED. best val loss {best_val:.3f}. final weights saved.", "done")
if DIST:
    dist.barrier()
    dist.destroy_process_group()
