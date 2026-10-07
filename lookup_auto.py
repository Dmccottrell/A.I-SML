"""lookup_auto.py - the chat app's "Auto" lookup: find notes for a message before the model answers.

The model never searches by itself (docs/V3.md). The app does, then hands the passages to the model as notes; v3 was trained to
answer from notes, name the source, and say "I don't know" when the notes don't cover it.

    1. Is the message a question that a fact could answer? ("Hi", "write me a poem", "list 3 fruits" are not: no lookup.)
    2. Search the local Wikipedia index (fast, free, private, works offline).
    3. Search the web too when the setting allows it AND (the question is about something recent, OR the Wikipedia notes
       barely match the question). Never in a private chat, and a failed or offline search just means no web notes.

The setting is per person: "auto" (the default), "off" (Wikipedia on this computer only), "always" (web for every factual
question) or "none" (no lookup at all: the model answers from what it knows). `gather` returns (notes, info); `info` is what the page shows ("Read 2 notes from Wikipedia and 1 from the web").
"""
import re
import threading

MODES = ("auto", "off", "always", "none")     # "none": no lookup at all, the model answers from what it knows

# a message that starts with one of these is a job, not a question: no lookup
TASK_START = re.compile(r"^(write|draft|compose|translate|rewrite|rephrase|summari[sz]e|proofread|edit|fix|make|create|generate|"
                        r"list|tell me a (story|joke)|continue|repeat|remember|forget|pretend|act as|imagine|code|"
                        r"explain (this|the following)|hi\b|hello\b|hey\b|thanks|thank you|ok\b|okay\b|yes\b|no\b)", re.I)
QUESTION_START = re.compile(r"^(who|whom|whose|what|when|where|which|why|how|is|are|was|were|do|does|did|can|could|will|would|"
                            r"should|tell me|define|explain|name|give me the)\b", re.I)
FACT_SHAPES = re.compile(r"\b(capital of|population of|president of|prime minister of|height of|born in|born on|died|invented|"
                         r"founded|how many|how much|how old|how tall|how far|meaning of|definition of|who is|who was|what is|what was)\b", re.I)
TIME_WORDS = re.compile(r"\b(latest|newest|current|currently|today|tonight|yesterday|tomorrow|this (week|month|year|season)|"
                        r"right now|nowadays|recent|recently|news|score|scores|price|prices|weather|forecast|stock|released?|"
                        r"release date|upcoming|just (won|released|announced)|who won|who is the (current )?(president|prime minister|ceo)|"
                        r"coming out|comes? out|come out|out yet|launch(es|ed|ing)?|release[sd]?|releasing|premieres?|"
                        r"when (is|are|does|do|will|did) .{1,60}\b(out|release|drop|start|begin|air|launch)\w*|"
                        r"next (game|movie|film|season|episode|version|update|album|model|iphone|console)|"
                        r"20(2[4-9]|3\d))\b", re.I)
DATE_WORDS = re.compile(r"\b(today|tonight|tomorrow|yesterday|this (year|month|week|weekend|morning|evening)|current (year|month|date|day|time)|"
                        r"what (day|date|year|month) is|what'?s the (date|day)|days? (until|till|left|from now)|how (long|many days|many weeks) until|"
                        r"next (week|month|year)|last (week|month|year))\b", re.I)


def date_note(question, now):
    """A one-line note with today's date for questions that depend on it ("what day is Christmas this year?"): a model has no clock, so
    without this it guesses or says it doesn't know. None for other questions."""
    if not DATE_WORDS.search(question or ""):
        return None
    import time
    t = time.localtime(now or time.time())
    return {"title": "Today", "text": time.strftime("Today is %A, %B ", t) + str(t.tm_mday) + time.strftime(", %Y.", t)}


WEATHER_WORDS = re.compile(r"\b(weather|forecast)\b", re.I)
STOP = set("the a an of to in on at for and or is are was were be been do does did what who whom when where which why how "
           "can could will would should it its this that these those with as by from about me my you your i tell give name".split())


def wants_lookup(text):
    """True for a message that a fact could answer."""
    t = " ".join((text or "").split())
    words = t.split()
    if len(words) < 3 and not t.endswith("?"):
        return False
    if TASK_START.match(t) and not t.endswith("?"):
        return False
    return bool(t.endswith("?") or QUESTION_START.match(t) or FACT_SHAPES.search(t) or WEATHER_WORDS.search(t))


GAVE_UP = re.compile(r"\b(i (do not|don'?t) know|i'?m not sure|i am not sure|(the )?notes (do not|don'?t) (say|mention|have|cover|include)|"
                     r"(no|not enough) (information|notes)|can(no|')t find|could(n'?t| not) find|i have no)\b", re.I)


