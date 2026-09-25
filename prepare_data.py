"""
prepare_data.py - Download TinyStories, train the tokenizer, and turn all the
text into token IDs saved as train.bin / val.bin (fast to read during training).

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

tok = None


def init_worker():
    global tok
    tok = BPETokenizer.load(os.path.join(OUT_DIR, "tokenizer.json"))


def encode_story(text):
    return tok.encode(text.strip() + "<|endoftext|>")


def encode_split(stories, filename):
    path = os.path.join(OUT_DIR, filename)
    total = 0
    with open(path, "wb") as f, Pool(os.cpu_count(), initializer=init_worker) as pool:
        for i, ids in enumerate(pool.imap(encode_story, stories, chunksize=256)):
            np.array(ids, dtype=np.uint16).tofile(f)
            total += len(ids)
            if i % 100_000 == 0:
                print(f"  {filename}: {i:,} stories, {total:,} tokens")
    print(f"wrote {path}: {total:,} tokens")


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
