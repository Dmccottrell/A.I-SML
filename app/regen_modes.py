"""
regen_modes.py - "Regenerate" with a choice of how the new answer should differ (docs/APP_SPEC.md, "Regenerate options").

WHAT THIS FILE DOES
    Pressing Regenerate offers a short menu instead of just rolling the dice again:
      again      Try again               the same question, a fresh answer
      different  A different answer      another take, with more variety
      other_way  Explain it differently  another explanation, with an example
      simpler    Make it simpler         plain words, like to a beginner
      detail     More detail             a fuller answer
      shorter    Shorter                 the short version
      choices    Give me choices         three different options to pick from
    A mode changes only what the model is asked for this one time: a short hint added to the end of the question (the saved chat
    still shows the original question, never the hint), how much it may write, and how adventurous the wording is.
"""
MODES = {
    "again": {"label": "Try again", "blurb": "Same question, a fresh answer", "hint": "", "temp": 0.15, "length": 1.0},
    "different": {"label": "A different answer", "blurb": "Another take, with more variety",
                  "hint": "Give a different answer from before.", "temp": 0.3, "length": 1.0},
    "other_way": {"label": "Explain it differently", "blurb": "Another explanation, with an example",
                  "hint": "Explain this a different way, with an example.", "temp": 0.15, "length": 1.0},
    "simpler": {"label": "Make it simpler", "blurb": "Plain words, like to a beginner",
                "hint": "Explain this in simple words, like to a beginner.", "temp": 0.0, "length": 0.8},
    "detail": {"label": "More detail", "blurb": "A fuller answer",
               "hint": "Answer in more detail.", "temp": 0.0, "length": 1.6},
    "shorter": {"label": "Shorter", "blurb": "The short version",
                "hint": "Answer briefly, in a few sentences.", "temp": 0.0, "length": 0.45},
    "choices": {"label": "Give me choices", "blurb": "Three different options to pick from",
                "hint": "Give three different options, numbered 1, 2 and 3.", "temp": 0.2, "length": 1.4},
}
ORDER = ("again", "different", "other_way", "simpler", "detail", "shorter", "choices")
MAX_TEMPERATURE = 1.1


def menu():
    """The menu the page shows: [{"id", "label", "blurb"}] in order."""
    return [{"id": k, "label": MODES[k]["label"], "blurb": MODES[k]["blurb"]} for k in ORDER]


def get(mode):
    """The settings for a mode (None or "" means plain Regenerate = "again"). Unknown modes are an error."""
    mode = mode or "again"
    if mode not in MODES:
        raise ValueError("unknown regenerate option")
    return MODES[mode]


def hinted(question, mode):
    """The question as the model sees it this once: the original, plus the mode's hint."""
    hint = get(mode)["hint"]
    return question if not hint else f"{question.rstrip()}\n\n{hint}"


def sampling_for(base_temperature, mode):
    """A little more adventurous wording for modes that want a different answer (never above MAX_TEMPERATURE)."""
    return round(min(MAX_TEMPERATURE, base_temperature + get(mode)["temp"]), 2)


def length_for(max_new, mode):
    """How much it may write: shorter for 'shorter', longer for 'detail' and 'choices' (never below 32)."""
    return max(32, int(max_new * get(mode)["length"]))
