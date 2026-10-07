"""
live_more.py - The second batch of live facts (see live_data.py for the idea and the first batch).

      plain code, offline      finance (loan and mortgage payments, compound interest, BMI, percent change), time-zone conversion ("3pm EST in PST"),
                               moon phase, dice and coin, number bases and Roman numerals
      online, free, no key     people's ages and heights (Wikidata), latest package versions (PyPI, npm, GitHub), next TV episode (TVmaze),
                               game prices and release dates (Steam), songs and albums (iTunes), nutrition (Open Food Facts), sunrise and sunset,
                               distance and drive time (Open-Meteo + OSRM), past weather, elevation and surf (Open-Meteo), US weather alerts
                               (weather.gov), country statistics (World Bank), research papers (arXiv, PubMed), coding questions (Stack Exchange),
                               trivia (Open Trivia DB), company filings (SEC EDGAR), more currencies (open.er-api.com, used by live_data's currency)
      online, optional free key  USDA_API_KEY (food data), FRED_API_KEY (US economy), WOLFRAM_APPID (hard math, science and unit questions)

    Each provider has the signature (question, now, net, online) and returns a list of notes; see live_data.gather for how they are used.
    This file imports live_data only inside functions (live_data imports this file when it loads).
"""
import math
import random
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
import os
from datetime import date, datetime, timedelta, timezone


def _L():
    import live_data
    return live_data


def _note(title, text, url=""):
    return _L()._note(title, text, url)


def _q(q):
    return " ".join((q or "").replace("’", "'").split()).rstrip("?!. ")


def _num(s):
    return float(str(s).replace(",", ""))


def _money(x):
    return f"${x:,.2f}"


# =========================================================================================== finance (offline)
_AMT = r"\$?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|million|m)?\b"


def _amount(m):
    v = _num(m.group(1))
    unit = (m.group(2) or "").lower()
    return v * (1000 if unit in ("k", "thousand") else 1_000_000 if unit in ("m", "million") else 1)


def _principal(q):
    """The money amount in a loan or investment question: a $ amount, a number with k/million, or the first big number (never the rate or the years)."""
    m = re.search(r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|million|m)?\b", q) or re.search(r"\b(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|million)\b", q)
    if m:
        return _amount(m)
    for m in re.finditer(r"\b(\d[\d,]*(?:\.\d+)?)\b(?!\s*(?:%|percent|per cent|year|yr|month|mo\b|ft|feet))", q):
        if _num(m.group(1)) >= 1000:
            return _num(m.group(1))
    return None


def _rate(q):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent|per cent)", q)
    return float(m.group(1)) if m else None


def _years(q):
    m = re.search(r"(\d+(?:\.\d+)?)\s*[- ]?\s*(year|yr|month|mo)s?\b", q)
    if not m:
        return None
    return float(m.group(1)) * (1 if m.group(2).startswith("y") else 1 / 12)


def finance(q, now, net, online):
    q = _q(q).lower()
    # loan / mortgage payment
    if re.search(r"\b(mortgage|loan|monthly payment|car payment|amortiz\w*|financ\w+)\b", q) and re.search(r"\bpayment|\bmonthly\b|how much (?:would|will|is)", q):
        rate, yrs = _rate(q), _years(q)
        p = _principal(q)
        if p and rate is not None and yrs:
            n = int(round(yrs * 12))
            r = rate / 100 / 12
            pay = p / n if r == 0 else p * r / (1 - (1 + r) ** -n)
            total = pay * n
            return [_note("Loan payment (exact formula)", f"A {_money(p)} loan at {rate:g}% for {yrs:g} years ({n} months) costs {_money(pay)} a month, "
                                                         f"{_money(total)} in all, of which {_money(total - p)} is interest. Taxes, insurance and fees are not included.")]
    # compound interest
    if re.search(r"\b(compound\w*|invest\w*|savings|grow|interest)\b", q) and re.search(r"\b(for|over|after|in)\b", q):
        rate, yrs = _rate(q), _years(q)
        p = _principal(q)
        if p and rate is not None and yrs:
            per = 12 if re.search(r"compound\w*\s+(?:monthly|every month)", q) else 365 if re.search(r"compound\w*\s+daily", q) else 4 if re.search(r"compound\w*\s+quarterly", q) else 1
            contrib = 0.0
            cm = re.search(r"(?:add|contribut\w*|deposit\w*|plus)\s*(?:of\s*)?\$?\s*(\d[\d,]*(?:\.\d+)?)\s*(?:a|per|each|every)\s*month", q)
            if cm:
                contrib, per = _num(cm.group(1)), 12
            bal = p
            for _ in range(int(round(yrs * per))):
                bal = bal * (1 + rate / 100 / per) + contrib
            paid_in = p + contrib * 12 * yrs
            return [_note("Compound interest (exact formula)", f"{_money(p)} at {rate:g}% a year for {yrs:g} years, compounded {'monthly' if per == 12 else 'daily' if per == 365 else 'quarterly' if per == 4 else 'yearly'}"
                                                              + (f", adding {_money(contrib)} a month" if contrib else "") + f", grows to {_money(bal)} (you put in {_money(paid_in)}). Returns are not guaranteed.")]
    # BMI
    if re.search(r"\bbmi\b|body mass index", q):
        w = re.search(r"(\d+(?:\.\d+)?)\s*(kg|kilos?|kilograms?|lbs?|pounds?)", q)
        h = re.search(r"(\d+(?:\.\d+)?)\s*(cm|centimet\w+|m\b|meters?|in\b|inch\w*)", q)
        ft = re.search(r"(\d)\s*(?:ft|feet|foot|')\s*(\d{1,2})?", q)
        if w and (h or ft):
            kg = _num(w.group(1)) * (1 if w.group(2).startswith("k") else 0.45359237)
            if ft and not h:
                m_ = (int(ft.group(1)) * 12 + int(ft.group(2) or 0)) * 0.0254
            else:
                v, u = _num(h.group(1)), h.group(2)
                m_ = v / 100 if u.startswith("cm") or u.startswith("centi") else v if u.startswith("m") else v * 0.0254
            if 0.5 < m_ < 2.8 and 10 < kg < 500:
                b = kg / m_ ** 2
                cat = "underweight" if b < 18.5 else "healthy range" if b < 25 else "overweight" if b < 30 else "obese"
                return [_note("BMI (exact formula)", f"BMI = {b:.1f} ({cat} on the standard adult scale). BMI is a rough screening number, not a diagnosis.")]
    # percent change / percent of
    m = re.search(r"(?:percent(?:age)?|%)\s*(?:change|increase|decrease|difference)\s*(?:from|between)\s*\$?(-?\d[\d,]*(?:\.\d+)?)\s*(?:to|and)\s*\$?(-?\d[\d,]*(?:\.\d+)?)", q)
    if m:
        a, b = _num(m.group(1)), _num(m.group(2))
        if a != 0:
            ch = (b - a) / abs(a) * 100
            return [_note("Percent change (exact)", f"From {a:,g} to {b:,g} is a {'rise' if ch >= 0 else 'drop'} of {abs(ch):.2f}%.")]
    m = re.search(r"what percent(?:age)? is\s*\$?(\d[\d,]*(?:\.\d+)?)\s*of\s*\$?(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s*is what percent(?:age)? of\s*(\d[\d,]*(?:\.\d+)?)", q)
    if m:
        a, b = (_num(m.group(1)), _num(m.group(2))) if m.group(1) else (_num(m.group(3)), _num(m.group(4)))
        if b != 0:
            return [_note("Percentage (exact)", f"{a:,g} is {a / b * 100:.2f}% of {b:,g}.")]
    return []


