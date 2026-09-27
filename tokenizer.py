"""
tokenizer.py - Byte-level BPE tokenizer, written from scratch.

WHAT THIS FILE DOES
    A neural network can only work with numbers, so before the model sees any
    text we must turn that text into a list of integers ("token IDs"). This
    file does that conversion in both directions:

        encode("The cat sat.")  ->  [464, 3797, 3332, 13]
        decode([464, 3797, 3332, 13])  ->  "The cat sat."

HOW IT WORKS (Byte Pair Encoding, "BPE")
    1. Every string is first turned into raw UTF-8 bytes (numbers 0-255).
       Because of this, ANY text (emoji, accents, code) can be encoded.
    2. Training looks for the most common pair of neighbouring tokens,
       e.g. 't' + 'h', and creates a brand-new token 'th' for it.
    3. That repeats thousands of times. Common words end up as one token,
       rare words are built from smaller pieces.

USED BY
    prepare_data.py (trains + saves it), train.py, generate.py, finetune.py,
    export_hf.py (all load it from data/tokenizer.json).

Run `python tokenizer.py` for a quick self-test that prints "tokenizer OK".
"""
import heapq
import json
from collections import Counter, defaultdict

import regex as re   # the third-party "regex" module; it supports \p{L} (any letter)

# GPT-2 style pre-split. Before merging, text is chopped into chunks such as
# words, numbers, punctuation and whitespace. Merges only happen INSIDE a
# chunk, so "dog." and "dog!" both reuse the same " dog" token.
#   's|'t|'re...     common English contractions
#    ?\p{L}+         a word (optionally with its leading space)
#    ?\p{N}+         a number
#    ?[^\s\p{L}\p{N}]+  punctuation / symbols
#   \s+(?!\S)|\s+    runs of whitespace
SPLIT_PATTERN = r"""'s|'t|'re|'ve|'m|'ll|'d| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)|\s+"""

# Special tokens get their own single ID and are never split into bytes.
#   <|endoftext|>  marks the end of a story / answer (the model learns to stop)
#   <|user|>       marks the start of a user message (chat fine-tuning)
#   <|assistant|>  marks the start of the AI's reply (chat fine-tuning)
SPECIAL_TOKENS = ["<|endoftext|>", "<|user|>", "<|assistant|>"]

# v3+ also reserve tokens for planned features, so the tokenizer never has to
# change later (changing it would mean retraining the model from scratch):
#   <|system|>                          instructions ("You are a study helper", v4)
#   <|notes|> ... <|end_notes|>         looked-up Wikipedia passages (v3 lookups)
#   <|tool_call|> ... <|end_tool_call|> the model asking for a tool (v4)
#   <|tool_result|> ... <|end_tool_result|>  what the tool answered (v4)
#   <|reserved_0|> ... <|reserved_19|>  spare slots for features not planned yet
EXTENDED_SPECIAL_TOKENS = SPECIAL_TOKENS + [
    "<|system|>", "<|notes|>", "<|end_notes|>",
    "<|tool_call|>", "<|end_tool_call|>", "<|tool_result|>", "<|end_tool_result|>",
] + [f"<|reserved_{i}|>" for i in range(20)]


def merge_ids(ids, pair, new_id):
    """Replace every occurrence of `pair` in `ids` with `new_id`.

    This is the core operation of BPE.

    Example:
        merge_ids([116, 104, 101, 116, 104], pair=(116, 104), new_id=300)
        -> [300, 101, 300]          # "t"+"h" became the single token 300

    Args:
        ids:    list of token IDs
        pair:   tuple of two IDs to look for, side by side
        new_id: the ID that replaces each matched pair
    Returns:
        a new list (the input list is not modified)
    """
    out, i = [], 0
    while i < len(ids):
        # If the pair starts here, emit the new token and skip both items
        if i < len(ids) - 1 and ids[i] == pair[0] and ids[i + 1] == pair[1]:
            out.append(new_id)
            i += 2
        else:
            out.append(ids[i])
            i += 1
    return out


