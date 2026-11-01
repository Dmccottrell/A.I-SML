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
# Where it fits: the chat server calls these helpers around each model reply (the pause, the typing speed, the chat title,
# hints for the model, and shortening a long chat). None of them train or change the model.
import re      # regular expressions ("regex"): text patterns used to recognise kinds of messages
import time

import chat    # the core chat module (core/chat.py); here it is used only to count tokens (see compact_chat)

# The labels shown in turn while the model is thinking.
THINKING_WORDS = ("Thinking", "Pondering", "Reasoning", "Working it out", "Considering", "Mulling it over",
                  "Figuring it out", "Reflecting", "Weighing it up", "Putting it together")
THINKING_SWITCH_S = 2.2         # the label changes to the next one after this many seconds
MIN_FIRST_S = 1.5               # the pause for a normal message (Balanced, short): the others scale from it
PAUSE_BASE = {"quick": 0.5, "balanced": 1.2, "deep": 2.4}   # seconds before the first word, by how hard the question is
PAUSE_MAX = 3.2                 # the pause is never longer than this many seconds
PAUSE_SCALE = {"off": 0.0, "short": 0.4, "natural": 1.0}   # the person's setting: how much of that pause to keep (the models answer fast now)
RATE_CPS = 90.0                 # characters per second when text arrives faster than this (about 22 words a second)
MAX_LAG_S = 1.5                 # the text on screen is never allowed to be more than this many seconds behind the model
FAST_PIECE_S = 0.02             # paced(adaptive=True): a piece that took less than this to arrive was already waiting
FIXES_PAUSE_MAX = 0.6           # chat_fixes: the longest staged pause before the first word (a model that is slower is never made to wait longer)