# =========================================================================================== time-zone conversion (offline)
ZONES = {"est": "America/New_York", "edt": "America/New_York", "et": "America/New_York", "eastern": "America/New_York", "new york": "America/New_York",
         "cst": "America/Chicago", "cdt": "America/Chicago", "ct": "America/Chicago", "central": "America/Chicago", "chicago": "America/Chicago",
         "mst": "America/Denver", "mdt": "America/Denver", "mt": "America/Denver", "mountain": "America/Denver", "denver": "America/Denver",
         "pst": "America/Los_Angeles", "pdt": "America/Los_Angeles", "pt": "America/Los_Angeles", "pacific": "America/Los_Angeles", "los angeles": "America/Los_Angeles",
         "san francisco": "America/Los_Angeles", "seattle": "America/Los_Angeles", "gmt": "Etc/GMT", "utc": "Etc/UTC", "london": "Europe/London", "bst": "Europe/London",
         "paris": "Europe/Paris", "berlin": "Europe/Berlin", "madrid": "Europe/Madrid", "rome": "Europe/Rome", "cet": "Europe/Paris", "cest": "Europe/Paris",
         "moscow": "Europe/Moscow", "dubai": "Asia/Dubai", "mumbai": "Asia/Kolkata", "delhi": "Asia/Kolkata", "ist": "Asia/Kolkata", "singapore": "Asia/Singapore",
         "hong kong": "Asia/Hong_Kong", "beijing": "Asia/Shanghai", "shanghai": "Asia/Shanghai", "tokyo": "Asia/Tokyo", "jst": "Asia/Tokyo", "seoul": "Asia/Seoul",
         "sydney": "Australia/Sydney", "aest": "Australia/Sydney", "melbourne": "Australia/Melbourne", "auckland": "Pacific/Auckland", "toronto": "America/Toronto",
         "vancouver": "America/Vancouver", "mexico city": "America/Mexico_City", "sao paulo": "America/Sao_Paulo", "cairo": "Africa/Cairo", "lagos": "Africa/Lagos",
         "johannesburg": "Africa/Johannesburg", "honolulu": "Pacific/Honolulu", "hst": "Pacific/Honolulu", "hawaii": "Pacific/Honolulu", "alaska": "America/Anchorage"}
ZONE_RE = "|".join(re.escape(z) for z in sorted(ZONES, key=len, reverse=True))
TZ_Q = re.compile(rf"(?P<h>\d{{1,2}})(?::(?P<m>\d{{2}}))?\s*(?P<ap>am|pm|a\.m\.|p\.m\.)?\s*(?P<a>{ZONE_RE})(?:\s+time)?\s+(?:to|in|into|->)\s+(?:the\s+)?(?P<b>{ZONE_RE})(?:\s+time)?\b", re.I)


def tzconvert(q, now, net, online):
    m = TZ_Q.search(_q(q))
    if not m:
        return []
    h, mi, ap = int(m.group("h")), int(m.group("m") or 0), (m.group("ap") or "").lower().replace(".", "")
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if h > 23 or mi > 59:
        return []
    try:
        from zoneinfo import ZoneInfo
        za, zb = ZoneInfo(ZONES[m.group("a").lower()]), ZoneInfo(ZONES[m.group("b").lower()])
        today = datetime.fromtimestamp(now or time.time()).date()
        src = datetime(today.year, today.month, today.day, h, mi, tzinfo=za)
        dst = src.astimezone(zb)
    except Exception as e:
        print(f"(time zone conversion failed: {e})")
        return []
    day = "" if dst.date() == src.date() else (" the next day" if dst.date() > src.date() else " the previous day")
    f = lambda d: f"{d:%I:%M %p}".lstrip("0")
    return [_note("Time zone conversion (exact, daylight saving included for today)",
                  f"{f(src)} {m.group('a').upper() if len(m.group('a')) <= 4 else m.group('a').title()} ({src.tzname()}) is {f(dst)}{day} in {m.group('b').upper() if len(m.group('b')) <= 4 else m.group('b').title()} ({dst.tzname()}).")]


# =========================================================================================== moon phase (offline)
SYNODIC = 29.530588853
NEW_MOON_EPOCH = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)


def _moon_age(t):
    return ((t - NEW_MOON_EPOCH).total_seconds() / 86400) % SYNODIC


def _phase_name(age):
    frac = age / SYNODIC
    names = [(0.03, "new moon"), (0.22, "waxing crescent"), (0.28, "first quarter"), (0.47, "waxing gibbous"), (0.53, "full moon"), (0.72, "waning gibbous"),
             (0.78, "last quarter"), (0.97, "waning crescent"), (1.01, "new moon")]
    return next(n for edge, n in names if frac < edge)


def moon(q, now, net, online):
    if not re.search(r"\b(moon phase|phase of the moon|full moon|new moon|moon tonight|is the moon|how full is the moon|what.s the moon)\b", _q(q), re.I):
        return []
    t = datetime.fromtimestamp(now or time.time(), timezone.utc)
    age = _moon_age(t)
    illum = (1 - math.cos(2 * math.pi * age / SYNODIC)) / 2 * 100
    to_full = (SYNODIC / 2 - age) % SYNODIC
    to_new = (SYNODIC - age) % SYNODIC
    full, new = t + timedelta(days=to_full), t + timedelta(days=to_new)
    return [_note("Moon phase (calculated, accurate to about a day)",
                  f"Today the moon is a {_phase_name(age)}, about {illum:.0f}% lit. The next full moon is around {full:%A, %B} {full.day}, {full.year}; the next new moon around {new:%A, %B} {new.day}, {new.year}.")]


# =========================================================================================== dice, coins, bases, Roman numerals (offline)
_rng = random.SystemRandom()


def dice(q, now, net, online):
    q = _q(q).lower()
    m = re.search(r"\broll\s+(?:a\s+)?(?:(\d+)\s*d\s*(\d+)|(\d+)\s+(?:six[- ]sided\s+)?dice|(?:a\s+)?(?:d(\d+)|die|dice))\b", q)
    if m:
        if m.group(1):
            n, s = int(m.group(1)), int(m.group(2))
        elif m.group(3):
            n, s = int(m.group(3)), 6
        else:
            n, s = 1, int(m.group(4) or 6)
        if 1 <= n <= 20 and 2 <= s <= 1000:
            rolls = [_rng.randint(1, s) for _ in range(n)]
            return [_note("Dice roll (random)", f"Rolled {n}d{s}: {', '.join(map(str, rolls))}" + (f" (total {sum(rolls)})" if n > 1 else "") + ".")]
    if re.search(r"\b(flip|toss)\s+a\s+coin\b|\bheads or tails\b", q):
        return [_note("Coin flip (random)", f"The coin landed on {_rng.choice(['heads', 'tails'])}.")]
    m = re.search(r"\b(?:random|pick)\s+(?:a\s+)?(?:number|integer)?\s*(?:between|from)\s+(-?\d+)\s+(?:and|to)\s+(-?\d+)", q)
    if m:
        a, b = sorted((int(m.group(1)), int(m.group(2))))
        return [_note("Random number", f"The random number between {a} and {b} is {_rng.randint(a, b)}.")]
    return []


