"""
accuracy.py - Making answers more accurate, after and around the model (each part behind its own feature flag; chat_turn.py calls them).

WHAT THIS FILE DOES
    * chat_cite: the notes the model was given are numbered [1], [2]... (core/chat.py format_notes). CITE_HINT asks it to put the number after a fact
      it took from one; `cites_for` keeps what each number was (title and link) so the page can turn [1] into a link to the source.
    * chat_verify: `unsupported` finds the sentences of an answer that state a figure (a number, a year, a percentage) that appears in none of
      the notes it was given and not in the question: the page marks them "not found in the sources" so a made-up figure stands out.
    * chat_calc: `fix_sums` checks the sums an answer writes out ("12 x 7 = 84", "15% of 80 is 12") with an exact calculator and puts the right
      result in place of a wrong one, saying what it changed. Code blocks are left alone.
    Nothing here calls a model: it is plain code, instant, and costs no GPU time.

    Words used below:
      * A "regex" (regular expression) is a text pattern, such as "one or more digits"; `re` is Python's tool for using them.
      * A "note" is a snippet of looked-up text (a dict with "title", "text", maybe "url" and "kind") that is handed to the model as source material.
"""
import re
import urllib.parse

# The instruction text added to the model's prompt when citations are on (chat_cite). It is one string, split over two lines only for width.
CITE_HINT = ("Each note above has a number in square brackets. When a sentence uses a fact from a note, end the sentence with that note's number, "
             "like [1] or [2][3]. Never put a number on something that is not in the notes.")

# NUM finds one figure in text: "1,234", "45", "3.5", "12%".
#   (?<![\w.])            not directly after a letter/digit/underscore or a dot, so the "2" inside "v2" or "1.2.3" is skipped
#   \d{1,3}(?:,\d{3})+    a number with thousands commas ("1,234,567")   ... or ...   \d+   plain digits
#   (?:\.\d+)?            an optional decimal part (".5")
#   %?                     an optional percent sign
NUM = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?")
# SENT cuts text into sentences: a run of characters that are not . ! ? or a newline, then the ending punctuation (or the end of the text).
SENT = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")
# CODE matches a fenced code block (``` ... ```). re.S lets "." also match newlines, and ".*?" takes the shortest stretch, so each block is matched alone.
CODE = re.compile(r"```.*?```", re.S)


def cites_for(notes, sources=()):
    """[{"n", "title", "url"}] for the notes in the order the model saw them. The model only sees a note's title and text: `sources` (the
    lookup's full notes, with kind and url) gives each its link."""
    # Look up the full note by its title (the title is the only thing that ties a note the model saw to a full one).
    full = {str(x.get("title", "")): x for x in sources or []}
    out = []
    # Number the notes from 1, the same order the model saw them, so "[1]" in the answer means out[0].
    for i, n in enumerate(notes or [], 1):
        title = str(n.get("title", ""))[:120]
        # Merge: start from the full note, then lay the non-empty fields of the note itself on top.
        n = dict(full.get(n.get("title", ""), {}), **{k: v for k, v in n.items() if v})
        url = n.get("url") or ""
        # A Wikipedia note may have no link; build one from its title (spaces become underscores, other characters are made URL-safe).
        if not url and n.get("kind") == "wikipedia" and title:
            url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
        # Cut long values so a huge title or link cannot bloat the reply.
        out.append({"n": i, "title": title, "url": str(url)[:300]})
    return out


def _norm(tok):
    """Write a figure in a plain comparable form: no thousands commas, no trailing "%" or "." ("1,234" -> "1234", "45%" -> "45")."""
    return tok.replace(",", "").rstrip("%").rstrip(".")


def _figures(text):
    """The figures in a piece of text, normalised ("1,234" -> "1234", "45%" -> "45")."""
    return {_norm(m.group()) for m in NUM.finditer(text)}


def unsupported(answer, notes, question=""):
    """[{"sentence", "figures"}]: sentences that state a figure found in no note and not in the question. Small numbers (0-10), list numbers
    and citation marks are not counted: they are rarely facts."""
    # Every figure that appears in the notes (their text and title) or in the question counts as "known" (supported).
    known = _figures(" ".join(str(n.get("text", "")) + " " + str(n.get("title", "")) for n in notes or []) + " " + str(question))
    # Blank out the parts that are not claims, so their numbers are not flagged: code blocks first...
    text = CODE.sub(" ", str(answer))
    text = re.sub(r"\[\d{1,2}\]", " ", text)                       # citation marks
    text = PCT.sub(" ", SUM.sub(" ", text))                          # a sum it worked out is not a fact from a source (chat_calc checks those)
    text = re.sub(r"(?m)^\s*\d+[.)]\s", " ", text)                  # numbered lists
    out = []
    # Look at the answer one sentence at a time.
    for m in SENT.finditer(text):
        s = m.group().strip()
        # Keep each figure that is not known and is not a small whole number (0 to 10).
        figs = [f for f in (_norm(x.group()) for x in NUM.finditer(s)) if f not in known and not (f.isdigit() and int(f) <= 10)]
        if figs:
            # Report the sentence (cut to 300 characters) and up to 5 distinct figures, in the order they appear (sorted by first position).
            out.append({"sentence": s[:300], "figures": sorted(set(figs), key=figs.index)[:5]})
    # At most 10 flagged sentences, so a long answer cannot flood the page.
    return out[:10]