def pause_for(text, effort="balanced"):
    """How long to show the thinking state before the first word: it depends on the message, so a greeting is answered
    almost at once and a hard question gets a longer, more thoughtful pause. Quick 0.5 s, Balanced 1.2 s, Deep 2.4 s, plus a
    little for a long message (0.1 s per 20 words, up to 0.8 s), never more than 3.2 s. It is a minimum: a model that is
    slower than this is never made to wait longer.

    text: the person's message. effort: "quick", "balanced" or "deep" (anything else counts as "balanced").
    Returns seconds as a number with one decimal.
    """
    # .get with a default: an unknown effort name falls back to the balanced value instead of crashing.
    base = PAUSE_BASE.get(effort, PAUSE_BASE["balanced"])
    words = len((text or "").split())
    # words // 20 counts whole groups of 20 words; each group adds 0.1 s, capped at 0.8 s; the total is capped at PAUSE_MAX.
    return round(min(PAUSE_MAX, base + min(0.8, words // 20 * 0.1)), 1)


# Patterns that spot a short message which depends on the previous reply ("make it shorter", "now in Spanish").
# re.I = ignore capital letters; \b = a word edge, so "it" does not match inside "city".
# FOLLOW_REF: contains a pointing word such as it / that / this / again.
FOLLOW_REF = re.compile(r"\b(it|that|this|those|these|them|same|above|previous|again|instead|too|also|one)\b", re.I)
# FOLLOW_START: begins with a word that usually starts an edit request ("now", "make", "translate", "in ", ...).
FOLLOW_START = re.compile(r"^(now|then|and|also|but|ok(ay)?|and then|make|change|use|write|do|try|show|give|translate|convert|add|remove|shorter|longer|simpler|more|less|in |with |without )", re.I)
# The note that is added (for the model only) when a message looks like a follow-up.
FOLLOW_HINT = ("[This message follows on from your last reply in this chat. Do what it asks with that reply, or with what that reply was about. "
               "Do not go back to earlier topics and do not start something new.]")


def is_repeat(new_reply, old_reply, threshold=0.9):
    """True when the new reply is (nearly) a copy of the one before it: a small model answering its own last message again.

    threshold: how alike (0 to 1) the first 1500 characters must be to count as a copy.
    """
    # Lower-case both and squeeze every run of whitespace to one space, so only the words are compared.
    a, b = " ".join(str(new_reply or "").lower().split()), " ".join(str(old_reply or "").lower().split())
    # Very short replies ("Yes.") repeat by chance, so they never count as a copy.
    if len(a) < 40 or len(b) < 40:
        return False
    # One contains the other (or they are equal): clearly a copy.
    if a == b or a in b or b in a:
        return True
    # Imported here because it is rarely needed. SequenceMatcher.ratio() is a similarity score from 0 (nothing alike)
    # to 1 (identical); only the first 1500 characters are compared to keep it fast.
    import difflib
    return difflib.SequenceMatcher(None, a[:1500], b[:1500]).ratio() >= threshold


def repeat_hint(text):
    """The note (for the model only) telling it that its last reply was a copy, quoting the person's new message (first 300 characters)."""
    return (f'[Your last reply was a copy of the one before it. Do not repeat it. Answer only this new message from the person, with new content: "{" ".join(str(text or "").split())[:300]}"]')


def last_question(reply):
    """The last question the assistant asked at the end of its reply ("Quick check: What is 6 x 5?"), or ''."""
    # Look only at the last 700 characters, going from the last line upwards; the first line with a "?" is the question.
    for line in reversed(str(reply or "")[-700:].splitlines()):
        line = line.strip()
        if "?" in line:
            # If the line has a "Quick check:" label, keep only the text after it (rfind = the last position of it).
            q = line[line.rfind("Quick check:") + len("Quick check:"):].strip() if "Quick check:" in line else line
            return q[:200]
    return ""


# A pattern for messages that START like a request or question ("please ...", "what ...", "give me ..."), as opposed to a bare answer.
# The leading r in r"..." means a raw string: backslashes are kept as they are, which regexes need.
REQUEST = re.compile(r"^(please|can|could|would|will|give|make|write|create|generate|list|show|tell|explain|teach|help|let|now|next|more|another|again|repeat|start|stop|quiz|"
                     r"what|who|when|where|why|how|which|do|does|is|are|i (want|need|would like)|i'?d like|try|use|change|add|remove|translate|convert|continue|go on)\b", re.I)


def answer_hint(text, last_reply, max_words=8):
    """A note for the model when a short message ("30", "yes", "B", "x = 4") is the answer to the question it just asked. On its own such a message names no
    subject, and a small model can answer its own last reply again instead of checking the answer. Shown to the model only, never saved.

    text: the person's new message. last_reply: the assistant's previous reply. max_words: longer messages are not treated as answers.
    Returns the hint text, or "" when no hint is needed.
    """
    # Squeeze whitespace, then rule out: empty, too long, a question itself, or a request. What is left may be an answer.
    t = " ".join(str(text or "").split())
    if not t or len(t.split()) > max_words or t.endswith("?") or REQUEST.match(t):          # "give me 15 questions" is a request, not an answer
        return ""
    # Only helpful if the assistant really did end its last reply with a question.
    q = last_question(last_reply)
    if not q:
        return ""
    return (f'[This message is the person\'s ANSWER to your last question: "{q}". Say clearly whether the answer is right or wrong, and if it is wrong explain the mistake kindly. '
            "Then go on to the next step or ask one new question. Do not repeat your last reply.]")


def follow_up_hint(text, has_reply, max_words=10):
    """A short note for the model when a message is a short follow-up ("write it in java", "make it shorter", "now in Spanish"): on its own it names no
    subject, and a model tuned on one-question chats may answer an older message instead of the one just before. Shown to the model only, never saved.

    text: the new message. has_reply: True if the assistant already replied earlier in this chat. max_words: longer messages are not follow-ups.
    Returns FOLLOW_HINT or "".
    """
    words = str(text or "").split()
    if not has_reply or not words or len(words) > max_words:
        return ""
    # search = pattern anywhere in the text; match = pattern at the very start of the text.
    if FOLLOW_REF.search(text) or FOLLOW_START.match(text.strip()):
        return FOLLOW_HINT
    return ""


# A pattern for polite padding at the start of a message ("hey, can you please", "I want you to", "quick question:").
# The (?:...) groups are plain groups; the trailing + lets the filler repeat, so several pieces in a row are all matched.
TITLE_FILLER = re.compile(r"^(?:(?:hey|hi|hello|yo|ok(?:ay)?|so|um+|uh+)\b[\s,!.]*|(?:can|could|would|will) (?:you|u)(?: please)?\s+|please\s+|i (?:want|need|would like) (?:you )?to\s+|"
                          r"i'?d like (?:you )?to\s+|help me(?: to)?\s+|tell me\s+|quick question[\s,:]*|question[\s,:]+)+", re.I)


def short_title(text, limit=48):
    """chat_fixes: a chat list title like other assistants make: the request without "hey, can you please", its first sentence, at most `limit`
    characters cut at a word, starting with a capital and without the question mark."""
    t = " ".join(str(text or "").split())
    # Remove the filler; "or t" keeps the original if removing it would leave nothing.
    t = TITLE_FILLER.sub("", t).strip() or t
    # Keep only the first sentence: split after . ! or ? when followed by whitespace ((?<=...) looks behind without using up characters).
    t = re.split(r"(?<=[.!?])\s", t, maxsplit=1)[0].rstrip(" .!?,;:")
    # Too long: cut at `limit`, then drop the last half-cut word; if there is no space at all, keep the plain cut.
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-") or t[:limit]
    # Capital first letter; an empty result falls back to "New chat".
    return (t[:1].upper() + t[1:]) if t else "New chat"


def thinking_word(n):
    """The n-th label (0, 1, 2, ...): cycles through the list, so two in a row are never the same."""
    # % (remainder) wraps the number around the list length, so the labels repeat in a loop.
    return THINKING_WORDS[n % len(THINKING_WORDS)]


def thinking_index(elapsed_s):
    """Which label to show after `elapsed_s` seconds of thinking."""
    # max(0.0, ...) guards against a negative time; // is whole-number division: how many 2.2 s steps have passed.
    return int(max(0.0, elapsed_s) // THINKING_SWITCH_S)


# Matches one word plus the spaces after it (\S+\s*), or else a run of spaces on its own (\s+): the units text is released in.
_BITS = re.compile(r"\S+\s*|\s+")


def _bits(text):
    """Split into words (with their trailing space), and long words into chunks of at most 12 characters."""
    for m in _BITS.findall(text):
        # Slice a long word into pieces of 12 characters so one huge word cannot appear all at once.
        for i in range(0, len(m), 12):
            yield m[i:i + 12]


def paced(pieces, min_first_s=MIN_FIRST_S, rate_cps=RATE_CPS, max_lag_s=MAX_LAG_S, clock=time.monotonic,
          sleep=time.sleep, start=None, adaptive=False):
    """Yield the same text as `pieces`, but not before `min_first_s` after `start` (default: now) and no faster than
    `rate_cps`, unless that would put the screen more than `max_lag_s` behind (then it catches up).
    `adaptive` (flag chat_fixes): when the next piece was already waiting (the model writes faster than `rate_cps`), it is shown at once. Without
    it a fast model's long answer took twice as long on screen as the model needed, because the waiting pieces were never counted as lag."""
    start = clock() if start is None else start
    due = None                                          # when the next bit may appear
    # Take the pieces one at a time (pieces may be a generator that produces text as the model writes it).
    it = iter(pieces)
    try:
        while True:
            # Note the time before waiting for the model's next piece, to see afterwards whether it was already there.
            asked = clock()
            try:
                piece = next(it)
            except StopIteration:
                break
            waiting = adaptive and due is not None and clock() - asked < FAST_PIECE_S and due > clock()     # it was already here: the screen is behind
            # Break the piece into small word-sized bits, released one by one.
            bits = list(_bits(piece))
            left = len(piece)                           # what is still waiting to be shown from this piece
            for bit in bits:
                now = clock()
                # The very first bit may not appear before start + min_first_s (the thinking pause).
                if due is None:
                    due = start + min_first_s
                # How long to wait before this bit is allowed to show.
                wait = due - now
                if waiting and due > start + min_first_s:
                    wait = 0                            # catching up with a fast model (never before the first-word pause)
                if wait > 0:
                    sleep(wait)
                    now = due
                # yield hands one bit to whoever is reading this generator, then resumes here for the next bit.
                yield bit
                left -= len(bit)
                rate = max(rate_cps, left / max_lag_s)  # a big piece that is already here: catch up, never lag far behind
                # The next bit is due after this one has "taken" len(bit)/rate seconds of typing time.
                due = (now if waiting else max(due, now)) + len(bit) / rate
    # finally: runs even if the reader stops early, so the model's stream is closed and not left running.
    finally:
        close = getattr(pieces, "close", None)
        if close:
            close()


# ------------------------------------------------------------------ shortening a long chat
# The first line of every summary message; it is how a summary is recognised later.
SUMMARY_MARK = "[Earlier in this chat, shortened to save room]"


def _clip(text, n):
    """Squeeze whitespace and cut `text` to at most `n` characters, ending with an ellipsis (...) if it was cut."""
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def extractive_summary(messages, max_chars=1200):
    """A short list of what was asked and answered, no model needed. An earlier summary is carried forward.

    messages: dicts with "role", "content" and optionally "status". max_chars: rough size limit of the whole summary.
    Returns the summary text, starting with SUMMARY_MARK.
    """
    lines = []
    for m in messages:
        # An older summary: reuse its lines (skip its first line, the mark) so nothing it recorded is lost.
        if m.get("status") == "summary":
            lines += [l for l in m["content"].split("\n")[1:] if l.strip()]
        elif m["role"] == "user":
            lines.append("- You asked: " + _clip(m["content"], 90))
        elif m["content"].strip():
            lines.append("  Answer: " + _clip(m["content"], 110))
    # Too long: drop lines from the front (the oldest) until it fits, but always keep at least two.
    while sum(len(l) + 1 for l in lines) > max_chars and len(lines) > 2:
        lines.pop(0)                                    # the oldest goes first
    return SUMMARY_MARK + "\n" + "\n".join(lines)


# Settings for when a long chat is shortened (see compact_point).
COMPACT_SHARE = 0.75        # a chat is shortened at 75% of the room for the prompt...
COMPACT_CAP = 96_000        # ...or at 96K tokens, whichever comes first: past ~100K these models reason less sharply and every re-read is slow


def compact_point(window, max_new, share=COMPACT_SHARE, cap=COMPACT_CAP):
    """The number of tokens at which a chat gets shortened (the memory meter shows it too).

    window: the model's total memory in tokens (a token is a word piece). max_new: tokens kept free for the reply.
    """
    # Share of the room left for the prompt (at least 64 so it never goes to zero), but never more than `cap`.
    return int(min(share * max(64, window - max_new), cap))


def compact_chat(tok, store, chat_id, window, max_new, keep=4, trigger=COMPACT_SHARE, summarize=None, keep_notes=1, on_start=None, cap=COMPACT_CAP, force=False):
    """If the chat fills more than `trigger` of the room for the prompt (or `cap` tokens), replace the older messages with a summary.
    `force=True` (the "Compact now" button) shortens it whatever its size, as long as there is something old enough to fold.
    `summarize(messages) -> text` may use the model; if it fails or returns nothing, the extractive summary is used.
    `on_start()` is called just before the folding starts (the page shows "Summarizing earlier messages" while it runs).
    Returns how many messages were folded into the summary (0 = nothing to do)."""
    # Messages already folded into an earlier summary are skipped.
    msgs = [m for m in store.messages(chat_id) if m["status"] != "compacted"]
    # Too few messages to be worth folding.
    if len(msgs) <= keep + 1:
        return 0
    # The shape the token counter expects: just role and content, and no empty messages.
    history = [{"role": m["role"], "content": m["content"]} for m in msgs if m["content"]]
    # Count exactly how many tokens the chat uses; "forgotten" are tokens that no longer fit and are already cut.
    r = chat.context_report(tok, history, window, reserve=max_new, keep_notes=keep_notes)
    if not force and r["used"] + r["forgotten"] <= compact_point(window, max_new, trigger, cap):
        return 0
    # Everything except the last `keep` messages is to be folded.
    old = msgs[:-keep]
    while old and old[-1]["role"] == "user":            # never leave a question without its answer in the kept part
        old.pop()
    if len(old) < 2:
        return 0
    if on_start:
        on_start()
    text = None
    # Try the model-written summary first.
    if summarize:
        try:
            text = (summarize(old) or "").strip()
        # Any failure of the model summary just means we use the simple summary below.
        except Exception:
            text = None
        # Make sure the summary starts with the mark, so it can be recognised later.
        if text and not text.startswith(SUMMARY_MARK):
            text = SUMMARY_MARK + "\n" + text
    # No model summary (not given, failed or empty): build the plain one from the messages.
    text = text or extractive_summary(old)
    # Save it: the first old message becomes the summary and the others are marked "compacted" (still visible on screen).
    store.fold(chat_id, [m["id"] for m in old], text)
    return len(old)