ROMAN = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


def _to_roman(n):
    out = ""
    for v, s in ROMAN:
        while n >= v:
            out += s
            n -= v
    return out


def _from_roman(s):
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    for i, ch in enumerate(s):
        v = vals[ch]
        total += -v if i + 1 < len(s) and vals[s[i + 1]] > v else v
    return total


def bases(q, now, net, online):
    q = _q(q).lower()
    m = re.search(r"\b(?:what is |convert |write )?(\d+)\s+(?:in|to|as)\s+(binary|hex|hexadecimal|octal)\b|\b(binary|hex|hexadecimal|octal) (?:of|for)\s+(\d+)\b", q)
    if m:
        n = int(m.group(1) or m.group(4))
        kind = m.group(2) or m.group(3)
        if n < 10 ** 12:
            s = bin(n)[2:] if kind == "binary" else hex(n)[2:].upper() if kind.startswith("hex") else oct(n)[2:]
            return [_note("Number base conversion (exact)", f"{n} in {kind} is {s}.")]
    m = re.search(r"\b(?:0b([01]+)|(?:binary )?([01]{3,}) (?:in|to) (?:decimal|base 10)|0x([0-9a-f]+)|hex(?:adecimal)? ([0-9a-f]+) (?:in|to) decimal)\b", q)
    if m:
        if m.group(1) or m.group(2):
            s = m.group(1) or m.group(2)
            return [_note("Number base conversion (exact)", f"Binary {s} is {int(s, 2)} in decimal.")]
        s = m.group(3) or m.group(4)
        return [_note("Number base conversion (exact)", f"Hexadecimal {s.upper()} is {int(s, 16)} in decimal.")]
    m = re.search(r"\b(\d{1,4})\s+(?:in|as|to)\s+roman(?: numerals?)?\b|\broman numerals? (?:for|of)\s+(\d{1,4})\b", q)
    if m:
        n = int(m.group(1) or m.group(2))
        if 0 < n < 4000:
            return [_note("Roman numerals (exact)", f"{n} in Roman numerals is {_to_roman(n)}.")]
    m = re.search(r"\b(?:what is|what's|convert)\s+([ivxlcdm]{2,12})\s+(?:in|to|as)\s+(?:number|numbers|decimal|digits|arabic)", q)
    if m and re.fullmatch(r"m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})", m.group(1)):
        return [_note("Roman numerals (exact)", f"{m.group(1).upper()} is {_from_roman(m.group(1).upper())}.")]
    return []


# =========================================================================================== people (Wikidata)
PERSON_Q = re.compile(r"^(?:how old (?:is|was)\s+(?P<a>.+?)|when (?:was|is)\s+(?P<b>.+?)\s+born|when did\s+(?P<c>.+?)\s+die|how tall (?:is|was)\s+(?P<d>.+?)|"
                      r"when (?:is|was)\s+(?P<e>.+?)'s birthday|what(?:'s| is)\s+(?P<f>.+?)'s age|what(?:'s| is| was)\s+(?P<g>.+?)'s height|how old is\s+(?P<h>.+?)\s+now)$", re.I)


def _wd_time(claim):
    try:
        v = claim["mainsnak"]["datavalue"]["value"]
        s, prec = v["time"].lstrip("+"), v.get("precision", 11)
        y, mo, d = int(s[:4]), int(s[5:7]), int(s[8:10])
        if prec < 11 or mo == 0 or d == 0:
            return None, y
        return date(y, mo, d), y
    except (KeyError, ValueError, TypeError):
        return None, None


def _age(born, end):
    return end.year - born.year - ((end.month, end.day) < (born.month, born.day))


def person(q, now, net, online):
    if not online:
        return []
    m = PERSON_Q.match(_q(q))
    if not m:
        return []
    name = next(g for g in m.groups() if g)
    if name.lower() in ("it", "this", "that", "he", "she", "the earth", "the sun", "the universe", "the moon", "my dog", "my cat", "my mom", "my dad") or len(name) < 3 or name.lower().startswith(("my ", "mount ", "mt ", "mt. ", "the ", "lake ", "river ", "tower ", "bridge ", "statue ", "building ", "a ", "an ")):
        return []
    try:
        hits = net.json("https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
            {"action": "wbsearchentities", "search": name, "language": "en", "format": "json", "limit": 3, "type": "item"})).get("search") or []
        ent = None
        for h in hits:
            data = net.json(f"https://www.wikidata.org/wiki/Special:EntityData/{h['id']}.json")["entities"][h["id"]]
            claims = data.get("claims", {})
            if any(c["mainsnak"].get("datavalue", {}).get("value", {}).get("id") == "Q5" for c in claims.get("P31", [])):
                ent = (h, data, claims)
                break
        if not ent:
            return []
    except Exception as e:
        print(f"(Wikidata lookup failed: {e})")
        return []
    h, data, claims = ent
    label = (data.get("labels", {}).get("en") or {}).get("value") or h.get("label") or name
    desc = (data.get("descriptions", {}).get("en") or {}).get("value") or ""
    born = _wd_time(claims["P569"][0])[0] if claims.get("P569") else None
    died = _wd_time(claims["P570"][0])[0] if claims.get("P570") else None
    today = datetime.fromtimestamp(now or time.time()).date()
    parts = []
    if born:
        parts.append(f"born {_L()._long(born)}")
        parts.append(f"died {_L()._long(died)} at age {_age(born, died)}" if died else f"is {_age(born, today)} years old today ({_L()._long(today)})")
    elif died:
        parts.append(f"died {_L()._long(died)}")
    if claims.get("P2048"):
        try:
            amt = float(claims["P2048"][0]["mainsnak"]["datavalue"]["value"]["amount"])
            unit = claims["P2048"][0]["mainsnak"]["datavalue"]["value"].get("unit", "")
            m_ = amt / 100 if unit.endswith("Q174728") else amt
            parts.append(f"height {m_:.2f} m ({int(m_ / 0.3048)} ft {round(m_ / 0.0254 % 12)} in)")
        except (KeyError, ValueError, TypeError):
            pass
    if not parts:
        return []
    return [_note(f"{label} - Wikidata", f"{label}" + (f" ({desc})" if desc else "") + ": " + "; ".join(parts) + ".", f"https://www.wikidata.org/wiki/{h['id']}")]


