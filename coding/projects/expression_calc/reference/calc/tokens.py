# Tokenizer for the expression calculator (reference solution for the coding exercises).
# A "token" is one small meaningful piece of the text: a number, a name, or a symbol.
# This file cuts a string like "2 + x" into tokens; calc/parser.py then arranges them into a tree.
import re

from calc.errors import CalcError

# A regex (a text pattern) that matches ONE token, with optional spaces in front:
#   \s*                 skip any spaces
#   (\d+\.?\d*|\.\d+)   group 1, a number: digits with an optional dot ("3", "3.", "3.5") or starting with a dot (".5")
#   ([A-Za-z_]\w*)      group 2, a name: a letter or underscore, then letters/digits/underscores
#   ([-+*/^(),=])       group 3, a one-character symbol
# Exactly one of the three groups matches; the other two come back as None.
TOKEN = re.compile(r"\s*(?:(\d+\.?\d*|\.\d+)|([A-Za-z_]\w*)|([-+*/^(),=]))")


def tokenize(text):
    """Split text into a list of (kind, value) tokens.

    Example: "2 + x" gives [("num", 2.0), ("sym", "+"), ("name", "x")]. Numbers are always floats.
    Raises CalcError at the first character that fits no pattern (for example "$").
    """
    # out collects tokens, pos is how far along the text we are. Trailing spaces are cut so they are not seen as bad input.
    out, pos, text = [], 0, text.rstrip()
    while pos < len(text):
        # match() only tries at exactly position pos, so no characters can be silently skipped.
        m = TOKEN.match(text, pos)
        if not m:
            raise CalcError(f"unexpected character {text[pos:].strip()[:1]!r}")
        num, name, sym = m.groups()
        # Pick the kind from whichever group matched (a chained "if num ... else if name ... else symbol").
        out.append(("num", float(num)) if num else ("name", name) if name else ("sym", sym))
        pos = m.end()
    return out
