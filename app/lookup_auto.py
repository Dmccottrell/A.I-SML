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
# re = regular expressions: text patterns used to recognise kinds of messages. threading = a lock so threads take turns.
import re
import threading

# The four settings a person can pick for lookups (see the top of the file).
MODES = ("auto", "off", "always", "none")     # "none": no lookup at all, the model answers from what it knows

# a message that starts with one of these is a job, not a question: no lookup
# A "regex" (regular expression) is a text pattern. In these patterns: ^ = start of the text, | = "or", (a|b) = a group of choices,
# \b = a word edge (so "hi\b" matches "hi" but not "history"), re.I = ignore upper/lower case. TASK_START spots messages that are jobs ("write me...", "hi"), not questions.
TASK_START = re.compile(r"^(write|draft|compose|translate|rewrite|rephrase|summari[sz]e|proofread|edit|fix|make|create|generate|"
                        r"list|tell me a (story|joke)|continue|repeat|remember|forget|pretend|act as|imagine|code|"
                        r"explain (this|the following)|hi\b|hello\b|hey\b|thanks|thank you|ok\b|okay\b|yes\b|no\b)", re.I)
# QUESTION_START: the message begins like a question (who, what, how, is, can, tell me...).
QUESTION_START = re.compile(r"^(who|whom|whose|what|when|where|which|why|how|is|are|was|were|do|does|did|can|could|will|would|"
                            r"should|tell me|define|explain|name|give me the)\b", re.I)
# FACT_SHAPES: phrases typical of fact questions anywhere in the text ("capital of", "how many", "who was"...).
FACT_SHAPES = re.compile(r"\b(capital of|population of|president of|prime minister of|height of|born in|born on|died|invented|"
                         r"founded|how many|how much|how old|how tall|how far|meaning of|definition of|who is|who was|what is|what was)\b", re.I)
# TIME_WORDS: words that mean the answer may have changed recently (latest, today, price, weather, "who won", release dates, years 2024-2039).
# {1,60} means "between 1 and 60 characters", \w* means "any letters"; these let phrases like "when is X out" match.
TIME_WORDS = re.compile(r"\b(latest|newest|current|currently|today|tonight|yesterday|tomorrow|this (week|month|year|season)|"
                        r"right now|nowadays|recent|recently|news|score|scores|price|prices|weather|forecast|stock|released?|"
                        r"release date|upcoming|just (won|released|announced)|who won|who is the (current )?(president|prime minister|ceo)|"
                        r"coming out|comes? out|come out|out yet|launch(es|ed|ing)?|release[sd]?|releasing|premieres?|"
                        r"when (is|are|does|do|will|did) .{1,60}\b(out|release|drop|start|begin|air|launch)\w*|"
                        r"next (game|movie|film|season|episode|version|update|album|model|iphone|console)|"
                        r"20(2[4-9]|3\d))\b", re.I)
# DATE_WORDS: the question depends on today's date ("what day is it", "next week", "days until..."). Used by date_note().
DATE_WORDS = re.compile(r"\b(today|tonight|tomorrow|yesterday|this (year|month|week|weekend|morning|evening)|current (year|month|date|day|time)|"
                        r"what (day|date|year|month) is|what'?s the (date|day)|days? (until|till|left|from now)|how (long|many days|many weeks) until|"
                        r"next (week|month|year)|last (week|month|year))\b", re.I)


def date_note(question, now):
    """A one-line note with today's date for questions that depend on it ("what day is Christmas this year?"): a model has no clock, so
    without this it guesses or says it doesn't know. None for other questions.
    Input: the question text and `now` (a Unix time in seconds, or 0/None to use the real clock). Output: {"title", "text"} or None."""
    # Only questions that mention the date need the note.
    if not DATE_WORDS.search(question or ""):
        return None
    import time
    # Break the time into parts (year, month, day...). `now or time.time()` uses the real time when `now` is empty.
    t = time.localtime(now or time.time())
    # strftime builds text from a time: %A = weekday name, %B = month name, %Y = year. The day number is added separately so it has no leading zero.
    return {"title": "Today", "text": time.strftime("Today is %A, %B ", t) + str(t.tm_mday) + time.strftime(", %Y.", t)}


# WEATHER_WORDS: the message is about weather (counts as a fact question even without a "?").
WEATHER_WORDS = re.compile(r"\b(weather|forecast)\b", re.I)
# STOP = very common words ignored when comparing a question with a note. .split() cuts the long string into a list of words; set() makes lookups fast.
STOP = set("the a an of to in on at for and or is are was were be been do does did what who whom when where which why how "
           "can could will would should it its this that these those with as by from about me my you your i tell give name".split())


