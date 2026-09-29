"""
generate.py - Talk to your model.

WHAT THIS FILE DOES
    Loads a checkpoint and the tokenizer, then writes text:
      * story mode: continues your --prompt
      * chat mode (--chat): wraps messages as <|user|>...<|assistant|>
        (see chat.py) so a fine-tuned model (finetune.py) answers them.
        v2 remembers the conversation; v1 treats every message separately
        (it was only trained on single messages). Type 'reset' to forget
        the conversation, 'quit' to exit. 'context' shows the memory meter and
        'window' lists what the model can still see (see below).

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
    --context      chat mode: show the context meter after every reply (how full the
                   model's memory is, and what it has forgotten)
    --lookup       chat mode: search the Wikipedia index (wiki_index.py) for each
                   message and give the best passages to the model as notes. Only the
                   newest question keeps its notes (older ones are dropped to save room)
    --memory       chat mode: remember earlier chats and facts you save ("remember: ..."), on this
                   computer only (see chat_memory.py). --private: this chat isn't saved
    --notes        with --lookup: passages per question (default 3; 2 leaves more room)
"""
import argparse, os

import torch

from chat import build_prompt, context_report, format_meter, format_window_view, special_ids
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
p.add_argument("--context", action="store_true", help="chat: show the context meter after every reply")
p.add_argument("--lookup", action="store_true", help="chat: look each message up in Wikipedia first")
p.add_argument("--notes", type=int, default=3, help="chat --lookup: passages per question (fewer = more room)")
p.add_argument("--memory", action="store_true", help="chat: remember earlier chats and saved facts (chat_memory.py)")
p.add_argument("--private", action="store_true", help="with --memory: don't save this chat")
p.add_argument("--memory_db", default=os.path.join("data", "memory", "memory.db"))
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
    print(f"Chat mode ({V.name}, {ckpt_path}) - type 'reset' to start over, 'quit' to exit, "
          f"'context' for the memory meter, 'window' to see what the model can still see")
    history = []
    # Leave room in the context for the reply
    max_prompt = max(64, model.cfg.max_seq_len - args.tokens)
    wiki = None
    if args.lookup:
        from wiki_index import WikiIndex
        wiki = WikiIndex(args.db)
    mem = chat_id = None
    if args.memory:
        from chat_memory import ChatMemory, handle_command
        mem = ChatMemory(args.memory_db)
        chat_id = None if args.private else mem.start_chat()
        print("(memory on" + (", private: this chat won't be saved" if args.private else "") +
              ". 'remember: <fact>', 'memories', 'forget <n>')")
    while True:
        try:
            msg = input("\nYou: ").strip()
        except EOFError:
            break                              # input ended (e.g. piped text)
        if msg == "quit":
            break
        if mem:
            said = handle_command(mem, msg)
            if said is not None:
                print(said)
                continue
        if msg == "reset":
            history = []
            if mem and chat_id is not None:
                chat_id = mem.start_chat()         # the cleared messages can now come back as memories
            print("(conversation cleared)")
            continue
        if msg in ("context", "window"):
            report = context_report(tok, history, model.cfg.max_seq_len, args.tokens) if history else None
            if report is None:
                print("(nothing in the window yet)")
            else:
                print(format_meter(report))
                if msg == "window":
                    print(format_window_view(report))
            continue
        if not V.chat_memory:
            history = []                       # v1: every message on its own
        message = {"role": "user", "content": msg}
        found = []
        if mem:
            found += mem.notes(msg, exclude_chat=chat_id)
        if wiki:
            found += [{"title": n["title"], "text": n["text"]} for n in wiki.search(msg, args.notes)]
        if found:
            message["notes"] = found
            print("(looked up: " + "; ".join(n["title"] for n in found) + ")")
        history.append(message)
        reply = continue_ids(build_prompt(tok, history, max_prompt)).strip()
        history.append({"role": "assistant", "content": reply})
        print("AI:", reply)
        if mem and chat_id is not None:
            mem.add_exchange(chat_id, msg, reply)
        if args.context:
            print(format_meter(context_report(tok, history, model.cfg.max_seq_len, args.tokens)))
else:
    print(args.prompt + continue_ids(tok.encode(args.prompt)))