# =========================================================================================== packages
NPM_HINT = re.compile(r"\b(npm|node|nodejs|javascript|js|react|vue|angular|svelte|typescript|express|next\.?js|webpack|vite|jquery|tailwind)\b", re.I)
PY_HINT = re.compile(r"\b(pip|pypi|python|django|flask|numpy|pandas|requests|fastapi|pytest|torch|pytorch|tensorflow|scipy|matplotlib|transformers)\b", re.I)
PKG_Q = re.compile(r"\b(?:latest|newest|current)\s+(?:stable\s+)?(?:version|release)\s+of\s+(?:the\s+)?(?:python\s+|npm\s+|node\s+)?(?:package\s+|library\s+)?(?P<n>[@a-z0-9][\w@./\-]{0,60})|"
                   r"\bwhat(?:'s| is)\s+(?:the\s+)?(?:latest\s+)?version\s+of\s+(?P<n2>[@a-z0-9][\w@./\-]{0,60})|\bpip\s+install\s+(?P<n3>[a-z0-9][\w.\-]+)\s+version\b", re.I)


def packages(q, now, net, online):
    if not online:
        return []
    m = PKG_Q.search(_q(q))
    if not m:
        return []
    name = (m.group("n") or m.group("n2") or m.group("n3")).strip().lower().rstrip(".,")
    if name in ("python", "node", "nodejs", "java", "it", "the", "windows", "ios", "android", "chrome", "firefox", "linux", "macos"):
        return []
    notes = []
    if re.fullmatch(r"[\w.-]+/[\w.-]+", name) and not name.startswith("@"):
        try:
            r = net.json(f"https://api.github.com/repos/{name}/releases/latest")
            return [_note(f"Latest release of {name} - GitHub", f"{name} latest release: {r.get('tag_name')} ({r.get('name') or ''}), published {r.get('published_at', '')[:10]}.", r.get("html_url") or "")]
        except Exception as e:
            print(f"(GitHub release lookup failed: {e})")
            return []
    order = ["npm", "pypi"] if NPM_HINT.search(q) and not PY_HINT.search(q) else ["pypi", "npm"]
    for src in order:
        try:
            if src == "pypi":
                r = net.json(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json")
                info = r["info"]
                up = (r.get("urls") or [{}])[0].get("upload_time", "")[:10]
                notes.append(_note(f"{info['name']} on PyPI", f"{info['name']} latest version on PyPI: {info['version']}" + (f", uploaded {up}" if up else "")
                                   + (f". Requires Python {info['requires_python']}" if info.get("requires_python") else "") + ".", f"https://pypi.org/project/{info['name']}/"))
            else:
                r = net.json(f"https://registry.npmjs.org/{urllib.parse.quote(name, safe='@')}/latest")
                notes.append(_note(f"{r['name']} on npm", f"{r['name']} latest version on npm: {r['version']}.", f"https://www.npmjs.com/package/{r['name']}"))
        except Exception:
            continue
        if notes:
            break
    return notes


# =========================================================================================== TV, games, music
TV_Q = re.compile(r"\b(?:next|new|latest|upcoming)\s+(?:episode|season)\s+of\s+(?P<t>.+)$|\bwhen (?:does|is|will)\s+(?P<t2>.+?)\s+(?:come back|return|premiere|season \d+|next episode|new season|air)\b|"
                  r"\bwhen (?:does|is|will) the next episode of\s+(?P<t3>.+?)\s*(?:air|come out)?$", re.I)


def tv(q, now, net, online):
    if not online:
        return []
    m = TV_Q.search(_q(q))
    if not m:
        return []
    title = re.sub(r"\b(come out|air|premiere|out)$", "", next(g for g in m.groups() if g), flags=re.I).strip(" ,.")
    if len(title) < 2:
        return []
    try:
        s = net.json("https://api.tvmaze.com/singlesearch/shows?" + urllib.parse.urlencode({"q": title}) + "&embed[]=nextepisode&embed[]=previousepisode")
    except Exception as e:
        print(f"(TV lookup failed: {e})")
        return []
    emb = s.get("_embedded") or {}
    nxt, prev = emb.get("nextepisode"), emb.get("previousepisode")
    bits = [f"{s.get('name')} ({s.get('status')}, premiered {s.get('premiered') or 'unknown'})"]
    if nxt:
        bits.append(f"next episode: S{nxt.get('season')}E{nxt.get('number')} \"{nxt.get('name')}\" airs {nxt.get('airdate')}" + (f" at {nxt['airtime']}" if nxt.get("airtime") else ""))
    elif s.get("status") == "Ended":
        bits.append("the show has ended, so no new episodes are scheduled")
    else:
        bits.append("no next episode date is announced yet")
    if prev:
        bits.append(f"last episode: S{prev.get('season')}E{prev.get('number')} aired {prev.get('airdate')}")
    return [_note(f"{s.get('name')} schedule - tvmaze.com", "; ".join(bits) + ".", s.get("url") or "https://www.tvmaze.com/")]


STEAM_Q = re.compile(r"\bsteam\b", re.I)


def steam(q, now, net, online):
    if not online:
        return []
    q = _q(q)
    if not STEAM_Q.search(q):
        return []
    title = re.sub(r"\b(steam|price|cost|how much|is|on|sale|the|of|for|game|release|date|when|does|do|a|an|to|buy|cheap|discount|coming|out|released)\b", " ", q, flags=re.I)
    title = " ".join(title.split())
    if len(title) < 2:
        return []
    try:
        items = net.json("https://store.steampowered.com/api/storesearch/?" + urllib.parse.urlencode({"term": title, "cc": "us", "l": "en"})).get("items") or []
        if not items:
            return []
        it = items[0]
        det = net.json("https://store.steampowered.com/api/appdetails?" + urllib.parse.urlencode({"appids": it["id"], "cc": "us", "l": "en"}))[str(it["id"])]["data"]
    except Exception as e:
        print(f"(Steam lookup failed: {e})")
        return []
    rd = det.get("release_date") or {}
    po = det.get("price_overview") or {}
    price = "free to play" if det.get("is_free") else (po.get("final_formatted") + (f" (was {po['initial_formatted']}, {po['discount_percent']}% off)" if po.get("discount_percent") else "")) if po else "no price listed"
    return [_note(f"{det.get('name')} on Steam", f"{det.get('name')}: {price}; " + ("not released yet, " if rd.get("coming_soon") else "released ") + f"{rd.get('date', 'date unknown')}.",
                  f"https://store.steampowered.com/app/{it['id']}/")]


MUSIC_Q = re.compile(r"\b(?:who sings|who sang|who performs|song by|songs by|albums? by|discography of|latest (?:album|song|single) (?:by|from)|new (?:album|song) (?:by|from)|"
                     r"when (?:did|was|is) .+? (?:album|song|single) (?:come out|released|release))\b(?P<t>.*)$", re.I)


def music(q, now, net, online):
    if not online:
        return []
    q = _q(q)
    m = MUSIC_Q.search(q)
    if not m:
        return []
    term = (m.group("t") or q).strip(" ,.\"'")
    term = re.sub(r"\b(album|song|single|come out|released?|did|was|is|when|the)\b", " ", term, flags=re.I)
    term = " ".join(term.split())
    if len(term) < 2:
        return []
    entity = "album" if re.search(r"album|discography", q, re.I) else "song"
    try:
        rows = net.json("https://itunes.apple.com/search?" + urllib.parse.urlencode({"term": term, "entity": entity, "limit": 6})).get("results") or []
    except Exception as e:
        print(f"(iTunes lookup failed: {e})")
        return []
    if not rows:
        return []
    lines = []
    for r in rows[:6]:
        nm = r.get("collectionName") if entity == "album" else r.get("trackName")
        lines.append(f"{nm} by {r.get('artistName')} ({(r.get('releaseDate') or '')[:10]})")
    return [_note(f"Music matching '{term}' - Apple iTunes Search", "; ".join(lines) + ".", "https://music.apple.com/")]


# =========================================================================================== nutrition
FOOD_Q = re.compile(r"\b(?:calories|calorie|protein|carbs|carbohydrates|fat|sugar|nutrition(?: facts)?|nutritional (?:value|info\w*))\s+(?:in|of|for)\s+(?:an?\s+|one\s+|1\s+|a (?:cup|slice|bowl|serving) of\s+)?(?P<f>[a-z][a-z ,'&\-]{1,40})|"
                    r"\bhow (?:many|much)\s+(?:calories|protein|carbs|sugar|fat)\s+(?:are |is )?(?:in|does)\s+(?:an?\s+|one\s+|1\s+)?(?P<f2>[a-z][a-z ,'&\-]{1,40})", re.I)


def nutrition(q, now, net, online):
    if not online:
        return []
    m = FOOD_Q.search(_q(q))
    if not m:
        return []
    food = re.sub(r"\b(have|contain|per|serving|please)\b.*$", "", (m.group("f") or m.group("f2")), flags=re.I).strip(" ,.")
    if len(food) < 2:
        return []
    key = os.environ.get("USDA_API_KEY")
    try:
        if key:
            foods = net.json("https://api.nal.usda.gov/fdc/v1/foods/search?" + urllib.parse.urlencode({"query": food, "pageSize": 3, "dataType": "Foundation,SR Legacy", "api_key": key})).get("foods") or []
            f = foods[0]
            nut = {n["nutrientName"]: (n["value"], n.get("unitName", "")) for n in f.get("foodNutrients", [])}
            def g(*names):
                for nm in names:
                    if nm in nut:
                        return f"{nut[nm][0]:g} {nut[nm][1].lower()}"
                return None
            parts = [x for x in (f"energy {g('Energy')}" if g("Energy") else None, f"protein {g('Protein')}" if g("Protein") else None,
                                 f"fat {g('Total lipid (fat)')}" if g("Total lipid (fat)") else None, f"carbs {g('Carbohydrate, by difference')}" if g("Carbohydrate, by difference") else None) if x]
            return [_note(f"{f['description']} - USDA FoodData Central (per 100 g)", "Per 100 g: " + ", ".join(parts) + ".", "https://fdc.nal.usda.gov/")] if parts else []
        prods = net.json("https://world.openfoodfacts.org/cgi/search.pl?" + urllib.parse.urlencode(
            {"search_terms": food, "search_simple": 1, "action": "process", "json": 1, "page_size": 3, "fields": "product_name,brands,nutriments"})).get("products") or []
        p = next(x for x in prods if (x.get("nutriments") or {}).get("energy-kcal_100g") is not None)
        n = p["nutriments"]
    except Exception as e:
        print(f"(nutrition lookup failed: {e})")
        return []
    return [_note(f"{p.get('product_name')} - Open Food Facts (per 100 g)",
                  f"{p.get('product_name')}{' (' + p['brands'] + ')' if p.get('brands') else ''}, per 100 g: {n.get('energy-kcal_100g'):g} kcal, protein {n.get('proteins_100g', 0):g} g, "
                  f"fat {n.get('fat_100g', 0):g} g, carbs {n.get('carbohydrates_100g', 0):g} g, sugar {n.get('sugars_100g', 0):g} g. Packaged products vary: check the label.",
                  "https://world.openfoodfacts.org/")]


# =========================================================================================== places: sun, distance, past weather, elevation, surf, alerts
def _place_after(q, words):
    m = re.search(rf"\b(?:{words})\s+(?:in|at|for|near|of)?\s*([A-Za-z][A-Za-z'.\- ,]*)", q, re.I)
    return m


def _clean_place(p):
    p = re.sub(r"\b(today|tonight|tomorrow|now|right now|please|this (?:week|weekend|morning|evening)|yesterday)\b.*$", "", p or "", flags=re.I).strip(" ,.-")
    return re.sub(r"^(the|my)\s+", "", p, flags=re.I)


def sun(q, now, net, online, default_place=""):
    if not online:
        return []
    q = _q(q)
    if not re.search(r"\b(sunrise|sunset|sun rise|sun set|daylight|golden hour|when does the sun)\b", q, re.I):
        return []
    m = re.search(r"\b(?:in|at|for|near)\s+([A-Za-z][A-Za-z'.\- ,]*)$", q)
    place = _clean_place(m.group(1)) if m else default_place
    if not place:
        return []
    try:
        hit = _L()._geocode(place, net)
        if not hit:
            return []
        d = net.json("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(
            {"latitude": hit["latitude"], "longitude": hit["longitude"], "daily": "sunrise,sunset,daylight_duration", "timezone": "auto", "forecast_days": 2}))["daily"]
    except Exception as e:
        print(f"(sunrise lookup failed: {e})")
        return []
    where = ", ".join(x for x in (hit.get("name"), hit.get("admin1"), hit.get("country")) if x)
    lines = []
    for i, label in enumerate(("Today", "Tomorrow")):
        rise, sset = d["sunrise"][i][11:16], d["sunset"][i][11:16]
        hrs = d["daylight_duration"][i] / 3600
        lines.append(f"{label} ({d['time'][i]}): sunrise {rise}, sunset {sset} (local time), {int(hrs)} h {round(hrs % 1 * 60)} min of daylight")
    return [_note(f"Sunrise and sunset in {where} - open-meteo.com", "; ".join(lines) + ".", "https://open-meteo.com/")]


