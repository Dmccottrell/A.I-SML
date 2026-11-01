"""
live_data.py - Exact, live facts for questions where a number must be right: sums, dates, prices, rates, scores, time, definitions, news.

WHAT THIS FILE DOES
    A language model guesses at arithmetic, today's date, a price or a score. This file answers those from the real source and hands the
    result to the model as a note ({"title", "text", "url", "kind": "live"}), the same way Wikipedia and web notes work. The model only has to
    put it into words. Each source is a small "provider" with a pattern for the questions it understands, so ordinary chat never triggers one.

      works offline (plain code)     calculator (sums, percentages, tips, unit conversion), dates (holidays, "what day is Christmas",
                                     "days until Thanksgiving", the weekday of any date, days between dates), local time
      online, free, no key           time in another city (Open-Meteo geocoding), currency rates (Frankfurter, European Central Bank),
                                     crypto prices (CoinGecko), stock prices (Stooq, delayed), sports results (TheSportsDB), dictionary
                                     (dictionaryapi.dev), country facts (REST Countries), public holidays (Nager.Date), news headlines
                                     (Google News RSS), books (Open Library), recipes (TheMealDB), air quality (Open-Meteo),
                                     "on this day" (Wikimedia), recent big earthquakes (USGS)
      online, optional free key      games: RAWG_API_KEY (rawg.io), films and shows: TMDB_API_KEY (themoviedb.org), for release dates

    Only the part of the question the source needs is sent (a place, a currency code, a team, a word), never the chat. `gather(question, now,
    online=...)` returns (notes, info). Online providers run only when the caller says it is online (not in private chats, not in "Wikipedia
    only" or "Model only" mode). A provider that fails, times out or finds nothing just returns nothing and the chat goes on.
    Live services change: the shapes used here come from each service's documentation, and every answer names its source and time.
"""
# Tools used below: ast (reads a sum as a safe tree instead of running it), math, operator (+ - * / as functions), os (environment variables),
# re (regular expressions = text patterns), time, urllib.parse (build safe web addresses), ElementTree (reads XML/RSS feeds),
# date/datetime/timedelta (calendar maths), Fraction (exact fractions, so 0.1 + 0.2 is exactly 0.3).
import ast
import math
import operator
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from fractions import Fraction

# web_search.py holds the small HTTP helpers (get, get_json, cut, clean_text, nice_date) that every provider below uses.
import web_search as W

# MAX_PROVIDERS = how many different sources may answer one question; MAX_NOTES = the most notes handed to the model in total.
MAX_PROVIDERS = 2          # one question rarely needs more
MAX_NOTES = 4


class Net:
    """The real internet (tests pass a fake with the same two methods).
    Every provider is given a `net` object and calls net.json(url) or net.text(url), so tests never touch the real internet."""

    def json(self, url):
        """Fetch a web address and return the reply parsed as JSON (a dict/list)."""
        return W.get_json(url)

    def text(self, url):
        """Fetch a web address and return the reply as plain text (CSV, RSS/XML ...)."""
        return W.get(url)


def _note(title, text, url=""):
    """Build one note in the shape the chat expects: {title, text (cut to 900 characters), url, kind "live"}."""
    return {"title": title, "text": W.cut(text, 900), "url": url, "kind": "live"}


def _clean(q):
    """Tidy the question: curly apostrophes become straight ones and runs of spaces/newlines become single spaces. None becomes ""."""
    return " ".join((q or "").replace("’", "'").split())


# CALCULATOR: answers sums, percentages, tips and unit conversions exactly, in plain code (no internet, no model guessing).
# =========================================================================================== calculator
def _fmt(x):
    """Format a number for people: thousands commas (1,234,567), up to 10 significant digits, scientific notation (1.5e+20) for huge or tiny values. Raises ValueError for NaN / infinity."""
    # A Fraction that is a whole number is shown as an integer (switch to scientific notation at 10**15); any other Fraction becomes a float.
    if isinstance(x, Fraction):
        if x.denominator == 1:
            n = x.numerator
            return f"{n:,}" if abs(n) < 10 ** 15 else f"{float(n):.6e}"
        x = float(x)
    # `x != x` is only true for NaN ("not a number"); so this rejects NaN and infinity.
    if x != x or x in (math.inf, -math.inf):
        raise ValueError("not a number")
    if abs(x) >= 1e15 or (x != 0 and abs(x) < 1e-6):
        return f"{x:.6e}"
    # Format with up to 10 significant digits. If Python chose "e" notation, redo it as a plain decimal and strip trailing zeros.
    # Then put commas in the whole-number part.
    s = f"{x:.10g}"
    if "e" in s:
        s = f"{x:.10f}".rstrip("0").rstrip(".")
    if "." in s:
        whole, frac = s.split(".")
        return f"{int(whole):,}.{frac}"
    return f"{int(s):,}"


def _pow(a, b):
    """a to the power b. Whole-number powers of exact Fractions stay exact; anything else uses floats. Refuses answers that would be gigantic (bit_length * power over 20000)."""
    if isinstance(a, Fraction) and isinstance(b, Fraction) and b.denominator == 1 and abs(b) <= 1000:
        if abs(a.numerator).bit_length() * abs(int(b)) > 20000:
            raise ValueError("too big")
        return a ** int(b)
    return float(a) ** float(b)


# Maps each allowed arithmetic operator in the parsed tree to the function that does it. Anything not listed here is refused.
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: _pow, ast.Mod: operator.mod}


def _eval(node):
    """Safely work out a sum from its parsed tree (never uses eval/exec, so no code in a question can run). Allowed: numbers, + - * / ** %, unary minus/plus, sqrt(). Returns a Fraction (exact) or float; raises ValueError for anything else."""
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    # A literal number. bool is excluded (True/False are ints in Python). Fraction(str(...)) keeps decimals exact.
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return Fraction(str(node.value))
    # A two-sided operation like 2 + 3: evaluate both sides, then apply the matching function from _BIN.
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        return _BIN[type(node.op)](_eval(node.left), _eval(node.right))
    # A sign in front of a value (-5 or +5).
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _eval(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    # The only function call allowed is sqrt(x). A perfect square gives an exact integer, otherwise a float.
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sqrt" and len(node.args) == 1:
        v = _eval(node.args[0])
        if v < 0:
            raise ValueError("square root of a negative number")
        r = math.sqrt(v)
        return Fraction(int(r)) if r == int(r) and Fraction(int(r)) ** 2 == v else r
    raise ValueError("not a plain sum")


# DATE_LIKE: things that look like dates or phone numbers (2024-05-01, 5/1/24, 555-1234); these are never treated as sums.
# WORD_OPS: spoken operators turned into symbols ("plus" -> +). CALC_CUE: words that hint the message is a calculation.
DATE_LIKE = re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{3}-\d{3,4}\b")
WORD_OPS = [(r"\bto the power of\b", "**"), (r"\bmultiplied by\b", "*"), (r"\bdivided by\b", "/"), (r"\bplus\b", "+"), (r"\bminus\b", "-"),
            (r"\btimes\b", "*"), (r"\bover\b", "/"), (r"\bmod(ulo)?\b", "%"), (r"×", "*"), (r"÷", "/"), (r"\^", "**")]
CALC_CUE = re.compile(r"\b(calculate|compute|solve|what is|what's|whats|how much is|work out|equals?|percent|plus|minus|times|divided|multiplied|squared|cubed|"
                      r"sqrt|square root|power of)\b|[=%]", re.I)


def _expression(q):
    """Turn the question into a clean arithmetic expression like "(15)/100*(80)" or "12*(3+4)", or return None when it is not a plain sum."""
    # Work on a lower-case copy. Each re.sub below rewrites one spoken pattern into maths. In the patterns: \d = a digit, (?:...) = a group,
    # \s = a space, (?<=\d) / (?=...) = look at the neighbouring text without consuming it.
    t = q.lower().replace("’", "'")
    if DATE_LIKE.search(t):
        return None
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)                      # 1,000 -> 1000
    # Money symbols are dropped; "15% of 80" becomes ((15)/100*(80)); roots, squares and cubes are rewritten as sqrt(...), **2 and **3.
    t = t.replace("$", "").replace("€", "").replace("£", "")
    t = re.sub(r"(\d+(?:\.\d+)?)\s*(?:%|percent)\s*of\s*(\d+(?:\.\d+)?)", r"((\1)/100*(\2))", t)
    t = re.sub(r"(?:the\s+)?square root of\s*(\d+(?:\.\d+)?)", r"sqrt(\1)", t)
    t = re.sub(r"\bsqrt\s*(\d+(?:\.\d+)?)", r"sqrt(\1)", t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*squared", r"((\1)**2)", t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*cubed", r"((\1)**3)", t)
    t = re.sub(r"(?<=\d)\s*x\s*(?=\d)", "*", t)
    # Spoken operators ("times", "divided by", "^") become symbols with spaces around them.
    for pat, rep in WORD_OPS:
        t = re.sub(pat, f" {rep} ", t)
    # Remove filler words, then trailing punctuation.
    t = re.sub(r"\b(what is|what's|whats|calculate|compute|solve|how much is|work out|equals?|the answer to|answer|please|is|=)\b", " ", t)
    t = re.sub(r"[?!.]+\s*$", "", t).strip()
    # Safety gate: after cleaning, only digits, operators, brackets, dots and sqrt(number) may remain, and there must be at least one digit.
    # Otherwise this is not a sum.
    if not re.fullmatch(r"[0-9+\-*/().%\s]*(sqrt\([0-9.]+\)[0-9+\-*/().%\s]*)*", t) or not re.search(r"\d", t):
        return None
    # A lone number with no operator is not a sum. A leftover % (modulo) is also refused here. Finally all spaces are removed.
    if not re.search(r"[+\-*/%]|sqrt|\*\*", t) or re.fullmatch(r"\s*-?\d+(\.\d+)?\s*", t):
        return None
    return None if "%" in t else re.sub(r"\s+", "", t)