# SUM finds a written-out sum: "12 x 7 = 84", "100 / 8 = 12.5", "3.5 * 2 = 7"
#   group 1 = the left number, group 2 = the operator (+ - * / x × ÷), group 3 = the right number, group 4 = the result the answer claims.
#   The final (?!\d|\.\d) stops the result from being cut short (so "= 84" is not taken from "= 843" or "= 84.5").
# "12 x 7 = 84", "100 / 8 = 12.5", "3.5 * 2 = 7"
SUM = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*([+\-*/x×÷])\s*(\d+(?:\.\d+)?)\s*=\s*(-?\d+(?:,\d{3})*(?:\.\d+)?)(?!\d|\.\d)")
# PCT finds a written-out percentage: "15% of 80 is 12", "20 percent of 50 = 10". re.I = ignore upper/lower case.
#   group 1 = the percent, group 2 = the whole amount (may have commas or a leading $), group 3 = the claimed result.
PCT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:%|percent)\s+of\s+\$?(\d+(?:,\d{3})*(?:\.\d+)?)\s+(?:is|=|equals|comes to)\s+\$?(-?\d+(?:,\d{3})*(?:\.\d+)?)(?!\d|\.\d)", re.I)


def _show(x, like):
    """The right result, written with as many decimals as the wrong one had (at least as many as it needs, up to 4)."""
    # How many decimals the wrong result was written with ("12.50" -> 2, "84" -> 0).
    want = len(like.split(".")[1]) if "." in like else 0
    # A whole number written without decimals: show it as a plain integer.
    if abs(x - round(x)) < 1e-9 and want == 0:
        return str(int(round(x)))
    # Otherwise use the fewest decimals (from `want` up to 4) that show the value exactly. 1e-9 absorbs tiny floating-point rounding noise.
    for d in range(want, 5):
        if abs(round(x, d) - x) < 1e-9:
            return f"{x:.{d}f}"
    # No exact short form (like 1/3): fall back to at least 2 decimals.
    return f"{x:.{max(want, 2)}f}"


def _close(a, b):
    """True when two numbers are equal enough: within half a percent of `a` (or a tiny 1e-9), so a rounded result such as 3.33 for 10/3 passes."""
    return abs(a - b) <= max(1e-9, abs(a) * 0.005)


def fix_sums(answer):
    """(text, [{"was", "now"}]): the sums written in the answer checked exactly, a wrong result replaced by the right one."""
    fixes = []

    def one(m, calc):
        """Check one regex match. `calc` works out the right result from the match. Returns the text to put in its place (the same text if fine)."""
        try:
            # m.lastindex is the last group = the result the answer claimed. Commas are removed so "1,234" becomes a number.
            right, said = calc(m), float(m.group(m.lastindex).replace(",", ""))
        except (ZeroDivisionError, ValueError):
            # Dividing by zero or an unreadable number: leave the sum untouched.
            return m.group()
        if _close(right, said):
            return m.group()
        now = _show(right, m.group(m.lastindex).replace(",", ""))
        whole = m.group()
        # Rebuild the text: everything before the claimed result, the right result, then everything after it.
        # (m.start(group) is a position in the whole string, so m.start() is subtracted to get a position inside `whole`.)
        fixed = whole[:m.start(m.lastindex) - m.start()] + now + whole[m.end(m.lastindex) - m.start():]
        fixes.append({"was": whole.strip(), "now": fixed.strip()})
        return fixed

    def sum_calc(m):
        """The true result of "a op b". Both "x" and the multiplication sign mean times; "/" and the division sign mean divide."""
        a, op, b = float(m.group(1)), m.group(2), float(m.group(3))
        # The dict computes every option eagerly, so a / b with b == 0 raises ZeroDivisionError (caught in `one`) whichever operator was used.
        return {"+": a + b, "-": a - b, "*": a * b, "x": a * b, "×": a * b, "/": a / b, "÷": a / b}[op]

    def pct_calc(m):
        """The true value of "p% of whole"."""
        return float(m.group(1)) * float(m.group(2).replace(",", "")) / 100

    # re.split with a capturing group keeps the code blocks in the list at the odd positions (1, 3, ...), with plain text at the even ones.
    parts = re.split(r"(```.*?```)", str(answer), flags=re.S)        # code blocks are left exactly as they are
    for i, p in enumerate(parts):
        if i % 2 == 0:
            # Fix the sums first, then the percentages. The lambda hands each regex match to `one` with the right calculator.
            p = SUM.sub(lambda m: one(m, sum_calc), p)
            parts[i] = PCT.sub(lambda m: one(m, pct_calc), p)
    # At most 10 fixes are reported, but every wrong sum has already been corrected in the text.
    return "".join(parts), fixes[:10]
