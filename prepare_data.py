"""
prepare_data.py - Download TinyStories, train the tokenizer, and turn all the
text into token IDs saved as train.bin / val.bin (fast to read during training).

WHAT THIS FILE DOES (run it once)
    1. Downloads the TinyStories dataset (~2GB of simple short stories).
    2. Trains the BPE tokenizer on 20,000 stories -> data/tokenizer.json
       (skipped if that file already exists).
    3. Encodes every story into token IDs using all CPU cores and writes them
       as raw 16-bit integers:
         data/val.bin    ~ a few million tokens (for measuring progress)
         data/train.bin  ~ 470 million tokens  (for learning)

WHY .bin FILES
    Tokenizing is slow, training is fast. Doing it once and saving plain
    numbers lets train.py read random slices straight from disk millions of times.

Usage:  python prepare_data.py

Note: this downloads a public *dataset* (text), not a pretrained model.
"""
import os
from multiprocessing import Pool

import numpy as np
from datasets import load_dataset

from tokenizer import BPETokenizer

VOCAB_SIZE = 8192
TOKENIZER_TRAIN_STORIES = 20_000   # tokenizer only needs a sample
OUT_DIR = "data"
os.makedirs(OUT_DIR, exist_ok=True)

# Each worker process gets its own tokenizer (processes don't share memory).
# It's set by init_worker() inside each worker.
tok = None


def init_worker():
    """Runs once inside each worker process: load the tokenizer from disk."""
    global tok
    tok = BPETokenizer.load(os.path.join(OUT_DIR, "tokenizer.json"))


def encode_story(text):
    """Encode one story, adding <|endoftext|> so the model learns where stories end."""
    return tok.encode(text.strip() + "<|endoftext|>")


def encode_split(stories, filename):
    """Encode a list of stories in parallel and append their IDs to data/<filename>.

    Pool(os.cpu_count()) starts one worker per CPU core. imap() hands out
    stories in chunks of 256 and returns results IN ORDER, so the file keeps
    the original story order. Each ID is stored as uint16 (2 bytes), which
    fits any ID up to 65,535.

    Args:
        stories:  list of story strings
        filename: "train.bin" or "val.bin"
    """
    path = os.path.join(OUT_DIR, filename)
    total = 0
    with open(path, "wb") as f, Pool(os.cpu_count(), initializer=init_worker) as pool:
        for i, ids in enumerate(pool.imap(encode_story, stories, chunksize=256)):
            np.array(ids, dtype=np.uint16).tofile(f)
            total += len(ids)
            if i % 100_000 == 0:
                print(f"  {filename}: {i:,} stories, {total:,} tokens")
    print(f"wrote {path}: {total:,} tokens")


# The `if __name__ == "__main__"` guard is REQUIRED for multiprocessing on
# Windows: worker processes re-import this file, and must not re-run this part.
if __name__ == "__main__":
    ds = load_dataset("roneneldan/TinyStories")
    train_text, val_text = list(ds["train"]["text"]), list(ds["validation"]["text"])

    tok_path = os.path.join(OUT_DIR, "tokenizer.json")
    if not os.path.exists(tok_path):
        print("training tokenizer...")
        t = BPETokenizer()
        t.train("\n".join(train_text[:TOKENIZER_TRAIN_STORIES]), VOCAB_SIZE)
        t.save(tok_path)

    encode_split(val_text, "val.bin")
    encode_split(train_text, "train.bin")
