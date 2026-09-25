"""
finetune.py - Teach the pretrained model to answer in a chat format.

WHAT THIS FILE DOES
    Pretraining (train.py) teaches the model language. Fine-tuning teaches it
    a FORMAT: when it sees <|user|> question <|assistant|>, write an answer and
    then <|endoftext|>. It starts from checkpoints/dev/ckpt.pt and saves
    checkpoints/dev/chat.pt.

Data: data/chat.jsonl, one example per line, e.g.
  {"prompt": "My printer says offline", "response": "Check that it is powered on..."}
The model only learns from the response tokens (the prompt is masked out).

Each example becomes:
    tokens: <|user|> My printer says offline <|assistant|> Check that ... <|endoftext|>
    mask:      0     0   0      0     0          0          1     1   ...      1
(mask 1 = "learn to write this", mask 0 = "just context, don't learn it")

Usage:  python finetune.py
"""
import json, random

import torch

from model import TinyLM, ModelConfig
from stage import CKPT_DIR
from tokenizer import BPETokenizer

BASE_CKPT = f"{CKPT_DIR}/ckpt.pt"   # the pretrained model to start from
OUT_CKPT = f"{CKPT_DIR}/chat.pt"    # where the chat model is saved
DATA = "data/chat.jsonl"
# Small learning rate (10x lower than pretraining) so the model learns the
# chat format without forgetting the language it already knows.
epochs, batch_size, lr = 3, 16, 5e-5

device = "cuda" if torch.cuda.is_available() else "cpu"
tok = BPETokenizer.load("data/tokenizer.json")
U, A, EOT = (tok.special[s] for s in ("<|user|>", "<|assistant|>", "<|endoftext|>"))

# Load the pretrained model
ckpt = torch.load(BASE_CKPT, map_location=device)
cfg = ModelConfig(**ckpt["config"])
model = TinyLM(cfg).to(device)
model.load_state_dict(ckpt["model"])

# ---- turn every JSON line into (token IDs, loss mask) ----
examples = []
with open(DATA, encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue                       # skip blank lines
        ex = json.loads(line)
        prompt_ids = [U] + tok.encode(ex["prompt"], allow_special=False) + [A]
        resp_ids = tok.encode(ex["response"], allow_special=False) + [EOT]
        # Cut to max_seq_len + 1 (the +1 is because x and y are shifted by one)
        ids = (prompt_ids + resp_ids)[: cfg.max_seq_len + 1]
        mask = ([0] * len(prompt_ids) + [1] * len(resp_ids))[: len(ids)]
        examples.append((ids, mask))
print(f"{len(examples)} examples")


def make_batch(batch):
    """Pad a list of (ids, mask) examples to the same length and return tensors.

    Examples have different lengths, so shorter ones are padded with EOT.
    Padded positions get mask 0, so they never affect the loss.

    Returns:
        x: (B, T) inputs
        y: (B, T) targets (x shifted by one token)
        m: (B, T) loss mask, 1.0 only on response tokens
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
optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.0)
model.train()
for epoch in range(epochs):                # one epoch = one pass over all examples
    random.shuffle(examples)
    for step in range(0, len(examples), batch_size):
        x, y, m = make_batch(examples[step:step + batch_size])
        _, loss = model(x, y, loss_mask=m)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        if (step // batch_size) % 20 == 0:
            print(f"epoch {epoch} step {step // batch_size}: loss {loss.item():.3f}")

torch.save({"model": model.state_dict(), "config": cfg.__dict__}, OUT_CKPT)
print("saved", OUT_CKPT)