# TIP: "tip on $80 at 15%". UNIT TABLES below: each maps a unit name to its size in a base unit (metres, kilograms, litres, metres/second, bytes, seconds, square metres),
# so converting is: value * size_of_from / size_of_to.
TIP = re.compile(r"\btip\b.*?\$?(\d+(?:\.\d+)?)\s*(?:dollars?)?\s*(?:at|of|with)?\s*(\d+(?:\.\d+)?)\s*%", re.I)

_L = {"m": 1.0, "meter": 1.0, "metre": 1.0, "mm": 0.001, "millimeter": 0.001, "millimetre": 0.001, "cm": 0.01, "centimeter": 0.01, "centimetre": 0.01,
      "km": 1000.0, "kilometer": 1000.0, "kilometre": 1000.0, "inch": 0.0254, "in": 0.0254, "ft": 0.3048, "foot": 0.3048, "feet": 0.3048,
      "yard": 0.9144, "yd": 0.9144, "mile": 1609.344, "mi": 1609.344}
_M = {"kg": 1.0, "kilogram": 1.0, "kilo": 1.0, "g": 0.001, "gram": 0.001, "mg": 1e-6, "milligram": 1e-6, "lb": 0.45359237, "pound": 0.45359237,
      "oz": 0.028349523125, "ounce": 0.028349523125, "stone": 6.35029318, "tonne": 1000.0}
_V = {"l": 1.0, "liter": 1.0, "litre": 1.0, "ml": 0.001, "milliliter": 0.001, "millilitre": 0.001, "gallon": 3.785411784, "gal": 3.785411784,
      "quart": 0.946352946, "qt": 0.946352946, "pint": 0.473176473, "pt": 0.473176473, "cup": 0.2365882365, "fl oz": 0.0295735295625,
      "fluid ounce": 0.0295735295625, "tbsp": 0.01478676478125, "tablespoon": 0.01478676478125, "tsp": 0.00492892159375, "teaspoon": 0.00492892159375}
_S = {"m/s": 1.0, "km/h": 1 / 3.6, "kph": 1 / 3.6, "kmh": 1 / 3.6, "mph": 0.44704, "knot": 0.514444, "kt": 0.514444}
_D = {"byte": 1.0, "b": 1.0, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12, "kilobyte": 1e3, "megabyte": 1e6, "gigabyte": 1e9, "terabyte": 1e12,
      "kib": 1024.0, "mib": 1024.0 ** 2, "gib": 1024.0 ** 3, "tib": 1024.0 ** 4}
_T = {"second": 1.0, "sec": 1.0, "s": 1.0, "minute": 60.0, "min": 60.0, "hour": 3600.0, "hr": 3600.0, "h": 3600.0, "day": 86400.0, "week": 604800.0}
_A = {"sq m": 1.0, "square meter": 1.0, "square metre": 1.0, "sq ft": 0.09290304, "square foot": 0.09290304, "square feet": 0.09290304, "acre": 4046.8564224,
      "hectare": 10000.0, "sq km": 1e6, "square kilometer": 1e6, "square kilometre": 1e6, "sq mile": 2589988.110336, "square mile": 2589988.110336}
# UNITS merges all the tables into one: unit name -> (kind of measurement, size in the base unit). TEMP is separate because temperatures need
# adding/subtracting as well as multiplying.
UNITS = {}
for dim, table in (("length", _L), ("mass", _M), ("volume", _V), ("speed", _S), ("data", _D), ("time", _T), ("area", _A)):
    for k, v in table.items():
        UNITS[k] = (dim, v)
TEMP = {"c": "C", "celsius": "C", "centigrade": "C", "f": "F", "fahrenheit": "F", "k": "K", "kelvin": "K"}


def _unit(raw):
    """Recognise a unit word. Returns ("unit", name) or ("temp", C/F/K) or None. Tries the word as typed, without a plural "s"/"es", and without "squared"."""
    u = re.sub(r"[°\s]+", " ", raw.lower().strip(" .?,!")).strip()
    u = re.sub(r"^(degrees?|deg)\s+", "", u)
    for cand in (u, u.rstrip("s"), u[:-2] if u.endswith("es") else u, u.replace("squared", "").strip()):
        if cand in UNITS:
            return ("unit", cand)
        if cand in TEMP:
            return ("temp", TEMP[cand])
    return None


# CONV: "convert 5 km to miles" / "5 km in miles". HOWMANY: "how many feet in a mile". Both capture the number and the two unit words.
CONV = re.compile(r"(?:convert\s+)?(-?\d[\d,]*\.?\d*)\s*(?:°\s*)?([a-z°/ ]{1,22}?)\s+(?:to|in|into|=)\s+(?:how many\s+)?([a-z°/ ]{1,22}?)\s*[?.!]*$", re.I)
HOWMANY = re.compile(r"how many\s+([a-z/ ]{1,22}?)\s+(?:are |is )?(?:there )?in\s+(?:an?\s+|one\s+|1\s+|(\d[\d,]*\.?\d*)\s*)?([a-z/ ]{1,22}?)\s*[?.!]*$", re.I)


def _convert(q):
    """Answer a unit conversion question as text like "5 km = 3.1069 miles", or None if it is not one (or the units are of different kinds)."""
    m = CONV.search(q)
    a = b = n = None
    if m:
        n, a, b = m.group(1), m.group(2), m.group(3)
    else:
        m = HOWMANY.search(q)
        if m:
            b, n, a = m.group(1), m.group(2) or "1", m.group(3)
    if not m:
        return None
    n = float(str(n).replace(",", ""))
    ua, ub = _unit(a), _unit(b)
    if not ua or not ub:
        return None
    # Temperatures: first convert to Celsius (c), then from Celsius to the target scale.
    if ua[0] == "temp" and ub[0] == "temp":
        f, t = ua[1], ub[1]
        c = n if f == "C" else (n - 32) * 5 / 9 if f == "F" else n - 273.15
        out = c if t == "C" else c * 9 / 5 + 32 if t == "F" else c + 273.15
        sym = {"C": "°C", "F": "°F", "K": " K"}
        return f"{_fmt(n)}{sym[f]} = {_fmt(round(out, 4))}{sym[t]}"
    # Other units: both must measure the same kind of thing (length to length). Result = n * size_from / size_to.
    if ua[0] == "unit" and ub[0] == "unit":
        (da, fa), (db, fb) = UNITS[ua[1]], UNITS[ub[1]]
        if da != db:
            return None
        return f"{_fmt(n)} {a.strip()} = {_fmt(round(n * fa / fb, 6))} {b.strip()}"
    return None


def calculator(q, now, net, online):
    """Provider: tip maths, unit conversion and plain arithmetic, all exact and offline. Returns a list of notes, empty when the question is not for this provider. (Every provider takes (question, now, net, online).)"""
    q = _clean(q)
    # Tip question: bill * percent / 100, using Fractions to avoid rounding errors.
    m = TIP.search(q)
    if m:
        bill, pct = float(m.group(1)), float(m.group(2))
        tip = Fraction(str(bill)) * Fraction(str(pct)) / 100
        return [_note("Calculation (exact)", f"A {pct:g}% tip on ${bill:,.2f} is ${float(tip):,.2f}, so the total is ${float(Fraction(str(bill)) + tip):,.2f}.")]
    conv = _convert(q)
    if conv:
        return [_note("Unit conversion (exact)", conv)]
    # Only go on if there is a calculation cue or the whole message already looks like a sum ("12*(3+4)=").
    if not CALC_CUE.search(q) and not re.fullmatch(r"[\d\s+\-*/().x×÷^%]+=?\??", q.strip()):
        return []
    expr = _expression(q)
    if not expr:
        return []
    try:
        # ast.parse turns the text into a tree and _eval walks it safely. Bad maths (divide by zero, huge numbers...) means "not for us": return nothing.
        result = _eval(ast.parse(expr, mode="eval"))
        shown = _fmt(result)
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, RecursionError, MemoryError):
        return []
    # Build a readable label: "15% of 80" when it was a percentage question, otherwise the expression with spaces around operators.
    pct = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent)\s*of\s*\$?(\d[\d,]*(?:\.\d+)?)", q, re.I)
    label = f"{pct.group(1)}% of {pct.group(2)}" if pct and expr.startswith("((") else re.sub(r"\s*([+\-*/])\s*", r" \1 ", expr.replace("**", "^")).replace("( ", "(")
    return [_note("Calculation (exact)", f"{label} = {shown}")]


