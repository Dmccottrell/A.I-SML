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

import web_search

MAX_SEARCHES = 5
MAX_NOTES = 10
NOTE_CHARS = 900

REPORT_HINT = ("[This is a research request. Write a report from the notes: first two or three sentences that answer the question directly, then "
               "sections with ## headings that cover each part of it, with the note numbers like [1] or [2][3] after every fact you take from a note. "
               "Compare what the notes say when they differ. End with a short ## What is still unsure section. Use only the notes for facts and figures; "
               "if they do not cover something, say so plainly instead of guessing.]")

VS = re.compile(r"\b(?:vs\.?|versus|compared (?:to|with)|or)\b", re.I)
HOW = re.compile(r"^\s*(?:how (?:do|can|to|should)|what(?:'s| is) the best way)\b", re.I)
WHY = re.compile(r"^\s*why\b", re.I)
FILLER = re.compile(r"^\s*(?:please\s+)?(?:research|look into|find out|tell me|explain|give me (?:a )?(?:report|overview) (?:on|of|about))\s+(?:about\s+)?", re.I)


def topic(question):
    """The question without "research ..." and the question mark: the words to search for."""
    q = FILLER.sub("", " ".join(str(question).split()))
    return q.rstrip(" ?.!") or str(question).strip()


def plan(question, year=None):
    """The searches for a report on `question`, most important first (at most MAX_SEARCHES, never the same twice)."""
    t = topic(question)
    out = [t]
    sides = [s.strip(" ,?") for s in VS.split(t) if s.strip(" ,?")]
    if len(sides) == 2 and VS.search(t):                     # a comparison: each side on its own, then the difference
        out += [sides[0], sides[1], f"{sides[0]} vs {sides[1]} differences"]
    elif HOW.search(t):
        out += [f"{t} step by step", f"{t} common mistakes"]
    elif WHY.search(t):
        out += [f"{t} causes explained", f"{t} evidence"]
    else:
        out += [f"{t} explained", f"{t} statistics figures"]
    out.append(f"{t} latest news {year}" if year else f"{t} latest news")
    seen, picked = set(), []
    for q in out:
        k = q.lower()
        if k not in seen:
            seen.add(k)
            picked.append(q)
    return picked[:MAX_SEARCHES]


def gather(question, search=None, on_step=None, year=None):
    """Runs the searches and returns the notes for the report ([{"title", "text", "url"}]). `search(q)` is web_search.web_notes by default;
    `on_step(text, done, of)` is told each step for the page."""
    search = search or (lambda q: web_search.web_notes(q, k=3, read=True))
    queries = plan(question, year)
    notes, seen = [], set()
    for i, q in enumerate(queries):
        if on_step:
            on_step(f"Searching: {q}", i, len(queries))
        try:
            found = search(q) or []
        except Exception:                                       # one search failing does not stop the report
            found = []
        for n in found:
            key = (n.get("url") or n.get("title") or "").split("#")[0].rstrip("/").lower()
            if not key or key in seen or not str(n.get("text", "")).strip():
                continue
            seen.add(key)
            notes.append({"title": str(n.get("title", ""))[:160], "text": str(n["text"])[:NOTE_CHARS], "url": n.get("url", "")})
        if len(notes) >= MAX_NOTES:
            break
    if on_step:
        on_step(f"Read {len(notes)} sources" if notes else "No sources found", len(queries), len(queries))
    return notes[:MAX_NOTES]
