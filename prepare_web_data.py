"""
prepare_web_data.py - Build training data for the web-data versions (v2, v3, ...).

WHAT THIS FILE DOES (run it once per version; it takes a while)
    1. Streams public datasets. "Streaming" reads them piece by piece over
       the internet instead of downloading everything first, so it needs
       only about as much disk as the finished data:
         fineweb    - FineWeb-Edu: educational web pages
         wikipedia  - English Wikipedia
         code       - Python source code (codeparrot-clean)          (v3+)
         math       - FineMath: web pages with step-by-step math      (v3+)
         tinystories- the v1 stories (already on your PC)
       How much of each is set per version in config.py (data_mix):
         v2: 80% fineweb, 15% wikipedia, 5% stories          ~2.8B tokens
         v3: 63% fineweb, 20% wikipedia, 10% code, 5% math, 2% stories  ~12B tokens
    2. Trains the version's tokenizer on a sample of all sources
       -> <data_dir>/tokenizer.json
    3. Encodes the text into token IDs with all CPU cores, source by source,
       and finally joins them into <data_dir>/train.bin and val.bin.

IT CAN BE STOPPED AND RESTARTED
    Progress is saved after every batch (<data_dir>/<source>.progress.json).
    If it crashes, loses internet, or you press Ctrl+C, just run it again:
    finished sources are skipped and an unfinished one continues where it
    stopped.

Usage:
    python prepare_web_data.py --version v3 --test   quick check: 20M tokens into data/v3-test
    python prepare_web_data.py --version v3          the real run
    (python prepare_data_v2.py still works for v2)

Note: this downloads public *datasets* (text and code), not pretrained models.
"""
import argparse, itertools, json, os, sys, time
from multiprocessing import Pool

import numpy as np

from config import VERSIONS, get_version
from tokenizer import BPETokenizer

# Each worker process gets its own tokenizer (processes don't share memory).
tok = None
EOT = None


# ------------------------------------------------------------------ sources
# Each loader yields plain-text documents, one at a time, always in the same
# order (so a restarted run can skip the documents it already did).
def load_fineweb():
    """FineWeb-Edu: web pages filtered to keep educational, well-written ones."""
    from datasets import load_dataset
    ds = load_dataset("HuggingFaceFW/fineweb-edu", name="sample-10BT", split="train", streaming=True)
    for row in ds:
        yield row["text"]


def load_wikipedia():
    """English Wikipedia. The title is added on top so facts are tied to their subject."""
    from datasets import load_dataset
    ds = load_dataset("wikimedia/wikipedia", "20231101.en", split="train", streaming=True)
    for row in ds:
        yield f"{row['title']}\n\n{row['text']}"


def load_tinystories():
    """The TinyStories dataset from v1 (already cached, so no download)."""
    from datasets import load_dataset
    for row in load_dataset("roneneldan/TinyStories", split="train"):
        yield row["text"]


def load_code():
    """Python source files from GitHub (codeparrot-clean: deduplicated, permissively usable).

    Very large files (usually generated data, not real code) are skipped.
    """
    from datasets import load_dataset
    ds = load_dataset("codeparrot/codeparrot-clean", split="train", streaming=True)
    for row in ds:
        if len(row["content"]) <= 50_000:
            yield row["content"]


def load_math():
    """FineMath (4+ quality): web pages that explain math step by step.

    Worked examples, lessons and solved problems, from arithmetic up to
    calculus. Only pages rated 4 or 5 (out of 5) for educational quality.
    """
    from datasets import load_dataset
    ds = load_dataset("HuggingFaceTB/finemath", "finemath-4plus", split="train", streaming=True)
    for row in ds:
        yield row["text"]


# Source name (as used in config.py's data_mix) -> loader
LOADERS = {
    "fineweb": load_fineweb,
    "wikipedia": load_wikipedia,
    "code": load_code,
    "math": load_math,
    "tinystories": load_tinystories,
}


def sources_for(V):
    """[(name, loader, share), ...] for a version, from its data_mix in config.py."""
    return [(name, LOADERS[name], share) for name, share in V.data_mix]


# ------------------------------------------------------------------ workers
def init_worker(tok_path):
    """Runs once inside each worker process: load the tokenizer from disk."""
    global tok, EOT
    tok = BPETokenizer.load(tok_path)
    EOT = tok.special["<|endoftext|>"]


def encode_doc(text):
    """Encode one document and end it with <|endoftext|>.

    allow_special=False: web pages sometimes contain the literal text
    "<|endoftext|>"; it must NOT become the real control token.
    """
    return tok.encode(text.strip(), allow_special=False) + [EOT]


# ------------------------------------------------------------------ steps
def train_tokenizer(out_dir, sample_chars, sources, vocab_size):
    """Train the tokenizer on a sample mixed from all sources (by share)."""
    path = os.path.join(out_dir, "tokenizer.json")
    if os.path.exists(path):
        print(f"tokenizer: {path} already exists, skipping")
        return path
    parts = []
    for name, loader, share in sources:
        want, got = int(sample_chars * share), 0
        for text in loader():
            parts.append(text)
            got += len(text)
            if got >= want:
                break
        print(f"tokenizer sample: {name} {got/1e6:.1f}M characters")
    t = BPETokenizer()
    t.train_fast("\n".join(parts), vocab_size)
    t.save(path)
    print(f"saved {path}")
    return path


