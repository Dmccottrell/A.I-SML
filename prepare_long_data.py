"""
prepare_long_data.py - Build the long-document data for stretching a model's context (docs/LONG_CONTEXT.md).

WHAT THIS FILE DOES
    Stretching a model from 2,048 tokens to 8K-32K only teaches it to USE the extra room if the
    training text is genuinely long and the far-away parts matter. Short web pages glued together
    teach almost nothing. So this builds a separate data set from long material:

        books         Project Gutenberg books (PG-19: public domain, whole books)      30%
        wiki_long     Wikipedia articles of 24,000+ characters (~6K+ tokens)           15%
        web_long      FineWeb-Edu pages of 16,000+ characters                          10%
        code_repos    Python files grouped by repository, so one file's functions are
                      used in another (whole repositories, not single files)           10%
        recall        made-up practice documents: facts scattered through long text,
                      questions about them at the end (including one that isn't in the
                      text: "The text doesn't say")                                     5%
        replay        ordinary short text copied from the base version's own train.bin,
                      so the model doesn't lose its short-text skill                    30%

    The recall documents never use the wording of the tests in eval_long.py (no "secret code",
    "vault", "Mira", "get_port_"): the tests must measure a skill, not a memorized format.

    Output (same tokenizer as the base version, copied in):
        data/v3-long/tokenizer.json, train.bin, val.bin
    val.bin holds only long natural documents, so eval_long.py uses it as its filler text.

    Documents containing test questions are skipped, as in prepare_web_data.py. It can be stopped
    and restarted the same way (progress is saved per source).

Usage:
    python prepare_long_data.py --version v3 --test     quick check: ~20M tokens into data/v3-long-test
    python prepare_long_data.py --version v3            the real set: ~1.4B tokens (~2.8 GB) into data/v3-long

    It needs the base version's data (data/v3/tokenizer.json and train.bin) on the same machine.
"""
import argparse
import itertools
import os
import random
import shutil
import sys
from collections import OrderedDict

import numpy as np

import prepare_web_data as W
from config import get_version

# name -> share of the tokens
LONG_MIX = (("books", 0.30), ("wiki_long", 0.15), ("web_long", 0.10), ("code_repos", 0.10),
            ("recall", 0.05), ("replay", 0.30))
TOTAL_TOKENS = 1_400_000_000        # covers the 8K, 16K and 32K stretch steps (~1.3B)
VAL_TOKENS = 2_000_000
BATCH_DOCS = {"books": 8, "recall": 16}   # documents per progress save (books are huge)

MIN_CHARS = {"wiki_long": 24_000, "web_long": 16_000, "code_repos": 12_000}
REPO_TARGET_CHARS = 120_000          # a repository document is closed once it reaches this size
REPO_BUFFER = 3000                   # repositories kept open at once while grouping files
REPLAY_CHUNK = 1_000_000             # replay copies this many tokens at a time from a random place


# ------------------------------------------------------------------ long natural text
def load_books():
    """Whole public-domain books (PG-19, from Project Gutenberg). Tries two copies of the data set."""
    from datasets import load_dataset
    last = None
    for name in ("emozilla/pg19", "deepmind/pg19"):
        try:
            rows = iter(load_dataset(name, split="train", streaming=True))
            first = next(rows)
        except Exception as e:           # this copy isn't readable here: try the next one
            last = e
            continue
        # From here on, errors are real (e.g. the internet dropped): switching copies mid-way would
        # change the order of the books, and a restarted run relies on the order staying the same.
        yield first["text"]
        for row in rows:
            yield row["text"]
        return
    raise SystemExit(f"couldn't read PG-19 books ({last}). Check the internet connection; "
                     "the data set names are in load_books() in prepare_long_data.py.")


def long_only(texts, min_chars):
    for text in texts:
        if len(text) >= min_chars:
            yield text


def load_wiki_long():
    yield from long_only(W.load_wikipedia(), MIN_CHARS["wiki_long"])


def load_web_long():
    yield from long_only(W.load_fineweb(), MIN_CHARS["web_long"])


# ------------------------------------------------------------------ code, grouped by repository
def _code_rows():
    """(repository, file path, content) for Python files (codeparrot-clean, as in v3's data)."""
    from datasets import load_dataset
    ds = load_dataset("codeparrot/codeparrot-clean", split="train", streaming=True)
    for row in ds:
        yield row["repo_name"], row["path"], row["content"]


def repo_document(repo, files):
    return f"# Repository: {repo}\n\n" + "\n\n".join(f"# File: {path}\n{content}" for path, content in files)


