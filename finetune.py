"""
finetune.py - Teach the pretrained model to answer in a chat format.

WHAT THIS FILE DOES
    Pretraining (train.py) teaches the model language. Fine-tuning teaches it
    a FORMAT: when it sees <|user|> question <|assistant|>, write an answer and
    then <|endoftext|>. It starts from the finished pretraining run's final
    weights and saves chat.pt in the same folder (see config.py).

Data: chat.jsonl in the version's data folder, one example per line, in
either format (see chat.py):
  {"prompt": "My printer says offline", "response": "Check that it is powered on..."}
  {"messages": [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello!"}, ...]}
The model only learns from the AI's answers (the user's messages are masked out).

A two-turn conversation becomes:
    tokens: <|user|> Hi <|assistant|> Hello! <|endoftext|> <|user|> Bye <|assistant|> Goodbye! <|endoftext|>
    mask:      0     0      0          1          1          0     0       0           1          1
(mask 1 = "learn to write this", mask 0 = "just context, don't learn it")

PAUSE AND RESUME
    Press Ctrl+C to pause: it saves chat_latest.pt and stops. Run the same
    command again to continue where it stopped. It also saves automatically
    every ~10 minutes, so a crash or power cut loses at most a few minutes.
    Use --fresh to ignore chat_latest.pt and start over.
    (If chat.jsonl changes, the old resume point no longer matches: use --fresh.)

Usage:  python finetune.py                 (v1: data/chat.jsonl)
        python finetune.py --version v2    (v2: data/v2/chat.jsonl)
        python finetune.py --version v2 --fresh

READING THE OUTPUT
    epoch 0 step 5240/13162: loss 1.166  182ms/step  ~2.1h left
    Lower loss is better. It jumps around between lines because every batch
    of chats is different; watch the overall trend.
"""
import argparse, json, os, random, sys, time

import torch

from chat import encode_conversation, normalize, special_ids
from config import add_version_arg, get_version
from model import load_checkpoint
from tokenizer import BPETokenizer

p = argparse.ArgumentParser()
add_version_arg(p)
p.add_argument("--base", default=None,
               help="pretrained checkpoint to start from (default: the finished run's final weights)")
p.add_argument("--fresh", action="store_true", help="ignore chat_latest.pt and start over")
args = p.parse_args()
V = get_version(args.version)
S = V.finetune

def pick_base():
    """The pretrained checkpoint to fine-tune from.

    Prefers the FINAL weights of a finished run over ckpt.pt (the best val
    score): val scores are noisy, and the last steps (with the smallest
    learning rate) usually give the best model even if val didn't show it.
      1. final.pt (written by train.py when a run finishes)
      2. latest.pt, if its run finished (older train.py didn't write final.pt)
      3. ckpt.pt
    """
    final = os.path.join(V.ckpt_dir, "final.pt")
    if os.path.exists(final):
        return final
    latest = os.path.join(V.ckpt_dir, "latest.pt")
    if os.path.exists(latest) and torch.load(latest, map_location="cpu")["iter"] > V.train.max_iters:
        return latest
    return os.path.join(V.ckpt_dir, "ckpt.pt")


OUT_CKPT = os.path.join(V.ckpt_dir, "chat.pt")            # where the chat model is saved
LATEST_PATH = os.path.join(V.ckpt_dir, "chat_latest.pt")  # resume point while fine-tuning
SAVE_EVERY_SECONDS = 10 * 60                               # autosave interval
resuming = os.path.exists(LATEST_PATH) and not args.fresh
if resuming:
    BASE_CKPT = LATEST_PATH
    print(f"resuming fine-tuning from {LATEST_PATH}")
else:
    BASE_CKPT = args.base or pick_base()   # the pretrained model to start from
    print(f"fine-tuning from {BASE_CKPT}")
DATA = os.path.join(V.data_dir, "chat.jsonl")

device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = (torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16) if device == "cuda" else torch.float32
autocast = torch.autocast(device_type=device, dtype=dtype, enabled=(device == "cuda"))
tok = BPETokenizer.load(os.path.join(V.data_dir, "tokenizer.json"))
_, _, EOT = special_ids(tok)

# Load the pretrained model (or, when resuming, the half-finished chat model)
model, ckpt = load_checkpoint(BASE_CKPT, device)
cfg = model.cfg

