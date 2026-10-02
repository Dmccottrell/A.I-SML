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
        python generate.py --version v3 --chat --web      (v3+: searches the web first; online mode)

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
    --suggest      chat mode: after each reply, suggest what you might ask next; press Enter on an
                   empty line to send it (needs a v3+ chat model, trained with user follow-ups)
    --memory       chat mode: remember earlier chats and facts you save ("remember: ..."), on this
                   computer only (see chat_memory.py). --private: this chat isn't saved
    --web          chat mode: search the web for each message (web_search.py) and give the best results to
                   the model as notes, with the site and date. OFF by default: when on, your message is
                   sent to the search service (Wikipedia's free search, or Brave with BRAVE_API_KEY set).
                   --web_source auto|wikipedia|brave, --web_read opens the pages for better passages
    --notes        with --lookup / --web: passages per question (default 3; 2 leaves more room)
    save <name>    chat mode: save the last answer as a PDF, Word, Markdown or text file in documents/
                   (e.g. "save fractions.pdf"; worksheets get a Name/Date line and the answer key on page 2)
    --skill        chat mode: switch on a skill pack (skills.py, docs/SKILLS.md), e.g. --skill study, or
                   --skill auto: the Beta router picks a trained pack for each message (or none).
                   --user <name> checks that person's access (python skills.py access); default: the owner
"""
import argparse, os

import torch

from chat import (build_prompt, clean_suggestion, context_report, format_meter, format_window_view, special_ids,
                  split_memory_calls, suggest_prompt)
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
p.add_argument("--web", action="store_true", help="chat: search the web for each message (online mode)")
p.add_argument("--web_source", default="auto", help="with --web: auto, wikipedia or brave (needs BRAVE_API_KEY)")
p.add_argument("--web_read", action="store_true", help="with --web: open the result pages (slower, better notes)")
p.add_argument("--notes", type=int, default=3, help="chat --lookup/--web: passages per question (fewer = more room)")
p.add_argument("--suggest", action="store_true", help="chat: suggest a likely next message after each reply")
p.add_argument("--memory", action="store_true", help="chat: remember earlier chats and saved facts (chat_memory.py)")
p.add_argument("--private", action="store_true", help="with --memory: don't save this chat")
p.add_argument("--no_meaning", action="store_true", help="with --memory: keyword search only (no embedding model)")
p.add_argument("--memory_db", default=os.path.join("data", "memory", "memory.db"))
p.add_argument("--db", default=os.path.join("data", "wiki", "wiki.db"))
p.add_argument("--skill", default=None, help="chat: a skill pack name (e.g. study), or auto (the router picks)")
p.add_argument("--any_base", action="store_true", help="with --skill: use a pack trained on another chat.pt")
p.add_argument("--user", default="owner", help="with --skill: whose access to check (python skills.py access); "
               "the owner can use every pack")
args = p.parse_args()
V = get_version(args.version)
ckpt_path = args.ckpt or os.path.join(V.ckpt_dir, "chat.pt" if args.chat else "ckpt.pt")

# ---- load the model: rebuild it from the saved config, then load the weights ----
device = "cuda" if torch.cuda.is_available() else "cpu"
model, _ = load_checkpoint(ckpt_path, device)
tok = BPETokenizer.load(os.path.join(V.data_dir, "tokenizer.json"))
_, assistant_id, eot = special_ids(tok)   # generation stops at <|endoftext|> (a suggestion stops at <|assistant|>)
switcher = None
if args.skill:
    from skills import SKILLS, SkillSwitcher, allowed_skills, load_access, route, trained_skills
    names = trained_skills(V.ckpt_dir) if args.skill == "auto" else [args.skill]
    if args.skill != "auto" and args.skill not in SKILLS:
        raise SystemExit(f"unknown skill {args.skill!r}: choose from {', '.join(SKILLS)} or auto")
    names = allowed_skills(names, args.user, load_access())       # the access toggle (Beta packs: testers only)
    if not names and args.skill != "auto":
        raise SystemExit(f"{args.user} may not use the {args.skill} pack (Beta packs are for testers: "
                         "python skills.py access), or it isn't trained yet (train_skill.py)")
    if names:
        switcher = SkillSwitcher(model, V.ckpt_dir, names, strict_base=not args.any_base)
        if args.skill != "auto":
            switcher.use(args.skill)
        print("(skill packs: " + ", ".join(switcher.titles.values())
              + (", picked per message)" if args.skill == "auto" else ")"))
    else:
        print(f"(no skill packs available for {args.user}: plain chat)")


def continue_ids(ids, n_tokens=None):
    """Let the model continue a list of token IDs; return ONLY the new text."""
    idx = torch.tensor([ids], device=device)   # shape (1, T)
    out = model.generate(idx, n_tokens or args.tokens, args.temperature, args.top_k, stop_id=eot,
                         repetition_penalty=args.repetition_penalty)
    # out[0, idx.size(1):] = everything after the prompt
    return tok.decode(out[0, idx.size(1):].tolist()).replace("<|endoftext|>", "")


def suggest(history):
    """A likely next message from the user, or "" (never sent without you pressing Enter)."""
    ids = suggest_prompt(tok, history, max(64, model.cfg.max_seq_len - 32))
    idx = torch.tensor([ids], device=device)
    out = model.generate(idx, 32, 0.7, 40, stop_id=assistant_id, repetition_penalty=args.repetition_penalty)
    return clean_suggestion(tok.decode(out[0, idx.size(1):].tolist()))


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
    if args.web:
        from web_search import pick_source, web_notes
        print(f"(web search on, using {pick_source(args.web_source)}: each message is sent to the search "
              "service. 'web off' / 'web on' to switch)")
    mem = chat_id = None
    if args.memory:
        from chat_memory import ChatMemory, handle_command, load_embedder
        mem = ChatMemory(args.memory_db, None if args.no_meaning else load_embedder())
        chat_id = None if args.private else mem.start_chat()
        print("(memory on" + (", private: this chat won't be saved" if args.private else "") +
              ". 'remember: <fact>', 'memories', 'forget <n>')")
    suggestion = ""
    while True:
        try:
            msg = input("\nYou: ").strip()
        except EOFError:
            break                              # input ended (e.g. piped text)
        if not msg:
            if not suggestion:
                continue
            msg = suggestion                   # Enter on an empty line sends the suggestion
            print(f"You: {msg}")
        suggestion = ""
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
        if msg == "save" or msg.startswith("save "):
            last = next((m["content"] for m in reversed(history) if m["role"] == "assistant"), None)
            if last is None:
                print("(nothing to save yet)")
                continue
            from export_doc import export, safe_name
            try:
                print(f"(saved {export(last, safe_name(msg[5:]))})")
            except (ValueError, SystemExit) as e:
                print(f"(couldn't save: {e})")
            continue
        if msg in ("web on", "web off"):
            if msg == "web on" and "web_notes" not in globals():
                from web_search import pick_source, web_notes
            args.web = msg == "web on"
            print(f"(web search {'on' if args.web else 'off'})")
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
        if args.web:
            web = web_notes(msg, args.notes, args.web_source, args.web_read)
            found += [{"title": n["title"], "text": n["text"]} for n in web]
            for n in web:
                print(f"  (web: {n['url']})")
        if found:
            message["notes"] = found
            print("(looked up: " + "; ".join(n["title"] for n in found) + ")")
        history.append(message)
        if switcher and args.skill == "auto":
            picked = route(msg, list(switcher.packs))
            switcher.use(picked)
            print(f"(skill: {switcher.titles[picked]})" if picked else "(skill: none, plain chat)")
        # A worksheet or lesson plan is longer than a chat answer: give the Teacher assistant more room
        long_doc = switcher is not None and switcher.current == "teacher"
        n_tokens = max(args.tokens, min(700, model.cfg.max_seq_len // 2)) if long_doc else args.tokens
        reply, facts = split_memory_calls(continue_ids(
            build_prompt(tok, history, max(64, model.cfg.max_seq_len - n_tokens)), n_tokens))
        history.append({"role": "assistant", "content": reply, **({"memory": facts} if facts else {})})
        print("AI:", reply)
        if long_doc or reply.lstrip().startswith("# "):
            print("(save it: 'save worksheet.pdf' or 'save worksheet.docx' -> documents/)")
        for fact in facts:                     # the AI decided to remember something about you
            if mem and chat_id is not None:
                mem.remember(fact)
                print(f"(saved to memory: {fact}  - 'memories' to see, 'forget <n>' to delete)")
            else:
                print(f"(it wanted to remember: {fact} - not saved, memory is " +
                      ("private for this chat)" if mem else "off; use --memory)"))
        if mem and chat_id is not None:
            mem.add_exchange(chat_id, msg, reply)
        if args.context:
            print(format_meter(context_report(tok, history, model.cfg.max_seq_len, args.tokens)))
        if args.suggest and V.chat_memory:
            suggestion = suggest(history)
            if suggestion:
                print(f"(suggestion: {suggestion}   - press Enter to send it)")
else:
    print(args.prompt + continue_ids(tok.encode(args.prompt)))
