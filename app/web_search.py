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
import argparse
import html
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser

from wiki_index import keywords

USER_AGENT = "A.I-SML/1.0 (personal research project; https://github.com/dmccottrell/a.i-sml)"
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
    return any(host == n or host.endswith("." + n) for n in names)


def is_trusted(url):
    return _matches(domain(url), TRUSTED)


def is_blocked(url):
    return _matches(domain(url), BLOCKED)


def clean_text(text):
    """Plain text from a search snippet: no HTML tags or entities, single spaces."""
    text = html.unescape(re.sub(r"<[^>]+>", "", text or ""))
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", text)
    return " ".join(text.split())


def nice_date(text):
    """ "2026-09-30T14:00:00Z" -> "Sep 30, 2026"; anything else ("2 days ago") is kept as it is. """
    if not text:
        return ""
    try:
        d = datetime.fromisoformat(text.strip().replace("Z", "+00:00")[:25])
        return f"{d:%b} {d.day}, {d.year}"
    except ValueError:
        return clean_text(text)[:30]


def web_title(title, url, date=""):
    """The note title: what the page is, WHERE it's from and WHEN (so the model can cite it)."""
    where = domain(url) + (f", {date}" if date else "")
    title = clean_text(title)
    return f"{title} - {where}" if title else where


def cut(text, limit=NOTE_CHARS):
    """At most `limit` characters, ending at a word (or sentence) boundary."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    text = text[:limit].rsplit(" ", 1)[0]
    end = text.rfind(". ")
    return text[:end + 1] if end > limit // 2 else text + " ..."


def best_passage(text, question, words=PASSAGE_WORDS):
    """The ~120-word piece of a long page that shares the most keywords with the question."""
    tokens = text.split()
    if len(tokens) <= words:
        return " ".join(tokens)
    want = set(keywords(question))
    best, best_score = 0, -1
    for start in range(0, len(tokens) - words // 2, words // 2):
        piece = {w.strip(".,;:!?()\"'").lower() for w in tokens[start:start + words]}
        score = len(want & piece)
        if score > best_score:
            best, best_score = start, score
    return " ".join(tokens[best:best + words])


JUNK = re.compile(r"^(advertisement|subscribe|sign up|share this|related:|read more|cookie|accept all|"
                  r"skip to|menu|log ?in|follow us|all rights reserved|\W*$)", re.I)


class _PageText(HTMLParser):
    """Collects the text of a page's paragraphs (<p>, <li>, headings), skipping menus and scripts."""
    SKIP = {"script", "style", "nav", "header", "footer", "aside", "form", "noscript", "svg", "button"}
    KEEP = {"p", "li", "h1", "h2", "h3", "td", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip, self.keep, self.parts, self.cur = 0, 0, [], []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.KEEP:
            self.keep += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.KEEP and self.keep:
            self.keep -= 1
            line = " ".join("".join(self.cur).split())
            if len(line.split()) >= 6 and not JUNK.match(line):
                self.parts.append(line)
            self.cur = []

    def handle_data(self, data):
        if self.keep and not self.skip:
            self.cur.append(data)


def page_text(raw_html):
    """The readable text of a web page (paragraphs only, no menus, ads or scripts)."""
    parser = _PageText()
    try:
        parser.feed(raw_html)
    except Exception:            # a broken page: keep whatever was read before it broke
        pass
    return "\n".join(parser.parts)


# ------------------------------------------------------------------ the internet
def get(url, headers=None, limit=2_000_000):
    """Download `url` (at most `limit` bytes) and return it as text."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        charset = r.headers.get_content_charset() or "utf-8"
        return r.read(limit).decode(charset, "replace")


def get_json(url, headers=None):
    return json.loads(get(url, headers))


def post_json(url, body, headers=None, limit=2_000_000):
    """POST `body` (a dict) as JSON and return the JSON answer."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"User-Agent": USER_AGENT, "Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read(limit).decode("utf-8", "replace"))


