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
import re

BUILD = r"(?:build|make|create|code|write|program|develop|start|do)"
THING = r"(?:something|anything|a project|an? (?:new )?(?:app|game|website|site|tool|program|project|thing))"
VAGUE = re.compile(
    r"^\s*(?:hi|hey|hello)?[\s,!.]*(?:"
    rf"(?:let'?s|lets|can we|could we|shall we|we should|help me|i want to|i wanna|i'd like to|i would like to|please)?\s*{BUILD}\s+(?:me\s+|us\s+)?{THING}"
    r"|(?:i want to|i wanna|let'?s|lets)\s+(?:code|program|build|make something)"
    r"|what (?:should|can|could) (?:i|we) (?:build|make|code|create)"
    r"|(?:any|give me some|got any) (?:ideas?|suggestions?)(?: (?:for|on) what to (?:build|make|code))?"
    r"|surprise me"
    r")\s*(?:for me|together|today|now|with you|please|cool|fun)?\s*[?!.]*\s*$", re.I)
KIND = re.compile(r"\b(game|website|site|app|tool)\b", re.I)

IDEAS = {
    "game": ["A Snake game you play with the arrow keys", "A memory card-matching game", "Tic-tac-toe against the computer", "A quiz game with a score"],
    "website": ["A personal homepage about you", "A recipe site with a search box", "A photo gallery page", "A landing page for a small business"],
    "app": ["A to-do list that remembers your tasks", "A budget tracker for money in and out", "A habit tracker with a streak count", "A notes app with search"],
    "tool": ["A tip and bill splitter", "A password generator", "A unit converter (miles, kg, °C)", "A countdown timer to a date"],
}
MIXED = ["A to-do list that remembers your tasks", "A Snake game you play with the arrow keys", "A personal homepage about you", "A budget tracker for money in and out"]
NEXT = ["Add a new feature", "Fix something that is not working", "Make it look better", "Explain how the code works"]


def vague(text):
    return bool(VAGUE.match(" ".join(str(text or "").split())))


def options_for(text, files=()):
    """(question, options) for an open-ended message. `files`: the project's files (empty for a new project)."""
    real = [f for f in files or () if not str(f).startswith(".")]
    if real:
        return "Sure. What would you like to do with this project?", list(NEXT)
    m = KIND.search(str(text or ""))
    kind = {"site": "website"}.get(m.group(1).lower(), m.group(1).lower()) if m else None
    return ("Happy to. Here are a few ideas — pick one, or tell me your own:", list(IDEAS.get(kind, MIXED)))


def with_choice(text, choice):
    return f"{str(text).strip()}\n\nI asked what to build, and the person chose: {str(choice).strip()}. Build that."
