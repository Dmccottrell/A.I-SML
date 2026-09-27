"""
make_chat_data_v2.py - Build v2's chat examples -> data/v2/chat.jsonl

WHAT THIS FILE DOES
    Mixes four kinds of conversations (multi-turn, in the "messages" format
    described in chat.py):

      * general chat  - smol-smoltalk: public multi-turn conversations made
                        for small models (questions, explanations, advice).
                        These were written by other AIs; your model's brain
                        is still 100% trained by you, but it learns its chat
                        STYLE partly from them.
      * identity      - who the AI is (edit IDENTITY below to change its personality)
      * stories       - "Tell me a story about..." so it keeps v1's skill
      * your examples - data/v2/my_examples.jsonl if it exists (either format,
                        each counted 3 times)

    Long conversations are skipped so every example fits the 1024-token context.

Usage:  python make_chat_data_v2.py              (100,000 general conversations)
        python make_chat_data_v2.py --n 50000
"""
import argparse, json, os, random

from config import get_version
from make_chat_data import story_to_examples

V = get_version("v2")
OUT_PATH = os.path.join(V.data_dir, "chat.jsonl")
MY_EXAMPLES = os.path.join(V.data_dir, "my_examples.jsonl")
MAX_CHARS = 3000        # ~750 tokens: leaves room so examples fit in 1024 tokens

# Who the AI says it is. Edit these to give your AI its own name and personality!
IDENTITY = ("I'm a small AI assistant that was trained from scratch on a home computer. "
            "I can answer simple questions, explain things, chat, and tell stories. "
            "I'm still small, so I can make mistakes. Please double-check anything important!")
GREETING = "Hi! I'm a small AI assistant. What would you like to talk about?"
IDENTITY_QUESTIONS = ["Who are you?", "What are you?", "Tell me about yourself.",
                      "Are you ChatGPT?", "Who made you?", "What can you do?"]
GREETINGS = ["Hi", "Hello", "Hey", "Hi there", "Good morning", "Hey, how's it going?"]


def load_smoltalk():
    """Yield conversations (lists of messages) from smol-smoltalk."""
    from datasets import load_dataset
    ds = load_dataset("HuggingFaceTB/smol-smoltalk", split="train")
    for row in ds.shuffle(seed=42):        # mix the topics (the file is grouped by type)
        yield row["messages"]


def load_story_texts():
    """TinyStories validation stories (cached from v1)."""
    from datasets import load_dataset
    return list(load_dataset("roneneldan/TinyStories", split="validation")["text"])


def fits(messages):
    """True if the conversation is short enough and actually has an answer."""
    return (sum(len(m["content"]) for m in messages) <= MAX_CHARS
            and any(m["role"] == "assistant" for m in messages))


def identity_conversations(rng, n):
    """Short conversations that teach the AI its name and personality.

    Some are one message; others start with a greeting and then ask, so it
    also learns to handle a second message in the same chat.
    """
    out = []
    for _ in range(n):
        q = rng.choice(IDENTITY_QUESTIONS)
        if rng.random() < 0.5:
            msgs = [{"role": "user", "content": q}, {"role": "assistant", "content": IDENTITY}]
        else:
            msgs = [{"role": "user", "content": rng.choice(GREETINGS)},
                    {"role": "assistant", "content": GREETING},
                    {"role": "user", "content": q},
                    {"role": "assistant", "content": IDENTITY}]
        out.append({"messages": msgs})
    return out


def story_conversations(stories, rng, n):
    """Story requests built from TinyStories (see make_chat_data.py)."""
    out = []
    for story in stories:
        for prompt, response in story_to_examples(story, rng):
            out.append({"messages": [{"role": "user", "content": prompt},
                                     {"role": "assistant", "content": response}]})
        if len(out) >= n:
            break
    return out[:n]


def build(general, stories, n_general, n_stories, seed=1337):
    """Combine all sources into one shuffled list of {"messages": [...]} examples.

    Args:
        general: iterable of conversations (lists of messages)
        stories: list of story strings
    """
    rng = random.Random(seed)
    examples = []
    for messages in general:
        if fits(messages):
            examples.append({"messages": messages})
            if len(examples) >= n_general:
                break
    print(f"general conversations: {len(examples):,}")
    rng.shuffle(stories)
    story_ex = story_conversations(stories, rng, n_stories)
    ident_ex = identity_conversations(rng, 300)
    print(f"stories: {len(story_ex):,}  identity: {len(ident_ex):,}")
    examples += story_ex + ident_ex
    if os.path.exists(MY_EXAMPLES):
        with open(MY_EXAMPLES, encoding="utf-8") as f:
            mine = [json.loads(line) for line in f if line.strip()]
        examples += mine * 3
        print(f"your own examples: {len(mine)} (x3)")
    rng.shuffle(examples)
    return examples


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=100_000, help="general conversations to use")
    p.add_argument("--stories", type=int, default=5_000, help="story requests to add")
    a = p.parse_args()

    examples = build(load_smoltalk(), load_story_texts(), a.n, a.stories)
    os.makedirs(V.data_dir, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    print(f"wrote {OUT_PATH}: {len(examples):,} conversations")
