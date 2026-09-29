"""
prepare_web_data.py - Build training data for the web-data versions (v2, v3, ...).

WHAT THIS FILE DOES (run it once per version; it takes a while)
    1. Streams public datasets. "Streaming" reads them piece by piece over
       the internet instead of downloading everything first, so it needs
       only about as much disk as the finished data:
         fineweb    - FineWeb-Edu: educational web pages
         wikipedia  - English Wikipedia
         code       - Python source code (codeparrot-clean)          (v3)
         code_multi - Python, JavaScript, HTML, CSS, Java, C#, SQL, shell and
                      PowerShell (The Stack, license-filtered)          (v3.5)
         fineweb_100bt / fineweb_hq_100bt - the bigger FineWeb-Edu slice (v3.5)
         math       - FineMath: web pages with step-by-step math      (v3+)
         tinystories- the v1 stories (already on your PC)
       How much of each is set per version in config.py (data_mix):
         v2: 80% fineweb, 15% wikipedia, 5% stories          ~2.8B tokens
         v3: 63% fineweb, 20% wikipedia, 10% code, 5% math, 2% stories  ~12B tokens
    2. Trains the version's tokenizer on a sample of all sources
       -> <data_dir>/tokenizer.json
    3. Encodes the text into token IDs with all CPU cores, source by source,
       and finally joins them into <data_dir>/train.bin and val.bin.
    4. (v3+) Skips any document that contains a public test question
       (HellaSwag, GSM8K), so test scores stay fair ("decontamination").
    5. (v3+) Builds a separate, higher-quality "anneal" set in
       <data_dir>/anneal/train.bin, read during the last 10% of training.

IT CAN BE STOPPED AND RESTARTED
    Progress is saved after every batch (<data_dir>/<source>.progress.json).
    If it crashes, loses internet, or you press Ctrl+C, just run it again:
    finished sources are skipped and an unfinished one continues where it
    stopped. (A restart re-reads the stream up to where it stopped without
    encoding it, which needs the internet again: a restart late in a 30B-token
    v3.5 run re-downloads a lot, so avoid Ctrl+C on that one unless you must.)

v3.5's code data (code_multi) comes from bigcode/the-stack-dedup, which needs a free
Hugging Face account: open https://huggingface.co/datasets/bigcode/the-stack-dedup, accept
the terms, then run `hf auth login` (older versions: `huggingface-cli login`) once. Without that, use v3's Python-only
"code" source instead.

Usage:
    python prepare_web_data.py --version v3 --test   quick check: 20M tokens into data/v3-test
    python prepare_web_data.py --version v3          the real run
    (python prepare_data_v2.py still works for v2)

Note: this downloads public *datasets* (text and code), not pretrained models.
"""
import argparse, hashlib, itertools, json, os, re, sys, time
from multiprocessing import Pool

import numpy as np

from config import VERSIONS, get_version
from tokenizer import BPETokenizer

# Each worker process gets its own tokenizer (processes don't share memory).
tok = None
EOT = None
TEST_NGRAMS = None   # set of hashed 13-word phrases from test questions (decontamination)
NGRAM = 13


# ------------------------------------------------------------------ sources
# Each loader yields plain-text documents, one at a time, always in the same
# order (so a restarted run can skip the documents it already did).
def load_fineweb():
    """FineWeb-Edu: web pages filtered to keep educational, well-written ones."""
    from datasets import load_dataset
    ds = load_dataset("HuggingFaceFW/fineweb-edu", name="sample-10BT", split="train", streaming=True)
    for row in ds:
        yield row["text"]


def load_fineweb_100bt():
    """The 10x bigger FineWeb-Edu slice (v3.5 reads ~19B tokens, so a 10B slice would repeat pages)."""
    from datasets import load_dataset
    ds = load_dataset("HuggingFaceFW/fineweb-edu", name="sample-100BT", split="train", streaming=True)
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