# DATES: holidays, weekdays and day counts worked out with the calendar, so they are always right.
# =========================================================================================== dates
def _nth(year, month, weekday, n):
    """The date of the n-th given weekday in a month (weekday 0 = Monday ... 6 = Sunday), e.g. the 4th Thursday of November = Thanksgiving."""
    d = date(year, month, 1)
    # Jump forward from the 1st to the first matching weekday (% 7 wraps around the week), then add whole weeks.
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last(year, month, weekday):
    """The date of the last given weekday in a month (e.g. Memorial Day = last Monday of May)."""
    # Start from the first day of the NEXT month (December rolls into January of next year; True counts as 1), step back one day to get the month's last day,
    # then step back to the wanted weekday.
    d = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _easter(y):
    """Easter Sunday for year y (the standard Gauss/Meeus computus formula: only whole-number maths, valid for the Gregorian calendar)."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(y, month, day + 1)


# Weekday numbers as Python counts them (Monday = 0).
MON, TUE, WED, THU, FRI, SAT, SUN = range(7)
# HOLIDAYS: holiday name -> a small function that gives its date for a given year. Fixed ones are date(y, m, d); floating ones use _nth / _last / _easter.
HOLIDAYS = {
    "new year's day": lambda y: date(y, 1, 1), "new years day": lambda y: date(y, 1, 1), "new year's": lambda y: date(y, 1, 1), "new years": lambda y: date(y, 1, 1),
    "martin luther king day": lambda y: _nth(y, 1, MON, 3), "mlk day": lambda y: _nth(y, 1, MON, 3),
    "valentine's day": lambda y: date(y, 2, 14), "valentines day": lambda y: date(y, 2, 14), "valentine's": lambda y: date(y, 2, 14),
    "presidents day": lambda y: _nth(y, 2, MON, 3), "president's day": lambda y: _nth(y, 2, MON, 3),
    "st patrick's day": lambda y: date(y, 3, 17), "st patricks day": lambda y: date(y, 3, 17),
    "easter": _easter, "easter sunday": _easter, "good friday": lambda y: _easter(y) - timedelta(days=2),
    "mother's day": lambda y: _nth(y, 5, SUN, 2), "mothers day": lambda y: _nth(y, 5, SUN, 2),
    "memorial day": lambda y: _last(y, 5, MON), "father's day": lambda y: _nth(y, 6, SUN, 3), "fathers day": lambda y: _nth(y, 6, SUN, 3),
    "juneteenth": lambda y: date(y, 6, 19), "independence day": lambda y: date(y, 7, 4), "fourth of july": lambda y: date(y, 7, 4),
    "4th of july": lambda y: date(y, 7, 4), "july 4th": lambda y: date(y, 7, 4), "labor day": lambda y: _nth(y, 9, MON, 1),
    "columbus day": lambda y: _nth(y, 10, MON, 2), "halloween": lambda y: date(y, 10, 31), "veterans day": lambda y: date(y, 11, 11),
    "thanksgiving": lambda y: _nth(y, 11, THU, 4), "black friday": lambda y: _nth(y, 11, THU, 4) + timedelta(days=1),
    "cyber monday": lambda y: _nth(y, 11, THU, 4) + timedelta(days=4),
    "christmas eve": lambda y: date(y, 12, 24), "christmas day": lambda y: date(y, 12, 25), "christmas": lambda y: date(y, 12, 25),
    "new year's eve": lambda y: date(y, 12, 31), "new years eve": lambda y: date(y, 12, 31),
}
# HOLI_RE joins all holiday names into one regex "a|b|c", longest first so "new year's eve" is tried before "new year's".
HOLI_RE = "|".join(re.escape(h) for h in sorted(HOLIDAYS, key=len, reverse=True))
# MONTHS maps month names to 1..12 (enumerate(..., 1) counts from 1). MON_RE allows full names or 3-letter short forms.
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
MON_RE = "|".join(MONTHS) + "|" + "|".join(m[:3] for m in MONTHS)
# EXPLICIT finds written dates: "March 5, 2025", "5th of March", or "2025-03-05". (?P<name>...) gives each part a name so the code can read it.
EXPLICIT = re.compile(rf"\b(?P<mon>{MON_RE})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(?P<y>\d{{4}}))?\b|\b(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<mon2>{MON_RE})\.?(?:,?\s+(?P<y2>\d{{4}}))?\b|\b(?P<iso>\d{{4}}-\d{{2}}-\d{{2}})\b", re.I)


def _today(now):
    """Today's date from a Unix time (seconds since 1970); if `now` is empty use the computer's clock."""
    return datetime.fromtimestamp(now or time.time()).date()


def _long(d):
    """A date in full words: "Thursday, November 27, 2025"."""
    return f"{d:%A}, {d:%B} {d.day}, {d.year}"


def _month_num(s):
    """Month number (1-12) from a name or abbreviation like "sept"; None if unknown."""
    s = s.lower()
    return MONTHS.get(s) or next((n for m, n in MONTHS.items() if m.startswith(s[:3])), None)


def _explicit_dates(q, today):
    """Every written date found in the question, as date objects. A missing year means this year; impossible dates (Feb 30) are skipped."""
    out = []
    for m in EXPLICIT.finditer(q):
        try:
            if m.group("iso"):
                out.append(date.fromisoformat(m.group("iso")))
            elif m.group("mon"):
                out.append(date(int(m.group("y") or today.year), _month_num(m.group("mon")), int(m.group("d"))))
            else:
                out.append(date(int(m.group("y2") or today.year), _month_num(m.group("mon2")), int(m.group("d2"))))
        except (ValueError, TypeError):
            continue
    return out


def dates(q, now, net, online):
    """Provider: days between two dates, "when is/how many days until [holiday or date]", and "what weekday is [date]". Offline, exact."""
    q = _clean(q).lower().rstrip("?!. ")
    today = _today(now)
    # days between two explicit dates
    # Case 1: "how many days between X and Y" needs two written dates.
    m = re.search(r"\b(how many days|how long|days)\b.*\bbetween\b", q)
    if m:
        found = _explicit_dates(q, today)
        if len(found) >= 2:
            a, b = found[0], found[1]
            return [_note("Date calculation (exact)", f"From {_long(a)} to {_long(b)} is {abs((b - a).days):,} days.")]
    # Detect which kind of question this is: a named holiday, a countdown ("until"), a weekday question, or "when is".
    # year_m picks up an explicit year such as 2027.
    hol = re.search(rf"\b({HOLI_RE})\b", q)
    until = re.search(r"\b(how many days|how many weeks|how long|days?|weeks?)\b.*\b(until|till|to go until|before|left until|away)\b|\b(countdown|days left)\b", q)
    weekday_q = re.search(r"\bwhat (day|weekday|day of the week)\b", q) or re.search(r"\b(which|what) day of the week\b", q)
    when_q = re.search(r"\bwhen (is|was|are|will)\b", q)
    year_m = re.search(r"\b(?:in\s+)?(20\d\d|19\d\d)\b", q)
    # Case 2: a holiday question. Choose the year: explicit year, "next/last year", else this year, moving to next year if this year's date already passed (unless the question says "was").
    if hol and (until or weekday_q or when_q):
        name = hol.group(1)
        fn = HOLIDAYS[name]
        if year_m:
            y = int(year_m.group(1))
        elif re.search(r"\bnext year\b", q):
            y = today.year + 1
        elif re.search(r"\blast year\b", q):
            y = today.year - 1
        elif weekday_q and re.search(r"\bthis year\b", q):
            y = today.year
        else:
            y = today.year
            if fn(y) < today and (until or when_q) and not re.search(r"\bwas\b", q):
                y += 1
        d = fn(y)
        delta = (d - today).days
        # delta = whole days from today to the holiday; turn it into words like "12 days from today".
        rel = "today" if delta == 0 else f"{delta:,} days from today" if delta > 0 else f"{-delta:,} days ago"
        label = name.title().replace("'S", "'s")
        return [_note("Date calculation (exact)", f"{label} {y} falls on {_long(d)} ({rel}; today is {_long(today)}).")]
    found = _explicit_dates(q, today)
    # Case 3: a written date with a countdown or weekday question. A countdown to a past date with no year means next year's one.
    if found and (until or weekday_q or re.search(r"\bwhat day\b", q)):
        d = found[0]
        delta = (d - today).days
        if until and not weekday_q:
            if delta < 0 and not re.search(r"\b\d{4}\b", q):
                d = date(d.year + 1, d.month, d.day)
                delta = (d - today).days
            return [_note("Date calculation (exact)", f"{_long(d)} is {delta:,} days from today ({_long(today)})." if delta >= 0
                          else f"{_long(d)} was {-delta:,} days ago (today is {_long(today)}).")]
        return [_note("Date calculation (exact)", f"{d.month}/{d.day}/{d.year} {'is' if d >= today else 'was'} a {d:%A} ({_long(d)}).")]
    return []


# TIME: the local time from this computer's clock, or the time in another city (needs the internet to find the city's time zone).
# =========================================================================================== time
def _geocode(place, net):
    """Look up a place name with the free Open-Meteo geocoding service. Returns the best hit (a dict with name, country, latitude, longitude, timezone...) or None. "Paris, Texas" uses the part after the comma to choose between matches."""
    name, _, region = place.partition(",")
    geo = net.json("https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({"name": name.strip(), "count": 5, "language": "en"}))
    hits = geo.get("results") or []
    if not hits:
        return None
    want = region.strip().lower()
    return next((h for h in hits if want and want in (str(h.get("country", "")) + " " + str(h.get("admin1", ""))).lower()), hits[0])


# TIME_Q: "what time is it" with an optional "in <place>" (named group "place").
TIME_Q = re.compile(r"\b(what(?:'s| is)? the time|what time is it|what time(?:'s| is) it|current time|time now|local time|time right now)\b(?:\s+(?:right now|now|currently))?"
                    r"(?:\s+(?:in|at|for)\s+(?P<place>[a-z][a-z'.\- ,]*))?", re.I)


def clock(q, now, net, online):
    """Provider: the current time. No place named -> this computer's clock (offline). A place named -> its time zone is looked up online, and the time is shown there."""
    q = _clean(q).rstrip("?!. ")
    m = TIME_Q.search(q)
    if not m:
        return []
    place = (m.group("place") or "").strip(" ,.")
    # Strip trailing filler words from the place name.
    place = re.sub(r"\b(right now|now|currently|today|please)\b$", "", place, flags=re.I).strip(" ,.")
    if not place:
        d = datetime.fromtimestamp(now or time.time()).astimezone()
        return [_note("Current time (this computer)", f"It is {d:%I:%M %p}".lstrip("0") + f" on {_long(d.date())} ({d.tzname()}), by the clock of the computer running the app.")]
    if not online:
        return []
    try:
        hit = _geocode(place, net)
        if not hit or not hit.get("timezone"):
            return []
        # zoneinfo is Python's built-in time zone database (e.g. "Europe/Paris"); it is imported here because only this branch needs it.
        from zoneinfo import ZoneInfo
        d = datetime.fromtimestamp(now or time.time(), ZoneInfo(hit["timezone"]))
    except Exception as e:
        print(f"(time lookup failed: {e})")
        return []
    where = ", ".join(x for x in (hit.get("name"), hit.get("admin1"), hit.get("country")) if x)
    return [_note(f"Time in {where}", f"It is {d:%I:%M %p}".lstrip("0") + f" on {_long(d.date())} in {where} (time zone {hit['timezone']}, {d.tzname()}).", "https://open-meteo.com/")]


