"""
code_options.py - vryxcode_options: when a message to VryxCode is open-ended ("let's build something", "what should I code?"), it talks first, the
way Claude does: it asks what you would like and offers a few choices to tap (or you write your own), instead of guessing and writing files.

WHAT THIS FILE DOES
    * `vague(text)` is True for a message that asks to build or code without saying what ("let's build something", "make me an app", "I want to
      code", "any ideas?"). A message that names the thing ("build a to-do app") is not vague and starts straight away, as before.
    * `options_for(text, files)` is the question and 2 to 4 choices: ideas for a new project in an empty folder, or what to do next in a project
      that already has files. Ideas to build fit the kind asked for when one was named (a game, a website, an app, a tool).
    * `with_choice(text, choice)` is the message the model then works from: what was asked and what the person picked.
"""
# re = regular expressions (a regex is a text pattern used to match or search text).
import re

# Building blocks for the VAGUE pattern below. BUILD = verbs like "build", "make", "code". THING = a non-specific
# object like "something" or "an app" (a named thing such as "a to-do app" does NOT match, which is the point).
# (?:...) is a group that does not capture; "|" means "or"; "?" means "optional".
BUILD = r"(?:build|make|create|code|write|program|develop|start|do)"
THING = r"(?:something|anything|a project|an? (?:new )?(?:app|game|website|site|tool|program|project|thing))"
# Matches a whole message that asks to build something without saying what. The parts, joined by "|" (or):
#   1) optional greeting + optional lead-in ("let's", "can we", "i want to"...) + a BUILD verb + THING
#   2) "i want to / let's" + "code / program / build / make something"
#   3) "what should I build?"   4) "any ideas?"   5) "surprise me"
# then optional filler words ("please", "together"...) and punctuation, then the end of the text ("$").
# "^" = start of the text; re.I = ignore upper/lower case. rf"..." lets {BUILD} and {THING} be filled in.
VAGUE = re.compile(
    r"^\s*(?:hi|hey|hello)?[\s,!.]*(?:"
    rf"(?:let'?s|lets|can we|could we|shall we|we should|help me|i want to|i wanna|i'd like to|i would like to|please)?\s*{BUILD}\s+(?:me\s+|us\s+)?{THING}"
    r"|(?:i want to|i wanna|let'?s|lets)\s+(?:code|program|build|make something)"
    r"|what (?:should|can|could) (?:i|we) (?:build|make|code|create)"
    r"|(?:any|give me some|got any) (?:ideas?|suggestions?)(?: (?:for|on) what to (?:build|make|code))?"
    r"|surprise me"
    r")\s*(?:for me|together|today|now|with you|please|cool|fun)?\s*[?!.]*\s*$", re.I)
# Finds the kind of thing asked for, if the message names one (game, website, site, app or tool). \b = word edge.
KIND = re.compile(r"\b(game|website|site|app|tool)\b", re.I)

# Ideas to offer for each kind of project.
IDEAS = {
    "game": ["A Snake game you play with the arrow keys", "A memory card-matching game", "Tic-tac-toe against the computer", "A quiz game with a score"],
    "website": ["A personal homepage about you", "A recipe site with a search box", "A photo gallery page", "A landing page for a small business"],
    "app": ["A to-do list that remembers your tasks", "A budget tracker for money in and out", "A habit tracker with a streak count", "A notes app with search"],
    "tool": ["A tip and bill splitter", "A password generator", "A unit converter (miles, kg, °C)", "A countdown timer to a date"],
}
# Ideas when no kind was named: one of each.
MIXED = ["A to-do list that remembers your tasks", "A Snake game you play with the arrow keys", "A personal homepage about you", "A budget tracker for money in and out"]
# Choices offered when the project already has files.
NEXT = ["Add a new feature", "Fix something that is not working", "Make it look better", "Explain how the code works"]


def vague(text):
    """True if the message is an open-ended request to build something. split()+join squeezes extra spaces and new lines first."""
    return bool(VAGUE.match(" ".join(str(text or "").split())))


def options_for(text, files=()):
    """(question, options) for an open-ended message. `files`: the project's files (empty for a new project)."""
    # Hidden files (names starting with ".") do not count: a folder with only those is still a new project.
    real = [f for f in files or () if not str(f).startswith(".")]
    # The project already has files: ask what to do next with it.
    if real:
        return "Sure. What would you like to do with this project?", list(NEXT)
    # New project: look for a kind word in the message. "site" is treated as "website". No match = None (mixed ideas).
    m = KIND.search(str(text or ""))
    kind = {"site": "website"}.get(m.group(1).lower(), m.group(1).lower()) if m else None
    return ("Happy to. Here are a few ideas — pick one, or tell me your own:", list(IDEAS.get(kind, MIXED)))


def with_choice(text, choice):
    """The message the model works from: the original request plus what the person tapped or typed as their choice."""
    return f"{str(text).strip()}\n\nI asked what to build, and the person chose: {str(choice).strip()}. Build that."
