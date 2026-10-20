"""
effort_router.py - "Auto" effort: decide from the message how long Emvryx should think (docs/APP_SPEC.md, "Effort: Auto").

WHAT THIS FILE DOES
    The effort menu has Quick, Balanced and Deep. With **Auto**, this decides for each message:
      Quick      greetings, thanks, very short or simple questions, and "briefly" / "tl;dr" requests
      Balanced   normal questions and everyday writing (the default when nothing stands out)
      Deep       code and errors, maths, "step by step", comparisons, long writing, long pasted text, several questions
    It is plain rules (no model call), so it costs nothing and is instant, and it always gives a reason in plain words.
    Two limits apply on top: a model that has no Deep (Ember) is held to Balanced, and when the person's usage is
    nearly used up Auto thinks less (below 20% left: at most Balanced; below 5%: Quick) so it never burns the last of it.
"""
import re

ORDER = ("quick", "balanced", "deep")
GREETING = re.compile(r"^\s*(hi|hello|hey|yo|thanks|thank you|thx|ok|okay|yes|no|yep|nope|lol|bye|good (morning|night|evening)|"
                      r"what'?s up|how are you)\b[\s!.?]*$", re.I)
SIMPLE_START = re.compile(r"^\s*(what is|what's|who is|who was|when|where|define|capital of|translate|spell|how do you say|"
                          r"how many|is it|are there)\b", re.I)
BRIEF = re.compile(r"\b(briefly|in a word|one word|one sentence|short answer|tl;?dr|quick question|yes or no|just tell me)\b", re.I)
CODE = re.compile(r"```|\bdef \w+|\bclass \w+\s*[:({]|\bimport \w+|\bfunction \w+\s*\(|\b(traceback|exception|stack trace|segfault|"
                  r"compile error|regex|sql|python|javascript|typescript|c\+\+|debug|bug|refactor)\b|\berror:|[{};]\s*$|\w+\(.*\)",
                  re.I | re.M)
MATH = re.compile(r"\d\s*[\+\-\*/^=x×÷]\s*\d|\b(solve|equation|calculate|derive|prove|integral|derivative|probability|"
                  r"percent(age)? of|algebra|geometry|theorem)\b", re.I)
CAREFUL = re.compile(r"\b(step[- ]by[- ]step|explain why|think (hard|carefully|it through)|in detail|thoroughly|compare|"
                     r"pros and cons|trade-?offs?|analy[sz]e|critique|evaluate|plan for|strategy|essay|report|lesson plan|"
                     r"write (a|an|me a) (story|article|essay|report|plan|speech|letter|email|poem)|design|optimi[sz]e|"
                     r"why does|why do|how does .* work|difference between)\b", re.I)


# strict (flag chat_fixes): Deep thinks first, which is slow, so it is kept for what needs it. A range ("2020-2021", "10-15 minutes") is not a sum,
# writing an email or a story needs no hidden reasoning, and a long pasted text is read just as well on Balanced.
MATH_STRICT = re.compile(r"\d\s*[\+\*/^=×÷]\s*\d|\d\s+[-x]\s+\d|\d\s*x\s*\d|\b(solve|equation|calculate|derive|prove|integral|derivative|probability|"
                         r"percent(age)? of|algebra|geometry|theorem|how much (?:is|are|does|do|will|would)|how many .* (?:if|when|each|per)|% off|discount|original price|"
                         r"interest rate|average speed|how far|how fast|how long will it take)\b|\d\s*%[^?]*\?", re.I)
WRITING = re.compile(r"\b(write (a|an|me a) (story|article|essay|report|speech|letter|email|poem)|essay|report|lesson plan)\b", re.I)


def choose_effort(text, allowed=ORDER, tank_pct=100.0, strict=False):
    """(effort, reason) for this message. `allowed` are the levels the model offers; `tank_pct` how much usage is left. `strict`: see MATH_STRICT."""
    t = (text or "").strip()
    words = len(t.split())
    questions = t.count("?")
    deep = []
    if CODE.search(t):
        deep.append("it has code or an error in it")
    if (MATH_STRICT if strict else MATH).search(t):
        deep.append("it needs working out")
    if CAREFUL.search(t) and not (strict and WRITING.search(t) and not CAREFUL.search(WRITING.sub("", t))):
        deep.append("it asks for careful or detailed thinking")
    if words > 120 and not strict:
        deep.append("it is long")
    if questions >= 3:
        deep.append("it has several questions")
    if GREETING.match(t):
        effort, why = "quick", "a short greeting"
    elif deep and not (BRIEF.search(t) and "it has code or an error in it" not in deep):
        effort, why = "deep", "; ".join(deep[:2]).capitalize()
    elif BRIEF.search(t):
        effort, why = "quick", "you asked for a short answer"
    elif words <= 6 and not deep:
        effort, why = "quick", "a short question"
    elif words <= 12 and SIMPLE_START.match(t):
        effort, why = "quick", "a simple question"
    else:
        effort, why = "balanced", "a normal question"
    # limits on top of the guess
    if effort == "deep" and "deep" not in allowed:
        effort, why = "balanced", why + ", but this model has no Deep"
    if tank_pct < 5 and effort != "quick":
        effort, why = "quick", "your usage is almost used up"
    elif tank_pct < 20 and effort == "deep":
        effort, why = "balanced", "your usage is getting low"
    if effort not in allowed:
        effort = next(e for e in ORDER if e in allowed)
    return effort, why


# ---------------------------------------------------------------- temperature (how adventurous the wording is)
CREATIVE = re.compile(r"\b(story|stories|poem|song|lyrics|brainstorm|ideas?|imagine|creative|invent|slogan|joke|"
                      r"roleplay|role-play|pretend|names? for|come up with)\b", re.I)
EXACT = re.compile(r"\b(json|exactly|fewer than|at most|at least|without using|do not use|only the|only one|no more than|"
                   r"in (one|two|three|\d+) (word|sentence)s?)\b", re.I)
DEFAULT_BOUNDS = (0.2, 1.0)
PRECISE_TEMP, CREATIVE_TEMP = 0.2, 1.0


def choose_temperature(text, base=0.8, bounds=DEFAULT_BOUNDS):
    """(temperature, reason) for this message. Code, maths and strict formats want predictable answers (low); stories and
    brainstorming want variety (high); everything else keeps the model's own tested setting `base`. A model can limit the
    range with `bounds` (small models turn to nonsense when the temperature is high, so Ember's range is narrow)."""
    t = text or ""
    lo, hi = bounds
    if CODE.search(t) or MATH.search(t) or EXACT.search(t):
        temp, why = PRECISE_TEMP, "it needs an exact answer"
    elif CREATIVE.search(t):
        temp, why = CREATIVE_TEMP, "it asks for something creative"
    else:
        temp, why = base, "a normal question"
    return round(min(hi, max(lo, temp)), 2), why

