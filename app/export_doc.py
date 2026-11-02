"""
export_doc.py - Turn an AI answer into a printable PDF or an editable Word file.

WHAT THIS FILE DOES
    The model only writes text. The Teacher assistant (skill pack, docs/SKILLS.md) writes it in a simple
    layout that reads fine in the chat and that this file turns into a clean page:

        # Fractions on a Number Line                  <- title
        Grade 3 - Math - Worksheet                    <- plain lines: paragraphs
        Instructions: Write the fraction for each point.
        ## Questions                                  <- a section
        1. What fraction is halfway between 0 and 1?  <- numbered items
        2. ...
        - bullet points work too
        ## Answer key                                 <- always starts on a NEW PAGE
        1. 1/2

    The layout is fixed code, not the model's job, so every worksheet looks the same and prints well:
    big readable fonts, "Name: ____  Date: ____" on student pages, writing space under each question,
    and the answer key on its own page (print page 1 for the class, keep the key).

    Everything runs offline on your computer. Needs:  pip install fpdf2 python-docx

Usage:
    python app/export_doc.py answer.txt --out worksheet.pdf          (or .docx, .md, .txt)
    In chat (generate.py --chat):  save worksheet.pdf            (saves the last answer into documents/)

    Where it fits: the steps are parse() (text -> a Doc made of Sections), then one writer: to_pdf, to_docx or to_markdown. export() picks the
    writer from the file ending, and to_bytes() is what the chat app's Save as PDF / Word buttons call.
"""
# The next line (kept as one line on purpose) adds the project's code folders to Python's import search path.
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import argparse      # reads command-line options such as --out
import os
import re            # regular expressions ("regex"): text patterns
from dataclasses import dataclass, field   # @dataclass writes the boring __init__ for a class that is just a bundle of fields

# The folder (inside the project) where chat "save" commands put files, and the file endings that can be written.
DOCS_DIR = "documents"
FORMATS = (".pdf", ".docx", ".md", ".txt")


@dataclass
class Section:
    """One part of a document: an optional heading and a list of blocks (paragraphs, numbered lists, bullet lists, tables)."""

    heading: str = ""
    # field(default_factory=list) gives every Section its own new empty list (a plain "= []" would be shared by all of them).
    blocks: list = field(default_factory=list)     # ("para", text) | ("numbered", [items]) | ("bullets", [items])

    # @property lets code write section.is_key instead of section.is_key(): it looks like a field but is worked out when read.
    @property
    def is_key(self):
        """True for the answer-key section (the heading says "answer key" or "answers"); \\b in the pattern marks a word edge, re.I ignores capitals."""
        return bool(re.search(r"\banswer key\b|\banswers\b", self.heading, re.I))

    @property
    def is_notes(self):
        """Pages for the teacher only (notes, tips, suggestions): they start on a new page, after the part students use."""
        return bool(re.search(r"\bteacher'?s? notes?\b|\bnotes for (the )?teacher\b|\bteaching tips\b|\bsuggestions\b|\brecommendations\b", self.heading, re.I))

    @property
    def starts_page(self):
        """True when the section must begin on a new page (the answer key and teacher-only notes)."""
        return self.is_key or self.is_notes

    @property
    def is_questions(self):
        """True for a section of things students answer (the heading says questions, problems, practice or exercises)."""
        return bool(re.search(r"\bquestions?\b|\bproblems?\b|\bpractice\b|\bexercises?\b", self.heading, re.I))


@dataclass
class Doc:
    """A whole parsed document: a title and its Sections in order."""

    title: str = ""
    sections: list = field(default_factory=list)

    @property
    def for_students(self):
        """A page students write on (worksheets, reading questions): gets the Name/Date line."""
        return any(s.is_questions for s in self.sections)

    def items(self, which):
        """Numbered items of the question sections ("questions") or the answer key ("key")."""
        # `want` is a small test function (lambda) that says whether a section is wanted.
        want = (lambda s: s.is_key) if which == "key" else (lambda s: s.is_questions and not s.is_key)
        # Flatten: for each wanted section, for each numbered block in it, collect every item.
        return [it for s in self.sections if want(s) for kind, v in s.blocks if kind == "numbered" for it in v]


