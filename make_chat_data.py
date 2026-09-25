"""
make_chat_data.py - Build data/chat.jsonl (fine-tuning examples) automatically.

WHAT THIS FILE DOES
    finetune.py needs a few thousand {"prompt": ..., "response": ...} examples.
    Writing them all by hand takes weeks, so this script builds them from the
    TinyStories data you already downloaded in prepare_data.py (it is cached,
    so nothing new is downloaded):

      * story requests   "Tell me a story about Lily."        -> a story with Lily
      * word requests    "Write a short story that uses the word "garden"." -> a story with it
      * open requests    "Tell me a bedtime story."            -> any story
      * basics           greetings and "who are you?" answers (see BASICS below)
      * your own examples from data/my_examples.jsonl, if that file exists
        (same format; each one is repeated 3 times so it counts more)

    The model learns the chat FORMAT from these: <|user|> request <|assistant|> reply.

Usage:  python make_chat_data.py              (writes data/chat.jsonl, 5000 examples)
        python make_chat_data.py --n 10000
"""
import argparse, json, os, random
import regex as re

OUT_PATH = "data/chat.jsonl"
MY_EXAMPLES = "data/my_examples.jsonl"   # optional: your own hand-written examples
MAX_STORY_CHARS = 1500                    # keep examples well under the 512-token limit

# Short hand-written answers so the model can handle simple small talk.
# Edit these to give your AI its own personality!
BASICS = [
    (["Hi", "Hello", "Hey", "Hi there", "Hello!", "Good morning"],
     "Hello! I am a small AI. I love telling stories. What would you like a story about?"),
    (["Who are you?", "What are you?", "What is your name?", "Tell me about yourself."],
     "I am a small AI that was trained from scratch. I know how to tell simple stories. "
     "Ask me for a story about anything you like!"),
    (["What can you do?", "How can you help me?", "What are you good at?"],
     "I can tell you short stories. Tell me a name, an animal, or a word, and I will make a story with it."),
    (["Thank you", "Thanks!", "Thanks, that was nice."],
     "You are welcome! Would you like another story?"),
    (["Bye", "Goodbye", "See you later"],
     "Goodbye! Come back any time for another story."),
]

OPEN_PROMPTS = ["Tell me a story.", "Tell me a bedtime story.", "Can you tell me a short story?",
                "Write a story for a child.", "I want to hear a story."]
NAME_PROMPTS = ["Tell me a story about {x}.", "Write a story about someone named {x}.",
                "Can you tell me a story with {x} in it?"]
WORD_PROMPTS = ['Write a short story that uses the word "{x}".', "Tell me a story about a {x}.",
                "Can you make a story with a {x}?"]

# Common words that make boring "use this word" prompts
STOPWORDS = set("""the and was were they them their there then that this with from have had
said very into when what your will would could should about after before because little
wanted went saw one day time once upon happy liked loved play played looked felt make made
back came come knew know thought took like just also some more other than been being every
""".split())


def story_to_examples(story, rng):
    """Turn ONE story into 1-2 (prompt, response) pairs, or [] if it's unsuitable.

    Looks for a character name ("named Lily") and for an interesting word in
    the story, and builds a request that the story actually answers.
    """
    story = story.strip()
    if not story or len(story) > MAX_STORY_CHARS:
        return []
    out = []
    m = re.search(r"\bnamed ([A-Z][a-z]+)", story)
    if m:
        out.append((rng.choice(NAME_PROMPTS).format(x=m.group(1)), story))
    words = [w for w in re.findall(r"\b[a-z]{4,10}\b", story) if w not in STOPWORDS]
    if words and (not out or rng.random() < 0.3):
        out.append((rng.choice(WORD_PROMPTS).format(x=rng.choice(words)), story))
    if not out:
        out.append((rng.choice(OPEN_PROMPTS), story))
    return out


def build_examples(stories, n, seed=1337):
    """Build `n` story examples plus the BASICS and your own examples.

    Args:
        stories: list of story strings
        n:       how many story-based examples to make
    Returns:
        shuffled list of {"prompt": str, "response": str} dicts
    """
    rng = random.Random(seed)
    examples = []
    order = list(range(len(stories)))
    rng.shuffle(order)
    for i in order:
        for prompt, response in story_to_examples(stories[i], rng):
            examples.append({"prompt": prompt, "response": response})
        if len(examples) >= n:
            break
    examples = examples[:n]

    # Small talk: each prompt variation appears a few times
    for prompts, response in BASICS:
        for p in prompts:
            examples.extend({"prompt": p, "response": response} for _ in range(5))

    # Your own examples count 3x
    if os.path.exists(MY_EXAMPLES):
        with open(MY_EXAMPLES, encoding="utf-8") as f:
            mine = [json.loads(line) for line in f if line.strip()]
        examples.extend(mine * 3)
        print(f"added {len(mine)} of your own examples (x3)")

    rng.shuffle(examples)
    return examples


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=5000, help="number of story examples")
    a = p.parse_args()

    from datasets import load_dataset   # imported here so the functions above work without it
    # The validation split is small and is NOT the text the model trained on
    # most, which gives a little extra variety.
    stories = list(load_dataset("roneneldan/TinyStories")["validation"]["text"])

    examples = build_examples(stories, a.n)
    os.makedirs("data", exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    print(f"wrote {OUT_PATH}: {len(examples)} examples")
    for ex in examples[:3]:
        print("\n  USER:", ex["prompt"], "\n  AI:  ", ex["response"][:120] + "...")