def _haversine(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a["latitude"], a["longitude"], b["latitude"], b["longitude"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


DIST_Q = re.compile(r"\bhow far is\s+(?P<a>.+?)\s+(?:from|to)\s+(?P<b>.+)$|\bdistance\s+(?:between|from)\s+(?P<a2>.+?)\s+(?:and|to)\s+(?P<b2>.+)$|"
                    r"\bhow long (?:does it take )?to (?:drive|fly|travel)\s+from\s+(?P<a3>.+?)\s+to\s+(?P<b3>.+)$|\b(?:drive|driving) (?:time|distance) (?:from|between)\s+(?P<a4>.+?)\s+(?:to|and)\s+(?P<b4>.+)$", re.I)


def distance(q, now, net, online):
    if not online:
        return []
    m = DIST_Q.search(_q(q))
    if not m:
        return []
    g = m.groupdict()
    a = next(g[k] for k in ("a", "a2", "a3", "a4") if g.get(k))
    b = next(g[k] for k in ("b", "b2", "b3", "b4") if g.get(k))
    a, b = _clean_place(a), _clean_place(re.sub(r"\b(by car|driving|by road|in miles|in km|in kilometers)\b", "", b, flags=re.I))
    if len(a) < 2 or len(b) < 2 or re.search(r"\b(sun|moon|mars|earth|venus|jupiter|saturn|star|galaxy|light)\b", a + " " + b, re.I):
        return []
    try:
        ha, hb = _L()._geocode(a, net), _L()._geocode(b, net)
        if not ha or not hb:
            return []
    except Exception as e:
        print(f"(distance lookup failed: {e})")
        return []
    km = _haversine(ha, hb)
    text = f"{ha['name']} to {hb['name']}: {km:,.0f} km ({km * 0.621371:,.0f} miles) in a straight line"
    if re.search(r"\b(drive|driving|car|road|how long|travel|trip|route)\b", q.lower()):
        try:
            r = net.json(f"https://router.project-osrm.org/route/v1/driving/{ha['longitude']},{ha['latitude']};{hb['longitude']},{hb['latitude']}?overview=false")["routes"][0]
            hrs = r["duration"] / 3600
            text += f"; by road about {r['distance'] / 1000:,.0f} km ({r['distance'] / 1609.344:,.0f} miles), roughly {int(hrs)} h {round(hrs % 1 * 60)} min of driving without stops or traffic"
        except Exception:
            pass
    return [_note("Distance - Open-Meteo places, OSRM routes", text + ".", "https://project-osrm.org/")]


def past_weather(q, now, net, online, default_place=""):
    if not online:
        return []
    q = _q(q)
    if not re.search(r"\b(weather|temperature|rain|snow|hot|cold)\b", q, re.I) or not re.search(r"\b(was|were|on|yesterday|last)\b", q, re.I):
        return []
    L = _L()
    today = datetime.fromtimestamp(now or time.time()).date()
    day = None
    if re.search(r"\byesterday\b", q, re.I):
        day = today - timedelta(days=1)
    else:
        found = L._explicit_dates(q, today)
        if found:
            day = found[0]
    if not day or day >= today:
        return []
    m = re.search(r"\b(?:in|at|for|near)\s+([A-Za-z][A-Za-z'.\- ,]*?)(?:\s+(?:on|in|last|yesterday)\b|$)", q)
    place = _clean_place(m.group(1)) if m else default_place
    if not place:
        return []
    try:
        hit = L._geocode(place, net)
        if not hit:
            return []
        d = net.json("https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode(
            {"latitude": hit["latitude"], "longitude": hit["longitude"], "start_date": day.isoformat(), "end_date": day.isoformat(),
             "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code", "timezone": "auto"}))["daily"]
        hi, lo, pr, wc = d["temperature_2m_max"][0], d["temperature_2m_min"][0], d["precipitation_sum"][0], d["weather_code"][0]
    except Exception as e:
        print(f"(past weather lookup failed: {e})")
        return []
    import web_search as W
    where = ", ".join(x for x in (hit.get("name"), hit.get("admin1"), hit.get("country")) if x)
    return [_note(f"Past weather in {where} - open-meteo.com", f"On {L._long(day)}: {W.WMO.get(wc, 'unknown conditions')}, high {hi:.0f}°C ({hi * 9 / 5 + 32:.0f}°F), low {lo:.0f}°C "
                                                               f"({lo * 9 / 5 + 32:.0f}°F), precipitation {pr:g} mm.", "https://open-meteo.com/")]


def elevation(q, now, net, online):
    if not online:
        return []
    m = re.search(r"\b(?:elevation|altitude)\s+(?:of|in|at)\s+(?P<p>[A-Za-z][A-Za-z'.\- ,]+)$|\bhow high (?:above sea level )?is\s+(?P<p2>[A-Za-z][A-Za-z'.\- ,]+)$|\bhow (?:high|many (?:feet|meters|metres)) above sea level is\s+(?P<p3>.+)$", _q(q), re.I)
    if not m:
        return []
    place = _clean_place(next(g for g in m.groups() if g))
    try:
        hit = _L()._geocode(place, net)
        if not hit or hit.get("elevation") is None:
            return []
    except Exception as e:
        print(f"(elevation lookup failed: {e})")
        return []
    where = ", ".join(x for x in (hit.get("name"), hit.get("admin1"), hit.get("country")) if x)
    el = hit["elevation"]
    return [_note(f"Elevation of {where} - open-meteo.com", f"{where} is about {el:,.0f} m ({el * 3.28084:,.0f} ft) above sea level (the point the place name resolves to).", "https://open-meteo.com/")]


def surf(q, now, net, online):
    if not online:
        return []
    m = re.search(r"\b(?:surf|wave|waves|swell|ocean conditions|surf report)\b.*?\b(?:in|at|for|near)\s+(?P<p>[A-Za-z][A-Za-z'.\- ,]+)$", _q(q), re.I)
    if not m:
        return []
    try:
        hit = _L()._geocode(_clean_place(m.group("p")), net)
        if not hit:
            return []
        cur = net.json("https://marine-api.open-meteo.com/v1/marine?" + urllib.parse.urlencode(
            {"latitude": hit["latitude"], "longitude": hit["longitude"], "current": "wave_height,wave_period,wave_direction", "timezone": "auto"}))["current"]
        h = cur["wave_height"]
    except Exception as e:
        print(f"(surf lookup failed: {e})")
        return []
    return [_note(f"Waves near {hit.get('name')} - open-meteo.com", f"Wave height {h:g} m ({h * 3.28084:.1f} ft), period {cur.get('wave_period')} s, from {cur.get('wave_direction')} degrees. "
                                                                    "Open-ocean model: beach conditions can differ.", "https://open-meteo.com/")]


def alerts(q, now, net, online, default_place=""):
    if not online:
        return []
    q = _q(q)
    if not re.search(r"\b(weather alerts?|severe weather|weather warnings?|tornado warning|flood warning|storm warning|any alerts)\b", q, re.I):
        return []
    m = re.search(r"\b(?:in|at|for|near)\s+([A-Za-z][A-Za-z'.\- ,]*)$", q)
    place = _clean_place(m.group(1)) if m else default_place
    if not place:
        return []
    try:
        hit = _L()._geocode(place, net)
        if not hit or hit.get("country_code") != "US":
            return []
        feats = net.json(f"https://api.weather.gov/alerts/active?point={hit['latitude']:.4f},{hit['longitude']:.4f}").get("features") or []
    except Exception as e:
        print(f"(weather alert lookup failed: {e})")
        return []
    where = ", ".join(x for x in (hit.get("name"), hit.get("admin1")) if x)
    if not feats:
        return [_note(f"Weather alerts for {where} - weather.gov", f"No active weather alerts for {where} right now.", "https://www.weather.gov/")]
    lines = [f"{f['properties'].get('event')} ({f['properties'].get('severity')}): {f['properties'].get('headline')}" for f in feats[:4]]
    return [_note(f"Weather alerts for {where} - weather.gov", " | ".join(lines), "https://www.weather.gov/")]


# =========================================================================================== economy (World Bank, FRED)
WB = {"gdp per capita": ("NY.GDP.PCAP.CD", "GDP per person (US$)"), "gdp": ("NY.GDP.MKTP.CD", "GDP (US$)"), "inflation": ("FP.CPI.TOTL.ZG", "inflation (% a year)"),
      "unemployment": ("SL.UEM.TOTL.ZS", "unemployment (% of workforce)"), "life expectancy": ("SP.DYN.LE00.IN", "life expectancy (years)"),
      "literacy": ("SE.ADT.LITR.ZS", "adult literacy (%)"), "poverty": ("SI.POV.DDAY", "poverty rate at $2.15 a day (%)"), "co2": ("EN.GHG.CO2.PC.CE.AR5", "CO2 per person (tonnes)")}
WB_Q = re.compile(r"\b(?P<k>gdp per capita|gdp|inflation(?: rate)?|unemployment(?: rate)?|life expectancy|literacy(?: rate)?|poverty(?: rate)?|co2 emissions?)\b\s+(?:of|in|for)\s+(?:the\s+)?(?P<c>[a-z][a-z ]{2,30})", re.I)


def worldbank(q, now, net, online):
    if not online:
        return []
    m = WB_Q.search(_q(q))
    if not m:
        return []
    key = re.sub(r"\s*(rate|emissions?)$", "", m.group("k").lower()).strip()
    key = "co2" if key.startswith("co2") else key
    code = _L().COUNTRY_CODES.get(re.sub(r"\b(right now|today|this year|last year|in \d{4})\b.*$", "", m.group("c").lower()).strip())
    if key not in WB or not code:
        return []
    ind, label = WB[key]
    try:
        rows = net.json(f"https://api.worldbank.org/v2/country/{code}/indicator/{ind}?format=json&per_page=5&mrnev=1")[1]
        row = next(r for r in rows if r.get("value") is not None)
    except Exception as e:
        print(f"(World Bank lookup failed: {e})")
        return []
    v = row["value"]
    shown = f"${v / 1e12:,.2f} trillion" if ind == "NY.GDP.MKTP.CD" and v >= 1e12 else f"${v / 1e9:,.1f} billion" if ind == "NY.GDP.MKTP.CD" else f"{v:,.2f}"
    return [_note(f"{row['country']['value']}: {label} - World Bank", f"{row['country']['value']} {label}: {shown} ({row['date']}, the latest year the World Bank has). Official statistics lag by a year or more.",
                  "https://data.worldbank.org/")]


FRED = {"unemployment": ("UNRATE", "US unemployment rate (%)"), "fed funds": ("FEDFUNDS", "federal funds rate (%)"), "interest rate": ("FEDFUNDS", "federal funds rate (%)"),
        "mortgage rate": ("MORTGAGE30US", "average 30-year mortgage rate (%)"), "30 year mortgage": ("MORTGAGE30US", "average 30-year mortgage rate (%)"),
        "10 year treasury": ("DGS10", "10-year Treasury yield (%)"), "treasury yield": ("DGS10", "10-year Treasury yield (%)"), "inflation": ("CPIAUCSL", "consumer price index (1982-84=100)"),
        "gas price": ("GASREGW", "average US regular gasoline price ($/gallon)"), "gdp": ("GDP", "US GDP (billions of dollars, annual rate)")}


def fred(q, now, net, online):
    key = os.environ.get("FRED_API_KEY")
    if not online or not key:
        return []
    low = _q(q).lower()
    if not re.search(r"\b(us|u\.s\.|american|america|united states|fed|mortgage|treasury|gas price)\b", low):
        return []
    k = next((k for k in sorted(FRED, key=len, reverse=True) if k in low), None)
    if not k:
        return []
    sid, label = FRED[k]
    try:
        obs = net.json("https://api.stlouisfed.org/fred/series/observations?" + urllib.parse.urlencode(
            {"series_id": sid, "api_key": key, "file_type": "json", "sort_order": "desc", "limit": 5}))["observations"]
        o = next(x for x in obs if x["value"] not in (".", ""))
    except Exception as e:
        print(f"(FRED lookup failed: {e})")
        return []
    return [_note(f"{label} - FRED (St. Louis Fed)", f"{label}: {o['value']} (as of {o['date']}).", f"https://fred.stlouisfed.org/series/{sid}")]


# =========================================================================================== research, coding, trivia, filings
ARXIV_Q = re.compile(r"\b(?:latest|recent|new|newest)\s+(?:research\s+)?papers?\s+(?:on|about)\s+(?P<t>.+)$|\barxiv\b.*?\b(?:on|about)\s+(?P<t2>.+)$", re.I)


def arxiv(q, now, net, online):
    if not online:
        return []
    m = ARXIV_Q.search(_q(q))
    if not m:
        return []
    topic = (m.group("t") or m.group("t2")).strip(" ,.")
    try:
        root = ET.fromstring(net.text("http://export.arxiv.org/api/query?" + urllib.parse.urlencode(
            {"search_query": "all:" + topic, "max_results": 5, "sortBy": "submittedDate", "sortOrder": "descending"})))
        ns = {"a": "http://www.w3.org/2005/Atom"}
        entries = root.findall("a:entry", ns)[:5]
        lines = [f"{' '.join((e.findtext('a:title', '', ns) or '').split())} ({(e.findtext('a:published', '', ns) or '')[:10]})" for e in entries]
    except Exception as e:
        print(f"(arXiv lookup failed: {e})")
        return []
    if not lines:
        return []
    return [_note(f"Recent arXiv papers on {topic} - arxiv.org", "; ".join(lines) + ". Preprints are not peer reviewed.", "https://arxiv.org/")]


PUBMED_Q = re.compile(r"\b(?:pubmed|clinical (?:trials?|studies)|medical (?:studies|research|papers)|studies (?:on|about)|research (?:on|about))\b\s*(?:on|about|for)?\s*(?P<t>.+)$", re.I)


def pubmed(q, now, net, online):
    if not online:
        return []
    m = PUBMED_Q.search(_q(q))
    if not m or not re.search(r"\b(pubmed|medical|clinical|disease|health|drug|treatment|therapy|cancer|diabetes|vaccine|studies)\b", q, re.I):
        return []
    topic = m.group("t").strip(" ,.")
    if len(topic) < 3:
        return []
    try:
        ids = net.json("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib.parse.urlencode(
            {"db": "pubmed", "term": topic, "retmax": 4, "retmode": "json", "sort": "relevance"}))["esearchresult"]["idlist"]
        if not ids:
            return []
        res = net.json("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?" + urllib.parse.urlencode({"db": "pubmed", "id": ",".join(ids), "retmode": "json"}))["result"]
        lines = [f"{res[i]['title']} ({res[i].get('source', '')}, {res[i].get('pubdate', '')})" for i in ids if i in res]
    except Exception as e:
        print(f"(PubMed lookup failed: {e})")
        return []
    return [_note(f"PubMed results for {topic} - pubmed.ncbi.nlm.nih.gov", "; ".join(lines) + ". Titles only: this is not medical advice.", "https://pubmed.ncbi.nlm.nih.gov/")]