def gave_up(reply):
    """True when the model's answer says it doesn't know (v3 is trained to say so when the notes don't cover the question)."""
    return bool(GAVE_UP.search((reply or "")[:400]))


def time_sensitive(text):
    return bool(TIME_WORDS.search(text or ""))


def _content_words(text):
    return {w for w in re.findall(r"[a-z0-9']+", (text or "").lower()) if len(w) > 2 and w not in STOP}


def notes_weak(notes, question):
    """True when no note covers at least half of the question's content words (the passages probably aren't about it)."""
    want = _content_words(question)
    if not notes:
        return True
    if not want:
        return False
    best = max(len(want & _content_words(n["title"] + " " + n["text"])) / len(want) for n in notes)
    return best < 0.5


def gather(question, wiki=None, web=None, mode="auto", private=False, max_notes=3, saved=None, now=0.0, force_web=False,
           policy="always", force_notes=False):
    """(notes, info). `wiki` has .search(question, k); `web(question, k)` returns [{"title", "text", "url"}]. Both optional.
    `saved` (saved_notes.SavedNotes) holds notes the person approved before: they are searched first, offline.
    `force_web` searches the web even if the rules wouldn't (the second try after the model said it doesn't know).
    `policy` "always" (small models: look up every factual question) or "when_needed" (strong models such as the Qwen ones know most famous
    things and a wrong passage misleads them: Wikipedia and the web are used only for recent things, or when `force_notes` is set because the
    model said it was not sure; notes the person approved are always used)."""
    info = {"asked": False, "saved": 0, "wiki": 0, "web": 0, "web_tried": False, "sources": []}
    mode = mode if mode in MODES else "auto"
    if not wants_lookup(question):
        return [], info
    if mode == "none":
        return [], info
    info["asked"] = True
    recent = time_sensitive(question)
    lazy = policy == "when_needed" and not (recent or force_notes)
    wiki_notes, web_notes, saved_notes = [], [], []
    if saved is not None and not private:
        try:
            saved_notes = saved.search(question, max_notes, now)
        except Exception as e:
            print(f"(saved notes failed: {e})")
    if lazy and not saved_notes:                                # the model answers from its own knowledge first
        info["asked"] = False
        return [], info
    if wiki is not None and not lazy:
        try:
            wiki_notes = [{"title": n["title"], "text": n["text"], "kind": "wikipedia", "url": None}
                          for n in wiki.search(question, max_notes)]
        except Exception as e:                                  # a missing or damaged index must not stop the chat
            print(f"(Wikipedia lookup failed: {e})")
    use_web = web is not None and not private and mode != "off" and not lazy and (
        mode == "always" or force_web or recent or notes_weak(saved_notes + wiki_notes, question))
    if use_web:
        info["web_tried"] = True
        try:
            web_notes = [{"title": n["title"], "text": n["text"], "kind": "web", "url": n.get("url")}
                         for n in (web(question, max_notes) or [])]
        except Exception as e:                                  # offline, a timeout, a bad key...
            print(f"(web search failed: {e})")
    # Which group is read first. Recent things: the web. A second try (the model was not sure): also the web, because a search engine fixes a misspelt
    # name and ranks the famous page first, where the local Wikipedia index matches the letters exactly (and may find a different person).
    first, second = (web_notes, wiki_notes) if (recent or force_notes) else (wiki_notes, web_notes)
    if (recent or force_notes) and second and len(first) >= max_notes > 1:
        first = first[:max_notes - 1]                            # keep a slot for the other source
    merged = []
    for group in ((saved_notes, first, second) if not (recent or force_notes) else (first, saved_notes, second)):                               # the notes the model reads: at most max_notes, best group first
        for n in group:
            if len(merged) < max_notes:
                merged.append(n)
    info["saved"] = sum(1 for n in merged if n["kind"] == "saved")
    info["wiki"] = sum(1 for n in merged if n["kind"] == "wikipedia")
    info["web"] = sum(1 for n in merged if n["kind"] == "web")
    info["sources"] = [{"title": n["title"], "kind": n["kind"], "url": n["url"]} for n in merged]
    info["recent"] = recent
    info["used"] = merged                      # the full notes (with kind, url, id): kept server-side so a thumbs up can save them
    return [{"title": n["title"], "text": n["text"]} for n in merged], info


class LockedWiki:
    """One Wikipedia index shared by the server's worker threads: searches take turns (SQLite's time limit is per connection)."""

    def __init__(self, wiki):
        self.wiki, self.lock = wiki, threading.Lock()

    def search(self, question, k=3):
        with self.lock:
            return self.wiki.search(question, k, deep=True)
