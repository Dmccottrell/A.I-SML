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
"""
import re
import urllib.parse

CITE_HINT = ("Each note above has a number in square brackets. When a sentence uses a fact from a note, end the sentence with that note's number, "
             "like [1] or [2][3]. Never put a number on something that is not in the notes.")

NUM = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?")
SENT = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")
CODE = re.compile(r"```.*?```", re.S)


def cites_for(notes, sources=()):
    """[{"n", "title", "url"}] for the notes in the order the model saw them. The model only sees a note's title and text: `sources` (the
    lookup's full notes, with kind and url) gives each its link."""
    full = {str(x.get("title", "")): x for x in sources or []}
    out = []
    for i, n in enumerate(notes or [], 1):
        title = str(n.get("title", ""))[:120]
        n = dict(full.get(n.get("title", ""), {}), **{k: v for k, v in n.items() if v})
        url = n.get("url") or ""
        if not url and n.get("kind") == "wikipedia" and title:
            url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
        out.append({"n": i, "title": title, "url": str(url)[:300]})
    return out


def _norm(tok):
    return tok.replace(",", "").rstrip("%").rstrip(".")


def _figures(text):
    """The figures in a piece of text, normalised ("1,234" -> "1234", "45%" -> "45")."""
    return {_norm(m.group()) for m in NUM.finditer(text)}


def unsupported(answer, notes, question=""):
    """[{"sentence", "figures"}]: sentences that state a figure found in no note and not in the question. Small numbers (0-10), list numbers
    and citation marks are not counted: they are rarely facts."""
    known = _figures(" ".join(str(n.get("text", "")) + " " + str(n.get("title", "")) for n in notes or []) + " " + str(question))
    text = CODE.sub(" ", str(answer))
    text = re.sub(r"\[\d{1,2}\]", " ", text)                       # citation marks
    text = PCT.sub(" ", SUM.sub(" ", text))                          # a sum it worked out is not a fact from a source (chat_calc checks those)
    text = re.sub(r"(?m)^\s*\d+[.)]\s", " ", text)                  # numbered lists
    out = []
    for m in SENT.finditer(text):
        s = m.group().strip()
        figs = [f for f in (_norm(x.group()) for x in NUM.finditer(s)) if f not in known and not (f.isdigit() and int(f) <= 10)]
        if figs:
            out.append({"sentence": s[:300], "figures": sorted(set(figs), key=figs.index)[:5]})
    return out[:10]


# "12 x 7 = 84", "100 / 8 = 12.5", "3.5 * 2 = 7"
SUM = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*([+\-*/x×÷])\s*(\d+(?:\.\d+)?)\s*=\s*(-?\d+(?:,\d{3})*(?:\.\d+)?)(?!\d|\.\d)")
# "15% of 80 is 12", "20 percent of 50 = 10"
PCT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:%|percent)\s+of\s+\$?(\d+(?:,\d{3})*(?:\.\d+)?)\s+(?:is|=|equals|comes to)\s+\$?(-?\d+(?:,\d{3})*(?:\.\d+)?)(?!\d|\.\d)", re.I)


def _show(x, like):
    """The right result, written with as many decimals as the wrong one had (at least as many as it needs, up to 4)."""
    want = len(like.split(".")[1]) if "." in like else 0
    if abs(x - round(x)) < 1e-9 and want == 0:
        return str(int(round(x)))
    for d in range(want, 5):
        if abs(round(x, d) - x) < 1e-9:
            return f"{x:.{d}f}"
    return f"{x:.{max(want, 2)}f}"


def _close(a, b):
    return abs(a - b) <= max(1e-9, abs(a) * 0.005)


def fix_sums(answer):
    """(text, [{"was", "now"}]): the sums written in the answer checked exactly, a wrong result replaced by the right one."""
    fixes = []

    def one(m, calc):
        try:
            right, said = calc(m), float(m.group(m.lastindex).replace(",", ""))
        except (ZeroDivisionError, ValueError):
            return m.group()
        if _close(right, said):
            return m.group()
        now = _show(right, m.group(m.lastindex).replace(",", ""))
        whole = m.group()
        fixed = whole[:m.start(m.lastindex) - m.start()] + now + whole[m.end(m.lastindex) - m.start():]
        fixes.append({"was": whole.strip(), "now": fixed.strip()})
        return fixed

    def sum_calc(m):
        a, op, b = float(m.group(1)), m.group(2), float(m.group(3))
        return {"+": a + b, "-": a - b, "*": a * b, "x": a * b, "×": a * b, "/": a / b, "÷": a / b}[op]

    def pct_calc(m):
        return float(m.group(1)) * float(m.group(2).replace(",", "")) / 100

    parts = re.split(r"(```.*?```)", str(answer), flags=re.S)        # code blocks are left exactly as they are
    for i, p in enumerate(parts):
        if i % 2 == 0:
            p = SUM.sub(lambda m: one(m, sum_calc), p)
            parts[i] = PCT.sub(lambda m: one(m, pct_calc), p)
    return "".join(parts), fixes[:10]
