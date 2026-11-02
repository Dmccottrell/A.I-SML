# Block-level part of the Markdown converter: headings, paragraphs and bullet lists.
# (Bold, italics, code and links inside a line are handled by md/inline.py.) Reference solution for "markdown_html".
import re

from md.inline import render_inline

# A heading line: 1 to 6 "#" characters, one space, then the text. "#No space" does not match. Group 1 = the hashes, group 2 = the text.
HEADING = re.compile(r"^(#{1,6}) (.*)$")


def convert(markdown):
    """Turn Markdown text into HTML.

    Supports "# " to "###### " headings (<h1>..<h6>), paragraphs (consecutive lines are joined with spaces),
    and "- " bullet lists (<ul><li>..). Blocks are separated by blank lines and joined with newlines in the output.
    """
    # out: finished HTML pieces. para: lines of the paragraph being collected. items: bullets of the list being collected.
    out, para, items = [], [], []

    def flush():
        """Close whatever paragraph or list is being collected: turn it into HTML, add it to out, and empty the buffer."""
        if para:
            out.append("<p>" + render_inline(" ".join(l.strip() for l in para).strip()) + "</p>")
            para.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{render_inline(i)}</li>" for i in items) + "</ul>")
            items.clear()

    for line in markdown.splitlines():
        # A blank line ends the current block.
        if not line.strip():
            flush()
            continue
        h = HEADING.match(line)
        if h:
            # A heading ends any open block; its level is the number of "#" characters.
            flush()
            n = len(h.group(1))
            out.append(f"<h{n}>{render_inline(h.group(2).strip())}</h{n}>")
        elif line.startswith("- "):
            # A bullet: first end any open paragraph, then collect the bullet text (without the "- ").
            if para:
                flush()
            items.append(line[2:].strip())
        else:
            # Ordinary text: first end any open list, then add the line to the current paragraph.
            if items:
                flush()
            para.append(line)
    # The text may end without a blank line, so close the last block.
    flush()
    return "\n".join(out)
