"""
make_chat_data_qwen.py - Build the lessons for Qwen-based Emvryx models -> data/qwen/chat.jsonl

WHAT THIS FILE DOES
    Makes a SMALL set of conversations (about 12,000, not the 80,000+ of data/v3/chat.jsonl) that teach manners and honesty, not knowledge. A Qwen model already knows
    its facts; what the old lessons (made for the tiny from-scratch models) taught it was to over-trust a wrong note and to hedge about real people. See qwen_lessons.py.

      kind            teaches
      --------------  ---------------------------------------------------------------------------------------------------------
      general         everyday chat and instructions, answers by an open model (smol-smoltalk); boilerplate like "As an AI language model" is dropped
      topic_switch    answer the NEWEST question, not an older one
      instruction     exact counts and formats ("List 3 ..."), from the teacher's instruction examples (make_teacher_data.py), if you have them
      facts / names   plain, confident answers about well-known things and people, also when a name is spelt wrongly (qwen_lessons.py)
      unknowable      live or personal things it cannot know: say so briefly and say who can help
      unfamiliar      a made-up name: ask about the spelling, never "it might be fictional"
      notes_use       the notes match the question: answer from them (no "(Source: ...)" tag: the app shows where an answer came from)
      notes_ignored   the notes are about something else: ignore them and answer the question normally
      stand_firm      the person doubts a right answer: keep it, politely
      small_talk, other_ai, typo   as before (typed messily copies of some lessons)

    NOT in this set, on purpose: "I don't know" when the notes are silent, doubting yourself when corrected, "it might be fictional", remembering-you tool calls (the app now
    keeps those itself), coding-helper lessons (VryxCode will learn from real runs), and identity (finetune_open.py adds corrected identity lessons for each model by itself).

Usage:  python make_chat_data_qwen.py                       (needs `pip install datasets` and the internet once for smol-smoltalk)
        python make_chat_data_qwen.py --general 4000 --notes_use 800
        then, for each model (see docs/QWEN_LESSONS.md for the exact commands):
        python finetune_open.py --model apogee-2 --data data/qwen/chat.jsonl --out checkpoints/dev/open/apogee-2q --export export/open/apogee-2q/my-ai --grad_accum 2
"""
import argparse
import itertools
import json
import os
import random

import make_chat_data_v3 as V3
import qwen_lessons as Q

OUT_PATH = os.path.join("data", "qwen", "chat.jsonl")
TEACHER_DIR = os.path.join("data", "v3", "teacher")      # the teacher's examples are plain text: the same ones serve every model
MAX_CHARS = 6000
CHARS_PER_TOKEN = 3.6


def clean(convs):
    """Conversations without any chatbot-disclaimer answer (those teach hedging)."""
    return [c for c in convs if not any(m["role"] == "assistant" and Q.is_overcautious(m["content"]) for m in c)]


def strip_sources(convs):
    for c in convs:
        for m in c:
            if m["role"] == "assistant":
                m["content"] = Q.strip_source(m["content"])
    return convs


def small_talk_conversations(rng, n):
    """Casual greetings and chit-chat (not v3's: its chats sometimes carry the old "trained from scratch" identity answers)."""
    out = []
    for _ in range(n):
        messages, replies = rng.choice(V3.SMALL_TALK)
        out.append([V3.user(V3.casual_variant(rng.choice(messages), rng)), V3.assistant(rng.choice(replies))])
    return out


OTHER_AI_REPLIES = [
    "I don't have reliable, up-to-date information about {a}. AI assistants change every few months, and I run offline, so anything I said could be old or wrong. "
    "The company that makes it publishes its results on its own website.",
    "I can't compare them fairly: I don't have current information about {a} or {b}, and their versions change often. Each maker publishes benchmark results, "
    "and independent leaderboards compare them. With web search turned on, I can look it up.",
]
SMARTER_REPLY = ("Possibly: {a} is a large model from a big company, and I'm a smaller one that runs on your own computer. Larger models are usually stronger "
                 "on hard questions, so please double-check anything important I tell you.")


def other_ai_conversations(rng, n):
    """Honest, short answers about other AI assistants (no claims about how this model was made)."""
    from web_lessons import OTHER_AIS, OTHER_AI_QUESTIONS
    out = []
    for _ in range(n):
        a, b = rng.sample(OTHER_AIS, 2)
        q = rng.choice(OTHER_AI_QUESTIONS)
        reply = SMARTER_REPLY if "smarter than you" in q else OTHER_AI_REPLIES[1] if "{b}" in q else OTHER_AI_REPLIES[0]
        q = q.format(a=a, b=b)
        if rng.random() < 0.3:
            q = q.lower().rstrip("?")
        out.append([V3.user(q), V3.assistant(reply.format(a=a, b=b))])
    return out


TYPO_KINDS = {"general", "topic_switch", "instruction", "facts", "names", "unknowable", "unfamiliar", "small_talk", "other_ai", "notes_use", "stand_firm"}


