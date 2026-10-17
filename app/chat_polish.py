"""
chat_polish.py - How a reply feels: the thinking label, the message-sized thinking pause, smooth word-by-word writing, and
automatic shortening of a long chat (docs/APP_SPEC.md, "How a reply feels").

WHAT THIS FILE DOES
    thinking_word(n)        the label shown while Emvryx thinks ("Thinking", "Pondering", ...): a different word every few
                            seconds, never the same twice in a row. The small logo animates next to it (the screen's job).
    paced(pieces, ...)      wraps the model's stream of text pieces:
                              1. the first word never appears sooner than `min_first_s` after sending (chosen from the message by `pause_for`:
                                 about half a second for a greeting, up to ~3 seconds for a hard question), so even
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
MIN_FIRST_S = 1.5               # the pause for a normal message (Balanced, short): the others scale from it
PAUSE_BASE = {"quick": 0.5, "balanced": 1.2, "deep": 2.4}   # seconds before the first word, by how hard the question is
PAUSE_MAX = 3.2
PAUSE_SCALE = {"off": 0.0, "short": 0.4, "natural": 1.0}   # the person's setting: how much of that pause to keep (the models answer fast now)
RATE_CPS = 90.0                 # characters per second when text arrives faster than this (about 22 words a second)
MAX_LAG_S = 1.5


def pause_for(text, effort="balanced"):
    """How long to show the thinking state before the first word: it depends on the message, so a greeting is answered
    almost at once and a hard question gets a longer, more thoughtful pause. Quick 0.5 s, Balanced 1.2 s, Deep 2.4 s, plus a
    little for a long message (0.1 s per 20 words, up to 0.8 s), never more than 3.2 s. It is a minimum: a model that is
    slower than this is never made to wait longer."""
    base = PAUSE_BASE.get(effort, PAUSE_BASE["balanced"])
    words = len((text or "").split())
    return round(min(PAUSE_MAX, base + min(0.8, words // 20 * 0.1)), 1)


FOLLOW_REF = re.compile(r"\b(it|that|this|those|these|them|same|above|previous|again|instead|too|also|one)\b", re.I)
FOLLOW_START = re.compile(r"^(now|then|and|also|but|ok(ay)?|and then|make|change|use|write|do|try|show|give|translate|convert|add|remove|shorter|longer|simpler|more|less|in |with |without )", re.I)
FOLLOW_HINT = ("[This message follows on from your last reply in this chat. Do what it asks with that reply, or with what that reply was about. "
               "Do not go back to earlier topics and do not start something new.]")


def is_repeat(new_reply, old_reply, threshold=0.9):
    """True when the new reply is (nearly) a copy of the one before it: a small model answering its own last message again."""
    a, b = " ".join(str(new_reply or "").lower().split()), " ".join(str(old_reply or "").lower().split())
    if len(a) < 40 or len(b) < 40:
        return False
    if a == b or a in b or b in a:
        return True
    import difflib
    return difflib.SequenceMatcher(None, a[:1500], b[:1500]).ratio() >= threshold


def repeat_hint(text):
    return (f'[Your last reply was a copy of the one before it. Do not repeat it. Answer only this new message from the person, with new content: "{" ".join(str(text or "").split())[:300]}"]')


def last_question(reply):
    """The last question the assistant asked at the end of its reply ("Quick check: What is 6 x 5?"), or ''."""
    for line in reversed(str(reply or "")[-700:].splitlines()):
        line = line.strip()
        if "?" in line:
            q = line[line.rfind("Quick check:") + len("Quick check:"):].strip() if "Quick check:" in line else line
            return q[:200]
    return ""


REQUEST = re.compile(r"^(please|can|could|would|will|give|make|write|create|generate|list|show|tell|explain|teach|help|let|now|next|more|another|again|repeat|start|stop|quiz|"
                     r"what|who|when|where|why|how|which|do|does|is|are|i (want|need|would like)|i'?d like|try|use|change|add|remove|translate|convert|continue|go on)\b", re.I)


def answer_hint(text, last_reply, max_words=8):
    """A note for the model when a short message ("30", "yes", "B", "x = 4") is the answer to the question it just asked. On its own such a message names no
    subject, and a small model can answer its own last reply again instead of checking the answer. Shown to the model only, never saved."""
    t = " ".join(str(text or "").split())
    if not t or len(t.split()) > max_words or t.endswith("?") or REQUEST.match(t):          # "give me 15 questions" is a request, not an answer
        return ""
    q = last_question(last_reply)
    if not q:
        return ""
    return (f'[This message is the person\'s ANSWER to your last question: "{q}". Say clearly whether the answer is right or wrong, and if it is wrong explain the mistake kindly. '
            "Then go on to the next step or ask one new question. Do not repeat your last reply.]")


def follow_up_hint(text, has_reply, max_words=10):
    """A short note for the model when a message is a short follow-up ("write it in java", "make it shorter", "now in Spanish"): on its own it names no
    subject, and a model tuned on one-question chats may answer an older message instead of the one just before. Shown to the model only, never saved."""
    words = str(text or "").split()
    if not has_reply or not words or len(words) > max_words:
        return ""
    if FOLLOW_REF.search(text) or FOLLOW_START.match(text.strip()):
        return FOLLOW_HINT
    return ""


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


COMPACT_SHARE = 0.75        # a chat is shortened at 75% of the room for the prompt...
COMPACT_CAP = 96_000        # ...or at 96K tokens, whichever comes first: past ~100K these models reason less sharply and every re-read is slow


def compact_point(window, max_new, share=COMPACT_SHARE, cap=COMPACT_CAP):
    """The number of tokens at which a chat gets shortened (the memory meter shows it too)."""
    return int(min(share * max(64, window - max_new), cap))


def compact_chat(tok, store, chat_id, window, max_new, keep=4, trigger=COMPACT_SHARE, summarize=None, keep_notes=1, on_start=None, cap=COMPACT_CAP, force=False):
    """If the chat fills more than `trigger` of the room for the prompt (or `cap` tokens), replace the older messages with a summary.
    `force=True` (the "Compact now" button) shortens it whatever its size, as long as there is something old enough to fold.
    `summarize(messages) -> text` may use the model; if it fails or returns nothing, the extractive summary is used.
    `on_start()` is called just before the folding starts (the page shows "Summarizing earlier messages" while it runs).
    Returns how many messages were folded into the summary (0 = nothing to do)."""
    msgs = [m for m in store.messages(chat_id) if m["status"] != "compacted"]
    if len(msgs) <= keep + 1:
        return 0
    history = [{"role": m["role"], "content": m["content"]} for m in msgs if m["content"]]
    r = chat.context_report(tok, history, window, reserve=max_new, keep_notes=keep_notes)
    if not force and r["used"] + r["forgotten"] <= compact_point(window, max_new, trigger, cap):
        return 0
    old = msgs[:-keep]
    while old and old[-1]["role"] == "user":            # never leave a question without its answer in the kept part
        old.pop()
    if len(old) < 2:
        return 0
    if on_start:
        on_start()
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
