"""
finetune.py - Teach the pretrained model to answer in a chat format.

WHAT THIS FILE DOES
    Pretraining (train.py) teaches the model language. Fine-tuning teaches it
    a FORMAT: when it sees <|user|> question <|assistant|>, write an answer and
    then <|endoftext|>. It starts from ckpt.pt and saves chat.pt in the same
    folder (see config.py).

Data: chat.jsonl in the version's data folder, one example per line, in
either format (see chat.py):
  {"prompt": "My printer says offline", "response": "Check that it is powered on..."}
  {"messages": [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello!"}, ...]}
The model only learns from the AI's answers (the user's messages are masked out).

A two-turn conversation becomes:
    tokens: <|user|> Hi <|assistant|> Hello! <|endoftext|> <|user|> Bye <|assistant|> Goodbye! <|endoftext|>
    mask:      0     0      0          1          1          0     0       0           1          1
(mask 1 = "learn to write this", mask 0 = "just context, don't learn it")

Usage:  python finetune.py                 (v1: data/chat.jsonl)
        python finetune.py --version v2    (v2: data/v2/chat.jsonl)
"""
import argparse, json, os, random

import torch

from chat import encode_conversation, normalize, special_ids
from config import add_version_arg, get_version
from model import load_checkpoint
from tokenizer import BPETokenizer

p = argparse.ArgumentParser()
add_version_arg(p)
args = p.parse_args()
V = get_version(args.version)
S = V.finetune

BASE_CKPT = os.path.join(V.ckpt_dir, "ckpt.pt")   # the pretrained model to start from
OUT_CKPT = os.path.join(V.ckpt_dir, "chat.pt")    # where the chat model is saved
DATA = os.path.join(V.data_dir, "chat.jsonl")

device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = (torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16) if device == "cuda" else torch.float32
autocast = torch.autocast(device_type=device, dtype=dtype, enabled=(device == "cuda"))
tok = BPETokenizer.load(os.path.join(V.data_dir, "tokenizer.json"))
_, _, EOT = special_ids(tok)

# Load the pretrained model
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


# ---- training loop: same idea as train.py, but over the chat examples ----
# Small learning rate so the model learns the chat format without
# forgetting the language it already knows.
optimizer = torch.optim.AdamW(model.parameters(), lr=S.lr, weight_decay=0.0)
model.train()
steps_per_epoch = (len(examples) + S.batch_size - 1) // S.batch_size
for epoch in range(S.epochs):              # one epoch = one pass over all examples
    random.shuffle(examples)
    for step in range(0, len(examples), S.batch_size):
        x, y, m = make_batch(examples[step:step + S.batch_size])
        with autocast:
            _, loss = model(x, y, loss_mask=m)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        if (step // S.batch_size) % 20 == 0:
            print(f"epoch {epoch} step {step // S.batch_size}/{steps_per_epoch}: loss {loss.item():.3f}")

torch.save({"model": model.state_dict(), "config": cfg.__dict__}, OUT_CKPT)
print("saved", OUT_CKPT)