# A numbered line such as "3. text" or "3) text": group 1 = the number, group 2 = the text. \s = a space, \d+ = digits.
NUMBERED = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
# A bullet line starting with "-", "*" or a bullet dot: group 1 = the text.
BULLET = re.compile(r"^\s*[-*•]\s+(.*)$")


def parse(text):
    """Doc from the model's text. Lines that don't match anything special become paragraphs."""
    doc = Doc()
    # `cur` is the section being filled; text before the first heading goes in a heading-less first section.
    cur = Section()
    doc.sections.append(cur)
    # Normalise Windows line endings, then go through the text line by line. `raw` keeps the indentation, `line` is trimmed.
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        # Blank lines are skipped.
        if not line:
            continue
        # Remove **bold** markers: keep what is between the stars (\1 = the first group; .+? = as little as possible).
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)                  # **bold** -> plain
        if line.startswith("|") and line.count("|") >= 2:                 # a table row: | a | b |
            # Split the row into its cells.
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):    # the |---|---| line under the header
                continue
            # Start a new table block unless the last block is already a table; then add this row to it.
            if not (cur.blocks and cur.blocks[-1][0] == "table"):
                cur.blocks.append(("table", []))
            cur.blocks[-1][1].append(cells)
            continue
        # The first single-"#" line is the document title.
        if line.startswith("# ") and not doc.title:
            doc.title = line[2:].strip()
            continue
        # Any other "#..." line starts a new section named by the text after the hashes.
        if line.startswith("#"):
            cur = Section(line.lstrip("#").strip())
            doc.sections.append(cur)
            continue
        # A numbered or bullet line adds an item to the list block before it, or starts a new list block if the last block is a different kind.
        m, b = NUMBERED.match(line), BULLET.match(line)
        if m or b:
            kind, item = ("numbered", m.group(2)) if m else ("bullets", b.group(1))
            if cur.blocks and cur.blocks[-1][0] == kind:
                cur.blocks[-1][1].append(item)
            else:
                cur.blocks.append((kind, [item]))
        # An indented line right after a list item continues that item.
        elif cur.blocks and cur.blocks[-1][0] in ("numbered", "bullets") and raw.startswith(("   ", "\t")):
            cur.blocks[-1][1][-1] += " " + line                       # an item that continues on the next line
        # Anything else is a plain paragraph.
        else:
            cur.blocks.append(("para", line))
    # Drop sections that ended up completely empty, and give an untitled document a default title.
    doc.sections = [s for s in doc.sections if s.heading or s.blocks]
    if not doc.title:
        doc.title = "Document"
    return doc


# ------------------------------------------------------------------ writers
# Fancy characters (curly quotes, dashes, bullet, arrow...) and the plain text to use instead, for the PDF's basic fonts.
_ASCII = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
          "•": "-", "…": "...", " ": " ", "−": "-", "→": "->", "≤": "<=",
          "≥": ">="}


def _latin1(s):
    """The PDF's built-in fonts only know Latin-1: swap curly quotes and dashes for plain ones."""
    # Replace each character that has a plain version; keep all others as they are.
    s = "".join(_ASCII.get(c, c) for c in s)
    # Any character Latin-1 still cannot hold becomes "?" instead of crashing the PDF writer.
    return s.encode("latin-1", "replace").decode("latin-1")


