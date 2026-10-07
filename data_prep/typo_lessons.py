"""
typo_lessons.py - Chat lessons for messy typing (used by make_chat_data_v3.py).

WHAT THIS FILE DOES
    People type fast: "waht is the captial of illinois", "whats up", "pls explain photosynthsis". A small model that
    only saw clean questions can answer a messy one badly. These lessons take ordinary lessons (everyday chat,
    lookups, instructions, topic switches, ...) and copy them with the USER's message typed messily. The answer stays
    exactly the clean answer, so the model learns "a slip in spelling is not a different question".

    Kinds of mess (a few per message, chosen at random):
      * keyboard slips (a neighbouring key), a dropped letter, a doubled letter, two letters swapped
      * all lowercase, no apostrophes, no ending punctuation
      * text-speak ("u", "r", "pls", "bc", "thx")
    Never touched: numbers (so "List 3 things" stays 3), words in code/backticks, very short words, the looked-up
    notes, and the assistant's answer. Everything is made by our own code; no other AI writes it.

    Limit: lessons teach the MODEL to read a typo. The Wikipedia lookup (wiki_index.py) still searches by the typed
    words, so a badly misspelled key word may not find its article (fuzzy matching there is a separate job).
"""
import random
import re

KEYS = ["qwertyuiop", "asdfghjkl", "zxcvbnm"]
NEIGHBOURS = {}
for row, line in enumerate(KEYS):
    for i, ch in enumerate(line):
        near = set()
        if i > 0:
            near.add(line[i - 1])
        if i < len(line) - 1:
            near.add(line[i + 1])
        for other in (KEYS[row - 1:row] + KEYS[row + 1:row + 2]):
            near.update(other[max(0, i - 1):i + 1])
        NEIGHBOURS[ch] = sorted(near)

TEXT_SPEAK = {"you": "u", "are": "r", "please": "pls", "because": "bc", "thanks": "thx", "why": "y", "your": "ur",
              "people": "ppl", "before": "b4", "okay": "ok", "about": "abt", "with": "w", "tomorrow": "tmrw"}
WORD = re.compile(r"[A-Za-z']+")


def _protected_spans(text):
    spans = [m.span() for m in re.finditer(r"`[^`]*`|\S*\d\S*", text)]
    return spans


def _in(spans, pos):
    return any(a <= pos < b for a, b in spans)


def slip(word, rng):
    """One spelling slip inside a word of 4+ letters."""
    i = rng.randrange(1, len(word) - 1)
    kind = rng.choice(("neighbour", "drop", "double", "swap"))
    c = word[i].lower()
    if kind == "neighbour" and c in NEIGHBOURS:
        new = rng.choice(NEIGHBOURS[c])
        return word[:i] + (new.upper() if word[i].isupper() else new) + word[i + 1:]
    if kind == "drop":
        return word[:i] + word[i + 1:]
    if kind == "double":
        return word[:i] + word[i] + word[i:]
    if word[i] != word[i + 1]:
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    return word[:i] + word[i] + word[i:]


def messy(text, rng, slips=None):
    """The same message typed carelessly. Always returns non-empty text; returns the text unchanged if it
    has nothing safe to change (code, numbers only, very short)."""
    if "```" in text:
        return text
    spans = _protected_spans(text)
    words = [m for m in WORD.finditer(text) if len(m.group()) >= 4 and not _in(spans, m.start())]
    out = text
    slips = rng.choice((1, 1, 2, 3)) if slips is None else slips
    for m in sorted(rng.sample(words, min(slips, len(words))), key=lambda m: -m.start()):
        out = out[:m.start()] + slip(m.group(), rng) + out[m.end():]
    if rng.random() < 0.5:
        out = out.lower()
    if rng.random() < 0.5:
        out = out.replace("'", "").rstrip("?!.")
    if rng.random() < 0.25:
        out = re.sub(r"\b(" + "|".join(TEXT_SPEAK) + r")\b", lambda m: TEXT_SPEAK[m.group().lower()], out, flags=re.I)
    return out if out.strip() else text


TYPO_KINDS = {"general", "topic_switch", "lookup", "dont_know", "correction", "stand_firm", "instruction", "unknowable",
              "identity", "web", "web_latest", "web_none", "other_ai"}


def typo_copies(examples, rng, share=0.12, kinds=TYPO_KINDS):
    """Messy copies of some examples: [{"messages": ..., "kind": "typo"}]. Only the user's own words change (the
    looked-up notes, tool markers and the assistant's answers stay clean)."""
    out = []
    for ex in examples:
        if kinds and ex["kind"] not in kinds or rng.random() > share:
            continue
        changed, convo = False, []
        for m in ex["messages"]:
            if m["role"] == "user" and not m.get("tools") and rng.random() < 0.8:
                new = messy(m["content"], rng)
                changed |= new != m["content"]
                convo.append({**m, "content": new})
            else:
                convo.append(dict(m))
        if changed:
            out.append({"messages": convo, "kind": "typo"})
    return out