def group_by_repo(rows, min_chars=None, target=REPO_TARGET_CHARS, buffer=REPO_BUFFER):
    """Collect files of the same repository into one document.

    Keeps up to `buffer` repositories open. A repository is written out when it reaches `target`
    characters, or when it is the oldest open one and room is needed (then only if it has at least
    `min_chars`, so short leftovers are dropped). Always the same order, so restarts line up.
    """
    min_chars = MIN_CHARS["code_repos"] if min_chars is None else min_chars
    open_repos = OrderedDict()                  # repo -> [files, size]
    for repo, path, content in rows:
        if not W.looks_like_real_code(content):
            continue
        entry = open_repos.setdefault(repo, [[], 0])
        entry[0].append((path, content))
        entry[1] += len(content)
        if entry[1] >= target:
            del open_repos[repo]
            yield repo_document(repo, entry[0])
        elif len(open_repos) > buffer:
            old, (files, size) = open_repos.popitem(last=False)
            if size >= min_chars:
                yield repo_document(old, files)
    for repo, (files, size) in open_repos.items():
        if size >= min_chars:
            yield repo_document(repo, files)


def load_code_repos():
    yield from group_by_repo(_code_rows())


# ------------------------------------------------------------------ made-up recall practice
FIRST = ["Anika", "Bruno", "Celeste", "Dmitri", "Elif", "Farid", "Greta", "Hugo", "Ines", "Jonas", "Kaito",
         "Lucia", "Mateo", "Nadia", "Oskar", "Priya", "Quentin", "Rosa", "Soren", "Talia", "Umar", "Vera"]
OBJECTS = ["blue notebook", "spare key", "brass compass", "old camera", "toolbox", "violin", "map of the coast",
           "first-aid kit", "chess set", "telescope", "sewing kit", "field journal"]
PLACES = ["attic", "garden shed", "top drawer", "basement", "car trunk", "library", "kitchen cupboard",
          "workshop", "hall closet", "boathouse", "office safe", "greenhouse"]
