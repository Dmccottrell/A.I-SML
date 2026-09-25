"""
generate.py - Talk to your model.

Usage:  python generate.py --prompt "Once upon a time"
        python generate.py --chat          (after fine-tuning)
"""
import argparse

import torch

from model import TinyLM, ModelConfig
from stage import CKPT_DIR
from tokenizer import BPETokenizer

p = argparse.ArgumentParser()
p.add_argument("--ckpt", default=f"{CKPT_DIR}/ckpt.pt")
p.add_argument("--tokenizer", default="data/tokenizer.json")
p.add_argument("--prompt", default="Once upon a time")
p.add_argument("--tokens", type=int, default=200)
p.add_argument("--temperature", type=float, default=0.8)
p.add_argument("--top_k", type=int, default=50)
p.add_argument("--chat", action="store_true")
args = p.parse_args()

device = "cuda" if torch.cuda.is_available() else "cpu"
ckpt = torch.load(args.ckpt, map_location=device)
model = TinyLM(ModelConfig(**ckpt["config"])).to(device)
model.load_state_dict(ckpt["model"])
model.eval()

tok = BPETokenizer.load(args.tokenizer)
eot = tok.special["<|endoftext|>"]


def run(text):
    idx = torch.tensor([tok.encode(text)], device=device)
    out = model.generate(idx, args.tokens, args.temperature, args.top_k, stop_id=eot)
    return tok.decode(out[0, idx.size(1):].tolist()).replace("<|endoftext|>", "")


if args.chat:
    print("Chat mode - type 'quit' to exit")
    while (msg := input("\nYou: ")) != "quit":
        print("AI:", run(f"<|user|>{msg}<|assistant|>").strip())
else:
    print(args.prompt + run(args.prompt))