class BPETokenizer:
    """Turns text into token IDs (encode) and back into text (decode).

    Typical use:
        tok = BPETokenizer()
        tok.train(big_text, vocab_size=8192)   # learn the vocabulary once
        tok.save("data/tokenizer.json")

        tok = BPETokenizer.load("data/tokenizer.json")   # later, anywhere
        ids = tok.encode("Hello there")
        text = tok.decode(ids)
    """

    def __init__(self):
        """Create an EMPTY tokenizer that only knows the 256 raw bytes.

        Attributes:
            merges:  learned rules {(id_a, id_b): new_id}. Python dicts keep
                     insertion order, so this is also the order they were learned.
            vocab:   {id: bytes} - what each token ID actually spells.
                     IDs 0-255 are single bytes; learned tokens come after.
            special: {"<|endoftext|>": id, ...} for the special tokens.
            pattern: compiled SPLIT_PATTERN regex used to chunk text.
            _cache:  {chunk_text: [ids]} so repeated words are only encoded once.
                     Cleared when it reaches max_cache entries, so encoding
                     billions of tokens of web text can't use up all your RAM.
        """
        self.merges = {}                                   # (id, id) -> new id, in rank order
        self.vocab = {i: bytes([i]) for i in range(256)}   # id -> bytes
        self.special = {}                                  # "<|x|>" -> id
        self.pattern = re.compile(SPLIT_PATTERN)
        self._cache = {}
        self.max_cache = 500_000

    # ---------------------------------------------------------------- training
    def train(self, text, vocab_size, verbose=True, special_tokens=None):
        """Learn merges from `text` until the vocabulary has `vocab_size` tokens.

        Steps:
            1. Split text into chunks and count how often each distinct chunk
               appears. ("the" appearing 50,000 times is stored once with a
               count of 50,000 - this is the big speed trick.)
            2. Repeat num_merges times:
                 a. count every neighbouring pair across all chunks
                 b. pick the most frequent pair
                 c. give it a new ID and merge it everywhere
            3. Add the special tokens at the very end of the vocabulary.

        Args:
            text:       training text (one big string)
            vocab_size: final number of tokens, including 256 bytes + specials
            verbose:    print progress every 100 merges
            special_tokens: list of special tokens (default: SPECIAL_TOKENS)
        """
        special_tokens = special_tokens or SPECIAL_TOKENS
        assert vocab_size > 256 + len(special_tokens)
        num_merges = vocab_size - 256 - len(special_tokens)

        # Count each distinct chunk once; this makes training much faster.
        chunk_counts = Counter(self.pattern.findall(text))
        chunks = [list(c.encode("utf-8")) for c in chunk_counts]   # each chunk as byte IDs
        freqs = list(chunk_counts.values())                        # how often each chunk appears

        for m in range(num_merges):
            # a. Count neighbouring pairs, weighted by how often the chunk appears
            pair_counts = Counter()
            for ids, f in zip(chunks, freqs):
                for pair in zip(ids, ids[1:]):
                    pair_counts[pair] += f
            if not pair_counts:
                break                      # nothing left to merge (tiny training text)

            # b. The most frequent pair becomes a new token
            best = max(pair_counts, key=pair_counts.get)
            new_id = 256 + m

            # c. Apply the merge everywhere and record it
            chunks = [merge_ids(ids, best, new_id) for ids in chunks]
            self.merges[best] = new_id
            self.vocab[new_id] = self.vocab[best[0]] + self.vocab[best[1]]
            if verbose and (m % 100 == 0 or m == num_merges - 1):
                print(f"merge {m+1}/{num_merges}: {self.vocab[new_id]!r} ({pair_counts[best]} uses)")

        # Special tokens take the IDs right after the last learned merge
        next_id = 256 + len(self.merges)
        for i, tok in enumerate(special_tokens):
            self.special[tok] = next_id + i
            self.vocab[next_id + i] = tok.encode("utf-8")
        self._cache = {}

    def train_fast(self, text, vocab_size, verbose=True, special_tokens=None):
        """Same result as train(), but fast enough for large, varied text (v2+).

        train() recounts EVERY pair after EVERY merge. That's fine for simple
        children's stories, but web text has hundreds of thousands of distinct
        words, and recounting them 16,000 times would take days.

        train_fast() keeps the counts up to date instead:
            * pair_counts: {pair: how often it appears}, built once
            * where:       {pair: set of chunks that contain it}
            * heap:        finds the most frequent pair quickly
        After a merge, only the chunks that contained the merged pair are
        updated. Each merge touches a few chunks instead of all of them.

        When several pairs tie for most frequent, the smallest pair wins
        (train() picks the first one it counted), so on ties the two methods
        can choose differently. Both produce a valid tokenizer.

        special_tokens: list of special tokens (default: SPECIAL_TOKENS)
        """
        special_tokens = special_tokens or SPECIAL_TOKENS
        assert vocab_size > 256 + len(special_tokens)
        num_merges = vocab_size - 256 - len(special_tokens)

        chunk_counts = Counter(self.pattern.findall(text))
        chunks = [list(c.encode("utf-8")) for c in chunk_counts]
        freqs = list(chunk_counts.values())
        if verbose:
            print(f"{len(chunks):,} distinct chunks")

        # Count every pair once, and remember which chunks contain it
        pair_counts = Counter()
        where = defaultdict(set)
        for ci, (ids, f) in enumerate(zip(chunks, freqs)):
            for pair in zip(ids, ids[1:]):
                pair_counts[pair] += f
                where[pair].add(ci)
        # Max-heap via negative counts. Entries go stale when counts change;
        # a stale entry is skipped when popped (its count no longer matches).
        heap = [(-c, p) for p, c in pair_counts.items()]
        heapq.heapify(heap)

        for m in range(num_merges):
            # Pop until we find an entry whose count is still current
            while heap:
                neg, best = heapq.heappop(heap)
                if pair_counts.get(best, 0) == -neg and -neg > 0:
                    break
            else:
                break                      # nothing left to merge
            count = -neg
            new_id = 256 + m
            touched = set()                # pairs whose count changed
            for ci in list(where[best]):
                ids, f = chunks[ci], freqs[ci]
                # Remove this chunk's old pairs, merge, then add its new pairs
                for pair in zip(ids, ids[1:]):
                    pair_counts[pair] -= f
                    touched.add(pair)
                    where[pair].discard(ci)
                ids = merge_ids(ids, best, new_id)
                chunks[ci] = ids
                for pair in zip(ids, ids[1:]):
                    pair_counts[pair] += f
                    touched.add(pair)
                    where[pair].add(ci)
            for pair in touched:
                c = pair_counts[pair]
                if c > 0:
                    heapq.heappush(heap, (-c, pair))
                else:
                    del pair_counts[pair]
            del where[best]

            self.merges[best] = new_id
            self.vocab[new_id] = self.vocab[best[0]] + self.vocab[best[1]]
            if verbose and (m % 500 == 0 or m == num_merges - 1):
                print(f"merge {m+1}/{num_merges}: {self.vocab[new_id]!r} ({count} uses)")

        next_id = 256 + len(self.merges)
        for i, tok in enumerate(special_tokens):
            self.special[tok] = next_id + i
            self.vocab[next_id + i] = tok.encode("utf-8")
        self._cache = {}

    # ---------------------------------------------------------------- encoding
    def _encode_chunk(self, chunk):
        """Encode ONE chunk (usually one word) into token IDs.

        Starts from raw bytes and keeps applying the EARLIEST-learned merge
        that is possible, until no learned merge applies. Using the same order
        as training guarantees we reproduce the same splits training produced.

        Example (if these merges were learned):
            " cat" -> [32, 99, 97, 116] -> [32, 99, 301] -> [415] (" cat")
        """
        if chunk in self._cache:
            return self._cache[chunk]
        ids = list(chunk.encode("utf-8"))
        while len(ids) >= 2:
            # Apply the earliest-learned merge available (lowest rank first).
            pairs = set(zip(ids, ids[1:]))
            pair = min(pairs, key=lambda p: self.merges.get(p, float("inf")))
            if pair not in self.merges:
                break                      # no learned merge applies anymore
            ids = merge_ids(ids, pair, self.merges[pair])
        if len(self._cache) >= self.max_cache:
            self._cache.clear()            # keep memory bounded on huge datasets
        self._cache[chunk] = ids
        return ids

    def encode(self, text, allow_special=True):
        """Convert text into a list of token IDs.

        Args:
            text:          any string
            allow_special: if True, strings like "<|endoftext|>" in the text
                           become their single special ID. finetune.py passes
                           False for user-written text, so a user typing
                           "<|endoftext|>" cannot inject a real control token.
        Returns:
            list[int]

        Example:
            tok.encode("Hi!<|endoftext|>")  ->  [...ids for "Hi!"..., 8189]
        """
        ids = []
        if allow_special and self.special:
            # Split around special tokens, keeping them (the "( )" capture group)
            special_re = "(" + "|".join(re.escape(s) for s in self.special) + ")"
            parts = re.split(special_re, text)
        else:
            parts = [text]
        for part in parts:
            if part in self.special:
                ids.append(self.special[part])           # special token -> one ID
            elif part:
                for chunk in self.pattern.findall(part):  # normal text -> chunks -> IDs
                    ids.extend(self._encode_chunk(chunk))
        return ids

    def decode(self, ids):
        """Convert token IDs back into text.

        Joins the bytes of every token, then decodes as UTF-8.
        errors="replace" means a half-finished character (e.g. the model
        generated only part of an emoji) shows as '�' instead of crashing.
        """
        data = b"".join(self.vocab.get(i, b"") for i in ids)
        return data.decode("utf-8", errors="replace")

    @property
    def vocab_size(self):
        """Total number of tokens (bytes + learned merges + specials), e.g. 8192.

        train.py uses this to size the model's embedding table.
        """
        return len(self.vocab)

    # ---------------------------------------------------------------- save/load
    def save(self, path):
        """Write the tokenizer to a JSON file.

        Only the merges and special tokens are saved; `vocab` can be rebuilt
        from them, so the file stays small.
        """
        with open(path, "w") as f:
            json.dump({
                "merges": [[a, b, n] for (a, b), n in self.merges.items()],
                "special": self.special,
            }, f)

    @classmethod
    def load(cls, path):
        """Create a tokenizer from a JSON file written by save().

        Rebuilds `vocab` by replaying the merges in the order they were learned.

        Usage:
            tok = BPETokenizer.load("data/tokenizer.json")
        """
        tok = cls()
        with open(path) as f:
            data = json.load(f)
        for a, b, n in data["merges"]:
            tok.merges[(a, b)] = n
            tok.vocab[n] = tok.vocab[a] + tok.vocab[b]
        tok.special = data["special"]
        for s, i in tok.special.items():
            tok.vocab[i] = s.encode("utf-8")
        return tok


if __name__ == "__main__":
    # Quick self-test: train a tiny tokenizer, then check that
    # decode(encode(text)) gives back exactly the original text.
    tok = BPETokenizer()
    sample = "The printer is jammed. The printer is offline. The scanner is fine. " * 50
    tok.train(sample, vocab_size=300, verbose=False)
    ids = tok.encode("The printer is jammed!<|endoftext|>")
    print(ids)
    print(tok.decode(ids))
    assert tok.decode(tok.encode("héllo wörld 123")) == "héllo wörld 123"
    print("tokenizer OK")