# CURRENCY: exchange rates from the free Frankfurter service (European Central Bank), with a second free service as a backup.
# =========================================================================================== currency
# CURRENCIES maps everyday words and codes ("euros", "usd", "bucks") to the 3-letter ISO currency code the services expect.
CURRENCIES = {"usd": "USD", "dollar": "USD", "dollars": "USD", "us dollar": "USD", "us dollars": "USD", "bucks": "USD", "eur": "EUR", "euro": "EUR", "euros": "EUR",
              "gbp": "GBP", "pound": "GBP", "pounds": "GBP", "pound sterling": "GBP", "sterling": "GBP", "jpy": "JPY", "yen": "JPY", "cad": "CAD",
              "canadian dollar": "CAD", "canadian dollars": "CAD", "aud": "AUD", "australian dollar": "AUD", "australian dollars": "AUD", "chf": "CHF",
              "franc": "CHF", "francs": "CHF", "swiss franc": "CHF", "cny": "CNY", "yuan": "CNY", "rmb": "CNY", "renminbi": "CNY", "inr": "INR", "rupee": "INR",
              "rupees": "INR", "mxn": "MXN", "peso": "MXN", "pesos": "MXN", "mexican peso": "MXN", "mexican pesos": "MXN", "brl": "BRL", "real": "BRL", "reais": "BRL",
              "krw": "KRW", "won": "KRW", "sek": "SEK", "krona": "SEK", "nok": "NOK", "dkk": "DKK", "nzd": "NZD", "new zealand dollar": "NZD", "sgd": "SGD",
              "hkd": "HKD", "zar": "ZAR", "rand": "ZAR", "try": "TRY", "lira": "TRY", "pln": "PLN", "zloty": "PLN", "czk": "CZK", "huf": "HUF", "thb": "THB",
              "baht": "THB", "idr": "IDR", "myr": "MYR", "php": "PHP", "ils": "ILS", "shekel": "ILS", "isk": "ISK", "ron": "RON", "bgn": "BGN",
              "aed": "AED", "dirham": "AED", "dirhams": "AED", "sar": "SAR", "riyal": "SAR", "egp": "EGP", "ngn": "NGN", "naira": "NGN", "kes": "KES", "vnd": "VND", "dong": "VND",
              "pkr": "PKR", "bdt": "BDT", "taka": "BDT", "ars": "ARS", "cop": "COP", "clp": "CLP", "uah": "UAH", "hryvnia": "UAH", "twd": "TWD", "qar": "QAR", "kwd": "KWD",
              "mad": "MAD", "lkr": "LKR", "rub": "RUB", "ruble": "RUB", "rubles": "RUB", "pen": "PEN", "ghs": "GHS", "ils ": "ILS"}
# CUR_RE is a regex "a|b|c" of every currency word, longest first (so "us dollar" wins over "dollar"). CUR_Q matches "100 usd to eur";
# CUR_Q2 matches "how much is 100 usd in eur". RATE_WORDS makes sure the message is really about exchange.
CUR_RE = "|".join(re.escape(c) for c in sorted(CURRENCIES, key=len, reverse=True))
CUR_Q = re.compile(rf"(?:(?P<amt>\d[\d,]*\.?\d*)\s*)?\b(?P<a>{CUR_RE})\b\s*(?:to|in|into|=|vs\.?|versus|->)\s*(?:how many\s+)?\b(?P<b>{CUR_RE})\b", re.I)
CUR_Q2 = re.compile(rf"how (?:much|many)\s+(?:is|are)?\s*(?P<amt>\d[\d,]*\.?\d*)\s*\b(?P<a>{CUR_RE})\b\s*(?:in|worth in|to)\s*\b(?P<b>{CUR_RE})\b", re.I)
RATE_WORDS = re.compile(r"\b(convert|exchange|rate|worth|how much|how many|in)\b", re.I)


def currency(q, now, net, online):
    """Provider: exchange-rate questions. Needs the internet. Tries Frankfurter first; if that fails (some currencies are not published) it tries open.er-api.com. Notes name the source."""
    if not online:
        return []
    q = _clean(q)
    m = CUR_Q2.search(q) or CUR_Q.search(q)
    if not m or not RATE_WORDS.search(q):
        return []
    # a = from-currency code, b = to-currency code, amt = the amount (default 1; commas removed).
    a, b = CURRENCIES[m.group("a").lower()], CURRENCIES[m.group("b").lower()]
    amt = float((m.group("amt") or "1").replace(",", ""))
    if a == b:
        return []
    try:
        # Ask for the converted amount directly. Any failure falls through to the except branch below, which tries the backup service.
        data = net.json("https://api.frankfurter.app/latest?" + urllib.parse.urlencode({"amount": amt, "from": a, "to": b}))
        got = data["rates"][b]
    except Exception as e:
        print(f"(currency lookup failed: {e})")
        try:                                                      # currencies the European Central Bank does not publish (AED, NGN ...): a second free source
            alt = net.json(f"https://open.er-api.com/v6/latest/{a}")
            got = alt["rates"][b] * amt
            return [_note("Exchange rate - open.er-api.com, " + str(alt.get("time_last_update_utc", ""))[:16],
                          f"{_fmt(amt)} {a} = {_fmt(round(got, 4))} {b} (market rate; banks and cards add their own margin).", "https://www.exchangerate-api.com/")]
        except Exception as e2:
            print(f"(second currency source failed: {e2})")
            return []
    return [_note("Exchange rate - European Central Bank via frankfurter.app, " + str(data.get("date", "")),
                  f"{_fmt(amt)} {a} = {_fmt(got)} {b} (reference rate of {data.get('date', 'the latest working day')}; banks and cards add their own margin).",
                  "https://www.frankfurter.app/")]


# CRYPTO AND STOCKS: prices from CoinGecko (crypto) and Stooq (shares and indexes, delayed). Information only, never advice.
# =========================================================================================== crypto and stocks
# COINS maps a name or ticker the person may type to (CoinGecko id, display name, symbol).
COINS = {"bitcoin": ("bitcoin", "Bitcoin", "BTC"), "btc": ("bitcoin", "Bitcoin", "BTC"), "ethereum": ("ethereum", "Ethereum", "ETH"), "ether": ("ethereum", "Ethereum", "ETH"),
         "eth": ("ethereum", "Ethereum", "ETH"), "solana": ("solana", "Solana", "SOL"), "sol": ("solana", "Solana", "SOL"), "dogecoin": ("dogecoin", "Dogecoin", "DOGE"),
         "doge": ("dogecoin", "Dogecoin", "DOGE"), "xrp": ("ripple", "XRP", "XRP"), "ripple": ("ripple", "XRP", "XRP"), "litecoin": ("litecoin", "Litecoin", "LTC"),
         "ltc": ("litecoin", "Litecoin", "LTC"), "cardano": ("cardano", "Cardano", "ADA"), "bnb": ("binancecoin", "BNB", "BNB"), "polkadot": ("polkadot", "Polkadot", "DOT"),
         "avalanche": ("avalanche-2", "Avalanche", "AVAX"), "chainlink": ("chainlink", "Chainlink", "LINK"), "shiba inu": ("shiba-inu", "Shiba Inu", "SHIB"),
         "toncoin": ("the-open-network", "Toncoin", "TON"), "tether": ("tether", "Tether", "USDT"), "monero": ("monero", "Monero", "XMR")}
