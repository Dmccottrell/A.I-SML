"""
tokenizer.py - Byte-level BPE tokenizer, written from scratch.

Every piece of text is first turned into raw bytes (0-255), so ANY text can be
encoded. Training repeatedly finds the most common pair of adjacent tokens and
merges it into a new token, until the vocabulary reaches vocab_size.
"""
import json
from collections import Counter

import regex as re

# GPT-2 style pre-split: keeps words, numbers, punctuation and spaces apart so
# merges never glue "dog." together with "dog!" etc.
SPLIT_PATTERN = r"""'s|'t|'re|'ve|'m|'ll|'d| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)|\s+"""
SPECIAL_TOKENS = ["<|endoftext|>", "<|user|>", "<|assistant|>"]


def merge_ids(ids, pair, new_id):
    """Replace every occurrence of `pair` in ids with new_id."""
    out, i = [], 0
    while i < len(ids):
        if i < len(ids) - 1 and ids[i] == pair[0] and ids[i + 1] == pair[1]:
            out.append(new_id)
            i += 2
        else:
            out.append(ids[i])
            i += 1
    return out


class BPETokenizer:
    def __init__(self):
        self.merges = {}                                   # (id, id) -> new id, in rank order
        self.vocab = {i: bytes([i]) for i in range(256)}   # id -> bytes
        self.special = {}                                  # "<|x|>" -> id
        self.pattern = re.compile(SPLIT_PATTERN)
        self._cache = {}

    # ---------------------------------------------------------------- training
    def train(self, text, vocab_size, verbose=True):
        assert vocab_size > 256 + len(SPECIAL_TOKENS)
        num_merges = vocab_size - 256 - len(SPECIAL_TOKENS)

        # Count each distinct chunk once; this makes training much faster.
        chunk_counts = Counter(self.pattern.findall(text))
        chunks = [list(c.encode("utf-8")) for c in chunk_counts]
        freqs = list(chunk_counts.values())

        for m in range(num_merges):
            pair_counts = Counter()
            for ids, f in zip(chunks, freqs):
                for pair in zip(ids, ids[1:]):
                    pair_counts[pair] += f
            if not pair_counts:
                break
            best = max(pair_counts, key=pair_counts.get)
            new_id = 256 + m
            chunks = [merge_ids(ids, best, new_id) for ids in chunks]
            self.merges[best] = new_id
            self.vocab[new_id] = self.vocab[best[0]] + self.vocab[best[1]]
            if verbose and (m % 100 == 0 or m == num_merges - 1):
                print(f"merge {m+1}/{num_merges}: {self.vocab[new_id]!r} ({pair_counts[best]} uses)")

        next_id = 256 + len(self.merges)
        for i, tok in enumerate(SPECIAL_TOKENS):
            self.special[tok] = next_id + i
            self.vocab[next_id + i] = tok.encode("utf-8")
        self._cache = {}

    # ---------------------------------------------------------------- encoding
    def _encode_chunk(self, chunk):
        if chunk in self._cache:
            return self._cache[chunk]
        ids = list(chunk.encode("utf-8"))
        while len(ids) >= 2:
            # Apply the earliest-learned merge available (lowest rank first).
            pairs = set(zip(ids, ids[1:]))
            pair = min(pairs, key=lambda p: self.merges.get(p, float("inf")))
            if pair not in self.merges:
                break
            ids = merge_ids(ids, pair, self.merges[pair])
        self._cache[chunk] = ids
        return ids

    def encode(self, text, allow_special=True):
        ids = []
        if allow_special and self.special:
            special_re = "(" + "|".join(re.escape(s) for s in self.special) + ")"
            parts = re.split(special_re, text)
        else:
            parts = [text]
        for part in parts:
            if part in self.special:
                ids.append(self.special[part])
            elif part:
                for chunk in self.pattern.findall(part):
                    ids.extend(self._encode_chunk(chunk))
        return ids

    def decode(self, ids):
        data = b"".join(self.vocab.get(i, b"") for i in ids)
        return data.decode("utf-8", errors="replace")

    @property
    def vocab_size(self):
        return len(self.vocab)

    # ---------------------------------------------------------------- save/load
    def save(self, path):
        with open(path, "w") as f:
            json.dump({
                "merges": [[a, b, n] for (a, b), n in self.merges.items()],
                "special": self.special,
            }, f)

    @classmethod
    def load(cls, path):
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
    # Quick self-test
    tok = BPETokenizer()
    sample = "The printer is jammed. The printer is offline. The scanner is fine. " * 50
    tok.train(sample, vocab_size=300, verbose=False)
    ids = tok.encode("The printer is jammed!<|endoftext|>")
    print(ids)
    print(tok.decode(ids))
    assert tok.decode(tok.encode("héllo wörld 123")) == "héllo wörld 123"
    print("tokenizer OK")