# The next four patterns detect how people talk about searching: WEB_ASK = an order to search, PRONOUN and ASKING = a short follow-up that leans on the
# earlier question ("what about him?"), PRETENDS = the model claiming to search when it cannot. (?:...) is a group that is not remembered; [^.?!]{0,40} means "up to 40 characters
# that are not sentence ends".
# "look online", "check again", "search for it": an order to search, so the search happens whatever the rules say
WEB_ASK = re.compile(r"\b((look|check|search|find|google|verify|confirm|double[- ]check|re-?check)\b[^.?!]{0,40}\b(online|on the (web|internet)|the (web|internet)|again|it up|up online|for it)|"
                     r"(search|google) (for|the web|online)|google (it|that|this|him|her|them)|look (it|that|this|him|her|them) up|(check|look) online|(on|from) the (web|internet)|online search)\b", re.I)
# a follow-up that leans on the earlier question: a pronoun or "again", plus something that asks or orders
PRONOUN = re.compile(r"\b(he|she|they|it|his|her|hers|their|its|him|them|that|this|those|these|there|again|then|same)\b", re.I)
ASKING = re.compile(r"^(check|search|look|find|tell|show|give|list|compare|verify|confirm|update|recheck|re-check|and|also|what|who|when|where|which|why|how|is|are|was|were|do|does|did|can|could|has|have|had)\b|\?|"
                    r"\b(how many|how much|since|so far|stats|score|goals)\b", re.I)
# the model describing a search it did not do ("*Checking online*", "Upon checking online, I see...")
PRETENDS = re.compile(r"(\*(checking|searching|looking)[^*]{0,30}\*|\b(i will|i'?ll|let me|i am going to|i'?m going to) (now )?(check|search|look)( it| that)?( up)?( online| on the (web|internet))?\b|"
                      r"\b(upon|after|having) (checking|searching|looking)( online| the web| it up)?|\b(i )?(checked|searched|looked) (online|the web|the internet|it up)\b)", re.I)


def asks_for_web(text):
    """True when the person orders a web search ("look it up online", "google that"). `text or ""` guards against None."""
    return bool(WEB_ASK.search(text or ""))


def is_follow_up(text):
    """True for a short message (24 words or fewer) that has a pronoun or "again" AND asks or orders something, so it needs the earlier question for context."""
    # " ".join(text.split()) squeezes any run of spaces/newlines into single spaces.
    t = " ".join((text or "").split())
    return bool(t) and len(t.split()) <= 24 and bool(PRONOUN.search(t)) and bool(ASKING.search(t))


def search_query(text, earlier, force=False):
    """What to search for. A follow-up ("check again, how many goals has he had") is searched together with the questions before it, so "he" has a name.
    `earlier` is the person's earlier messages in this chat, oldest first."""
    t = " ".join((text or "").split())
    if not earlier or not (force or is_follow_up(t) or asks_for_web(t)):
        return t
    # Take the last two earlier messages (each cut to 160 characters) to borrow names and context from.
    before = [" ".join(m.split())[:160] for m in earlier[-2:] if m and m.strip()]
    # A full question that already includes the words "online" etc. stands on its own, so nothing is borrowed.
    if not force and asks_for_web(t) and not is_follow_up(t) and len(t.split()) >= 6:
        return t                                   # a full question that also says "online": nothing to borrow
    # dict.fromkeys drops repeated messages while keeping order; the result is cut to 320 characters for the search engine.
    return " ".join(dict.fromkeys(before + [t]))[:320]


def pretends_to_search(reply):
    """True when the answer says it is checking or has checked online. The model cannot search: the app does, before it answers."""
    return bool(PRETENDS.search((reply or "")[:800]))


def wants_lookup(text):
    """True for a message that a fact could answer. Rules in order: an order to search always counts; very short non-questions do not;
    job-like messages ("write me a poem") do not; otherwise a "?" , a question opening, a fact phrase or weather talk counts."""
    t = " ".join((text or "").split())
    words = t.split()
    if asks_for_web(t):
        return True
    if len(words) < 3 and not t.endswith("?"):
        return False
    if TASK_START.match(t) and not t.endswith("?"):
        return False
    return bool(t.endswith("?") or QUESTION_START.match(t) or FACT_SHAPES.search(t) or WEATHER_WORDS.search(t))


# GAVE_UP: the model's answer says it does not know. GAVE_UP_LATE: softer "the notes don't mention it" wording that may come later in an answer.
GAVE_UP = re.compile(r"\b(i (do not|don'?t) know|i'?m not sure|i am not sure|(the )?notes (do not|don'?t) (say|mention|have|cover|include)|"
                     r"(no|not enough) (information|notes)|can(no|')t find|could(n'?t| not) find|i have no)\b", re.I)


GAVE_UP_LATE = re.compile(r"\b(no specific information|(does|do|did) not (directly )?(mention|provide|say|cover|include|relate)|(is|are) not (mentioned|provided|included|stated)|"
                          r"(additional|more|further) information (would|will) (need|be needed)|not (enough|any) (information|details) (is |are )?(provided|available))\b", re.I)