# COIN_RE: regex of all coin words, longest first. PRICE_WORDS: the message must also talk about price/value.
COIN_RE = "|".join(re.escape(c) for c in sorted(COINS, key=len, reverse=True))
PRICE_WORDS = re.compile(r"\b(price|worth|cost|value|trading|how much|rate|market cap|going for|at right now|doing)\b", re.I)


def crypto(q, now, net, online):
    """Provider: the current price of a well-known coin in US dollars, with the 24-hour change and market cap when CoinGecko gives them. Needs the internet."""
    if not online:
        return []
    q = _clean(q)
    m = re.search(rf"\b({COIN_RE})\b", q, re.I)
    if not m or not PRICE_WORDS.search(q):
        return []
    cid, name, sym = COINS[m.group(1).lower()]
    try:
        data = net.json("https://api.coingecko.com/api/v3/simple/price?" + urllib.parse.urlencode(
            {"ids": cid, "vs_currencies": "usd", "include_24hr_change": "true", "include_market_cap": "true"}))
        row = data[cid]
        price = row["usd"]
    except Exception as e:
        print(f"(crypto lookup failed: {e})")
        return []
    change, cap = row.get("usd_24h_change"), row.get("usd_market_cap")
    # Cheap coins (under $1) are shown with 6 decimals so the digits are not lost. `{change:+.1f}` always shows a sign (+ or -).
    text = f"{name} ({sym}) is ${price:,.2f} USD" if price >= 1 else f"{name} ({sym}) is ${price:.6f} USD"
    if change is not None:
        text += f", {change:+.1f}% over the last 24 hours"
    if cap:
        text += f", market cap about ${cap / 1e9:,.1f} billion"
    # The time of the price, in UTC, so the model and reader know how fresh it is.
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(now or time.time()))
    return [_note(f"{name} price - CoinGecko, {stamp}", text + ". Crypto prices move constantly; this is the price at the time shown.", "https://www.coingecko.com/")]


# COMPANIES maps company names to their US stock ticker symbol. INDICES maps index names to Stooq's code and a display name.
# STOCK_WORDS: words that show the message is about markets.
COMPANIES = {"apple": "AAPL", "microsoft": "MSFT", "google": "GOOGL", "alphabet": "GOOGL", "amazon": "AMZN", "tesla": "TSLA", "nvidia": "NVDA", "meta": "META",
             "facebook": "META", "netflix": "NFLX", "disney": "DIS", "walmart": "WMT", "costco": "COST", "target": "TGT", "nike": "NKE", "starbucks": "SBUX",
             "mcdonald's": "MCD", "mcdonalds": "MCD", "coca-cola": "KO", "coca cola": "KO", "pepsi": "PEP", "pepsico": "PEP", "ford": "F", "general motors": "GM",
             "boeing": "BA", "intel": "INTC", "amd": "AMD", "oracle": "ORCL", "ibm": "IBM", "salesforce": "CRM", "adobe": "ADBE", "paypal": "PYPL", "visa": "V",
             "mastercard": "MA", "jpmorgan": "JPM", "bank of america": "BAC", "goldman sachs": "GS", "exxon": "XOM", "chevron": "CVX", "pfizer": "PFE",
             "johnson & johnson": "JNJ", "uber": "UBER", "airbnb": "ABNB", "spotify": "SPOT", "shopify": "SHOP", "palantir": "PLTR", "gamestop": "GME",
             "amc": "AMC", "snap": "SNAP", "coinbase": "COIN", "robinhood": "HOOD", "at&t": "T", "verizon": "VZ", "home depot": "HD", "lowe's": "LOW",
             "berkshire": "BRK-B", "broadcom": "AVGO", "qualcomm": "QCOM", "cisco": "CSCO", "ea": "EA", "roblox": "RBLX", "zoom": "ZM"}
INDICES = {"s&p 500": ("^spx", "S&P 500"), "s&p": ("^spx", "S&P 500"), "sp500": ("^spx", "S&P 500"), "dow jones": ("^dji", "Dow Jones Industrial Average"),
           "the dow": ("^dji", "Dow Jones Industrial Average"), "nasdaq": ("^ndq", "Nasdaq 100"), "ftse 100": ("^ukx", "FTSE 100"), "dax": ("^dax", "DAX"),
           "nikkei": ("^nkx", "Nikkei 225")}
STOCK_WORDS = re.compile(r"\b(stock|stocks|share price|shares|ticker|trading at|market|index|closing|closed|price of|how is .{1,25} doing)\b", re.I)


def stocks(q, now, net, online):
    """Provider: the latest (delayed) share price or index level from Stooq's free CSV feed. Looks for an index name, then a company name, then a ticker typed like "stock AAPL" or "$TSLA"."""
    if not online:
        return []
    q = _clean(q)
    low = q.lower()
    if not STOCK_WORDS.search(low) and not re.search(r"\bprice\b", low):
        return []
    sym = label = None
    # Longest names first so "s&p 500" is tried before "s&p". break stops at the first match.
    for k in sorted(INDICES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(k)}\b", low):
            sym, label = INDICES[k][0], INDICES[k][1]
            break
    if not sym:
        for k in sorted(COMPANIES, key=len, reverse=True):
            if re.search(rf"(?<![\w]){re.escape(k)}(?![\w])", low):
                sym, label = COMPANIES[k].lower() + ".us", f"{k.title()} ({COMPANIES[k]})"
                break
    if not sym:
        m = re.search(r"(?:\bstock\b|\bshares?\b|\bticker\b|\bprice of\b)\s+(?:for\s+|of\s+)?\$?([A-Z]{1,5})\b", q) or re.search(r"\$([A-Za-z]{1,5})\b", q)
        if m:
            sym, label = m.group(1).lower() + ".us", m.group(1).upper()
    if not sym:
        return []
    if not (STOCK_WORDS.search(low) or re.search(r"\bprice\b", low)):
        return []
    try:
        # Stooq answers with a tiny CSV: a header row and one data row. We read both, pair header names with values, and take the closing price.
        # (The .replace turns the empty "h=" in the address into a bare "h" flag.)
        raw = net.text("https://stooq.com/q/l/?" + urllib.parse.urlencode({"s": sym, "f": "sd2t2ohlcv", "h": "", "e": "csv"}).replace("h=&", "h&"))
        lines = [l for l in raw.strip().splitlines() if l.strip()]
        head, row = lines[0].split(","), lines[1].split(",")
        d = dict(zip([h.strip().lower() for h in head], row))
        close = float(d["close"])
    except Exception as e:
        print(f"(stock lookup failed: {e})")
        return []
    # Indexes (codes starting with ^) are measured in points; shares in US dollars. Open/high/low are added when present.
    unit = "points" if sym.startswith("^") else "USD"
    bits = [f"{label}: last {close:,.2f} {unit}"]
    if d.get("date") not in (None, "N/D"):
        bits[0] += f" on {d['date']} {d.get('time', '')}".rstrip()
    for k, nm in (("open", "open"), ("high", "high"), ("low", "low")):
        try:
            bits.append(f"{nm} {float(d[k]):,.2f}")
        except (KeyError, ValueError):
            pass
    return [_note("Market price - stooq.com (delayed)", ", ".join(bits) + ". Quotes from Stooq are delayed and show the latest trading day; this is not advice.", "https://stooq.com/")]


# SPORTS: latest results or next games for a team, from the free TheSportsDB service.
# =========================================================================================== sports
# SPORT_Q: phrases that mark a sports question. SPORT_STOP: question words stripped out so only the team name is left.
SPORT_Q = re.compile(r"\b(who won|score of|score for|final score|last game|last match|latest game|next game|next match|when do .{1,30} play|when does .{1,30} play|"
                     r"did .{1,30} win|how did .{1,30} do|results?)\b", re.I)
SPORT_STOP = re.compile(r"\b(who|won|the|score|of|for|final|last|latest|next|game|match|when|do|does|play|did|win|how|do|results?|vs\.?|versus|against|tonight|today|"
                        r"yesterday|this|week|weekend|their|his|her|did|is|are|was|were)\b", re.I)


def sports(q, now, net, online):
    """Provider: last results or upcoming games for a team. Looks the team up by name, then asks for its last/next events (at most 3)."""
    if not online:
        return []
    q = _clean(q).rstrip("?!. ")
    if not SPORT_Q.search(q):
        return []
    # Remove the question words; what remains should be the team name.
    team = " ".join(SPORT_STOP.sub(" ", q).split())
    if len(team) < 3:
        return []
    # nxt = the person asked about the future ("next", "when do ... play").
    nxt = bool(re.search(r"\b(next|when do|when does|upcoming)\b", q, re.I))
    try:
        found = (net.json("https://www.thesportsdb.com/api/v1/json/3/searchteams.php?t=" + urllib.parse.quote(team)).get("teams") or [])
        if not found:
            return []
        t = found[0]
        key = "events" if nxt else "results"
        url = f"https://www.thesportsdb.com/api/v1/json/3/events{'next' if nxt else 'last'}.php?id={t['idTeam']}"
        evs = (net.json(url).get(key) or [])[:3]
    except Exception as e:
        print(f"(sports lookup failed: {e})")
        return []
    if not evs:
        return []
    lines = []
    for e in evs:
        # A finished game shows both scores; a future (or score-less) one just shows the event name and date.
        when = e.get("dateEvent") or ""
        if nxt or e.get("intHomeScore") in (None, ""):
            lines.append(f"{e.get('strEvent', '')} on {when}")
        else:
            lines.append(f"{e.get('strHomeTeam')} {e.get('intHomeScore')} - {e.get('intAwayScore')} {e.get('strAwayTeam')} on {when}")
    return [_note(f"{t.get('strTeam')} {'upcoming games' if nxt else 'latest results'} - thesportsdb.com", "; ".join(lines) + ".", "https://www.thesportsdb.com/")]