def notes_ignored_conversations(exchanges, passages, rng, n):
    """A question with notes about something else, answered normally from what the model knows (the answer is a general lesson's, not about the notes)."""
    out = []
    if not exchanges or len(passages) < 3:
        return out
    for _ in range(n):
        ex = rng.choice(exchanges)
        notes = [{"title": p["title"], "text": p["text"]} for p in rng.sample(passages, rng.randint(1, 3))]
        out.append([V3.user(ex[0]["content"], notes), V3.assistant(ex[1]["content"])])
    return out


def build(general, lookup_records, instruction_records, wiki, a, seed=1337):
    """Combine everything into one shuffled list of {"messages": [...], "kind": ...}."""
    rng = random.Random(seed)
    pool = clean(list(general))
    parts = {"general": V3.general_conversations(pool, a.general)}
    exchanges = clean(V3.first_exchanges(pool[a.general:] or pool, 30_000))
    parts["topic_switch"] = V3.topic_switch_conversations(exchanges, rng, a.topic_switch) if len(exchanges) >= 3 else []
    if instruction_records:
        parts["instruction"] = clean(V3.instruction_conversations(instruction_records, exchanges, rng))[:a.instruction]
    parts["facts"] = Q.fact_conversations(rng, a.facts)
    parts["names"] = Q.people_conversations(rng, a.people)
    parts["unknowable"] = Q.unknowable_conversations(rng, a.unknowable)
    parts["unfamiliar"] = Q.unfamiliar_conversations(rng, a.unfamiliar)
    parts["small_talk"] = small_talk_conversations(rng, a.small_talk)
    parts["other_ai"] = other_ai_conversations(rng, a.other_ai)
    if lookup_records:
        looked = V3.lookup_conversations(lookup_records, wiki, rng)
        parts["notes_use"] = strip_sources(looked["lookup"])[:a.notes_use]
        parts["stand_firm"] = strip_sources(looked["stand_firm"])
        passages = [r["source"] for r in lookup_records if r.get("source") and r["source"].get("text")]
        parts["notes_ignored"] = notes_ignored_conversations(exchanges, passages, rng, a.notes_ignored)
    examples = []
    for kind, convos in parts.items():
        kept = [c for c in convos if V3.total_chars(c) <= MAX_CHARS]
        print(f"  {kind:14s} {len(kept):7,}")
        examples += [{"messages": c, "kind": kind} for c in kept]
    if a.typos:
        from typo_lessons import typo_copies
        messy = typo_copies(examples, rng, a.typos, kinds=TYPO_KINDS)
        print(f"  {'typo':14s} {len(messy):7,}  (messy copies of {a.typos:.0%} of the lessons above)")
        examples += messy
    rng.shuffle(examples)
    return examples


def estimate(examples, batch_tokens=8192, accum=2):
    """(approximate tokens, approximate optimizer steps) so the run can be planned before it starts."""
    chars = sum(V3.total_chars(e["messages"]) for e in examples)
    tokens = int(chars / CHARS_PER_TOKEN)
    return tokens, max(1, int(tokens / (batch_tokens * accum)))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--general", type=int, default=6_000)
    p.add_argument("--pool", type=int, default=60_000, help="how many smol-smoltalk conversations to read (the lessons are chosen from them)")
    p.add_argument("--topic_switch", type=int, default=800)
    p.add_argument("--instruction", type=int, default=2_500)
    p.add_argument("--facts", type=int, default=900)
    p.add_argument("--people", type=int, default=700)
    p.add_argument("--unknowable", type=int, default=400)
    p.add_argument("--unfamiliar", type=int, default=300)
    p.add_argument("--small_talk", type=int, default=500)
    p.add_argument("--other_ai", type=int, default=300)
    p.add_argument("--notes_use", type=int, default=1_500)
    p.add_argument("--notes_ignored", type=int, default=1_200)
    p.add_argument("--typos", type=float, default=0.06)
    p.add_argument("--db", default=os.path.join("data", "wiki", "wiki.db"))
    p.add_argument("--search_seconds", type=float, default=0.0, help="Wikipedia search time per lookup lesson (0: use the teacher's source passage and random others)")
    p.add_argument("--teacher", default=TEACHER_DIR)
    p.add_argument("--out", default=OUT_PATH)
    p.add_argument("--seed", type=int, default=1337)
    a = p.parse_args(argv)
    V3.SEARCH_SECONDS = a.search_seconds
    from make_chat_data_v2 import load_smoltalk
    wiki = None
    if os.path.exists(a.db) and a.search_seconds > 0:
        from wiki_index import WikiIndex
        wiki = WikiIndex(a.db)
    general = itertools.islice(load_smoltalk(), a.pool)
    examples = build(general, V3.read_jsonl(os.path.join(a.teacher, "lookup.jsonl")), V3.read_jsonl(os.path.join(a.teacher, "instructions.jsonl")), wiki, a, a.seed)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    tokens, steps = estimate(examples)
    print(f"wrote {a.out}: {len(examples):,} conversations, about {tokens / 1e6:.1f}M tokens: roughly {steps} optimizer steps with --grad_accum 2 "
          f"(finetune_open.py also adds about 1,000 identity chats for each model)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
