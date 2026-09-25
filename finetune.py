"""
finetune.py - Teach the pretrained model to answer in a chat format.

Data: data/chat.jsonl, one example per line, e.g.
  {"prompt": "My printer says offline", "response": "Check that it is powered on..."}
The model only learns from the response tokens (the prompt is masked out).

Usage:  python finetune.py
"""
import json, random

import torch

from model import TinyLM, ModelConfig
from stage import CKPT_DIR
from tokenizer import BPETokenizer

BASE_CKPT = f"{CKPT_DIR}/ckpt.pt"
OUT_CKPT = f"{CKPT_DIR}/chat.pt"
DATA = "data/chat.jsonl"
epochs, batch_size, lr = 3, 16, 5e-5

device = "cuda" if torch.cuda.is_available() else "cpu"
tok = BPETokenizer.load("data/tokenizer.json")
U, A, EOT = (tok.special[s] for s in ("<|user|>", "<|assistant|>", "<|endoftext|>"))

ckpt = torch.load(BASE_CKPT, map_location=device)
cfg = ModelConfig(**ckpt["config"])
model = TinyLM(cfg).to(device)
model.load_state_dict(ckpt["model"])

examples = []
with open(DATA, encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        ex = json.loads(line)
        prompt_ids = [U] + tok.encode(ex["prompt"], allow_special=False) + [A]
        resp_ids = tok.encode(ex["response"], allow_special=False) + [EOT]
        ids = (prompt_ids + resp_ids)[: cfg.max_seq_len + 1]
        mask = ([0] * len(prompt_ids) + [1] * len(resp_ids))[: len(ids)]
        examples.append((ids, mask))
print(f"{len(examples)} examples")


def make_batch(batch):
    T = max(len(ids) for ids, _ in batch) - 1
    x = torch.full((len(batch), T), EOT)
    y = torch.full((len(batch), T), EOT)
    m = torch.zeros((len(batch), T))
    for i, (ids, mask) in enumerate(batch):
        n = len(ids) - 1
        x[i, :n] = torch.tensor(ids[:-1])
        y[i, :n] = torch.tensor(ids[1:])
        m[i, :n] = torch.tensor(mask[1:], dtype=torch.float)
    return x.to(device), y.to(device), m.to(device)


optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.0)
model.train()
for epoch in range(epochs):
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