ERR_RE = re.compile(r"\b(TypeError|ValueError|KeyError|AttributeError|ImportError|ModuleNotFoundError|IndexError|NameError|SyntaxError|NullPointerException|Traceback|segmentation fault|"
                    r"cannot find module|undefined is not a function)\b", re.I)


def stackexchange(q, now, net, online):
    if not online:
        return []
    q = _q(q)
    if not (re.search(r"\bstack ?overflow\b", q, re.I) or ERR_RE.search(q)):
        return []
    term = re.sub(r"\b(on |from |in )?stack ?overflow\b", " ", q, flags=re.I)
    term = " ".join(term.split())[:150]
    try:
        items = net.json("https://api.stackexchange.com/2.3/search/advanced?" + urllib.parse.urlencode(
            {"order": "desc", "sort": "relevance", "q": term, "accepted": "True", "site": "stackoverflow", "pagesize": 3}))["items"]
    except Exception as e:
        print(f"(Stack Exchange lookup failed: {e})")
        return []
    if not items:
        return []
    lines = [f"{W_clean(i['title'])} (score {i.get('score')}, {i.get('link')})" for i in items[:3]]
    return [_note("Stack Overflow questions with accepted answers - stackoverflow.com", "; ".join(lines) + ". Titles and links only: open them for the answers.", "https://stackoverflow.com/")]


