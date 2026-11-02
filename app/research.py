"""
research.py - chat_research: Deep Research. A question is looked up several ways on the web, the pages are read, and the model writes a report
from all of it with numbered sources, instead of answering from one quick lookup.

WHAT THIS FILE DOES
    * `plan` turns the question into a few searches (plain code, no model call): the question itself, then the angles a report needs, chosen from
      the kind of question (a comparison gets each side, "how to" gets steps and mistakes, anything gets recent news and figures).
    * `gather` runs the searches one after another (each reads the pages it finds), tells the page what it is doing as it goes, and keeps the best
      notes: one per page, the same page never twice, at most MAX_NOTES.
    * REPORT_HINT asks the model to write it as a report: a short answer first, then sections, the [n] source numbers after facts, and what is
      still unsure. The answer is a normal chat answer, so chat_cite links the numbers and chat_verify marks figures no source has.
    Only the search words leave the PC (as with the web search in chat). Private chats never research.
"""
import re
import threading
import time

import web_search

# Limits: at most 5 searches per report, 10 notes kept, and each note cut to 900 characters so the model's input stays small.
MAX_SEARCHES = 5
MAX_NOTES = 10
REPORT_BUDGET = 30        # seconds all the searches of one report may take together (they run at the same time)
NOTE_CHARS = 900

# Text added to the end of the question so the model writes a structured report instead of a short answer. The notes come with it.
REPORT_HINT = ("[This is a research request. Write a report from the notes: first two or three sentences that answer the question directly, then "
               "sections with ## headings that cover each part of it, with the note numbers like [1] or [2][3] after every fact you take from a note. "
               "Compare what the notes say when they differ. End with a short ## What is still unsure section. Use only the notes for facts and figures; "
               "if they do not cover something, say so plainly instead of guessing.]")

# A regex (a text pattern) that finds the words that split a comparison: vs, vs., versus, compared to/with, or.
# \b means a word edge, (?: ) groups without remembering, re.I ignores capital letters.
VS = re.compile(r"\b(?:vs\.?|versus|compared (?:to|with)|or)\b", re.I)
# Matches a question that starts like 'how do/can/to/should ...' or 'what is the best way ...' (^ = start of the text; \s* = optional spaces).
HOW = re.compile(r"^\s*(?:how (?:do|can|to|should)|what(?:'s| is) the best way)\b", re.I)
# Matches a question that starts with 'why'.
WHY = re.compile(r"^\s*why\b", re.I)
# Matches the lead-in words to cut off: 'please research', 'look into', 'tell me', 'give me a report on', etc., and an optional 'about'.
FILLER = re.compile(r"^\s*(?:please\s+)?(?:research|look into|find out|tell me|explain|give me (?:a )?(?:report|overview) (?:on|of|about))\s+(?:about\s+)?", re.I)


def topic(question):
    """The question without "research ..." and the question mark: the words to search for."""
    # Squeeze all runs of spaces/newlines into single spaces, then delete the lead-in words (FILLER) from the start.
    q = FILLER.sub("", " ".join(str(question).split()))
    # Drop trailing ' ?.!' characters; if nothing is left, fall back to the original question.
    return q.rstrip(" ?.!") or str(question).strip()


def plan(question, year=None):
    """The searches for a report on `question`, most important first (at most MAX_SEARCHES, never the same twice)."""
    # The cleaned question is search number one.
    t = topic(question)
    out = [t]
    # Split on the 'vs/or' words and keep the non-empty pieces. A comparison has exactly two sides.
    sides = [s.strip(" ,?") for s in VS.split(t) if s.strip(" ,?")]
    if len(sides) == 2 and VS.search(t):                     # a comparison: each side on its own, then the difference
        out += [sides[0], sides[1], f"{sides[0]} vs {sides[1]} differences"]
    # Otherwise pick extra searches by the kind of question: how-to, why, or anything else.
    elif HOW.search(t):
        out += [f"{t} step by step", f"{t} common mistakes"]
    elif WHY.search(t):
        out += [f"{t} causes explained", f"{t} evidence"]
    else:
        out += [f"{t} explained", f"{t} statistics figures"]
    # Always finish with a search for recent news (with the year, if the caller gave one).
    out.append(f"{t} latest news {year}" if year else f"{t} latest news")
    # Remove repeats, ignoring capital letters, but keep the original order.
    seen, picked = set(), []
    for q in out:
        k = q.lower()
        if k not in seen:
            seen.add(k)
            picked.append(q)
    # Keep only the first MAX_SEARCHES.
    return picked[:MAX_SEARCHES]


def gather(question, search=None, on_step=None, year=None):
    """Runs the searches and returns the notes for the report ([{"title", "text", "url"}]). `search(q)` is web_search.web_notes by default;
    `on_step(text, done, of)` is told each step for the page."""
    # Default search: web_search.web_notes reads up to 3 pages per search. A different function can be passed in (tests do this).
    search = search or (lambda q: web_search.web_notes(q, k=3, read=True))
    queries = plan(question, year)
    # The searches are started all at once (they wait on the internet, not on each other), then read in order: the best query's pages come first, and `on_step`
    # still moves from search to search. A search that is slower than the whole report may take is given up on.
    slots = [{"done": threading.Event(), "found": []} for _ in queries]

    def run(q, slot):
        try:
            slot["found"] = search(q) or []
        except Exception:                                       # one search failing does not stop the report
            slot["found"] = []
        slot["done"].set()

    for q, slot in zip(queries, slots):
        threading.Thread(target=run, args=(q, slot), daemon=True).start()
    end = time.monotonic() + REPORT_BUDGET
    # `seen` holds page keys already used so the same page is never added twice.
    notes, seen = [], set()
    # Take the searches in order; i is the step number for the progress message.
    for i, (q, slot) in enumerate(zip(queries, slots)):
        if on_step:
            on_step(f"Searching: {q}", i, len(queries))
        slot["done"].wait(max(0.0, end - time.monotonic()))
        found = slot["found"] if slot["done"].is_set() else []
        for n in found:
            # A page is identified by its address without a #fragment and trailing slash, lower case; if there is no address, its title.
            key = (n.get("url") or n.get("title") or "").split("#")[0].rstrip("/").lower()
            # Skip pages with no key, pages already seen, and pages with no text.
            if not key or key in seen or not str(n.get("text", "")).strip():
                continue
            seen.add(key)
            # Keep a cleaned-up note: title cut to 160 characters, text cut to NOTE_CHARS.
            notes.append({"title": str(n.get("title", ""))[:160], "text": str(n["text"])[:NOTE_CHARS], "url": n.get("url", "")})
        # Enough notes already: the remaining searches are not needed.
        if len(notes) >= MAX_NOTES:
            break
    # Tell the page the final count (the search is finished, so done equals the total).
    if on_step:
        on_step(f"Read {len(notes)} sources" if notes else "No sources found", len(queries), len(queries))
    return notes[:MAX_NOTES]