# DICTIONARY, COUNTRIES, HOLIDAYS: word definitions (dictionaryapi.dev), country facts (REST Countries) and upcoming public holidays (Nager.Date).
# =========================================================================================== dictionary, countries, holidays
# DEFINE: "define serendipity", "meaning of X", "what does X mean" (named groups w / w2 hold the word).
DEFINE = re.compile(r"^(?:define|definition of|meaning of|what does)\s+(?:the word\s+)?[\"']?(?P<w>[a-z][a-z'-]{1,30})[\"']?(?:\s+mean)?$|^what(?:'s| is) the (?:definition|meaning) of\s+(?:the word\s+)?[\"']?(?P<w2>[a-z][a-z'-]{1,30})[\"']?$", re.I)


def dictionary(q, now, net, online):
    """Provider: the first meanings of an English word (up to 3 parts of speech, 2 definitions each) plus its pronunciation if given."""
    if not online:
        return []
    m = DEFINE.match(_clean(q).rstrip("?!. "))
    if not m:
        return []
    word = (m.group("w") or m.group("w2")).lower()
    if word in ("life", "existence", "it", "this", "that"):                # "what is the meaning of life" is a question, not a dictionary lookup
        return []
    try:
        data = net.json("https://api.dictionaryapi.dev/api/v2/entries/en/" + urllib.parse.quote(word))
        entry = data[0]
    except Exception as e:
        print(f"(dictionary lookup failed: {e})")
        return []
    lines = []
    for meaning in entry.get("meanings", [])[:3]:
        defs = meaning.get("definitions", [])[:2]
        lines.append(f"{meaning.get('partOfSpeech', '')}: " + " / ".join(d["definition"] for d in defs if d.get("definition")))
    if not lines:
        return []
    ph = f" {entry['phonetic']}" if entry.get("phonetic") else ""
    return [_note(f"Definition of {word}{ph} - dictionaryapi.dev", " ".join(lines), "https://dictionaryapi.dev/")]


# COUNTRY_Q: "capital of France", "population of Brazil" ... group "c" is the country name.
COUNTRY_Q = re.compile(r"\b(?P<what>capital|population|currency|language|languages|area|size|continent|region)\b\s+(?:city\s+)?(?:of|in)\s+(?:the\s+)?(?P<c>[a-z][a-z .'-]{2,40})", re.I)


def countries(q, now, net, online):
    """Provider: facts about a country (capital, population, area, region, currency, languages) from REST Countries."""
    if not online:
        return []
    m = COUNTRY_Q.search(_clean(q).rstrip("?!. "))
    if not m:
        return []
    name = re.sub(r"\b(please|today|now|right now)\b.*$", "", m.group("c"), flags=re.I).strip(" .")
    try:
        rows = net.json("https://restcountries.com/v3.1/name/" + urllib.parse.quote(name) + "?fields=name,capital,population,currencies,languages,region,subregion,area")
        # The service can return several matches; prefer the one whose common name equals the typed name, else the first.
        c = next((r for r in rows if r["name"]["common"].lower() == name.lower()), rows[0])
    except Exception as e:
        print(f"(country lookup failed: {e})")
        return []
    cur = ", ".join(f"{v.get('name')} ({k})" for k, v in (c.get("currencies") or {}).items())
    langs = ", ".join((c.get("languages") or {}).values())
    parts = [f"{c['name']['common']} ({c['name'].get('official', '')}): capital {', '.join(c.get('capital') or ['none'])}", f"population {c.get('population', 0):,}",
             f"area {c.get('area', 0):,.0f} sq km", f"region {c.get('region', '')}" + (f" ({c['subregion']})" if c.get("subregion") else "")]
    if cur:
        parts.append("currency " + cur)
    if langs:
        parts.append("languages " + langs)
    return [_note(f"Country facts: {c['name']['common']} - restcountries.com", "; ".join(parts) + ".", "https://restcountries.com/")]


# COUNTRY_CODES: country name -> 2-letter code used by the holidays service. HOLIDAY_COUNTRY: "public holidays in Canada" (group "c").
COUNTRY_CODES = {"united states": "US", "usa": "US", "america": "US", "us": "US", "canada": "CA", "mexico": "MX", "united kingdom": "GB", "uk": "GB", "england": "GB",
                 "ireland": "IE", "france": "FR", "germany": "DE", "spain": "ES", "italy": "IT", "portugal": "PT", "netherlands": "NL", "belgium": "BE", "sweden": "SE",
                 "norway": "NO", "denmark": "DK", "finland": "FI", "poland": "PL", "austria": "AT", "switzerland": "CH", "greece": "GR", "australia": "AU",
                 "new zealand": "NZ", "japan": "JP", "south korea": "KR", "china": "CN", "india": "IN", "brazil": "BR", "argentina": "AR", "chile": "CL",
                 "south africa": "ZA", "turkey": "TR", "singapore": "SG", "philippines": "PH", "indonesia": "ID", "thailand": "TH", "israel": "IL"}
HOLIDAY_COUNTRY = re.compile(r"\b(?:public |bank |national )?holidays?\b.{0,20}?\b(?:in|for)\s+(?:the\s+)?(?P<c>[a-z][a-z ]{1,30})", re.I)


def public_holidays(q, now, net, online):
    """Provider: the next (up to 8) public holidays of a country, from Nager.Date. Only countries in COUNTRY_CODES are supported."""
    if not online:
        return []
    m = HOLIDAY_COUNTRY.search(_clean(q).rstrip("?!. "))
    if not m:
        return []
    name = re.sub(r"\b(this year|next year|in \d{4}|today|please)\b.*$", "", m.group("c"), flags=re.I).strip().lower()
    code = COUNTRY_CODES.get(name)
    if not code:
        return []
    try:
        rows = net.json(f"https://date.nager.at/api/v3/NextPublicHolidays/{code}")[:8]
    except Exception as e:
        print(f"(holiday lookup failed: {e})")
        return []
    if not rows:
        return []
    lines = []
    for r in rows:
        d = date.fromisoformat(r["date"])
        lines.append(f"{r.get('name') or r.get('localName')}: {_long(d)}")
    return [_note(f"Upcoming public holidays: {name.title()} - date.nager.at", "; ".join(lines) + ".", "https://date.nager.at/")]


# NEWS, BOOKS, RECIPES: Google News headlines (RSS feed), Open Library book search, and TheMealDB recipes.
# =========================================================================================== news, books, recipes
# NEWS_Q: "latest news about X", "news on X", "what's happening with X", "headlines". The topic can land in any of four named groups (t, t2, t3, t4).
NEWS_Q = re.compile(r"\b(?:latest|recent|breaking|top|today'?s)\s+(?:news|headlines)(?:\s+(?:on|about|for|in|regarding))?\s*(?P<t>.*)$|\bnews\s+(?:on|about|for|regarding)\s+(?P<t2>.+)$|"
                    r"\bwhat(?:'s| is)\s+(?:happening|going on|new)\s+(?:with|in|at)\s+(?P<t3>.+)$|\b(?:headlines|what(?:'s| is) in the news)\b(?P<t4>.*)$", re.I)


def news(q, now, net, online):
    """Provider: up to 6 recent headlines from Google News (optionally about a topic; a topic search looks only at the last 2 days). The note also tells the model to list them as bullets and that headlines are reports, not proof."""
    if not online:
        return []
    m = NEWS_Q.search(_clean(q).rstrip("?!. "))
    if not m:
        return []
    # filter(None, ...) drops the empty groups; the rest are joined into the topic text, then filler words are trimmed.
    topic = " ".join(filter(None, (m.group("t"), m.group("t2"), m.group("t3"), m.group("t4")))).strip(" ,.")
    topic = re.sub(r"\b(please|today|right now|now)\b$", "", topic, flags=re.I).strip()
    topic = re.sub(r"^(the|a|an)\s+", "", topic, flags=re.I)
    base = "https://news.google.com/rss"
    url = base + ("/search?" + urllib.parse.urlencode({"q": topic + " when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"}) if topic
                  else "?" + urllib.parse.urlencode({"hl": "en-US", "gl": "US", "ceid": "US:en"}))
    try:
        # RSS is XML: parse it and take the first 6 <item> entries under <channel>.
        root = ET.fromstring(net.text(url))
        items = root.findall("./channel/item")[:6]
    except Exception as e:
        print(f"(news lookup failed: {e})")
        return []
    lines = []
    for it in items:
        title = W.clean_text(it.findtext("title") or "")
        when = W.nice_date(it.findtext("pubDate") or "")
        if title:
            lines.append(f"{title}" + (f" ({when})" if when else ""))
    if not lines:
        return []
    return [_note("News headlines - Google News" + (f": {topic}" if topic else ""), "\n".join("- " + ln for ln in lines) + "\nHeadlines only: they say what was reported, not that it is true. "
                  "Give them as a short bulleted list: one line per story, each starting with \"- \", with the source in brackets at the end.",
                  "https://news.google.com/")]