def W_clean(text):
    import web_search as W
    return W.clean_text(text)


def trivia(q, now, net, online):
    if not online or not re.search(r"\btrivia\b", q or "", re.I):
        return []
    n = 5
    m = re.search(r"\b(\d{1,2})\s+(?:\w+\s+)?(?:trivia|questions)", q)
    if m:
        n = max(1, min(10, int(m.group(1))))
    try:
        rows = net.json(f"https://opentdb.com/api.php?amount={n}&type=multiple&encode=url3986")["results"]
    except Exception as e:
        print(f"(trivia lookup failed: {e})")
        return []
    if not rows:
        return []
    un = urllib.parse.unquote
    lines = [f"Q{i}: {un(r['question'])} Options: {', '.join(sorted([un(r['correct_answer'])] + [un(x) for x in r['incorrect_answers']]))}. Answer: {un(r['correct_answer'])}" for i, r in enumerate(rows, 1)]
    return [_note("Trivia questions - opentdb.com", " ".join(lines) + " (Give the questions one at a time and keep the answers hidden until the person answers.)", "https://opentdb.com/")]


FILING_Q = re.compile(r"\b(?:sec filings?|10-?k|10-?q|8-?k|annual report|quarterly report)\b", re.I)


def filings(q, now, net, online):
    if not online or not FILING_Q.search(q or ""):
        return []
    L = _L()
    low = _q(q).lower()
    tick = next((L.COMPANIES[k] for k in sorted(L.COMPANIES, key=len, reverse=True) if re.search(rf"(?<!\w){re.escape(k)}(?!\w)", low)), None)
    if not tick:
        mt = re.search(r"\b(?:for|of)\s+\$?([A-Z]{1,5})\b", q)
        tick = mt.group(1) if mt else None
    if not tick:
        return []
    try:
        txt = net.text("https://www.sec.gov/include/ticker.txt")
        cik = next(int(line.split()[1]) for line in txt.splitlines() if line.split() and line.split()[0] == tick.lower().replace("-", "-"))
        sub = net.json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        rec = sub["filings"]["recent"]
        rows = [(rec["form"][i], rec["filingDate"][i], rec["accessionNumber"][i].replace("-", ""), rec["primaryDocument"][i]) for i in range(len(rec["form"])) if
                rec["form"][i] in ("10-K", "10-Q", "8-K")][:5]
    except Exception as e:
        print(f"(SEC lookup failed: {e})")
        return []
    if not rows:
        return []
    lines = [f"{f} filed {d} (https://www.sec.gov/Archives/edgar/data/{cik}/{a}/{doc})" for f, d, a, doc in rows]
    return [_note(f"Recent SEC filings for {sub.get('name', tick)} - sec.gov", "; ".join(lines) + ".", "https://www.sec.gov/")]