# the model asks the person for something only they know (where they live, which one they mean): searching the web cannot answer that
ASKS_BACK = re.compile(r"\b(?:i don'?t know|i'?m not sure|i can'?t tell) (?:which|what|where|who|when|how many|your)\b[^.?!]{0,80}\b(?:you|your)\b|"
                       r"\b(?:please )?(?:tell|let) me (?:know )?(?:which|what|where|the name|your)\b|\bwhich (?:city|town|one|country|state|place) (?:do )?you\b", re.I)


def gave_up(reply):
    """True when the model's answer says it doesn't know (v3 is trained to say so when the notes don't cover the question). The "notes don't say" wording
    can come late in a longer answer ("Lamine Yamal is doing well. However, there is no specific information about this season..."), so those phrases are looked for further in."""
    reply = reply or ""
    # Only the first 600 characters are checked: that is where an opening "I don't know" sits.
    if ASKS_BACK.search(reply[:600]):          # "I don't know which city you live in. Tell me and I'll look it up": a question back, not a gap to search for
        return False
    return bool(GAVE_UP.search(reply[:400]) or GAVE_UP_LATE.search(reply[:1500]))


def time_sensitive(text):
    """True when the message is about something recent (matches TIME_WORDS), so a web search is worth it."""
    return bool(TIME_WORDS.search(text or ""))


def _content_words(text):
    """The set of meaningful words in the text: lower-case letters/digits, longer than 2 characters, and not in STOP."""
    return {w for w in re.findall(r"[a-z0-9']+", (text or "").lower()) if len(w) > 2 and w not in STOP}


def notes_weak(notes, question):
    """True when no note covers at least half of the question's content words (the passages probably aren't about it)."""
    # `want` = the question's key words. No notes at all means weak. A question with no key words cannot be judged, so call it fine.
    want = _content_words(question)
    if not notes:
        return True
    if not want:
        return False
    # For each note, the share of the question's key words it contains (& = the words in both sets); keep the best note's share.
    # Under 0.5 (less than half) means the notes probably are not about the question.
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
    # info is the report for the page: whether we looked, how many notes came from each place, and the list of sources.
    info = {"asked": False, "saved": 0, "wiki": 0, "web": 0, "web_tried": False, "sources": []}
    # An unknown setting falls back to "auto".
    mode = mode if mode in MODES else "auto"
    # Nothing to look up for chit-chat or jobs, or when the person turned lookups off.
    if not wants_lookup(question):
        return [], info
    if mode == "none":
        return [], info
    info["asked"] = True
    # `lazy` = a strong model that should answer from its own knowledge first: no lookup unless the question is recent, the model was unsure, or the person saved notes.
    recent = time_sensitive(question)
    lazy = policy == "when_needed" and not (recent or force_notes)
    wiki_notes, web_notes, saved_notes = [], [], []
    # Notes the person approved earlier are searched first (offline, free). Not in a private chat. A failure is only printed, never fatal.
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
    # Use the web only if: a web function exists, the chat is not private, the setting is not "off", and either the setting is "always", this is a second try,
    # the question is recent, or the notes found so far barely match.
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
    # Fill up to max_notes slots, taking notes from the groups in priority order (saved notes first normally; web first for recent questions).
    merged = []
    for group in ((saved_notes, first, second) if not (recent or force_notes) else (first, saved_notes, second)):                               # the notes the model reads: at most max_notes, best group first
        for n in group:
            if len(merged) < max_notes:
                merged.append(n)
    # Count how many of the chosen notes came from each source, for the line the page shows ("Read 2 notes from Wikipedia...").
    info["saved"] = sum(1 for n in merged if n["kind"] == "saved")
    info["wiki"] = sum(1 for n in merged if n["kind"] == "wikipedia")
    info["web"] = sum(1 for n in merged if n["kind"] == "web")
    info["sources"] = [{"title": n["title"], "kind": n["kind"], "url": n["url"]} for n in merged]
    info["recent"] = recent
    info["used"] = merged                      # the full notes (with kind, url, id): kept server-side so a thumbs up can save them
    return [{"title": n["title"], "text": n["text"]} for n in merged], info


class LockedWiki:
    """One Wikipedia index shared by the server's worker threads: searches take turns (SQLite's time limit is per connection).
    A Lock lets only one thread inside `with self.lock:` at a time; the rest wait their turn."""

    def __init__(self, wiki):
        self.wiki, self.lock = wiki, threading.Lock()

    def search(self, question, k=3):
        """Search the shared index for up to k notes (deep=True asks for the slower, more thorough search)."""
        with self.lock:
            return self.wiki.search(question, k, deep=True)
