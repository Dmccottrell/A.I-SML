"""
generate.py - Talk to your model.

WHAT THIS FILE DOES
    Loads a checkpoint and the tokenizer, then writes text:
      * story mode: continues your --prompt
      * chat mode (--chat): wraps each message as <|user|>...<|assistant|>
        so a fine-tuned model (finetune.py) answers it

Usage:  python generate.py --prompt "Once upon a time"
        python generate.py --chat          (after fine-tuning)

Options:
    --ckpt         checkpoint to load (default: checkpoints/dev/ckpt.pt)
    --tokens       max new tokens to write (default 200)
    --temperature  0.5 = safer/more repetitive, 1.0 = more creative (default 0.8)
    --top_k        only pick from the k most likely tokens (default 50)
"""
import argparse

import torch

from model import TinyLM, ModelConfig
from stage import CKPT_DIR
from tokenizer import BPETokenizer

# ---- command-line options ----
p = argparse.ArgumentParser()
p.add_argument("--ckpt", default=f"{CKPT_DIR}/ckpt.pt")
p.add_argument("--tokenizer", default="data/tokenizer.json")
p.add_argument("--prompt", default="Once upon a time")
p.add_argument("--tokens", type=int, default=200)
p.add_argument("--temperature", type=float, default=0.8)
p.add_argument("--top_k", type=int, default=50)
p.add_argument("--chat", action="store_true")
args = p.parse_args()

# ---- load the model: rebuild it from the saved config, then load the weights ----
device = "cuda" if torch.cuda.is_available() else "cpu"
ckpt = torch.load(args.ckpt, map_location=device)
model = TinyLM(ModelConfig(**ckpt["config"])).to(device)
model.load_state_dict(ckpt["model"])
model.eval()   # inference mode (no dropout)

tok = BPETokenizer.load(args.tokenizer)
eot = tok.special["<|endoftext|>"]   # generation stops when the model writes this


def run(text):
    """Encode `text`, let the model continue it, and return ONLY the new text."""
    idx = torch.tensor([tok.encode(text)], device=device)   # shape (1, T)
    out = model.generate(idx, args.tokens, args.temperature, args.top_k, stop_id=eot)
    # out[0, idx.size(1):] = everything after the prompt
    return tok.decode(out[0, idx.size(1):].tolist()).replace("<|endoftext|>", "")


if args.chat:
    # Simple chat loop. Each turn is independent (no memory of earlier turns).
    print("Chat mode - type 'quit' to exit")
    while (msg := input("\nYou: ")) != "quit":
        print("AI:", run(f"<|user|>{msg}<|assistant|>").strip())
else:
    print(args.prompt + run(args.prompt))
