import re

from md.inline import render_inline

HEADING = re.compile(r"^(#{1,6}) (.*)$")


def convert(markdown):
    out, para, items = [], [], []

    def flush():
        if para:
            out.append("<p>" + render_inline(" ".join(l.strip() for l in para).strip()) + "</p>")
            para.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{render_inline(i)}</li>" for i in items) + "</ul>")
            items.clear()

    for line in markdown.splitlines():
        if not line.strip():
            flush()
            continue
        h = HEADING.match(line)
        if h:
            flush()
            n = len(h.group(1))
            out.append(f"<h{n}>{render_inline(h.group(2).strip())}</h{n}>")
        elif line.startswith("- "):
            if para:
                flush()
            items.append(line[2:].strip())
        else:
            if items:
                flush()
            para.append(line)
    flush()
    return "\n".join(out)