# =========================================================================================== Wolfram|Alpha (optional key)
WOLFRAM_Q = re.compile(r"\b(integral|integrate|derivative|differentiate|limit of|factor|solve for|solve the equation|simplify|prime factors?|gcd|lcm|determinant|eigenvalue|logarithm|"
                       r"boiling point|melting point|molar mass|atomic (?:mass|number|weight)|speed of|mass of|diameter of|distance to the (?:moon|sun)|how many .{1,30} in a|density of|"
                       r"orbital period|escape velocity|half[- ]life|ph of|chemical formula)\b", re.I)


def wolfram(q, now, net, online):
    key = os.environ.get("WOLFRAM_APPID")
    if not online or not key or not WOLFRAM_Q.search(q or ""):
        return []
    try:
        text = net.text("https://api.wolframalpha.com/v1/result?" + urllib.parse.urlencode({"appid": key, "i": _q(q)}))
    except Exception as e:
        print(f"(Wolfram|Alpha lookup failed: {e})")
        return []
    text = (text or "").strip()
    if not text or "did not understand" in text.lower() or "no short answer" in text.lower():
        return []
    return [_note("Answer - Wolfram|Alpha", text, "https://www.wolframalpha.com/")]


# =========================================================================================== registry
for _fn in (sun, past_weather, alerts):
    _fn.needs_place = True

# (name, function, works offline, label). live_data.PROVIDERS gets these after its own.
MORE = [
    ("finance", finance, True, "Finance calculator"),
    ("tzconvert", tzconvert, True, "Time zones"),
    ("moon", moon, True, "Moon phase"),
    ("dice", dice, True, "Dice and coins"),
    ("bases", bases, True, "Number bases"),
    ("person", person, False, "People (Wikidata)"),
    ("packages", packages, False, "Package versions"),
    ("tv", tv, False, "TV schedule"),
    ("steam", steam, False, "Steam"),
    ("music", music, False, "Music"),
    ("nutrition", nutrition, False, "Nutrition"),
    ("sun", sun, False, "Sunrise and sunset"),
    ("distance", distance, False, "Distance"),
    ("pastweather", past_weather, False, "Past weather"),
    ("elevation", elevation, False, "Elevation"),
    ("surf", surf, False, "Surf"),
    ("alerts", alerts, False, "Weather alerts"),
    ("worldbank", worldbank, False, "World Bank"),
    ("fred", fred, False, "FRED"),
    ("arxiv", arxiv, False, "arXiv"),
    ("pubmed", pubmed, False, "PubMed"),
    ("stackexchange", stackexchange, False, "Stack Overflow"),
    ("trivia", trivia, False, "Trivia"),
    ("filings", filings, False, "SEC filings"),
    ("wolfram", wolfram, False, "Wolfram|Alpha"),
]