def to_pdf(doc, path):
    """Write `doc` as a PDF file at `path`. Needs the optional package fpdf2 (the ImportError is turned into a plain message in export())."""
    # Imported here because the package is optional.
    from fpdf import FPDF
    # US Letter paper, margins in millimetres (left, top, right), automatic new page 18 mm from the bottom.
    pdf = FPDF(format="Letter")
    pdf.set_margins(20, 18, 20)
    pdf.set_auto_page_break(True, 18)
    pdf.add_page()
    # w = width of the writable area.
    w = pdf.w - pdf.l_margin - pdf.r_margin

    def text(s, size=14, style="", h=None, indent=0):
        """Write one block of wrapped text: font size, style ("B" bold, "I" italic), line height `h` (default 0.55 x size) and an indent in mm."""
        pdf.set_font("Helvetica", style, size)
        pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell(w - indent, h or size * 0.55, _latin1(s))

    # Title in big bold type, then (for student pages) the Name/Date line.
    text(doc.title, 22, "B", 11)
    if doc.for_students:
        pdf.ln(2)
        text("Name: ______________________________    Date: ______________", 13)
    pdf.ln(4)
    for sec in doc.sections:
        # Answer key and teacher notes begin on a fresh page.
        if sec.starts_page:
            pdf.add_page()
            text(doc.title, 11, "I")                                  # which worksheet this key belongs to
        if sec.heading:
            pdf.ln(2)
            text(sec.heading, 17, "B", 9)
            pdf.ln(1)
        for kind, v in sec.blocks:
            if kind == "para":
                text(v)
                pdf.ln(1.5)
            elif kind == "table":
                pdf.set_font("Helvetica", "", 12)
                # The widest row sets the number of columns; shorter rows are padded with empty cells and longer ones cut: (r + [""] * width)[:width].
                width = max(len(r) for r in v)
                with pdf.table(first_row_as_headings=True, line_height=7) as table:
                    for r in v:
                        row = table.row()
                        for c in (r + [""] * width)[:width]:
                            row.cell(_latin1(c))
                pdf.ln(3)
            else:
                # A list (numbered or bullets): number the items from 1, indented 2 mm.
                for i, item in enumerate(v, 1):
                    text((f"{i}. " if kind == "numbered" else "-  ") + item, indent=2)
                    if kind == "numbered" and sec.is_questions and not sec.starts_page:
                        pdf.ln(5 if "____" in item else 16)          # room to write the answer
                    else:
                        pdf.ln(1.5)
    # Write the finished PDF to disk.
    pdf.output(path)


def to_docx(doc, path):
    """Write `doc` as a Word (.docx) file at `path`. Needs the optional package python-docx."""
    from docx import Document
    from docx.enum.text import WD_BREAK
    from docx.shared import Pt
    # A new empty Word document with 14 point body text.
    d = Document()
    d.styles["Normal"].font.size = Pt(14)
    d.add_heading(doc.title, level=0)
    if doc.for_students:
        d.add_paragraph("Name: ______________________________    Date: ______________")
    for sec in doc.sections:
        # A page break is a run (a piece of text) containing a "page break" character, placed in its own paragraph.
        if sec.starts_page:
            d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        if sec.heading:
            d.add_heading(sec.heading, level=1)
        for kind, v in sec.blocks:
            if kind == "para":
                d.add_paragraph(v)
            elif kind == "table":
                # Same column rule as the PDF: pad short rows, cut long ones.
                width = max(len(r) for r in v)
                t = d.add_table(rows=len(v), cols=width)
                # "Table Grid" is a built-in style with visible borders.
                t.style = "Table Grid"
                for ri, r in enumerate(v):
                    for ci, c in enumerate((r + [""] * width)[:width]):
                        t.cell(ri, ci).text = c
                d.add_paragraph("")
            else:
                for i, item in enumerate(v, 1):
                    d.add_paragraph((f"{i}. " if kind == "numbered" else "• ") + item)
                    if kind == "numbered" and sec.is_questions and not sec.starts_page and "____" not in item:
                        d.add_paragraph("")                           # room to write the answer
    d.save(path)