# ---- v3.5: several programming languages ----
# Language folder in The Stack -> share of the code characters. Python stays the biggest
# (the v4 coding helper's main language); JavaScript/HTML/CSS for websites; SQL for data;
# shell/PowerShell for everyday computer tasks; Java and C# are common at work.
CODE_LANGUAGES = {"python": 0.49, "javascript": 0.14, "html": 0.05, "css": 0.04, "java": 0.07,
                  "c-sharp": 0.06, "sql": 0.08, "shell": 0.05, "powershell": 0.02}


def looks_like_real_code(text):
    """Skip generated or minified files and data dumps: very long lines, or mostly symbols/digits."""
    if not text or len(text) > 50_000:
        return False
    lines = text.split("\n")
    if max(map(len, lines)) > 1000 or len(text) / len(lines) > 100:
        return False
    return sum(c.isalpha() for c in text) / len(text) >= 0.25


def _stack_language(lang):
    """Files of one language from The Stack (license-filtered, deduplicated)."""
    from datasets import load_dataset
    try:
        ds = load_dataset("bigcode/the-stack-dedup", data_dir=f"data/{lang}", split="train", streaming=True)
        for row in ds:
            if looks_like_real_code(row["content"]):
                yield row["content"]
    except Exception as e:                       # usually: terms not accepted / not logged in
        if type(e).__name__ in ("GatedRepoError", "DatasetNotFoundError", "HfHubHTTPError",
                                "RepositoryNotFoundError", "HTTPError", "DataFilesNotFoundError"):
            raise SystemExit(f"can't read The Stack ({lang}): {e}\n"
                             "Open https://huggingface.co/datasets/bigcode/the-stack-dedup, accept the terms, "
                             "then run `hf auth login` (older versions: `huggingface-cli login`). Or use the Python-only 'code' source in config.py.")
        raise


def interleave(streams, weights):
    """Yield texts from several streams so each gets its share (`weights`) of the CHARACTERS.

    Always takes the next text from the stream that is furthest behind its share. There is no
    randomness, so a restarted run sees exactly the same order. A stream that runs out drops
    out and the others share its part.
    """
    streams = dict(streams)
    weights = {k: weights[k] for k in streams}
    sent = {k: 0 for k in streams}
    while streams:
        k = min(streams, key=lambda name: sent[name] / weights[name])
        try:
            text = next(streams[k])
        except StopIteration:
            del streams[k]
            continue
        sent[k] += len(text)
        yield text


def load_code_multi():
    """Code in several languages, mixed by CODE_LANGUAGES (so the tokenizer also sees all of them)."""
    yield from interleave({lang: _stack_language(lang) for lang in CODE_LANGUAGES}, CODE_LANGUAGES)


def load_fineweb_hq():
    """FineWeb-Edu pages rated 4 or 5 (out of 5) for educational quality.

    The best ~10% of the web pages, used for the "anneal" set that is read
    while the learning rate fades at the end of training.
    """
    for text, score in _fineweb_rows():
        if score >= 4:
            yield text


def _fineweb_rows(name="sample-10BT"):
    from datasets import load_dataset
    ds = load_dataset("HuggingFaceFW/fineweb-edu", name=name, split="train", streaming=True)
    for row in ds:
        yield row["text"], row["int_score"]


def load_fineweb_hq_100bt():
    """Score 4-5 pages from the big slice: v3.5's anneal set needs ~1.2B tokens of them,
    more than the ~1B a 10B-token slice holds."""
    for text, score in _fineweb_rows("sample-100BT"):
        if score >= 4:
            yield text


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
    "fineweb_hq": load_fineweb_hq,
    "fineweb_100bt": load_fineweb_100bt,
    "fineweb_hq_100bt": load_fineweb_hq_100bt,
    "code_multi": load_code_multi,
    "tinystories": load_tinystories,
}


def sources_for(V, mix=None):
    """[(name, loader, share), ...] for a version, from its data_mix in config.py."""
    return [(name, LOADERS[name], share) for name, share in (mix or V.data_mix)]


