"""
web_lessons.py - Chat lessons for answering from web search results (used by make_chat_data_v3.py).

WHAT THIS FILE DOES
    Web results look different from the Wikipedia notes the lookup lessons use: they have a site and
    a date, they're about new things (scores, prices, launches, forecasts), they can disagree, and
    pages carry junk ("Advertisement", "Subscribe..."). These lessons show the model how to read them:

      kind         the notes                                      the answer
      -----------  ---------------------------------------------  -----------------------------------------
      web          one result answers it (plus unrelated ones,    the answer, naming the site and date
                   sometimes with page junk mixed in)
      web_latest   two results, an older and a newer one          the NEWEST one, mentioning the update
      web_disagree two sites give different answers               says they disagree, gives both
      web_none     the results are about something else           "the search results don't say"
      other_ai     (none) "What are Claude's scores?", "Which is   honest: no reliable up-to-date info about
                   better, ChatGPT or Gemini?"                    other AIs; where to find it

    Everything is written from templates by our own code: no other AI writes these lessons. The
    teams, companies, products and AI models in the news stories are MADE UP (like "Velmora 4"), so
    the model learns to READ the answer from the notes, never to remember a fake fact as real.
    The notes use the same title format as web_search.py: "headline - site, date".

    Each version adds harder lessons on top (see docs/ROADMAP.md, "Web search, version by version"):
    v3 gets the five kinds above; v3.5 more of them (--web); v4 adds search tool calls.
"""
import random

SYLLABLES = ["zor", "vel", "mor", "quin", "dra", "kes", "lin", "tav", "ren", "bri", "sol", "nax",
             "pell", "ora", "dun", "fyr", "gal", "hesk", "ith", "jor"]
SITES = {"sports": ["sportswire.net", "scoreline.com", "theplaybook.org", "fieldreport.net"],
         "tech": ["techreport.org", "gadgetdaily.net", "bytebeat.com", "thedevlog.net"],
         "ai": ["aiweekly.net", "modelwatch.org", "techreport.org", "benchboard.com"],
         "weather": ["forecastnow.com", "skycast.net", "localweatherdesk.org"],
         "local": ["citynewsdaily.com", "thehometownpost.net", "metrobulletin.org"],
         "business": ["marketline.net", "businessdesk.org", "thetradepost.com"]}
JUNK = ["Advertisement", "Subscribe to our newsletter for the latest updates.", "Share this article:",
        "We use cookies to improve your experience. Accept all", "Read more: Top 10 stories this week",
        "Sign up for free to keep reading."]
CITIES = ["Chicago", "Houston", "Denver", "Atlanta", "Seattle", "Phoenix", "Nashville", "Detroit", "Miami",
          "Toronto", "Austin", "Boston"]
