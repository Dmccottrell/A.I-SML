"""
chat_plus.py - Parts of the chat that work like Claude's and Cursor's (each behind its own feature flag; the page side is web/js/chatplus.js).

WHAT THIS FILE DOES
    * Panels (chat_panel): a web page from an answer, shown in the side panel. The page sends the HTML, gets a short-lived secret address, and the
      panel's frame opens it sealed (a sandbox with no identity: it cannot read Emvryx's cookies or the person's chats).
    * followups (chat_followups): two or three things worth asking next, worked out from the answer itself (code, a list of steps, a long answer...),
      so they appear at once and cost no model time.
"""
import re
import secrets
import threading
import time

MAX_PANEL_BYTES, PANEL_TTL, MAX_PANELS = 900_000, 3600, 200          # under the server's 1 MB request limit


class Panels:
    def __init__(self, clock=time.time):
        self.clock, self.lock, self.items = clock, threading.Lock(), {}

    def make(self, user, html):
        data = str(html or "").encode("utf-8")
        if not data.strip():
            raise ValueError("There is nothing to show.")
        if len(data) > MAX_PANEL_BYTES:
            raise ValueError("That page is too big to show here (900 KB at most). Download it instead.")
        token = secrets.token_urlsafe(24)
        with self.lock:
            now = self.clock()
            self.items = {k: v for k, v in self.items.items() if v["until"] > now}
            while len(self.items) >= MAX_PANELS:
                self.items.pop(next(iter(self.items)))
            self.items[token] = {"user": user, "data": data, "until": now + PANEL_TTL}
        return token

    def get(self, token):
        with self.lock:
            v = self.items.get(token)
            return v["data"] if v and v["until"] > self.clock() else None


CODE = re.compile(r"```")
STEPS = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+\S", re.M)


def followups(question, answer, n=3):
    """Short follow-ups that fit this answer, best first."""
    a, q = str(answer or ""), str(question or "").lower()
    out = []
    if CODE.search(a):
        out += ["Explain how this code works, step by step", "Add comments to the code", "How do I run it?"]
    steps = STEPS.findall(a)
    if len(steps) >= 3:
        out += ["Go into more detail on the first point", "Make it a short checklist"]
    if "|" in a and re.search(r"^\s*\|.*\|\s*$", a, re.M):
        out.append("Explain what the table shows")
    if len(a) > 1200:
        out.append("Make it shorter")
    if re.search(r"\b(recipe|ingredients?|cook|bake)\b", q + " " + a.lower()):
        out.append("What can I swap if I am missing something?")
    if re.search(r"\b(plan|schedule|trip|week|day)\b", q):
        out.append("Turn it into a simple timetable")
    out += ["Explain it more simply", "Give me an example"]
    seen, picked = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            picked.append(x)
    return picked[:n]
