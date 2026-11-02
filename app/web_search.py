"""
web_search.py - Look things up on the internet (optional "online mode", v3+).

WHAT THIS FILE DOES
    The model never goes online itself (neither do ChatGPT or Claude). OUR CODE searches the web,
    cleans what it finds into a few short passages, and gives them to the model as notes, exactly
    like the offline Wikipedia lookup (wiki_index.py). The model was trained to answer from notes
    and name the source, so the same skill works for today's news, scores, prices and new products.

        you ask  ->  web_search.py searches  ->  notes  ->  the model reads them and answers

    A web note looks like this (the title says WHERE and WHEN it's from, so the model can cite it):
        [1] Tigers win the final 3-1 - sportswire.net, Sep 30, 2026: The Tigers beat the ...

    Sources (pick with --web_source, or "auto"):
        wikipedia   Wikipedia's live search (free, no key). Up to date, but encyclopedia topics only.
        brave       Brave Search API for the whole web (free tier; needs a key):
                        PowerShell:  $env:BRAVE_API_KEY = "paste-your-key"
        tavily      Tavily's search API, made for AI apps (free monthly allowance; needs a key):
                        PowerShell:  setx TAVILY_API_KEY "paste-your-key"      (then restart the app)
        gemini      Google's Gemini API with Google Search grounding (free tier; key from Google AI Studio). One note: Gemini's short answer
                    written from live Google results. Your question goes to Google, and free-tier content may be used to improve Google's
                    products, so this one is used only when it is the only key you set (or with --source gemini). Not tested against the live service.
                        PowerShell:  setx GEMINI_API_KEY "paste-your-key"
        auto        the first key found, in this order: tavily, brave, gemini; otherwise wikipedia (the default)

    Weather has its own free source, Open-Meteo (no key): a weather question ("weather in Paris", "will it rain tomorrow") is answered from
    a real forecast, not from search snippets. Say where in the question, or set a default place (app_server.py --weather-place "Austin, Texas").
    Open-Meteo's free service is for NON-COMMERCIAL use: if Emvryx is ever paid, use their commercial plan (see docs/DEPLOY.md).

    Trusted sites first: a small model believes whatever it reads, so known-reliable sites
    (encyclopedias, government, science, big news agencies) are moved to the top, and sites on the
    BLOCKED list are skipped.

    PRIVACY: web search is OFF unless you switch it on (generate.py --web). When it's on, your
    question is sent to the search service; nothing else (no chat history, no memories) is.

    Each version gets better at using it (docs/ROADMAP.md, "Web search, version by version"):
        v3    our code searches every message; the model reads the results and cites one
        v3.5  more web lessons: newest result wins, sources that disagree, messy pages
        v4    the model DECIDES when to search (a "search" tool call) and can search again
        v5+   combines several sources and judges which ones to trust

Usage:
    python app/web_search.py "who won the world series"                (prints the notes)
    python app/web_search.py "latest claude model" --source brave --k 5
    python tools/generate.py --version v3 --chat --web                   (chat with web search on)
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
# argparse = reads command-line options (used by main() at the bottom); html = decodes things like &amp;; json = reads/writes JSON text;
# re = regular expressions (a regex is a text pattern); urllib = makes web requests; datetime = dates; HTMLParser = walks through a web page's tags.
import argparse
import html
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser

# keywords() picks the meaningful words of a question (from the offline Wikipedia lookup); best_passage() uses it to score text.
from wiki_index import keywords

# Who we say we are when we ask a website for something (polite web clients identify themselves).
USER_AGENT = "A.I-SML/1.0 (personal research project; https://github.com/dmccottrell/a.i-sml)"
# Give up on a web request after this many seconds so a slow site cannot freeze the chat.
TIMEOUT = 10
PASSAGE_WORDS = 120            # the same size as the Wikipedia notes
NOTE_CHARS = 900               # a hard cap per note, so 3 notes never crowd out the chat

# Moved to the top of the results (a domain, or the end of one: "gov" covers every .gov site)
TRUSTED = ("wikipedia.org", "britannica.com", "gov", "edu", "who.int", "un.org", "nasa.gov", "nih.gov",
           "apnews.com", "reuters.com", "bbc.com", "bbc.co.uk", "npr.org", "pbs.org", "nature.com",
           "science.org", "nationalgeographic.com", "weather.gov", "espn.com", "github.com", "python.org",
           "mozilla.org", "microsoft.com", "apple.com", "google.com", "anthropic.com", "openai.com")
# Never used as notes (add sites you don't want the AI to read)
BLOCKED = ("pinterest.com", "quora.com")


# ------------------------------------------------------------------ small helpers
def domain(url):
    """ "https://www.bbc.com/news/x" -> "bbc.com" """
    host = urllib.parse.urlparse(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _matches(host, names):
    """True if `host` is one of `names`, or a sub-domain of one ("news.bbc.com" matches "bbc.com"). The "." in the test stops "notbbc.com" from matching."""
    return any(host == n or host.endswith("." + n) for n in names)


def is_trusted(url):
    """Is this web address on the trusted list?"""
    return _matches(domain(url), TRUSTED)


def is_blocked(url):
    """Is this web address on the blocked list?"""
    return _matches(domain(url), BLOCKED)


def clean_text(text):
    """Plain text from a search snippet: no HTML tags or entities, single spaces."""
    # Remove HTML tags (anything between < and >), then decode entities like &amp; into the real characters.
    text = html.unescape(re.sub(r"<[^>]+>", "", text or ""))
    # Replace control characters (hidden, non-printing codes) with spaces; tab and newline are not in the pattern and are tidied by the next line.
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", text)
    # split() with no argument splits on any run of whitespace, so joining with one space squeezes it all to single spaces.
    return " ".join(text.split())


def nice_date(text):
    """ "2026-09-30T14:00:00Z" -> "Sep 30, 2026"; anything else ("2 days ago") is kept as it is. """
    if not text:
        return ""
    try:
        # Read an ISO date (year-month-day, time, "Z" = UTC). Python wants "+00:00" instead of "Z", and only the first 25 characters matter.
        d = datetime.fromisoformat(text.strip().replace("Z", "+00:00")[:25])
        # d.day is used (not %d) so the day has no leading zero: "Sep 30", "Sep 3".
        return f"{d:%b} {d.day}, {d.year}"
    # Not an ISO date ("2 days ago"): keep the original words, cleaned and limited to 30 characters.
    except ValueError:
        return clean_text(text)[:30]


def web_title(title, url, date=""):
    """The note title: what the page is, WHERE it's from and WHEN (so the model can cite it)."""
    # "bbc.com, Sep 30, 2026" or just "bbc.com" when there is no date.
    where = domain(url) + (f", {date}" if date else "")
    title = clean_text(title)
    # No title? Then just the where/when.
    return f"{title} - {where}" if title else where