TOPICS = ["the bridge repair", "the school play", "the harvest fair", "the new budget", "the river survey",
          "the library move", "the bike race", "the museum opening"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
THINGS = ["copper pipes", "glass jars", "wool blankets", "oak planks", "paint cans", "rope coils", "solar lamps"]
VARS = ["max_retries", "timeout_seconds", "batch_limit", "cache_size", "worker_count", "page_width"]


def recall_facts(rng):
    """One made-up fact: (sentence to hide, question, answer)."""
    kind = rng.randrange(4)
    if kind == 0:
        who, obj, where = rng.choice(FIRST), rng.choice(OBJECTS), rng.choice(PLACES)
        return (f"{who} keeps the {obj} in the {where}.", f"Where does {who} keep the {obj}?",
                f"In the {where}.")
    if kind == 1:
        topic, day, hour = rng.choice(TOPICS), rng.choice(DAYS), rng.randint(7, 20)
        return (f"The meeting about {topic} is on {day} at {hour}:00.", f"When is the meeting about {topic}?",
                f"On {day} at {hour}:00.")
    if kind == 2:
        code, n, thing = f"{rng.choice('ABCDEFGHJKLMNP')}{rng.randint(10, 99)}", rng.randint(2, 900), rng.choice(THINGS)
        return (f"Stock list, item {code}: {n} {thing}.", f"How many {thing} are on the stock list under item {code}?",
                f"{n}.")
    var, n = rng.choice(VARS), rng.randint(2, 5000)
    return (f"In the settings file, {var} = {n}", f"What value is {var} set to in the settings file?", f"{n}.")


def recall_document(rng, filler_texts, target_chars):
    """Real text of about target_chars characters with 2-6 facts hidden in it, then questions and answers."""
    parts, size = [], 0
    while size < target_chars:
        t = next(filler_texts)
        parts.append(t)
        size += len(t) + 2
    text = "\n\n".join(parts)[:target_chars]
    facts, seen, n_facts = [], set(), rng.randint(2, 6)
    while len(facts) < n_facts:
        f = recall_facts(rng)
        if f[1] not in seen:                  # one answer per question
            seen.add(f[1])
            facts.append(f)
    cuts = sorted(rng.randint(0, len(text)) for _ in facts)
    pieces, last = [], 0
    for cut, (sentence, _, _) in zip(cuts, facts):
        pieces += [text[last:cut], f"\n\n{sentence}\n\n"]
        last = cut
    pieces.append(text[last:])
    qa = [(q, a) for _, q, a in facts]
    rng.shuffle(qa)
    if rng.random() < 0.3:                    # a question the text can't answer: it should say so
        who, obj = rng.choice(FIRST), rng.choice(OBJECTS)
        if all(f"{who} keep the {obj}" not in q for q, _ in qa):
            qa.insert(rng.randrange(len(qa) + 1), (f"Where does {who} keep the {obj}?", "The text doesn't say."))
    questions = "\n".join(f"Q: {q}\nA: {a}" for q, a in qa)
    return "".join(pieces) + "\n\nQuestions about the text above:\n" + questions


def load_recall(seed=1234, filler=None):
    """Recall practice documents of 8,000-130,000 characters (~2K-32K tokens), always the same ones."""
    rng = random.Random(seed)
    filler_texts = iter(filler if filler is not None else W.load_wikipedia())
    while True:
        target = int(8000 * (130_000 / 8000) ** rng.random())   # spread evenly on a log scale
        try:
            yield recall_document(rng, filler_texts, target)
        except StopIteration:
            return


LOADERS = {"books": load_books, "wiki_long": load_wiki_long, "web_long": load_web_long,
           "code_repos": load_code_repos, "recall": load_recall}


# ------------------------------------------------------------------ replay (short text, already tokenized)
def copy_replay(base_train, out_dir, n_tokens, seed=0):
    """Copy n_tokens of the base version's own training tokens, in 1M-token pieces from random places."""
    done = os.path.join(out_dir, "replay.done")
    train_part, val_part = os.path.join(out_dir, "replay_train.bin"), os.path.join(out_dir, "replay_val.bin")
    if os.path.exists(done):
        print("replay: already done, skipping")
        return
    src = np.memmap(base_train, dtype=np.uint16, mode="r")
    if len(src) < REPLAY_CHUNK * 2:
        raise SystemExit(f"{base_train} is too small to copy replay text from")
    rng = np.random.default_rng(seed)
    with open(train_part + ".tmp", "wb") as f:
        left = n_tokens
        while left > 0:
            n = min(REPLAY_CHUNK, left)
            start = int(rng.integers(0, len(src) - n))
            np.asarray(src[start:start + n]).tofile(f)
            left -= n
    os.replace(train_part + ".tmp", train_part)
    open(val_part, "wb").close()             # replay adds nothing to val (val is long text only)
    open(done, "w").close()
    print(f"replay: copied {n_tokens:,} tokens from {base_train}")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--version", default="v3", help="the base version whose tokenizer and data are used")
    p.add_argument("--test", action="store_true", help="small trial run into <data_dir>-long-test")
    p.add_argument("--total_tokens", type=int, default=TOTAL_TOKENS)
    p.add_argument("--val_tokens", type=int, default=VAL_TOKENS)
    p.add_argument("--workers", type=int, default=os.cpu_count())
    p.add_argument("--no_decontam", action="store_true", help="don't skip documents containing test questions")
    a = p.parse_args(argv)
    V = get_version(a.version)
    base_tok = os.path.join(V.data_dir, "tokenizer.json")
    base_train = os.path.join(V.data_dir, "train.bin")
    for path in (base_tok, base_train):
        if not os.path.exists(path):
            sys.exit(f"missing {path}: build {V.name}'s data first (prepare_web_data.py --version {V.name})")
    out_dir = V.data_dir.rstrip("/") + "-long"
    if a.test:
        out_dir += "-test"
        a.total_tokens, a.val_tokens = 20_000_000, 500_000
    os.makedirs(out_dir, exist_ok=True)
    tok_path = os.path.join(out_dir, "tokenizer.json")
    if not os.path.exists(tok_path):
        shutil.copyfile(base_tok, tok_path)      # the same tokenizer: token IDs must mean the same thing
    print(f"building {a.total_tokens:,} long-context tokens into {out_dir}/ with {a.workers} CPU workers")

    test_ngrams = W.load_test_ngrams() if V.decontaminate and not a.no_decontam else None
    text_shares = sum(s for n, s in LONG_MIX if n not in ("replay", "recall"))
    for name, share in LONG_MIX:
        budget = int(a.total_tokens * share)
        if name == "replay":
            copy_replay(base_train, out_dir, budget)
            continue
        val = 0 if name == "recall" else int(a.val_tokens * share / text_shares)
        W.encode_source(name, LOADERS[name], budget, val, out_dir, tok_path, a.workers,
                        BATCH_DOCS.get(name, 256), test_ngrams)
    names = [name for name, _ in LONG_MIX]
    W.join_files(out_dir, "val", names)
    W.join_files(out_dir, "train", names)
    print("all done!")


if __name__ == "__main__":
    main()