# ------------------------------------------------------------------ decontamination
def _phrases(text):
    """Yield every 13-word phrase in `text` as a number.

    Words are lowercased letters/digits only, so punctuation and spacing
    differences don't matter. A stable hash (blake2b) is used because
    Python's built-in hash() differs between worker processes.
    """
    words = re.findall(r"[a-z0-9]+", text.lower())
    for i in range(len(words) - NGRAM + 1):
        digest = hashlib.blake2b(" ".join(words[i:i + NGRAM]).encode(), digest_size=8).digest()
        yield int.from_bytes(digest, "little")


def contains_test_question(text):
    """True if the document shares any 13-word phrase with a test question."""
    return any(h in TEST_NGRAMS for h in _phrases(text))


def load_test_ngrams():
    """Hashed 13-word phrases from HellaSwag and GSM8K (downloaded once, see benchmarks.py)."""
    from benchmarks import test_texts
    try:
        texts = test_texts()
    except Exception as e:
        raise SystemExit(f"could not download the test sets for decontamination ({e}).\n"
                         "Check your internet connection, or run with --no_decontam to skip this step.")
    ngrams = set()
    for t in texts:
        ngrams.update(_phrases(t))
    print(f"decontamination: {len(texts):,} test questions -> {len(ngrams):,} phrases to avoid")
    return ngrams


# ------------------------------------------------------------------ workers
def init_worker(tok_path, test_ngrams=None):
    """Runs once inside each worker process: load the tokenizer from disk."""
    global tok, EOT, TEST_NGRAMS
    tok = BPETokenizer.load(tok_path)
    EOT = tok.special["<|endoftext|>"]
    TEST_NGRAMS = test_ngrams


def encode_doc(text):
    """Encode one document and end it with <|endoftext|>.

    allow_special=False: web pages sometimes contain the literal text
    "<|endoftext|>"; it must NOT become the real control token.
    Returns [] (skip it) if the document contains a test question.
    """
    if TEST_NGRAMS and contains_test_question(text):
        return []
    return tok.encode(text.strip(), allow_special=False) + [EOT]


# ------------------------------------------------------------------ steps
def train_tokenizer(out_dir, sample_chars, sources, vocab_size, special_tokens=None):
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
    t.train_fast("\n".join(parts), vocab_size, special_tokens=list(special_tokens or []) or None)
    t.save(path)
    print(f"saved {path}")
    return path