def cut(text, limit=NOTE_CHARS):
    """At most `limit` characters, ending at a word (or sentence) boundary."""
    # Squeeze whitespace, and return the text unchanged if it already fits.
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    # Cut at the limit, then back up to the last space so no word is chopped in half.
    text = text[:limit].rsplit(" ", 1)[0]
    # Find the last sentence end (". ") in what is left.
    end = text.rfind(". ")
    # If that sentence end is past the halfway point, stop there (a clean sentence). Otherwise keep the words and add " ...".
    return text[:end + 1] if end > limit // 2 else text + " ..."


def best_passage(text, question, words=PASSAGE_WORDS):
    """The ~120-word piece of a long page that shares the most keywords with the question."""
    # Split the page text into words.
    tokens = text.split()
    # Short enough already: keep it all.
    if len(tokens) <= words:
        return " ".join(tokens)
    # The question's important words, as a set, to compare with each piece.
    want = set(keywords(question))
    # Track the best-scoring starting word position and its score.
    best, best_score = 0, -1
    # Slide a window of `words` words along the text, moving half a window each time, so windows overlap and a good passage is not cut in two.
    for start in range(0, len(tokens) - words // 2, words // 2):
        # The words in this window, lower-cased with punctuation trimmed from the ends, as a set.
        piece = {w.strip(".,;:!?()\"'").lower() for w in tokens[start:start + words]}
        # Score = how many question keywords appear in this window.
        score = len(want & piece)
        if score > best_score:
            best, best_score = start, score
    return " ".join(tokens[best:best + words])


# Lines that are page clutter, not content: adverts, subscribe boxes, "read more", cookie notices, menu words, or lines with no letters/digits at all (\W*$ = only symbols). Matched at the start of a line, ignoring capitals.
JUNK = re.compile(r"^(advertisement|subscribe|sign up|share this|related:|read more|cookie|accept all|"
                  r"skip to|menu|log ?in|follow us|all rights reserved|\W*$)", re.I)


class _PageText(HTMLParser):
    """Collects the text of a page's paragraphs (<p>, <li>, headings), skipping menus and scripts.

    HTMLParser calls handle_starttag / handle_endtag / handle_data as it walks through the page. We count how deep we are inside
    "skip" tags (menus, scripts...) and "keep" tags (paragraphs...) and only collect text when inside a keep tag and not inside a skip tag.
    """
    # Tags whose whole content is ignored (code, menus, headers/footers, forms, buttons...).
    SKIP = {"script", "style", "nav", "header", "footer", "aside", "form", "noscript", "svg", "button"}
    # Tags that hold the real reading text (paragraphs, list items, headings, table cells, quotes).
    KEEP = {"p", "li", "h1", "h2", "h3", "td", "blockquote"}

    def __init__(self):
        # convert_charrefs=True turns &amp; style codes into real characters for us.
        super().__init__(convert_charrefs=True)
        # skip/keep: how many such tags we are currently inside; parts: finished paragraphs; cur: text pieces of the paragraph being read.
        self.skip, self.keep, self.parts, self.cur = 0, 0, [], []

    def handle_starttag(self, tag, attrs):
        """A tag opened: go one level deeper into a skip or a keep area."""
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.KEEP:
            self.keep += 1

    def handle_endtag(self, tag):
        """A tag closed: step out of the area; when a keep tag closes, finish the paragraph."""
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.KEEP and self.keep:
            self.keep -= 1
            # Join the pieces of the paragraph and squeeze whitespace.
            line = " ".join("".join(self.cur).split())
            # Keep it only if it has at least 6 words (drops captions, labels) and is not clutter (JUNK).
            if len(line.split()) >= 6 and not JUNK.match(line):
                self.parts.append(line)
            # Start a fresh paragraph.
            self.cur = []

    def handle_data(self, data):
        """Some text between tags: remember it only when inside a paragraph and not inside a skipped area."""
        if self.keep and not self.skip:
            self.cur.append(data)


def page_text(raw_html):
    """The readable text of a web page (paragraphs only, no menus, ads or scripts)."""
    # One parser per page.
    parser = _PageText()
    # feed() reads the HTML; badly broken HTML can raise an error.
    try:
        parser.feed(raw_html)
    except Exception:            # a broken page: keep whatever was read before it broke
        pass
    # Paragraphs on separate lines.
    return "\n".join(parser.parts)


# ------------------------------------------------------------------ the internet
# What was just downloaded is remembered for a short time, so the same address asked twice a moment apart (a follow-up, a retry, two parts of one answer looking
# up the same place or page) is not downloaded twice. Short on purpose: prices and scores must still be fresh. Only successful, small answers are kept.
CACHE_SECONDS = 45
CACHE_MAX = 200
CACHE_BIGGEST = 300_000
_recent = {}
_recent_lock = threading.Lock()


def forget_recent():
    """Empty the memory of recent downloads (tests, and "Check again")."""
    with _recent_lock:
        _recent.clear()


def get(url, headers=None, limit=2_000_000, timeout=None):
    """Download `url` (at most `limit` bytes) and return it as text. An answer from the last CACHE_SECONDS is reused; `timeout` is how long one wait may take."""
    key = (url, tuple(sorted((headers or {}).items())), limit)
    now = time.monotonic()
    with _recent_lock:
        hit = _recent.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    # Build the request with our polite User-Agent plus any extra headers (the ** unpacks a dict into the dict being built).
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    # Open the address, waiting at most `timeout` (TIMEOUT) seconds.
    with urllib.request.urlopen(req, timeout=timeout or TIMEOUT) as r:
        # Use the encoding the site declares (UTF-8 if it says nothing).
        charset = r.headers.get_content_charset() or "utf-8"
        # Read at most `limit` bytes (about 2 MB) so a huge page cannot use all memory; "replace" swaps unreadable bytes for a placeholder instead of crashing.
        text = r.read(limit).decode(charset, "replace")
    if len(text) <= CACHE_BIGGEST:
        with _recent_lock:
            if len(_recent) >= CACHE_MAX:                         # full: drop what is already out of date, or the oldest
                for k in [k for k, v in _recent.items() if now - v[0] >= CACHE_SECONDS] or [min(_recent, key=lambda k: _recent[k][0])]:
                    _recent.pop(k, None)
            _recent[key] = (now, text)
    return text


def run_together(jobs, budget):
    """Run the functions in `jobs` (no arguments each) at the same time and wait for all of them, but no longer than `budget` seconds in all.
    Returns one entry per job, in the same order: its result, or None when it failed or was still not finished (it is left to end by itself)."""
    out = [None] * len(jobs)

    def work(i, fn):
        try:
            out[i] = fn()
        except Exception:
            out[i] = None

    threads = [threading.Thread(target=work, args=(i, fn), daemon=True) for i, fn in enumerate(jobs)]
    for t in threads:
        t.start()
    end = time.monotonic() + budget
    for t in threads:
        t.join(max(0.0, end - time.monotonic()))
    return list(out)


def get_json(url, headers=None):
    """Download `url` and parse the JSON answer into Python lists and dicts."""
    return json.loads(get(url, headers))


def post_json(url, body, headers=None, limit=2_000_000):
    """POST `body` (a dict) as JSON and return the JSON answer."""
    # A POST request carries a body: the dict turned into JSON text, then into bytes.
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"User-Agent": USER_AGENT, "Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read(limit).decode("utf-8", "replace"))


# ------------------------------------------------------------------ sources
def search_wikipedia(question, k=3, fetch=get_json):
    """Live Wikipedia search (free, no key): the opening of the k best articles."""
    # Build the query-string part of the address (urlencode escapes spaces and symbols). It asks Wikipedia's API to search for the question and return the intro text of each hit plus its address.
    q = urllib.parse.urlencode({
        "action": "query", "format": "json", "formatversion": 2, "generator": "search",
        "gsrsearch": question, "gsrlimit": k, "prop": "extracts|info", "exintro": 1,
        "explaintext": 1, "exlimit": k, "inprop": "url"})
    # `fetch` is a parameter so tests can pass a fake instead of using the real internet.
    data = fetch("https://en.wikipedia.org/w/api.php?" + q)
    # Pages sorted into Wikipedia's search order ("index"); 99 for any page missing it.
    pages = sorted(data.get("query", {}).get("pages", []), key=lambda p: p.get("index", 99))
    # The results we will return, each as {title, url, date, text}.
    out = []
    for p in pages:
        # Keep the best ~120 words of the intro; skip articles with no text.
        text = best_passage(p.get("extract", ""), question)
        if text:
            # Use the page address Wikipedia gave; if absent, build one from the title.
            url = p.get("fullurl") or "https://en.wikipedia.org/wiki/" + urllib.parse.quote(p["title"])
            out.append({"title": p["title"], "url": url, "date": "", "text": text})
    return out


def search_brave(question, k=3, key=None, fetch=get_json):
    """Brave Search API (the whole web): title, address, date and the best snippets of each result."""
    # The key can be passed in or come from the environment variable BRAVE_API_KEY (never written in the code).
    key = key or os.environ.get("BRAVE_API_KEY")
    if not key:
        raise RuntimeError("Brave search needs an API key: set BRAVE_API_KEY (see web_search.py)")
    # Ask for more results than needed (at least 10) because some are dropped later; text_decorations 0 = no bold markers in snippets.
    q = urllib.parse.urlencode({"q": question, "count": max(k * 3, 10), "text_decorations": 0})
    # The key goes in a request header, not in the address.
    data = fetch("https://api.search.brave.com/res/v1/web/search?" + q,
                 {"Accept": "application/json", "X-Subscription-Token": key})
    out = []
    # Each result: join its description and any extra snippets into one text.
    for r in data.get("web", {}).get("results", []):
        text = " ".join(clean_text(s) for s in [r.get("description", "")] + list(r.get("extra_snippets") or []))
        # Keep only results that have an address and some text.
        if r.get("url") and text:
            out.append({"title": clean_text(r.get("title", "")), "url": r["url"],
                        "date": nice_date(r.get("page_age") or r.get("age") or ""), "text": text})
    return out


def search_tavily(question, k=3, key=None, fetch=None, post=post_json):
    """Tavily Search API (the whole web, built for AI apps): title, address, date and a short extract of each result."""
    # The key can be passed in or read from the environment variable TAVILY_API_KEY. `fetch` is unused here: it is accepted so every source can be called the same way.
    key = key or os.environ.get("TAVILY_API_KEY")
    if not key:
        raise RuntimeError("Tavily search needs an API key: set TAVILY_API_KEY (see web_search.py)")
    # POST the question as JSON; ask for twice as many results as needed (at least 5), a quick "basic" search, and no AI-written answer (we only want sources).
    data = post("https://api.tavily.com/search", {"query": question, "max_results": max(k * 2, 5), "search_depth": "basic",
                                                   "include_answer": False}, {"Authorization": "Bearer " + key})
    out = []
    for r in data.get("results", []):
        # Tavily's "content" field is a short extract of the page.
        text = clean_text(r.get("content", ""))
        if r.get("url") and text:
            out.append({"title": clean_text(r.get("title", "")), "url": r["url"], "date": nice_date(r.get("published_date") or ""), "text": text})
    return out


def search_gemini(question, k=3, key=None, fetch=None, post=post_json):
    """Google's Gemini API with "Grounding with Google Search" (free tier; needs a key from Google AI Studio). Unlike the other sources it returns
    ONE note: Gemini's short answer written from live Google results, plus the pages it used. Your question goes to Google (see docs/DEPLOY.md)."""
    # Key from the argument or the environment variable GEMINI_API_KEY.
    key = key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("Gemini search needs an API key: set GEMINI_API_KEY (see web_search.py)")
    # The model can be changed with the GEMINI_MODEL environment variable.
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    # Ask Gemini to answer briefly with the date, and switch on its Google Search tool so the answer comes from live results. The key goes in a header.
    data = post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                {"contents": [{"parts": [{"text": question + "\n\nAnswer briefly and factually, with the date of the information."}]}],
                 "tools": [{"google_search": {}}]}, {"x-goog-api-key": key})
    # Gemini may return several candidate answers; use the first (or an empty one if none).
    cand = (data.get("candidates") or [{}])[0]
    # Join the pieces of the answer text.
    text = clean_text(" ".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", [])))
    if not text:
        return []
    # The pages Gemini says it used ("grounding chunks"), and the first that has an address.
    chunks = [c.get("web", {}) for c in (cand.get("groundingMetadata") or {}).get("groundingChunks", [])]
    first = next((c for c in chunks if c.get("uri")), {})
    # Return just one note: the answer text, titled with the first source page if known.
    return [{"title": "Google Search (via Gemini)" + (f": {clean_text(first['title'])}" if first.get("title") else ""),
             "url": first.get("uri") or "https://ai.google.dev/gemini-api/docs/google-search", "date": "", "text": text}]


# Name -> function, so a source can be chosen by name (--source brave).
SOURCES = {"wikipedia": search_wikipedia, "brave": search_brave, "tavily": search_tavily, "gemini": search_gemini}


def pick_source(name="auto"):
    """Turn the user's choice into a real source name. "auto" picks the first source whose key is set (tavily, brave, gemini), else the free wikipedia. An unknown name stops the program with a message."""
    if name == "auto":
        return next((n for n, var in (("tavily", "TAVILY_API_KEY"), ("brave", "BRAVE_API_KEY"), ("gemini", "GEMINI_API_KEY")) if os.environ.get(var)), "wikipedia")
    if name not in SOURCES:
        raise SystemExit(f"unknown web source {name!r}: choose from auto, {', '.join(SOURCES)}")
    return name


PAGE_BUDGET = 8        # seconds in all for opening the result pages (they are opened together); a page that is slower keeps its short search snippet
PAGE_BYTES = 800_000   # a page is read up to this size (the best passage is near the top; reading 2 MB only costs time)


def read_pages(results, question, fetch_page=None, budget=PAGE_BUDGET):
    """Open each result's page and keep its best-matching passage (better than a short snippet). The pages are opened at the same time, so one slow site no longer
    holds up the others; after `budget` seconds the pages still loading are given up on and keep their snippet."""
    fetch_page = fetch_page or (lambda url: get(url, limit=PAGE_BYTES, timeout=budget))
    pages = run_together([(lambda u=r["url"]: page_text(fetch_page(u))) for r in results], budget)
    for r, text in zip(results, pages):
        # Only use the page if it gave at least 40 words; otherwise the short search snippet stays (a page that failed or was too slow gave None).
        if text and len(text.split()) >= 40:
            r["text"] = best_passage(text, question)
    return results


def rank(results, k, one_per_site=True):
    """Blocked sites out, one note per site (more views, not one site repeated), trusted sites first
    (otherwise the search order)."""
    # `seen` holds the sites already used; `kept` the results we keep.
    seen, kept = set(), []
    for r in results:
        # The key for "one note per site" is the domain; otherwise the full address.
        key = domain(r["url"]) if one_per_site else r["url"]
        # Skip blocked sites and sites we already have a note from.
        if is_blocked(r["url"]) or key in seen:
            continue
        seen.add(key)
        kept.append(r)
    # Sort trusted sites first. The sort key is False (0) for trusted and True (1) for others, and Python's sort keeps the old order among equals.
    kept.sort(key=lambda r: not is_trusted(r["url"]))     # stable: keeps the search order otherwise
    # Only the first k.
    return kept[:k]


def web_notes(question, k=3, source="auto", read=False, fetch=None, fetch_page=None):
    """Search the web for `question` and return up to k notes for the chat ({"title", "text", "url"}).

    read=True also opens the pages (slower, but the passage is chosen from the whole page).
    Never raises for network trouble: on any error it returns [] and the chat goes on without notes.
    """
    # Settle which source to use.
    name = pick_source(source)
    try:
        # Ask for twice as many results as needed (k * 2) so ranking has some to choose from. Each source function has its own way of searching.
        results = SOURCES[name](question, k * 2, fetch=fetch or get_json)
        # Rank: blocked sites out, trusted first, one per site.
        results = rank(results, k, one_per_site=name != "wikipedia")   # Wikipedia: every result is one site
        # Optionally read the whole pages for better passages.
        if read:
            results = read_pages(results, question, fetch_page)
    except Exception as e:                 # offline, a timeout, a bad key, a changed API...
        # Print the problem for the person running the server, and carry on with no notes.
        print(f"(web search failed: {e})")
        return []
    # Turn each result into a note: title with where/when, text cut to the size cap, and the address.
    return [{"title": web_title(r["title"], r["url"], r["date"]), "text": cut(r["text"]), "url": r["url"]}
            for r in results]


# ------------------------------------------------------------------ weather (Open-Meteo: free, no key)
# Does the question sound like a weather question? Two patterns joined by |: the words weather/forecast; or "will it rain"-style phrases;
# or "how hot is it"; or "temperature today/tomorrow/in...".
WEATHER_Q = re.compile(r"\b(weather|forecast)\b|\b(is it|will it|going to|gonna|does it look like) (be |going to )?(rain|raining|snow|snowing|hot|cold|warm|sunny|windy|storm)|"
                       r"\bhow (hot|cold|warm) is it\b|\btemperature (today|tonight|tomorrow|outside|now|right now|in)\b", re.I)
# Where a place name ends: the first of these filler/time words (and everything after it), or trailing punctuation. Used to trim "Paris today" down to "Paris".
PLACE_STOP = re.compile(r"\b(today|tonight|tomorrow|now|right|this|next|on|please|and|will|is|be|like|currently|later|this|at|the weather|weather|forecast)\b.*$|[?!.]+$", re.I)
# WMO weather codes (the world standard used by Open-Meteo) -> plain words, e.g. 61 = light rain.
WMO = {0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
       56: "freezing drizzle", 57: "heavy freezing drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "heavy freezing rain",
       71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "light showers", 81: "showers", 82: "heavy showers", 85: "snow showers",
       86: "heavy snow showers", 95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail"}


def is_weather_question(text):
    """True if the text looks like a weather question."""
    return bool(WEATHER_Q.search(text or ""))


def weather_place(question, default=""):
    """The place named in a weather question ("weather in Paris today" -> "Paris"), else the default place."""
    # Find "in/for/at/near/around <place>": group 1 is the words after it.
    m = re.search(r"\b(?:in|for|at|near|around)\s+([a-z][a-z'.\- ,]*)", question or "", re.I)
    if m:
        # Cut off time words ("today") and trailing punctuation, tidy the edges.
        place = PLACE_STOP.sub("", m.group(1)).strip(" ,.-")
        # Drop a leading "the" or "my".
        place = re.sub(r"^(the|my)\s+", "", place, flags=re.I)
        # Reject words that follow "in" but are not places ("in the morning", "in fact").
        if place and place.lower() not in ("morning", "afternoon", "evening", "night", "general", "case", "fact", "order"):
            return place
    # No place named: use the default place from settings (or nothing).
    return default or ""


def _f(c):
    """Celsius -> Fahrenheit, rounded to a whole number."""
    return round(c * 9 / 5 + 32)


def weather_notes(question, default_place="", fetch=get_json, today=None):
    """One note with the real forecast for the place in the question (or the default place); [] when there is no place or the service fails."""
    # Which place to look up.
    place = weather_place(question, default_place)
    # No place at all: we cannot give a forecast.
    if not place:
        return []
    try:
        # "Austin, Texas" -> name "Austin" and region "Texas".
        name, _, region = place.partition(",")
        # Step 1: Open-Meteo's geocoding service turns the place name into coordinates (up to 5 matches).
        geo = fetch("https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({"name": name.strip(), "count": 5, "language": "en"}))
        hits = geo.get("results") or []
        # Place not found: no note.
        if not hits:
            return []
        # Pick the match whose country or state contains the region the person typed; if none, or no region was given, take the first match.
        want = region.strip().lower()
        hit = next((h for h in hits if want and want in (str(h.get("country", "")) + " " + str(h.get("admin1", ""))).lower()), hits[0])
        # Step 2: ask for the forecast at those coordinates, in the place's own timezone, for 3 days: current temperature, "feels like", humidity, weather code and wind, plus each day's code, high, low and rain chance.
        q = urllib.parse.urlencode({"latitude": hit["latitude"], "longitude": hit["longitude"], "timezone": "auto", "forecast_days": 3,
                                    "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
                                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"})
        data = fetch("https://api.open-meteo.com/v1/forecast?" + q)
    except Exception as e:                       # offline, a timeout, a changed API...
        print(f"(weather lookup failed: {e})")
        return []
    # `cur` = right now, `day` = the daily lists. No temperature in the answer means it is unusable.
    cur, day = data.get("current") or {}, data.get("daily") or {}
    if "temperature_2m" not in cur:
        return []
    # A readable place name, such as "Austin, Texas, United States".
    where = ", ".join(x for x in (hit.get("name"), hit.get("admin1"), hit.get("country")) if x)
    # Temperature, "feels like" (falls back to the real temperature), wind speed.
    t, feels, wind = cur["temperature_2m"], cur.get("apparent_temperature", cur["temperature_2m"]), cur.get("wind_speed_10m", 0)
    # First line: now, in both Celsius and Fahrenheit; wind in km/h and mph (1 km/h = 0.621 mph). \u00b0 is the degree sign.
    parts = [f"Right now: {WMO.get(cur.get('weather_code'), 'unknown conditions')}, {t:.0f}\u00b0C ({_f(t)}\u00b0F), feels like {feels:.0f}\u00b0C ({_f(feels)}\u00b0F), "
             f"wind {wind:.0f} km/h ({wind * 0.621:.0f} mph), humidity {cur.get('relative_humidity_2m', '?')}%."]
    # Names for the three forecast days.
    labels = ["Today", "Tomorrow", "The day after"]
    # One line per day from the daily lists.
    for i, d in enumerate(day.get("time", [])[:3]):
        hi, lo = day["temperature_2m_max"][i], day["temperature_2m_min"][i]
        # Rain chance may be missing from the answer, so use a list of None as the fallback.
        rain = (day.get("precipitation_probability_max") or [None] * 3)[i]
        parts.append(f"{labels[i]} ({d}): {WMO.get(day['weather_code'][i], 'unknown')}, high {hi:.0f}\u00b0C ({_f(hi)}\u00b0F), low {lo:.0f}\u00b0C ({_f(lo)}\u00b0F)"
                     + (f", {rain}% chance of rain." if rain is not None else "."))
    # When the reading was taken, in a nice date format.
    stamp = nice_date(str(cur.get("time", "")))
    # A single note, with the data source named in the title.
    return [{"title": f"Weather in {where} - open-meteo.com" + (f", {stamp}" if stamp else ""), "text": " ".join(parts), "url": "https://open-meteo.com/"}]


def web_answer(question, k=3, place="", source="auto", read=False):
    """What the chat calls: a real forecast for a weather question, otherwise the web search."""
    # Weather questions get the real forecast, if it works.
    if is_weather_question(question):
        notes = weather_notes(question, place)
        if notes:
            return notes
    # Anything else (or a failed forecast) falls back to the normal web search.
    return web_notes(question, k, source=source, read=read)


def main():
    """Command-line entry point: search the web the same way the chat does and print the notes."""
    # Describe the options the person can type after the command.
    p = argparse.ArgumentParser(description="Search the web the way the chat does, and print the notes")
    p.add_argument("question")
    p.add_argument("--source", default="auto", help="auto, wikipedia, brave, tavily or gemini")
    p.add_argument("--k", type=int, default=3)
    p.add_argument("--read", action="store_true", help="open the pages too (slower, better passages)")
    # Read what was typed.
    a = p.parse_args()
    notes = web_notes(a.question, a.k, a.source, a.read)
    if not notes:
        print("(nothing found)")
    # Print each note numbered from 1, with its web address and text.
    for i, n in enumerate(notes, 1):
        print(f"[{i}] {n['title']}\n    {n['url']}\n    {n['text']}\n")


# Run main() only when this file is started directly, not when another file imports it.
if __name__ == "__main__":
    main()