# ------------------------------------------------------------------ sources
def search_wikipedia(question, k=3, fetch=get_json):
    """Live Wikipedia search (free, no key): the opening of the k best articles."""
    q = urllib.parse.urlencode({
        "action": "query", "format": "json", "formatversion": 2, "generator": "search",
        "gsrsearch": question, "gsrlimit": k, "prop": "extracts|info", "exintro": 1,
        "explaintext": 1, "exlimit": k, "inprop": "url"})
    data = fetch("https://en.wikipedia.org/w/api.php?" + q)
    pages = sorted(data.get("query", {}).get("pages", []), key=lambda p: p.get("index", 99))
    out = []
    for p in pages:
        text = best_passage(p.get("extract", ""), question)
        if text:
            url = p.get("fullurl") or "https://en.wikipedia.org/wiki/" + urllib.parse.quote(p["title"])
            out.append({"title": p["title"], "url": url, "date": "", "text": text})
    return out


def search_brave(question, k=3, key=None, fetch=get_json):
    """Brave Search API (the whole web): title, address, date and the best snippets of each result."""
    key = key or os.environ.get("BRAVE_API_KEY")
    if not key:
        raise RuntimeError("Brave search needs an API key: set BRAVE_API_KEY (see web_search.py)")
    q = urllib.parse.urlencode({"q": question, "count": max(k * 3, 10), "text_decorations": 0})
    data = fetch("https://api.search.brave.com/res/v1/web/search?" + q,
                 {"Accept": "application/json", "X-Subscription-Token": key})
    out = []
    for r in data.get("web", {}).get("results", []):
        text = " ".join(clean_text(s) for s in [r.get("description", "")] + list(r.get("extra_snippets") or []))
        if r.get("url") and text:
            out.append({"title": clean_text(r.get("title", "")), "url": r["url"],
                        "date": nice_date(r.get("page_age") or r.get("age") or ""), "text": text})
    return out


def search_tavily(question, k=3, key=None, fetch=None, post=post_json):
    """Tavily Search API (the whole web, built for AI apps): title, address, date and a short extract of each result."""
    key = key or os.environ.get("TAVILY_API_KEY")
    if not key:
        raise RuntimeError("Tavily search needs an API key: set TAVILY_API_KEY (see web_search.py)")
    data = post("https://api.tavily.com/search", {"query": question, "max_results": max(k * 2, 5), "search_depth": "basic",
                                                   "include_answer": False}, {"Authorization": "Bearer " + key})
    out = []
    for r in data.get("results", []):
        text = clean_text(r.get("content", ""))
        if r.get("url") and text:
            out.append({"title": clean_text(r.get("title", "")), "url": r["url"], "date": nice_date(r.get("published_date") or ""), "text": text})
    return out