def encode_source(name, loader, train_budget, val_budget, out_dir, tok_path, pool_size, batch_docs,
                  test_ngrams=None):
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
    prog = {"docs": 0, "train_bytes": 0, "val_bytes": 0, "skipped": 0}
    if os.path.exists(prog_path):
        try:
            with open(prog_path) as f:
                prog = json.load(f)
            print(f"{name}: resuming after {prog['docs']:,} documents")
        except (json.JSONDecodeError, KeyError, OSError):
            # Stopped (e.g. Ctrl+C) at the instant the file was being rewritten. Without it we don't know
            # how much of the .bin files is good, so this source starts again from its beginning.
            print(f"{name}: the progress file is damaged; starting this source again from the beginning")
            for path in (train_path, val_path):
                if os.path.exists(path):
                    os.remove(path)
            prog = {"docs": 0, "train_bytes": 0, "val_bytes": 0, "skipped": 0}

    # Open for appending, then cut off anything written after the last saved progress
    ftrain, fval = open(train_path, "ab"), open(val_path, "ab")
    ftrain.truncate(prog["train_bytes"]); fval.truncate(prog["val_bytes"])
    ftrain.seek(prog["train_bytes"]); fval.seek(prog["val_bytes"])
    n_train, n_val = prog["train_bytes"] // 2, prog["val_bytes"] // 2   # uint16 = 2 bytes per token

    docs = itertools.islice(loader(), prog["docs"], None)   # skip what we already did
    t0, start_tokens = time.time(), n_train + n_val
    prog.setdefault("skipped", 0)   # progress files from before decontamination existed
    with Pool(pool_size, initializer=init_worker, initargs=(tok_path, test_ngrams)) as pool:
        while n_train < train_budget:
            batch = list(itertools.islice(docs, batch_docs))
            if not batch:
                print(f"{name}: source ran out of text at {n_train:,} tokens")
                break
            for ids in pool.map(encode_doc, batch, chunksize=64):
                if not ids:
                    prog["skipped"] += 1           # contained a test question
                    continue
                arr = np.array(ids, dtype=np.uint16)
                if n_val < val_budget:
                    arr.tofile(fval); n_val += len(arr)
                elif n_train < train_budget:
                    arr.tofile(ftrain); n_train += len(arr)
            prog["docs"] += len(batch)
            ftrain.flush(); fval.flush()
            prog["train_bytes"], prog["val_bytes"] = ftrain.tell(), fval.tell()
            with open(prog_path + ".tmp", "w") as f:       # write a new file, then swap it in: never left half-written
                json.dump(prog, f)
            os.replace(prog_path + ".tmp", prog_path)
            rate = (n_train + n_val - start_tokens) / max(time.time() - t0, 1e-9)
            eta_h = max(0, train_budget - n_train) / max(rate, 1) / 3600
            print(f"  {name}: {n_train:,}/{train_budget:,} train tokens  "
                  f"({rate/1e3:.0f}k tokens/s, ~{eta_h:.1f}h left)")
    ftrain.close(); fval.close()
    open(done_path, "w").close()
    skipped = f", {prog['skipped']:,} documents skipped (test questions)" if prog["skipped"] else ""
    print(f"{name}: done ({n_train:,} train + {n_val:,} val tokens{skipped})")


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
    p.add_argument("--no_decontam", action="store_true", help="don't skip documents containing test questions")
    a = p.parse_args(argv)
    V = get_version(a.version)
    sources = sources_for(V)
    a.total_tokens = a.total_tokens or V.data_tokens
    a.sample_mb = a.sample_mb or V.tokenizer_sample_mb

    anneal_tokens = V.anneal_tokens
    out_dir = V.data_dir
    if a.test:
        out_dir = V.data_dir.rstrip("/") + "-test"
        a.total_tokens, a.val_tokens, a.sample_mb = 20_000_000, 1_000_000, 5
        anneal_tokens = 2_000_000 if V.anneal_mix else 0
    os.makedirs(out_dir, exist_ok=True)
    print(f"building {a.total_tokens:,} tokens into {out_dir}/ with {a.workers} CPU workers")

    test_ngrams = load_test_ngrams() if V.decontaminate and not a.no_decontam else None
    tok_path = train_tokenizer(out_dir, int(a.sample_mb * 1e6), sources, V.vocab_size, V.special_tokens)
    for name, loader, share in sources:
        encode_source(name, loader, int(a.total_tokens * share), int(a.val_tokens * share),
                      out_dir, tok_path, a.workers, a.batch_docs, test_ngrams)
    names = [name for name, _, _ in sources]
    join_files(out_dir, "val", names)
    join_files(out_dir, "train", names)

    if V.anneal_mix:
        # The "study the best material last" set: same tokenizer, its own folder
        anneal_dir = os.path.join(out_dir, "anneal")
        os.makedirs(anneal_dir, exist_ok=True)
        print(f"building the anneal set: {anneal_tokens:,} tokens into {anneal_dir}/")
        anneal_sources = sources_for(V, V.anneal_mix)
        for name, loader, share in anneal_sources:
            encode_source(name, loader, int(anneal_tokens * share), 0,
                          anneal_dir, tok_path, a.workers, a.batch_docs, test_ngrams)
            val_part = os.path.join(anneal_dir, f"{name}_val.bin")
            if os.path.exists(val_part):
                os.remove(val_part)           # the anneal set has no val split
        join_files(anneal_dir, "train", [name for name, _, _ in anneal_sources])
    print("all done!")


# The `if __name__ == "__main__"` guard is REQUIRED for multiprocessing on
# Windows: worker processes re-import this file, and must not re-run this part.
if __name__ == "__main__":
    main()