# BOOK_Q: "who wrote X", "author of X", "when was X published" (group "t" is the title).
BOOK_Q = re.compile(r"\b(?:who (?:wrote|is the author of|authored)|author of|when was|when did)\s+(?:the (?:book|novel)\s+)?[\"']?(?P<t>[A-Za-z0-9][A-Za-z0-9 ,:'\-!]{2,60}?)[\"']?"
                    r"(?:\s+(?:written|published|released|come out))?\s*$", re.I)


def books(q, now, net, online):
    """Provider: author and first publication year for a book title, from Open Library (up to 3 matches)."""
    if not online:
        return []
    q = _clean(q).rstrip("?!. ")
    if not re.search(r"\b(wrote|author|authored|book|novel|published|written)\b", q, re.I):
        return []
    m = BOOK_Q.search(q)
    if not m:
        return []
    title = m.group("t").strip()
    try:
        docs = net.json("https://openlibrary.org/search.json?" + urllib.parse.urlencode({"title": title, "limit": 3, "fields": "title,author_name,first_publish_year"})).get("docs") or []
    except Exception as e:
        print(f"(book lookup failed: {e})")
        return []
    lines = [f"{d.get('title')} by {', '.join(d.get('author_name') or ['unknown'])}" + (f", first published {d['first_publish_year']}" if d.get("first_publish_year") else "") for d in docs]
    if not lines:
        return []
    return [_note("Books matching the title - openlibrary.org", "; ".join(lines) + ".", "https://openlibrary.org/")]


# RECIPE_Q: "recipe for X", "how to cook X" (group "d" is the dish). FOOD_STOP: words that show it is NOT about food ("how to make a website").
RECIPE_Q = re.compile(r"\b(?:recipe for|recipe of|ingredients (?:for|in)|how (?:do i|to|can i) (?:cook|bake|make) (?:a |an |some )?)\s*(?P<d>[a-z][a-z '\-]{2,40})", re.I)
FOOD_STOP = re.compile(r"\b(website|app|account|game|program|script|function|list|plan|decision|money|friends?|bed|video|song|page)\b", re.I)


def recipes(q, now, net, online):
    """Provider: a recipe (ingredients with amounts, plus method) from TheMealDB. Skips vague asks like "a good dinner" and non-food uses of "make"."""
    if not online:
        return []
    q = _clean(q).rstrip("?!. ")
    m = RECIPE_Q.search(q)
    if not m or FOOD_STOP.search(q) or not re.search(r"\b(recipe|ingredients|cook|bake)\b", q, re.I) and not re.search(r"how (do i|to|can i) make", q, re.I):
        return []
    dish = re.sub(r"\b(please|at home|quickly|easily)\b", "", m.group("d"), flags=re.I).strip()
    if re.fullmatch(r"(a |an |some |the )?(good |easy |quick |simple |healthy |nice )?(one|dinner|lunch|breakfast|dessert|snack|meal|something|anything|tonight|food|recipe|ideas?|today)s?", dish, re.I) or len(dish) < 3:
        return []
    try:
        meals = net.json("https://www.themealdb.com/api/json/v1/1/search.php?s=" + urllib.parse.quote(dish)).get("meals") or []
    except Exception as e:
        print(f"(recipe lookup failed: {e})")
        return []
    if not meals:
        return []
    r = meals[0]
    # TheMealDB stores ingredients in numbered fields strIngredient1..20 and strMeasure1..20; collect the non-empty ones as "amount ingredient".
    ing = [f"{r.get(f'strMeasure{i}', '').strip()} {r.get(f'strIngredient{i}', '').strip()}".strip() for i in range(1, 21) if (r.get(f"strIngredient{i}") or "").strip()]
    text = f"{r['strMeal']} ({r.get('strCategory', '')}, {r.get('strArea', '')}). Ingredients: " + ", ".join(ing) + ". Method: " + W.clean_text(r.get("strInstructions", ""))
    return [_note(f"Recipe: {r['strMeal']} - themealdb.com", text, r.get("strSource") or "https://www.themealdb.com/")]


# AIR QUALITY, ON THIS DAY, EARTHQUAKES: Open-Meteo air quality, Wikimedia history events, and USGS earthquakes.
# =========================================================================================== air quality, on this day, earthquakes
# AIR_Q: "air quality in Paris", "uv index" (group "p" is the place).
AIR_Q = re.compile(r"\b(air quality|aqi|air pollution|uv index|how smoggy)\b(?:\s+(?:today|now|right now))?(?:\s+(?:in|for|at|near)\s+(?P<p>[a-z][a-z'.\- ,]*))?", re.I)


def air_quality(q, now, net, online, default_place=""):
    """Provider: the US air-quality index (AQI), PM2.5/PM10 and UV index for a place (default_place is used when none is typed). Needs the internet."""
    if not online:
        return []
    m = AIR_Q.search(_clean(q).rstrip("?!. "))
    if not m:
        return []
    place = re.sub(r"\b(today|now|right now|please)\b$", "", (m.group("p") or default_place or ""), flags=re.I).strip(" ,.")
    if not place:
        return []
    try:
        hit = _geocode(place, net)
        if not hit:
            return []
        d = net.json("https://air-quality-api.open-meteo.com/v1/air-quality?" + urllib.parse.urlencode(
            {"latitude": hit["latitude"], "longitude": hit["longitude"], "current": "us_aqi,pm2_5,pm10,uv_index", "timezone": "auto"}))
        cur = d["current"]
        aqi = cur["us_aqi"]
    except Exception as e:
        print(f"(air quality lookup failed: {e})")
        return []
    # Standard US AQI bands: up to 50 good, 100 moderate, 150 unhealthy for sensitive groups, 200 unhealthy, 300 very unhealthy, above that hazardous.
    level = ("good" if aqi <= 50 else "moderate" if aqi <= 100 else "unhealthy for sensitive groups" if aqi <= 150 else "unhealthy" if aqi <= 200
             else "very unhealthy" if aqi <= 300 else "hazardous")
    where = ", ".join(x for x in (hit.get("name"), hit.get("admin1"), hit.get("country")) if x)
    return [_note(f"Air quality in {where} - open-meteo.com", f"US AQI {aqi} ({level}); PM2.5 {cur.get('pm2_5')} ug/m3, PM10 {cur.get('pm10')} ug/m3, UV index {cur.get('uv_index')}.",
                  "https://open-meteo.com/")]


# ONTHISDAY: "on this day", "what happened on March 5" (group "rest" holds any date after it).
ONTHISDAY = re.compile(r"\b(on this day|this day in history|what happened on)\b(?P<rest>.*)$", re.I)