def to_markdown(doc):
    """Return `doc` as Markdown text (# title, ## headings, 1. and - lists, | tables |)."""
    # `out` collects lines; a "" entry is a blank line.
    out = [f"# {doc.title}", ""]
    if doc.for_students:
        out += ["Name: ____________  Date: ________", ""]
    for sec in doc.sections:
        if sec.heading:
            out += [f"## {sec.heading}", ""]
        for kind, v in sec.blocks:
            if kind == "para":
                out += [v, ""]
            elif kind == "table":
                width = max(len(r) for r in v)
                rows = [(r + [""] * width)[:width] for r in v]
                # Header row, then the separator row ("---|" once per column), then the other rows.
                out += ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width] + ["| " + " | ".join(r) + " |" for r in rows[1:]] + [""]
            else:
                out += [(f"{i}. " if kind == "numbered" else "- ") + it for i, it in enumerate(v, 1)] + [""]
    # Join the lines, trim trailing blank lines, and end with exactly one newline.
    return "\n".join(out).rstrip() + "\n"


def export(text, path):
    """Write `text` (the model's answer) to `path`; the format comes from the extension. Returns the path."""
    # The file ending (".pdf" ...) decides the format.
    ext = os.path.splitext(path)[1].lower()
    if ext not in FORMATS:
        raise ValueError(f"can't save as {ext or '(no extension)'}: use {', '.join(FORMATS)}")
    # Make sure the target folder exists.
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)       # invisible control characters
    doc = parse(text)
    # PDF and Word need optional packages; if one is missing, stop with a message that says what to install.
    try:
        if ext == ".pdf":
            to_pdf(doc, path)
        elif ext == ".docx":
            to_docx(doc, path)
        # .md and .txt are plain text files: Markdown is rebuilt from the parsed document; .txt keeps the answer as it was.
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(to_markdown(doc) if ext == ".md" else text.strip() + "\n")
    except ImportError as e:
        raise SystemExit(f"saving {ext} files needs an extra package: pip install fpdf2 python-docx ({e})") from None
    return path


# The "mime type" of each format: the label a web browser uses to know what kind of file it is getting.
MIME = {".pdf": "application/pdf", ".md": "text/markdown; charset=utf-8", ".txt": "text/plain; charset=utf-8",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def to_bytes(text, ext):
    """(file bytes, mime type, the document's title) for the chat app's Save as PDF / Word. A missing package is a RuntimeError the page can show."""
    import tempfile
    # The writers need a real file path, so write into a temporary folder that is deleted automatically afterwards, and read the bytes back.
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "doc" + ext)
        try:
            export(text, path)
        # export() ends the program with SystemExit when a package is missing; a web server must not exit, so turn it into a normal error.
        except SystemExit as e:
            raise RuntimeError(str(e)) from None
        with open(path, "rb") as f:
            data = f.read()
    return data, MIME[ext], parse(text).title


def safe_name(name, default="document.pdf"):
    """A file name inside documents/ (no folders, no odd characters); .pdf if no known extension."""
    # basename drops any folders the name might contain (so "../x" cannot escape documents/).
    base = os.path.basename(name.strip()) or default
    # Keep only letters, digits and . _ space -; also trim spaces and dots from the ends. Nothing left = the default name.
    base = re.sub(r"[^A-Za-z0-9._ -]", "", base).strip(" .") or default
    # No known file ending: make it a PDF.
    if os.path.splitext(base)[1].lower() not in FORMATS:
        base += ".pdf"
    return os.path.join(DOCS_DIR, base)


def main():
    """Command-line entry point: read the answer from a text file and save it in the format of the --out file name."""
    p = argparse.ArgumentParser(description="Save an AI answer as a PDF, Word, Markdown or text file")
    p.add_argument("input", help="a text file with the answer")
    p.add_argument("--out", required=True, help="e.g. worksheet.pdf or worksheet.docx")
    a = p.parse_args()
    with open(a.input, encoding="utf-8") as f:
        print("saved", export(f.read(), a.out))


# Runs only when started directly, not when imported.
if __name__ == "__main__":
    main()