def search_gemini(question, k=3, key=None, fetch=None, post=post_json):
    """Google's Gemini API with "Grounding with Google Search" (free tier; needs a key from Google AI Studio). Unlike the other sources it returns
    ONE note: Gemini's short answer written from live Google results, plus the pages it used. Your question goes to Google (see docs/DEPLOY.md)."""
    key = key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("Gemini search needs an API key: set GEMINI_API_KEY (see web_search.py)")
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    data = post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                {"contents": [{"parts": [{"text": question + "\n\nAnswer briefly and factually, with the date of the information."}]}],
                 "tools": [{"google_search": {}}]}, {"x-goog-api-key": key})
    cand = (data.get("candidates") or [{}])[0]
    text = clean_text(" ".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", [])))
    if not text:
        return []
    chunks = [c.get("web", {}) for c in (cand.get("groundingMetadata") or {}).get("groundingChunks", [])]
    first = next((c for c in chunks if c.get("uri")), {})
    return [{"title": "Google Search (via Gemini)" + (f": {clean_text(first['title'])}" if first.get("title") else ""),
             "url": first.get("uri") or "https://ai.google.dev/gemini-api/docs/google-search", "date": "", "text": text}]


SOURCES = {"wikipedia": search_wikipedia, "brave": search_brave, "tavily": search_tavily, "gemini": search_gemini}


def pick_source(name="auto"):
    if name == "auto":
        return next((n for n, var in (("tavily", "TAVILY_API_KEY"), ("brave", "BRAVE_API_KEY"), ("gemini", "GEMINI_API_KEY")) if os.environ.get(var)), "wikipedia")
    if name not in SOURCES:
        raise SystemExit(f"unknown web source {name!r}: choose from auto, {', '.join(SOURCES)}")
    return name


def read_pages(results, question, fetch_page=get):
    """Open each result's page and keep its best-matching passage (better than a short snippet)."""
    for r in results:
        try:
            text = page_text(fetch_page(r["url"]))
        except Exception:
            continue             # the page didn't load: keep the snippet
        if len(text.split()) >= 40:
            r["text"] = best_passage(text, question)
    return results


def rank(results, k, one_per_site=True):
    """Blocked sites out, one note per site (more views, not one site repeated), trusted sites first
    (otherwise the search order)."""
    seen, kept = set(), []
    for r in results:
        key = domain(r["url"]) if one_per_site else r["url"]
        if is_blocked(r["url"]) or key in seen:
            continue
        seen.add(key)
        kept.append(r)
    kept.sort(key=lambda r: not is_trusted(r["url"]))     # stable: keeps the search order otherwise
    return kept[:k]


def web_notes(question, k=3, source="auto", read=False, fetch=None, fetch_page=None):
    """Search the web for `question` and return up to k notes for the chat ({"title", "text", "url"}).

    read=True also opens the pages (slower, but the passage is chosen from the whole page).
    Never raises for network trouble: on any error it returns [] and the chat goes on without notes.
    """
    name = pick_source(source)
    try:
        results = SOURCES[name](question, k * 2, fetch=fetch or get_json)
        results = rank(results, k, one_per_site=name != "wikipedia")   # Wikipedia: every result is one site
        if read:
            results = read_pages(results, question, fetch_page or get)
    except Exception as e:                 # offline, a timeout, a bad key, a changed API...
        print(f"(web search failed: {e})")
        return []
    return [{"title": web_title(r["title"], r["url"], r["date"]), "text": cut(r["text"]), "url": r["url"]}
            for r in results]


# ------------------------------------------------------------------ weather (Open-Meteo: free, no key)
WEATHER_Q = re.compile(r"\b(weather|forecast)\b|\b(is it|will it|going to|gonna|does it look like) (be |going to )?(rain|raining|snow|snowing|hot|cold|warm|sunny|windy|storm)|"
                       r"\bhow (hot|cold|warm) is it\b|\btemperature (today|tonight|tomorrow|outside|now|right now|in)\b", re.I)
PLACE_STOP = re.compile(r"\b(today|tonight|tomorrow|now|right|this|next|on|please|and|will|is|be|like|currently|later|this|at|the weather|weather|forecast)\b.*$|[?!.]+$", re.I)
WMO = {0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
       56: "freezing drizzle", 57: "heavy freezing drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "heavy freezing rain",
       71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "light showers", 81: "showers", 82: "heavy showers", 85: "snow showers",
       86: "heavy snow showers", 95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail"}


def is_weather_question(text):
    return bool(WEATHER_Q.search(text or ""))


def weather_place(question, default=""):
    """The place named in a weather question ("weather in Paris today" -> "Paris"), else the default place."""
    m = re.search(r"\b(?:in|for|at|near|around)\s+([a-z][a-z'.\- ,]*)", question or "", re.I)
    if m:
        place = PLACE_STOP.sub("", m.group(1)).strip(" ,.-")
        place = re.sub(r"^(the|my)\s+", "", place, flags=re.I)
        if place and place.lower() not in ("morning", "afternoon", "evening", "night", "general", "case", "fact", "order"):
            return place
    return default or ""


def _f(c):
    return round(c * 9 / 5 + 32)


def weather_notes(question, default_place="", fetch=get_json, today=None):
    """One note with the real forecast for the place in the question (or the default place); [] when there is no place or the service fails."""
    place = weather_place(question, default_place)
    if not place:
        return []
    try:
        name, _, region = place.partition(",")
        geo = fetch("https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({"name": name.strip(), "count": 5, "language": "en"}))
        hits = geo.get("results") or []
        if not hits:
            return []
        want = region.strip().lower()
        hit = next((h for h in hits if want and want in (str(h.get("country", "")) + " " + str(h.get("admin1", ""))).lower()), hits[0])
        q = urllib.parse.urlencode({"latitude": hit["latitude"], "longitude": hit["longitude"], "timezone": "auto", "forecast_days": 3,
                                    "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
                                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"})
        data = fetch("https://api.open-meteo.com/v1/forecast?" + q)
    except Exception as e:                       # offline, a timeout, a changed API...
        print(f"(weather lookup failed: {e})")
        return []
    cur, day = data.get("current") or {}, data.get("daily") or {}
    if "temperature_2m" not in cur:
        return []
    where = ", ".join(x for x in (hit.get("name"), hit.get("admin1"), hit.get("country")) if x)
    t, feels, wind = cur["temperature_2m"], cur.get("apparent_temperature", cur["temperature_2m"]), cur.get("wind_speed_10m", 0)
    parts = [f"Right now: {WMO.get(cur.get('weather_code'), 'unknown conditions')}, {t:.0f}\u00b0C ({_f(t)}\u00b0F), feels like {feels:.0f}\u00b0C ({_f(feels)}\u00b0F), "
             f"wind {wind:.0f} km/h ({wind * 0.621:.0f} mph), humidity {cur.get('relative_humidity_2m', '?')}%."]
    labels = ["Today", "Tomorrow", "The day after"]
    for i, d in enumerate(day.get("time", [])[:3]):
        hi, lo = day["temperature_2m_max"][i], day["temperature_2m_min"][i]
        rain = (day.get("precipitation_probability_max") or [None] * 3)[i]
        parts.append(f"{labels[i]} ({d}): {WMO.get(day['weather_code'][i], 'unknown')}, high {hi:.0f}\u00b0C ({_f(hi)}\u00b0F), low {lo:.0f}\u00b0C ({_f(lo)}\u00b0F)"
                     + (f", {rain}% chance of rain." if rain is not None else "."))
    stamp = nice_date(str(cur.get("time", "")))
    return [{"title": f"Weather in {where} - open-meteo.com" + (f", {stamp}" if stamp else ""), "text": " ".join(parts), "url": "https://open-meteo.com/"}]


def web_answer(question, k=3, place="", source="auto", read=False):
    """What the chat calls: a real forecast for a weather question, otherwise the web search."""
    if is_weather_question(question):
        notes = weather_notes(question, place)
        if notes:
            return notes
    return web_notes(question, k, source=source, read=read)


def main():
    p = argparse.ArgumentParser(description="Search the web the way the chat does, and print the notes")
    p.add_argument("question")
    p.add_argument("--source", default="auto", help="auto, wikipedia, brave, tavily or gemini")
    p.add_argument("--k", type=int, default=3)
    p.add_argument("--read", action="store_true", help="open the pages too (slower, better passages)")
    a = p.parse_args()
    notes = web_notes(a.question, a.k, a.source, a.read)
    if not notes:
        print("(nothing found)")
    for i, n in enumerate(notes, 1):
        print(f"[{i}] {n['title']}\n    {n['url']}\n    {n['text']}\n")


if __name__ == "__main__":
    main()
