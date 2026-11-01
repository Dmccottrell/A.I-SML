"""
chat_plus.py - Parts of the chat that work like Claude's and Cursor's (each behind its own feature flag; the page side is web/js/chatplus.js).

WHAT THIS FILE DOES
    * Panels (chat_panel): a web page from an answer, shown in the side panel. The page sends the HTML, gets a short-lived secret address, and the
      panel's frame opens it sealed (a sandbox with no identity: it cannot read Emvryx's cookies or the person's chats).
    * followups (chat_followups): two or three things worth asking next, worked out from the answer itself (code, a list of steps, a long answer...),
      so they appear at once and cost no model time.
"""
# Where it fits: the chat server (app_server) calls Panels from its panel web addresses and followups() when it finishes an answer.
import re            # regular expressions: patterns for finding text ("regex")
import secrets       # a safe random-number source, meant for secrets and tokens
import threading     # lets us use a lock so two requests do not change the same data at once
import time

# Limits for panels: the biggest page in bytes, how long a panel lives in seconds (3600 = one hour), and how many
# panels are kept at once in memory.
MAX_PANEL_BYTES, PANEL_TTL, MAX_PANELS = 900_000, 3600, 200          # under the server's 1 MB request limit


class Panels:
    """A small in-memory store of web pages (HTML) waiting to be shown in the chat's side panel.

    Each page is saved under a random token (a long unguessable string); only someone who has the token can fetch it,
    and it disappears after PANEL_TTL seconds. Nothing is written to disk.
    """

    def __init__(self, clock=time.time):
        """`clock` returns the current time in seconds; tests pass a fake one so they do not have to wait."""
        # items maps token -> {"user", "data" (the page as bytes), "until" (time it expires)}.
        # The lock makes sure only one thread (one web request) changes `items` at a time.
        self.clock, self.lock, self.items = clock, threading.Lock(), {}

    def make(self, user, html):
        """Store `html` for `user` and return the secret token for it. Raises ValueError (with a message fit to show) if empty or too big."""
        # Turn the page into bytes so its size in bytes can be checked against the limit.
        data = str(html or "").encode("utf-8")
        if not data.strip():
            raise ValueError("There is nothing to show.")
        if len(data) > MAX_PANEL_BYTES:
            raise ValueError("That page is too big to show here (900 KB at most). Download it instead.")
        # 24 random bytes as URL-safe text: far too many possibilities for anyone to guess.
        token = secrets.token_urlsafe(24)
        with self.lock:
            now = self.clock()
            # Throw away panels that have already expired.
            self.items = {k: v for k, v in self.items.items() if v["until"] > now}
            # Still full: remove the oldest panel (a dict remembers the order things were added in) until there is room.
            while len(self.items) >= MAX_PANELS:
                self.items.pop(next(iter(self.items)))
            self.items[token] = {"user": user, "data": data, "until": now + PANEL_TTL}
        return token

    def get(self, token):
        """The page bytes for `token`, or None if the token is unknown or has expired."""
        with self.lock:
            v = self.items.get(token)
            return v["data"] if v and v["until"] > self.clock() else None


# A pattern that finds a code fence: three backticks, which is how a code block starts and ends in the answer text.
CODE = re.compile(r"```")
# A pattern for a line that starts a list item: optional spaces, then "1." / "1)" or a bullet (-, * or the bullet dot),
# then a space and at least one non-space character. re.M ("multiline") lets ^ match at the start of every line.
STEPS = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+\S", re.M)


def followups(question, answer, n=3):
    """Short follow-up questions that fit this answer, best first.

    `question` is what the person asked, `answer` is the reply, `n` is how many to return (default 3).
    Returns a list of up to `n` distinct strings. Only simple rules about the text are used (no model), so it is instant.
    """
    # a = the answer, q = the question in lower case; None becomes "" so the checks below never crash.
    a, q = str(answer or ""), str(question or "").lower()
    out = []
    # The answer contains a code block.
    if CODE.search(a):
        out += ["Explain how this code works, step by step", "Add comments to the code", "How do I run it?"]
    # Three or more list items: it is a list of steps or points.
    steps = STEPS.findall(a)
    if len(steps) >= 3:
        out += ["Go into more detail on the first point", "Make it a short checklist"]
    # A markdown table: a line that starts and ends with "|".
    if "|" in a and re.search(r"^\s*\|.*\|\s*$", a, re.M):
        out.append("Explain what the table shows")
    # A long answer (over 1200 characters).
    if len(a) > 1200:
        out.append("Make it shorter")
    # \b marks a word edge, so "cook" matches as a whole word; the question and answer are checked together.
    if re.search(r"\b(recipe|ingredients?|cook|bake)\b", q + " " + a.lower()):
        out.append("What can I swap if I am missing something?")
    if re.search(r"\b(plan|schedule|trip|week|day)\b", q):
        out.append("Turn it into a simple timetable")
    # These two always apply, so the list is never empty.
    out += ["Explain it more simply", "Give me an example"]
    # Remove duplicates but keep the order (a set alone would lose the order).
    seen, picked = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            picked.append(x)
    return picked[:n]
