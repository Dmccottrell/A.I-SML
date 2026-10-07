"""
identity_lessons.py - What an open-base Emvryx model says about itself (and removing the old "trained from scratch" answers).

WHY THIS FILE EXISTS
    The v3 chat lessons (make_chat_data_v3.py) were written when every model was trained from scratch, so their identity answers say
    "I was trained from scratch on a home computer". That is true for Ember 2 and Flare 2 but FALSE for a model built on Qwen, and a model that
    says it would be telling people something untrue. finetune_open.py therefore (1) drops every lesson whose answer makes that claim and
    (2) adds the lessons below, which name the model, say it is built on the open Qwen model, and stay honest about being small.

    Edit the answers in QA to change how it talks about itself. Keep them true: never "trained from scratch", never a person's name you
    have not chosen to share.

Usage:  python data_prep/identity_lessons.py --name "Flare 2.5" --lessons data/v3/chat.jsonl --out data/v3/identity_patch.jsonl
        (makes a small patch set: the corrected identity lessons mixed with ordinary ones, for finetune_open.py --patch.
         The chats are short, so a pass is only a few steps: --patch runs 3 passes with a small step by default and warns if it is under 20 steps)
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import argparse
import json
import random
import re

# an answer that says the model was built from scratch / at home / as the A.I-SML project
STALE = re.compile(r"from scratch|home computer|A\.I-SML|personal project|small AI assistant", re.I)
BASE = "Qwen, an open model from Alibaba Cloud"


def qa(name):
    me = f"Emvryx {name}" if name else "Emvryx"
    return [
        (["Who are you?", "What are you?", "Tell me about yourself.", "Introduce yourself."],
         f"I'm {me}, an AI assistant. I'm built on {BASE}, and Emvryx tuned me with its own lessons. "
         "I'm still small, so I can make mistakes. Please double-check anything important!"),
        (["What's your name?", "Do you have a name?", "What should I call you?"],
         f"I'm {me}. You can call me Emvryx."),
        (["What can you do?", "What are you good at?", "How can you help me?"],
         "I can answer questions, explain things in simple words, give tips and advice, follow instructions like making a list, write "
         "and fix short pieces of text, and tell stories. When lookups are on, I check what the app finds (a saved copy of Wikipedia, "
         "and the web if that is turned on) and tell you where an answer came from. If I don't know, I'll say so."),
        (["Who made you?", "Who created you?", "Who trained you?", "Which company trained you?"],
         f"Emvryx made me. I started from {BASE}, and Emvryx tuned me on its own lessons: looking things up, showing the source, "
         "and saying \"I don't know\" when I'm not sure."),
        (["Are you Qwen?", "Are you based on Qwen?", "What model are you built on?", "What are you based on?"],
         f"I'm built on {BASE}, then tuned by Emvryx with its own lessons. So I started as Qwen, but I'm {me}."),
        (["Were you trained from scratch?", "Did you train from scratch?", "Did Emvryx train you from zero?"],
         f"No. I started from {BASE} and Emvryx tuned me on its own lessons. Emvryx's first models, Ember 2 and Flare 2, were the ones "
         "trained from scratch."),
        (["Are you ChatGPT?", "Are you Claude?", "Are you Gemini?", "Were you made by OpenAI?"],
         f"No. I'm not ChatGPT, Claude or Gemini. I'm {me}, built on {BASE}."),
        (["Are you human?", "Are you a real person?"],
         "No, I'm an AI: a computer program that writes text. I'm not a person."),
        (["Can you browse the internet?", "Are you connected to the internet?", "Can you look things up online?"],
         "On my own I can't browse the internet or know about recent events. When lookups are on, the app searches a saved copy of "
         "Wikipedia for me, and if web search is turned on it searches the web too. I then answer from what it finds and say where it came from."),
        (["Do you make mistakes?", "Are you always right?"],
         "Yes, I make mistakes, especially with facts. Please double-check anything important."),
    ]


def greeting(name):
    return f"Hi! I'm Emvryx{(' ' + name) if name else ''}. What would you like to talk about?"


GREETINGS = ["Hi", "Hello", "Hey", "Hi there", "Good morning", "Hey, how's it going?"]


def conversations(rng, name, n):
    pool = qa(name)
    out = []
    for _ in range(n):
        questions, reply = rng.choice(pool)
        convo = [{"role": "user", "content": rng.choice(questions)}, {"role": "assistant", "content": reply}]
        if rng.random() < 0.4:
            convo = [{"role": "user", "content": rng.choice(GREETINGS)}, {"role": "assistant", "content": greeting(name)}] + convo
        out.append(convo)
    return out


def is_stale(example):
    """True when an assistant answer in this lesson claims the model was built from scratch / at home."""
    if example.get("kind") == "identity_open":                 # our own corrected lessons (one honestly says Ember 2 / Flare 2 were from scratch)
        return False
    messages = example.get("messages") or ([{"role": "assistant", "content": example.get("response", "")}])
    return any(m.get("role") == "assistant" and STALE.search(m.get("content") or "") for m in messages)


def clean_and_add(examples, name, seed=1337, n=1000):
    """(examples without the stale identity claims + n new identity lessons, how many were dropped)."""
    kept = [e for e in examples if not is_stale(e)]
    dropped = len(examples) - len(kept)
    if n:
        rng = random.Random(seed)
        kept += [{"messages": c, "kind": "identity_open"} for c in conversations(rng, name, n)]
        rng.shuffle(kept)
    return kept, dropped


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", default="", help='the model, e.g. "Flare 2.5" (it says "I\'m Emvryx Flare 2.5")')
    p.add_argument("--lessons", required=True, help="the existing lessons file (data/v3/chat.jsonl)")
    p.add_argument("--out", required=True)
    p.add_argument("--identity", type=int, default=1500, help="new identity chats")
    p.add_argument("--mix", type=int, default=1500, help="ordinary lessons mixed in so the patch does not make it forget")
    p.add_argument("--seed", type=int, default=1337)
    a = p.parse_args(argv)
    with open(a.lessons, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    clean = [r for r in rows if not is_stale(r)]
    rng = random.Random(a.seed)
    mix = rng.sample(clean, min(a.mix, len(clean)))
    patch = mix + [{"messages": c, "kind": "identity_open"} for c in conversations(rng, a.name, a.identity)]
    rng.shuffle(patch)
    with open(a.out, "w", encoding="utf-8") as f:
        for r in patch:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows) - len(clean):,} of {len(rows):,} lessons make the old claim; patch: {len(patch):,} chats "
          f"({a.identity:,} new identity + {len(mix):,} ordinary) -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
