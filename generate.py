"""
generate.py - Talk to your model.

WHAT THIS FILE DOES
    Loads a checkpoint and the tokenizer, then writes text:
      * story mode: continues your --prompt
      * chat mode (--chat): wraps messages as <|user|>...<|assistant|>
        (see chat.py) so a fine-tuned model (finetune.py) answers them.
        v2 remembers the conversation; v1 treats every message separately
        (it was only trained on single messages). Type 'reset' to forget
        the conversation, 'quit' to exit.

Usage:  python generate.py --prompt "Once upon a time"
        python generate.py --chat                    (v1, uses chat.pt)
        python generate.py --version v2 --chat
        python generate.py --version v3 --chat --lookup   (v3+: looks things up in Wikipedia first)

Options:
    --ckpt         checkpoint to load (default: ckpt.pt, or chat.pt with --chat)
    --tokens       max new tokens to write (default 200)
    --temperature  0.5 = safer/more repetitive, 1.0 = more creative (default 0.8)
    --top_k        only pick from the k most likely tokens (default 50)
    --repetition_penalty  discourage repeating recent words: 1.0 = off,
                   1.1-1.3 = gentle (default 1.15), higher = stronger
    --lookup       chat mode: search the Wikipedia index (wiki_index.py) for each
                   message and give the best passages to the model as notes
"""
import argparse, os

import torch

from chat import build_prompt, special_ids
from config import add_version_arg, get_version
from model import load_checkpoint
from tokenizer import BPETokenizer

# ---- command-line options ----
p = argparse.ArgumentParser()
add_version_arg(p)
p.add_argument("--ckpt", default=None)
p.add_argument("--prompt", default="Once upon a time")
p.add_argument("--tokens", type=int, default=200)
p.add_argument("--temperature", type=float, default=0.8)
p.add_argument("--top_k", type=int, default=50)
p.add_argument("--repetition_penalty", type=float, default=1.15)
p.add_argument("--chat", action="store_true")
p.add_argument("--lookup", action="store_true", help="chat: look each message up in Wikipedia first")
p.add_argument("--db", default=os.path.join("data", "wiki", "wiki.db"))
args = p.parse_args()
V = get_version(args.version)
ckpt_path = args.ckpt or os.path.join(V.ckpt_dir, "chat.pt" if args.chat else "ckpt.pt")

# ---- load the model: rebuild it from the saved config, then load the weights ----
device = "cuda" if torch.cuda.is_available() else "cpu"
model, _ = load_checkpoint(ckpt_path, device)
tok = BPETokenizer.load(os.path.join(V.data_dir, "tokenizer.json"))
_, _, eot = special_ids(tok)   # generation stops when the model writes <|endoftext|>


def continue_ids(ids):
    """Let the model continue a list of token IDs; return ONLY the new text."""
    idx = torch.tensor([ids], device=device)   # shape (1, T)
    out = model.generate(idx, args.tokens, args.temperature, args.top_k, stop_id=eot,
                         repetition_penalty=args.repetition_penalty)
    # out[0, idx.size(1):] = everything after the prompt
    return tok.decode(out[0, idx.size(1):].tolist()).replace("<|endoftext|>", "")


if args.chat:
    print(f"Chat mode ({V.name}, {ckpt_path}) - type 'reset' to start over, 'quit' to exit")
    history = []
    # Leave room in the context for the reply
    max_prompt = max(64, model.cfg.max_seq_len - args.tokens)
    wiki = None
    if args.lookup:
        from wiki_index import WikiIndex
        wiki = WikiIndex(args.db)
    while True:
        try:
            msg = input("\nYou: ").strip()
        except EOFError:
            break                              # input ended (e.g. piped text)
        if msg == "quit":
            break
        if msg == "reset":
            history = []
            print("(conversation cleared)")
            continue
        if not V.chat_memory:
            history = []                       # v1: every message on its own
        message = {"role": "user", "content": msg}
        if wiki:
            notes = wiki.search(msg, 3)
            if notes:
                message["notes"] = [{"title": n["title"], "text": n["text"]} for n in notes]
                print("(looked up: " + "; ".join(n["title"] for n in notes) + ")")
        history.append(message)
        reply = continue_ids(build_prompt(tok, history, max_prompt)).strip()
        history.append({"role": "assistant", "content": reply})
        print("AI:", reply)
else:
    print(args.prompt + continue_ids(tok.encode(args.prompt)))