MASCOTS = ["Tigers", "Hawks", "Comets", "Wolves", "Rangers", "Falcons", "Storm", "Pilots", "Bears", "Rockets"]
SPORTS = ["basketball", "soccer", "baseball", "hockey", "football"]
GADGETS = ["phone", "laptop", "smartwatch", "tablet", "game console", "pair of earbuds", "e-reader"]
BENCHES = ["MMLU", "HellaSwag", "GSM8K", "HumanEval", "ARC-Challenge"]
CONDITIONS = ["sunny", "partly cloudy", "rainy", "windy", "stormy", "snowy", "foggy"]
EVENTS = ["food festival", "book fair", "science fair", "marathon", "music festival", "art walk", "farmers market"]
ROLES = ["CEO", "head coach", "president", "mayor"]
FIRST = ["Jordan", "Priya", "Marcus", "Elena", "Kofi", "Hannah", "Diego", "Mei", "Samir", "Ruth", "Andre", "Ines"]
LAST = ["Okafor", "Lindqvist", "Ramirez", "Chen", "Abara", "Novak", "Haddad", "Brennan", "Mbeki", "Sato"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def made_up(rng, n=2):
    return "".join(rng.choice(SYLLABLES) for _ in range(n)).capitalize()


def a_date(rng, year=None):
    """(sortable number, "Sep 30, 2026")"""
    y = year or rng.randint(2025, 2028)
    m, d = rng.randrange(12), rng.randint(1, 28)
    return (y * 400 + m * 31 + d, f"{MONTHS[m]} {d}, {y}")


def later(rng, date):
    """A date a few days to a few weeks after `date`."""
    num, text = date
    m, d, y = text.replace(",", "").split()
    mi, di, yi = MONTHS.index(m), int(d) + rng.randint(2, 20), int(y)
    if di > 28:
        di, mi = di - 28, mi + 1
    if mi > 11:
        mi, yi = 0, yi + 1
    return (yi * 400 + mi * 31 + di, f"{MONTHS[mi]} {di}, {yi}")


# ------------------------------------------------------------------ the stories
# Each maker returns a "story": the facts, plus how to write them as a page, ask about them and answer.
# value(rng) draws the changeable part (a score, a price...), so the same story can be told twice with
# different values (an update, or two sites that disagree).

def story_sports(rng):
    city_a, city_b = rng.sample(CITIES, 2)
    a, b = f"{city_a} {rng.choice(MASCOTS)}", f"{city_b} {made_up(rng)}s"
    sport = rng.choice(SPORTS)

    def value(rng):
        x, y = rng.randint(1, 9), rng.randint(0, 8)
        return (x, y) if x != y else (x + 1, y)

    def page(v, date):
        hi, lo = max(v), min(v)
        win, lose = (a, b) if v[0] > v[1] else (b, a)
        return (f"{win} beat {lose}",
                f"The {win} beat the {lose} {hi}-{lo} on {rng.choice(WEEKDAYS)} night in {sport}. "
                f"Fans packed the stadium in {city_a} for the game.")

    def answer(v):
        hi, lo = max(v), min(v)
        win, lose = (a, b) if v[0] > v[1] else (b, a)
        return f"the {win} won, beating the {lose} {hi}-{lo}"

    q = rng.choice([f"Who won the {a} vs {b} game?", f"Did the {a} win against the {b}?",
                    f"What was the score of the {a} game against the {b}?"])
    return {"topic": "sports", "value": value, "page": page, "answer": answer, "question": q}


def story_product(rng):
    company = made_up(rng) + rng.choice(["", " Labs", " Tech", " Devices"])
    product = f"{made_up(rng)} {rng.randint(2, 9)}"
    gadget = rng.choice(GADGETS)

    def value(rng):
        return rng.choice([199, 249, 299, 349, 399, 499, 599, 699, 799, 999, 1199])

    def page(v, date):
        return (f"{company} launches the {product}",
                f"{company} released the {product}, a new {gadget}, on {date}. It costs ${v} in the US "
                f"and goes on sale in stores next week.")

    def answer(v):
        return f"the {product} costs ${v}"

    q = rng.choice([f"How much does the {product} cost?", f"What's the price of the new {product}?",
                    f"how much is the {product.lower()}"])
    return {"topic": "tech", "value": value, "page": page, "answer": answer, "question": q}


def story_ai_model(rng):
    lab = made_up(rng) + rng.choice([" AI", " Labs", " Research"])
    model = f"{made_up(rng)} {rng.randint(2, 7)}"
    bench = rng.choice(BENCHES)

    def value(rng):
        return round(rng.uniform(55, 95), 1)

    def page(v, date):
        return (f"{lab} announces {model}",
                f"{lab} announced {model}, its newest AI model. The company says it scored {v}% on the "
                f"{bench} benchmark, up from the previous version.")

    def answer(v):
        return f"{model} scored {v}% on {bench}, according to {lab}'s own announcement"

    q = rng.choice([f"What are the benchmark scores for {model}?", f"How did {model} do on {bench}?",
                    f"whats {model.lower()}'s {bench} score"])
    return {"topic": "ai", "value": value, "page": page, "answer": answer, "question": q}


def story_weather(rng):
    city = rng.choice(CITIES)
    day = rng.choice(WEEKDAYS)

    def value(rng):
        return (rng.randint(28, 98), rng.choice(CONDITIONS))

    def page(v, date):
        return (f"{city} forecast for {day}",
                f"Forecast for {city}: {v[1]} on {day}, with a high of {v[0]} degrees F. "
                f"Winds light and variable overnight.")

    def answer(v):
        return f"{city} is expected to be {v[1]} on {day}, with a high of {v[0]} degrees F"

    q = rng.choice([f"What's the weather going to be in {city} on {day}?", f"Will it rain in {city} on {day}?",
                    f"weather in {city.lower()} {day.lower()}"])
    return {"topic": "weather", "value": value, "page": page, "answer": answer, "question": q}


def story_event(rng):
    city = rng.choice(CITIES)
    event = f"{city} {made_up(rng)} {rng.choice(EVENTS)}"

    def value(rng):
        return a_date(rng)[1]

    def page(v, date):
        return (f"{event} returns",
                f"The {event} will be held on {v} at {made_up(rng)} Park. Entry is free and the "
                f"organizers expect large crowds.")

    def answer(v):
        return f"the {event} is on {v}"

    q = rng.choice([f"When is the {event}?", f"What date is the {event} this year?"])
    return {"topic": "local", "value": value, "page": page, "answer": answer, "question": q}


def story_leader(rng):
    org = made_up(rng) + rng.choice([" Corp", " Group", " Motors", " Foods"])
    role = rng.choice(ROLES[:2])

    def value(rng):
        return f"{rng.choice(FIRST)} {rng.choice(LAST)}"

    def page(v, date):
        return (f"{org} names new {role}",
                f"{org} named {v} as its new {role} on {date}, replacing the previous {role}, "
                f"who retired after eight years.")

    def answer(v):
        return f"{v} is the {role} of {org}"

    q = rng.choice([f"Who is the {role} of {org}?", f"Who runs {org} now?"])
    return {"topic": "business", "value": value, "page": page, "answer": answer, "question": q}


STORIES = [story_sports, story_product, story_ai_model, story_weather, story_event, story_leader]


def note(story, value, rng, date=None, site=None, junk=0.0):
    """One web result about `story`, in web_search.py's format."""
    date = date or a_date(rng)
    site = site or rng.choice(SITES[story["topic"]])
    headline, text = story["page"](value, date[1])
    if rng.random() < junk:
        text = rng.choice(JUNK) + " " + text if rng.random() < 0.5 else text + " " + rng.choice(JUNK)
    return {"title": f"{headline} - {site}, {date[1]}", "text": text}, site, date


def cite(site, date):
    return f"(Source: {site}, {date[1]})"


def sentence(s):
    return s[0].upper() + s[1:] + "."


# ------------------------------------------------------------------ the lessons
def web_lesson(rng):
    """One web lesson: (kind, [user message with notes, answer])."""
    story = rng.choice(STORIES)(rng)
    r = rng.random()
    if r < 0.55:                                   # one result answers it
        v = story["value"](rng)
        n, site, date = note(story, v, rng, junk=0.3)
        notes = [n] + distractors(rng, rng.randint(0, 2), avoid=n["title"])
        rng.shuffle(notes)
        reply = rng.choice([f"According to {site} ({date[1]}), {story['answer'](v)}. {cite(site, date)}",
                            f"{sentence(story['answer'](v))} {cite(site, date)}",
                            f"The search results say {story['answer'](v)}. {cite(site, date)}"])
        return "web", [user(story["question"], notes), assistant(reply)]
    if r < 0.70:                                   # an older and a newer result: the newest wins
        v_old, v_new = story["value"](rng), story["value"](rng)
        if v_old == v_new:
            return web_lesson(rng)
        n_old, s_old, d_old = note(story, v_old, rng)
        d_new = later(rng, d_old)
        n_new, s_new, _ = note(story, v_new, rng, date=d_new)
        notes = [n_old, n_new] + distractors(rng, rng.randint(0, 1), avoid=n_new["title"])
        rng.shuffle(notes)
        reply = (f"The newest result, from {s_new} ({d_new[1]}), says {story['answer'](v_new)}. "
                 f"An earlier report from {s_old} ({d_old[1]}) said {story['answer'](v_old)}, so it "
                 f"looks like that was updated. {cite(s_new, d_new)}")
        return "web_latest", [user(story["question"], notes), assistant(reply)]
    if r < 0.84:                                   # two sites disagree
        v1, v2 = story["value"](rng), story["value"](rng)
        if v1 == v2:
            return web_lesson(rng)
        s1, s2 = rng.sample(SITES[story["topic"]], 2)
        date = a_date(rng)
        n1, _, _ = note(story, v1, rng, date=date, site=s1)
        n2, _, _ = note(story, v2, rng, date=date, site=s2)
        notes = [n1, n2]
        rng.shuffle(notes)
        reply = (f"The sources disagree. {s1} says {story['answer'](v1)}, but {s2} says "
                 f"{story['answer'](v2)}. I can't tell which one is right, so it's worth checking an "
                 f"official source.")
        return "web_disagree", [user(story["question"], notes), assistant(reply)]
    notes = distractors(rng, rng.randint(1, 3), avoid=note(story, story["value"](rng), rng)[0]["title"])
    topics = " and ".join(dict.fromkeys(n["title"].split(" - ")[0] for n in notes))
    reply = rng.choice([f"I searched, but the results I got are about {topics}, not about this, so I "
                        f"don't know. Try asking in a different way, or check a news site.",
                        "The search results don't answer that, so I don't know. I'd rather not guess."])
    return "web_none", [user(story["question"], notes), assistant(reply)]


def distractors(rng, n, avoid=""):
    """Results about other, unrelated stories (never one with the same headline subject as `avoid`,
    e.g. a second forecast for the same city and day, which would answer the question)."""
    subject = avoid.split(" - ")[0]
    out = []
    while len(out) < n:
        s = rng.choice(STORIES)(rng)
        n_ = note(s, s["value"](rng), rng, junk=0.3)[0]
        if n_["title"].split(" - ")[0] != subject:
            out.append(n_)
    return out


def web_conversations(rng, n):
    """n web lessons, grouped by kind: {"web": [...], "web_latest": [...], ...}"""
    out = {k: [] for k in ("web", "web_latest", "web_disagree", "web_none")}
    for _ in range(n):
        kind, convo = web_lesson(rng)
        out[kind].append(convo)
    return out


# ------------------------------------------------------------------ other AI assistants
OTHER_AIS = ["Claude", "ChatGPT", "Gemini", "Copilot", "Llama", "Grok", "DeepSeek", "Mistral"]
OTHER_AI_QUESTIONS = [
    "What are the metrics for {a}?", "What are {a}'s benchmark scores?", "How good is {a}?",
    "whats the newest version of {a}", "Which is better, {a} or {b}?", "Is {a} better than {b}?",
    "Is {a} smarter than you?", "Compare {a} and {b}.", "What model does {a} use?",
    "How many parameters does {a} have?"]
OTHER_AI_REPLIES = [
    "I don't have reliable, up-to-date information about {a}. AI assistants change every few months, "
    "and I run offline, so anything I said could be old or wrong. The company that makes it publishes "
    "its results on its own website.",
    "I can't compare them fairly: I don't have current information about {a} or {b}, and their "
    "versions change often. Each maker publishes benchmark results, and independent leaderboards "
    "compare them. With web search turned on, I can look it up.",
    "I don't know the details of {a}, and I'd rather not guess. I'm a small AI trained on a home "
    "computer, without current information about other assistants. With web search turned on, I can "
    "check recent sources.",
]
SMARTER_REPLY = ("Almost certainly, yes. {a} is a far larger AI made by a big company. I'm a small model "
                 "trained from scratch on a home computer, so I make more mistakes. Please double-check "
                 "anything important I tell you.")


def other_ai_conversations(rng, n):
    """Honest answers about other AI assistants, with no notes (when web search is off)."""
    out = []
    for _ in range(n):
        a, b = rng.sample(OTHER_AIS, 2)
        q = rng.choice(OTHER_AI_QUESTIONS)
        if "smarter than you" in q:
            reply = SMARTER_REPLY
        elif "{b}" in q:
            reply = OTHER_AI_REPLIES[1]
        else:
            reply = rng.choice([OTHER_AI_REPLIES[0], OTHER_AI_REPLIES[2]])
        q = q.format(a=a, b=b)
        if rng.random() < 0.3:
            q = q.lower().rstrip("?")
        out.append([user(q), assistant(reply.format(a=a, b=b))])
    return out


# (the same message helpers as make_chat_data_v3.py, kept here so this file has no import loop)
def user(content, notes=None):
    m = {"role": "user", "content": content}
    if notes:
        m["notes"] = notes
    return m


def assistant(content):
    return {"role": "assistant", "content": content}


if __name__ == "__main__":
    import json
    rng = random.Random(0)
    for kind, convos in web_conversations(rng, 8).items():
        for c in convos[:1]:
            print(kind, json.dumps(c, indent=1, ensure_ascii=False))
    print(json.dumps(other_ai_conversations(rng, 2), indent=1))