# ---- turn every JSON line into (token IDs, loss mask) ----
examples = []
with open(DATA, encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue                       # skip blank lines
        messages = normalize(json.loads(line))
        # Cut to max_seq_len + 1 (the +1 is because x and y are shifted by one)
        ids, mask = encode_conversation(tok, messages, cfg.max_seq_len + 1)
        if sum(mask) > 0:                  # skip examples with nothing to learn
            examples.append((ids, mask))
print(f"{len(examples)} examples")


def make_batch(batch):
    """Pad a list of (ids, mask) examples to the same length and return tensors.

    Examples have different lengths, so shorter ones are padded with EOT.
    Padded positions get mask 0, so they never affect the loss.

    Returns:
        x: (B, T) inputs
        y: (B, T) targets (x shifted by one token)
        m: (B, T) loss mask, 1.0 only on the AI's answer tokens
    """
    T = max(len(ids) for ids, _ in batch) - 1
    x = torch.full((len(batch), T), EOT)
    y = torch.full((len(batch), T), EOT)
    m = torch.zeros((len(batch), T))
    for i, (ids, mask) in enumerate(batch):
        n = len(ids) - 1
        x[i, :n] = torch.tensor(ids[:-1])
        y[i, :n] = torch.tensor(ids[1:])
        m[i, :n] = torch.tensor(mask[1:], dtype=torch.float)   # mask lines up with y
    return x.to(device), y.to(device), m.to(device)


def save_atomic(obj, path):
    """torch.save to a temporary file, then rename it into place.

    If the PC loses power mid-save, the previous file is still intact.
    """
    tmp = path + ".tmp"
    torch.save(obj, tmp)
    os.replace(tmp, path)


def save_latest(epoch, step):
    """Save everything needed to resume at batch `step` of `epoch`."""
    save_atomic({"model": model.state_dict(), "optimizer": optimizer.state_dict(),
                 "config": cfg.__dict__, "epoch": epoch, "step": step,
                 "num_examples": len(examples), "base": BASE_CKPT}, LATEST_PATH)


def epoch_order(epoch):
    """The shuffled order of examples for one epoch.

    Seeded by the epoch number, so a resumed run sees exactly the same order
    and can skip the batches it already did.
    """
    order = list(range(len(examples)))
    random.Random(1234 + epoch).shuffle(order)
    return order


# ---- training loop: same idea as train.py, but over the chat examples ----
# Small learning rate so the model learns the chat format without
# forgetting the language it already knows.
optimizer = torch.optim.AdamW(model.parameters(), lr=S.lr, weight_decay=0.0)
steps_per_epoch = (len(examples) + S.batch_size - 1) // S.batch_size
start_epoch, start_step = 0, 0
if resuming:
    if ckpt.get("num_examples") != len(examples):
        sys.exit(f"{DATA} has changed since this fine-tuning run started "
                 f"({ckpt.get('num_examples')} examples then, {len(examples)} now).\n"
                 "Use --fresh to start over with the new data.")
    optimizer.load_state_dict(ckpt["optimizer"])
    start_epoch, start_step = ckpt["epoch"], ckpt["step"]
    print(f"continuing at epoch {start_epoch} step {start_step}/{steps_per_epoch}")
del ckpt                                   # free memory: the weights are in the model now

model.train()
total_steps = S.epochs * steps_per_epoch
done_steps = start_epoch * steps_per_epoch + start_step
# The resume point: the next (epoch, step) that hasn't been done yet
next_epoch, next_step = start_epoch, start_step
t_last_save = t_log = time.time()
steps_since_log = 0
try:
    for epoch in range(start_epoch, S.epochs):   # one epoch = one pass over all examples
        order = epoch_order(epoch)
        first = start_step if epoch == start_epoch else 0
        for step in range(first, steps_per_epoch):
            if time.time() - t_last_save > SAVE_EVERY_SECONDS:
                save_latest(epoch, step)            # the state BEFORE doing this step
                t_last_save = time.time()
            idx = order[step * S.batch_size:(step + 1) * S.batch_size]
            x, y, m = make_batch([examples[i] for i in idx])
            with autocast:
                _, loss = model(x, y, loss_mask=m)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            next_epoch, next_step = (epoch, step + 1) if step + 1 < steps_per_epoch else (epoch + 1, 0)
            done_steps += 1
            steps_since_log += 1
            if step % 20 == 0:
                ms = (time.time() - t_log) * 1000 / steps_since_log
                t_log, steps_since_log = time.time(), 0
                hours_left = ms * (total_steps - done_steps) / 3.6e6
                print(f"epoch {epoch} step {step}/{steps_per_epoch}: loss {loss.item():.3f}  "
                      f"{ms:.0f}ms/step  ~{hours_left:.1f}h left")
except KeyboardInterrupt:
    # Ctrl+C: save the first step that hasn't finished; resume redoes it
    optimizer.zero_grad(set_to_none=True)
    save_latest(next_epoch, next_step)
    print(f"\npaused at epoch {next_epoch} step {next_step}. Run the same command again to resume.")
    sys.exit(0)

save_atomic({"model": model.state_dict(), "config": cfg.__dict__}, OUT_CKPT)
if os.path.exists(LATEST_PATH):
    os.remove(LATEST_PATH)                 # finished: the next run starts fresh
print("saved", OUT_CKPT)