def encode_source(name, loader, train_budget, val_budget, out_dir, tok_path, pool_size, batch_docs):
    """Encode one source into <name>_train.bin / <name>_val.bin, resumably.

    The first documents fill the val file (val_budget tokens), the rest fill
    the train file until train_budget tokens. Progress is saved after each
    batch so an interrupted run continues where it stopped.
    """
    done_path = os.path.join(out_dir, f"{name}.done")
    if os.path.exists(done_path):
        print(f"{name}: already done, skipping")
        return
    prog_path = os.path.join(out_dir, f"{name}.progress.json")
    train_path = os.path.join(out_dir, f"{name}_train.bin")
    val_path = os.path.join(out_dir, f"{name}_val.bin")
    prog = {"docs": 0, "train_bytes": 0, "val_bytes": 0}
    if os.path.exists(prog_path):
        with open(prog_path) as f:
            prog = json.load(f)
        print(f"{name}: resuming after {prog['docs']:,} documents")

    # Open for appending, then cut off anything written after the last saved progress
    ftrain, fval = open(train_path, "ab"), open(val_path, "ab")
    ftrain.truncate(prog["train_bytes"]); fval.truncate(prog["val_bytes"])
    ftrain.seek(prog["train_bytes"]); fval.seek(prog["val_bytes"])
    n_train, n_val = prog["train_bytes"] // 2, prog["val_bytes"] // 2   # uint16 = 2 bytes per token

    docs = itertools.islice(loader(), prog["docs"], None)   # skip what we already did
    t0, start_tokens = time.time(), n_train + n_val
    with Pool(pool_size, initializer=init_worker, initargs=(tok_path,)) as pool:
        while n_train < train_budget:
            batch = list(itertools.islice(docs, batch_docs))
            if not batch:
                print(f"{name}: source ran out of text at {n_train:,} tokens")
                break
            for ids in pool.map(encode_doc, batch, chunksize=64):
                arr = np.array(ids, dtype=np.uint16)
                if n_val < val_budget:
                    arr.tofile(fval); n_val += len(arr)
                elif n_train < train_budget:
                    arr.tofile(ftrain); n_train += len(arr)
            prog["docs"] += len(batch)
            ftrain.flush(); fval.flush()
            prog["train_bytes"], prog["val_bytes"] = ftrain.tell(), fval.tell()
            with open(prog_path, "w") as f:
                json.dump(prog, f)
            rate = (n_train + n_val - start_tokens) / max(time.time() - t0, 1e-9)
            eta_h = max(0, train_budget - n_train) / max(rate, 1) / 3600
            print(f"  {name}: {n_train:,}/{train_budget:,} train tokens  "
                  f"({rate/1e3:.0f}k tokens/s, ~{eta_h:.1f}h left)")
    ftrain.close(); fval.close()
    open(done_path, "w").close()
    print(f"{name}: done ({n_train:,} train + {n_val:,} val tokens)")


def join_files(out_dir, split, names):
    """Concatenate every source's <name>_<split>.bin into <split>.bin, then delete the parts."""
    final = os.path.join(out_dir, f"{split}.bin")
    if os.path.exists(final):
        return
    tmp = final + ".tmp"
    with open(tmp, "wb") as out:
        for name in names:
            part = os.path.join(out_dir, f"{name}_{split}.bin")
            with open(part, "rb") as f:
                while chunk := f.read(64 * 1024 * 1024):
                    out.write(chunk)
    os.replace(tmp, final)
    for name in names:
        os.remove(os.path.join(out_dir, f"{name}_{split}.bin"))
    print(f"wrote {final}: {os.path.getsize(final)//2:,} tokens")


def main(argv=None):
    web_versions = [n for n, v in VERSIONS.items() if v.data_mix]
    p = argparse.ArgumentParser()
    p.add_argument("--version", default="v2", choices=web_versions)
    p.add_argument("--test", action="store_true", help="small trial run into <data_dir>-test")
    p.add_argument("--total_tokens", type=int, default=None, help="default: data_tokens in config.py")
    p.add_argument("--val_tokens", type=int, default=10_000_000)
    p.add_argument("--sample_mb", type=float, default=None, help="tokenizer sample size (default: config.py)")
    p.add_argument("--workers", type=int, default=os.cpu_count())
    p.add_argument("--batch_docs", type=int, default=4000, help="documents per batch (progress is saved after each)")
    a = p.parse_args(argv)
    V = get_version(a.version)
    sources = sources_for(V)
    a.total_tokens = a.total_tokens or V.data_tokens
    a.sample_mb = a.sample_mb or V.tokenizer_sample_mb

    out_dir = V.data_dir
    if a.test:
        out_dir = V.data_dir.rstrip("/") + "-test"
        a.total_tokens, a.val_tokens, a.sample_mb = 20_000_000, 1_000_000, 5
    os.makedirs(out_dir, exist_ok=True)
    print(f"building {a.total_tokens:,} tokens into {out_dir}/ with {a.workers} CPU workers")

    tok_path = train_tokenizer(out_dir, int(a.sample_mb * 1e6), sources, V.vocab_size)
    for name, loader, share in sources:
        encode_source(name, loader, int(a.total_tokens * share), int(a.val_tokens * share),
                      out_dir, tok_path, a.workers, a.batch_docs)
    names = [name for name, _, _ in sources]
    join_files(out_dir, "val", names)
    join_files(out_dir, "train", names)
    print("all done!")


# The `if __name__ == "__main__"` guard is REQUIRED for multiprocessing on
# Windows: worker processes re-import this file, and must not re-run this part.
if __name__ == "__main__":
    main()
