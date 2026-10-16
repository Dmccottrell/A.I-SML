import re

from calc.errors import CalcError

TOKEN = re.compile(r"\s*(?:(\d+\.?\d*|\.\d+)|([A-Za-z_]\w*)|([-+*/^(),=]))")


def tokenize(text):
    out, pos, text = [], 0, text.rstrip()
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            raise CalcError(f"unexpected character {text[pos:].strip()[:1]!r}")
        num, name, sym = m.groups()
        out.append(("num", float(num)) if num else ("name", name) if name else ("sym", sym))
        pos = m.end()
    return out