def on_this_day(q, now, net, online):
    """Provider: a handful of historical events that happened on today's date (or on a date written in the question), from Wikimedia."""
    if not online:
        return []
    m = ONTHISDAY.search(_clean(q).rstrip("?!. "))
    if not m:
        return []
    today = _today(now)
    d = today
    found = _explicit_dates(m.group("rest") or "", today)
    if found:
        d = found[0]
    try:
        evs = net.json(f"https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/events/{d.month:02d}/{d.day:02d}").get("events") or []
    except Exception as e:
        print(f"(on this day lookup failed: {e})")
        return []
    if not evs:
        return []
    # Take about 5 events spread evenly through the list (a step slice [::step]) so they are not all from one century.
    pick = evs[:: max(1, len(evs) // 5)][:5]
    return [_note(f"On this day, {d:%B} {d.day} - Wikipedia", "; ".join(f"{e.get('year')}: {W.clean_text(e.get('text', ''))}" for e in pick) + ".", "https://en.wikipedia.org/")]


# QUAKE_Q: earthquake wording together with "recent/latest/today/this week".
QUAKE_Q = re.compile(r"\b(earthquakes?|quakes?)\b.*\b(recent|latest|today|this week|lately|happening|news)\b|\b(recent|latest|biggest)\s+(earthquakes?|quakes?)\b", re.I)


def earthquakes(q, now, net, online):
    """Provider: the 5 most recent earthquakes of magnitude 4.5+ in the past week, from the USGS feed (place, magnitude, time in UTC)."""
    if not online or not QUAKE_Q.search(q or ""):
        return []
    try:
        feats = net.json("https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson")["features"][:5]
    except Exception as e:
        print(f"(earthquake lookup failed: {e})")
        return []
    if not feats:
        return []
    lines = []
    for f in feats:
        p = f["properties"]
        # USGS times are milliseconds since 1970, so divide by 1000 to get seconds.
        t = time.strftime("%b %d %H:%M UTC", time.gmtime(p["time"] / 1000))
        lines.append(f"M{p['mag']} {p['place']} ({t})")
    return [_note("Recent earthquakes of magnitude 4.5 and up (past week) - USGS", "; ".join(lines) + ".", "https://earthquake.usgs.gov/")]


# RELEASE DATES: games (RAWG) and films/shows (TMDB). These need free API keys read from the environment; with no key the part is silently skipped.
# =========================================================================================== release dates (optional free keys)
# RELEASE_Q: "release date of X", "when is X coming out". RELEASE_STOP: filler words removed so only the title remains.
RELEASE_Q = re.compile(r"\b(release date|when (?:is|does|will|did) .{1,60}?(?:coming out|come out|release|released|out|premiere|launch)|coming out|come out)\b", re.I)
RELEASE_STOP = re.compile(r"\b(when|is|does|will|did|the|coming|come|out|release|released|date|of|new|upcoming|game|movie|film|show|series)\b", re.I)


def releases(q, now, net, online):
    """Provider: release dates of games (needs RAWG_API_KEY) and films/shows (needs TMDB_API_KEY). Returns a note per service that has a key and found something."""
    if not online:
        return []
    q = _clean(q).rstrip("?!. ")
    if not RELEASE_Q.search(q):
        return []
    title = " ".join(RELEASE_STOP.sub(" ", q).split())
    if len(title) < 2:
        return []
    notes = []
    # The key comes from the computer's environment settings (keys.env on the owner's PC); it is never written in this file.
    key = os.environ.get("RAWG_API_KEY")
    if key:
        try:
            rows = net.json("https://api.rawg.io/api/games?" + urllib.parse.urlencode({"search": title, "page_size": 3, "key": key})).get("results") or []
            lines = [f"{r['name']}: " + ("release date to be announced" if r.get("tba") else f"released/releasing {r.get('released') or 'unknown'}") for r in rows]
            if lines:
                notes.append(_note("Games matching the title - rawg.io", "; ".join(lines) + ".", "https://rawg.io/"))
        except Exception as e:
            print(f"(game release lookup failed: {e})")
    key = os.environ.get("TMDB_API_KEY")
    if key:
        try:
            rows = net.json("https://api.themoviedb.org/3/search/multi?" + urllib.parse.urlencode({"query": title, "api_key": key})).get("results") or []
            lines = [f"{r.get('title') or r.get('name')}: {r.get('release_date') or r.get('first_air_date') or 'date unknown'}" for r in rows[:3]
                     if r.get("media_type") in ("movie", "tv")]
            if lines:
                notes.append(_note("Films and shows matching the title - themoviedb.org", "; ".join(lines) + ".", "https://www.themoviedb.org/"))
        except Exception as e:
            print(f"(film release lookup failed: {e})")
    return notes


# =========================================================================================== the pipeline
# PROVIDERS is the master list. gather() goes through it top to bottom, so order = priority. Each row is a tuple of four things (see the line above).
# (name, function, runs without the internet, label the page shows). Order = priority.
PROVIDERS = [
    ("calculator", calculator, True, "Calculator"),
    ("dates", dates, True, "Dates"),
    ("time", clock, True, "Time"),
    ("currency", currency, False, "Exchange rates"),
    ("crypto", crypto, False, "Crypto prices"),
    ("stocks", stocks, False, "Stock prices"),
    ("sports", sports, False, "Sports"),
    ("dictionary", dictionary, False, "Dictionary"),
    ("countries", countries, False, "Country facts"),
    ("holidays", public_holidays, False, "Public holidays"),
    ("news", news, False, "News"),
    ("books", books, False, "Books"),
    ("recipes", recipes, False, "Recipes"),
    ("air", air_quality, False, "Air quality"),
    ("onthisday", on_this_day, False, "On this day"),
    ("earthquakes", earthquakes, False, "Earthquakes"),
    ("releases", releases, False, "Release dates"),
]


import live_more                                  # the second batch (imported here, after everything it uses is defined)

# Re-order the list: offline providers first (this file's, then live_more's), then the online ones, then live_more's online ones, and release dates last.
# List comprehensions like [p for p in X if cond] build a new list from the items that pass the test.
_online = [p for p in PROVIDERS if not p[2] and p[0] != "releases"]
_release = [p for p in PROVIDERS if p[0] == "releases"]
PROVIDERS = [p for p in PROVIDERS if p[2]] + [m for m in live_more.MORE if m[2]] + _online + [m for m in live_more.MORE if not m[2]] + _release


def gather(question, now=None, online=True, net=None, offline_ok=True, default_place=""):
    """(notes, info). `online` lets the internet providers run; `offline_ok` lets the plain-code ones run (False = no live data at all).
    info: {"asked": bool, "live": number of notes, "names": [labels], "sources": [{"title", "kind": "live", "url"}]}."""
    # info is the report for the page: whether anything was found, how many notes, which source labels, and the source links.
    info = {"asked": False, "live": 0, "names": [], "sources": []}
    q = _clean(question)
    if not q or not offline_ok:
        return [], info
    # Use the real internet unless a test passed a fake.
    net = net or Net()
    notes, used = [], 0
    # Try each provider in priority order and stop once enough sources (MAX_PROVIDERS) or notes (MAX_NOTES) have been collected.
    # Online providers are skipped when `online` is off. Some providers also want the default place.
    for name, fn, offline, label in PROVIDERS:
        if used >= MAX_PROVIDERS or len(notes) >= MAX_NOTES:
            break
        if not offline and not online:
            continue
        try:
            got = fn(q, now, net, online, default_place) if (fn is air_quality or getattr(fn, "needs_place", False)) else fn(q, now, net, online)
        except Exception as e:                     # a provider must never break the chat
            print(f"(live data '{name}' failed: {e})")
            got = []
        if got:
            used += 1
            notes += got[:MAX_NOTES - len(notes)]
            info["names"].append(label)
    # Fill in the report only if something was found.
    if notes:
        info.update(asked=True, live=len(notes), sources=[{"title": n["title"], "kind": "live", "url": n.get("url")} for n in notes])
    return notes, info


# KEYED: provider name -> (names of its environment variables, whether the source is useless without one). Used for the settings page.
# which sources need a key (the environment variable names), and whether the source works without one
KEYED = {"releases": (("RAWG_API_KEY", "TMDB_API_KEY"), True), "fred": (("FRED_API_KEY",), True), "wolfram": (("WOLFRAM_APPID",), True), "nutrition": (("USDA_API_KEY",), False)}


# CHECKS: one tiny sample question per main online source: (provider id, label, question). check_sources() really asks them.
CHECKS = [("currency", "Exchange rates", "convert 10 USD to EUR"), ("crypto", "Crypto prices", "what is the price of bitcoin"),
          ("stocks", "Stock prices", "AAPL stock price"), ("sports", "Sports", "when does Liverpool play next"),
          ("dictionary", "Dictionary", "define serendipity"), ("countries", "Country facts", "what is the capital of France"),
          ("news", "News", "latest news headlines")]


def check_sources(env=None, net=None, web_check=None, workers=6):
    """Really ask the main sources one tiny question each: [{"id", "name", "ok", "detail", "ms"}].
    `web_check(name)` is given each web-search source in use and returns (ok, detail); a source with no key is reported as off, not as broken."""
    # concurrent.futures runs several checks at the same time in a thread pool (so six slow web calls take as long as one).
    import concurrent.futures
    import time as _t
    env = os.environ if env is None else env
    net = net or Net()

    # Runs one sample question through gather() and times it. Any crash is reported as a failed check instead of stopping the others.
    def one(item):
        sid, label, question = item
        t0 = _t.time()
        try:
            notes, info = gather(question, online=True, net=net)
            ok = label in info["names"]
            detail = "answered the test question" if ok else "no reply to the test question (the service may be down or blocking this computer)"
        except Exception as e:
            ok, detail = False, "failed: " + str(e)[:120]
        return {"id": sid, "name": label, "ok": ok, "detail": detail, "ms": int((_t.time() - t0) * 1000)}

    rows = []
    if web_check:
        import web_search
        # Web-search services that need a key: if the key is not set, report "off" (ok = None) rather than "broken".
        for name, var in (("tavily", "TAVILY_API_KEY"), ("brave", "BRAVE_API_KEY"), ("gemini", "GEMINI_API_KEY"), ("wikipedia", "")):
            if var and not env.get(var):
                rows.append({"id": "web-" + name, "name": "Web search: " + name.capitalize(), "ok": None, "detail": "off (no " + var + " set on this computer)", "ms": 0})
                continue
            t0 = _t.time()
            ok, detail = web_check(name)
            rows.append({"id": "web-" + name, "name": "Web search: " + name.capitalize(), "ok": ok, "detail": detail, "ms": int((_t.time() - t0) * 1000)})
    # Run the sample questions in parallel (up to `workers` at once) and collect the results in order.
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        rows += list(pool.map(one, CHECKS))
    return rows


def sources_status(env=None):
    """Every live source and whether it is on right now: [{"id", "name", "where": offline|online, "keys": [...], "needs_key", "active", "note"}]."""
    env = os.environ if env is None else env
    rows = []
    for name, fn, offline, label in PROVIDERS:
        # Which environment variables (keys) this source can use, and whether it needs one to work at all.
        keys, required = KEYED.get(name, ((), False))
        have = [k for k in keys if env.get(k)]
        row = {"id": name, "name": label, "where": "offline" if offline else "online", "keys": list(keys), "needs_key": bool(keys and required),
               "active": not (keys and required and not have), "note": ""}
        if keys and not required:
            row["note"] = "Works without a key; " + ("using your key." if have else "a key makes it better.")
        rows.append(row)
    return rows
