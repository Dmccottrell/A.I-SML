"""
chat_polish.py - How a reply feels: the thinking label, the three-second pause, smooth word-by-word writing, and
automatic shortening of a long chat (docs/APP_SPEC.md, "How a reply feels").

WHAT THIS FILE DOES
    thinking_word(n)        the label shown while Yuvra thinks ("Thinking", "Pondering", ...): a different word every few
                            seconds, never the same twice in a row. The small logo animates next to it (the screen's job).
    paced(pieces, ...)      wraps the model's stream of text pieces:
                              1. the first word never appears sooner than `min_first_s` (3 seconds) after sending, so even
                                 the quickest answer shows the thinking state first, like other AI chats;
                              2. text that arrives in a burst (or all at once) is released a few characters at a time at a
                                 steady speed, so it is written out cleanly; if it falls too far behind it speeds up, so
                                 the screen never lags more than `max_lag_s` behind the model.
    compact_chat(...)       when the chat fills the model's memory (80% by default), the older messages are replaced by a
                            short summary (the last few messages stay word for word). The messages stay visible on screen,
                            marked "summarized"; only what the model reads changes.
"""
import re
import time

import chat

THINKING_WORDS = ("Thinking", "Pondering", "Reasoning", "Working it out", "Considering", "Mulling it over",
                  "Figuring it out", "Reflecting", "Weighing it up", "Putting it together")
THINKING_SWITCH_S = 2.2
MIN_FIRST_S = 3.0
RATE_CPS = 90.0                 # characters per second when text arrives faster than this (about 22 words a second)
MAX_LAG_S = 1.5


def thinking_word(n):
    """The n-th label (0, 1, 2, ...): cycles through the list, so two in a row are never the same."""
    return THINKING_WORDS[n % len(THINKING_WORDS)]


def thinking_index(elapsed_s):
    """Which label to show after `elapsed_s` seconds of thinking."""
    return int(max(0.0, elapsed_s) // THINKING_SWITCH_S)


_BITS = re.compile(r"\S+\s*|\s+")


def _bits(text):
    """Split into words (with their trailing space), and long words into chunks of at most 12 characters."""
    for m in _BITS.findall(text):
        for i in range(0, len(m), 12):
            yield m[i:i + 12]


def paced(pieces, min_first_s=MIN_FIRST_S, rate_cps=RATE_CPS, max_lag_s=MAX_LAG_S, clock=time.monotonic,
          sleep=time.sleep, start=None):
    """Yield the same text as `pieces`, but not before `min_first_s` after `start` (default: now) and no faster than
    `rate_cps`, unless that would put the screen more than `max_lag_s` behind (then it catches up)."""
    start = clock() if start is None else start
    due = None                                          # when the next bit may appear
    try:
        for piece in pieces:
            bits = list(_bits(piece))
            left = len(piece)                           # what is still waiting to be shown from this piece
            for bit in bits:
                now = clock()
                if due is None:
                    due = start + min_first_s
                wait = due - now
                if wait > 0:
                    sleep(wait)
                    now = due
                yield bit
                left -= len(bit)
                rate = max(rate_cps, left / max_lag_s)  # a big piece that is already here: catch up, never lag far behind
                due = max(due, now) + len(bit) / rate
    finally:
        close = getattr(pieces, "close", None)
        if close:
            close()


# ------------------------------------------------------------------ shortening a long chat
SUMMARY_MARK = "[Earlier in this chat, shortened to save room]"


def _clip(text, n):
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def extractive_summary(messages, max_chars=1200):
    """A short list of what was asked and answered, no model needed. An earlier summary is carried forward."""
    lines = []
    for m in messages:
        if m.get("status") == "summary":
            lines += [l for l in m["content"].split("\n")[1:] if l.strip()]
        elif m["role"] == "user":
            lines.append("- You asked: " + _clip(m["content"], 90))
        elif m["content"].strip():
            lines.append("  Answer: " + _clip(m["content"], 110))
    while sum(len(l) + 1 for l in lines) > max_chars and len(lines) > 2:
        lines.pop(0)                                    # the oldest goes first
    return SUMMARY_MARK + "\n" + "\n".join(lines)


def compact_chat(tok, store, chat_id, window, max_new, keep=4, trigger=0.8, summarize=None, keep_notes=1):
    """If the chat fills more than `trigger` of the room for the prompt, replace the older messages with a summary.
    `summarize(messages) -> text` may use the model; if it fails or returns nothing, the extractive summary is used.
    Returns how many messages were folded into the summary (0 = nothing to do)."""
    msgs = [m for m in store.messages(chat_id) if m["status"] != "compacted"]
    if len(msgs) <= keep + 1:
        return 0
    history = [{"role": m["role"], "content": m["content"]} for m in msgs if m["content"]]
    r = chat.context_report(tok, history, window, reserve=max_new, keep_notes=keep_notes)
    if r["used"] + r["forgotten"] <= trigger * r["limit"]:
        return 0
    old = msgs[:-keep]
    while old and old[-1]["role"] == "user":            # never leave a question without its answer in the kept part
        old.pop()
    if len(old) < 2:
        return 0
    text = None
    if summarize:
        try:
            text = (summarize(old) or "").strip()
        except Exception:
            text = None
        if text and not text.startswith(SUMMARY_MARK):
            text = SUMMARY_MARK + "\n" + text
    text = text or extractive_summary(old)
    store.fold(chat_id, [m["id"] for m in old], text)
    return len(old)
