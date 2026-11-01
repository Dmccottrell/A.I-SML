"""
documents.py - Documents: files a person adds (PDF, Word, text ...) so a chat can answer questions about them.

WHAT THIS FILE DOES
    extract_text   a file's bytes -> plain text (PDF with [Page N] marks, Word with its tables, text/Markdown/CSV/JSON/code, HTML without tags)
    Library        one person's saved documents (SQLite, one file per person like the chats): add, list, get, delete, clear, with limits
    notes_for      the parts of the attached documents that matter for THIS question, as "notes" for the model

    Nothing is trained and nothing is sent anywhere: the text is kept on the computer that runs the app, in that person's own file, and the
    model only ever sees the few passages chosen for each question. A short document goes in whole. A long one is searched:
    the passages that share the most (rarer) words with the question win; for "summarize this" style questions the passages are spread over
    the whole document instead, so the answer is not about just one page.

    Limits (plain messages, never a crash): 10 MB per file, about 1.5 million letters of text per document, 40 documents per person.

    Where it fits: the chat routes call Library.add() when a person attaches a file, and chat_turn.py calls notes_for() and the *_hint() functions
    on every message of a chat that has documents. A problem with a file is always raised as ValueError with a message meant for the person.
    Words used here: a "regex" is a text pattern; "OCR" (optical character recognition) means reading the words out of a picture; a "chunk" or
    "piece" is a part of a long text; a "budget" is the most letters we allow to be given to the model.
"""
import html          # html.unescape turns "&amp;" back into "&"
import io            # BytesIO: treat bytes as if they were a file
import math          # math.log is used for the passage scoring
import re            # regular expressions
import sqlite3
import time

from safe_db import SafeDB   # a SQLite wrapper that is safe to use from several threads

# The biggest file accepted (10 MB), the most text kept per document (1.5 million characters) and the most documents per person.
MAX_FILE_BYTES = 10_000_000
MAX_CHARS = 1_500_000
MAX_DOCS = 40
# File endings (extensions) we read as plain text, as web pages, and as pictures.
TEXT_EXTS = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log", ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs",
             ".rb", ".php", ".sql", ".yaml", ".yml", ".toml", ".ini", ".xml", ".css", ".sh", ".bat", ".tex", ".rst"}
HTML_EXTS = {".html", ".htm"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".heic"}
# Shown to the person in "can't read that file" messages.
KINDS = "PDF, Word (.docx), HTML, a picture or screenshot (its text is read), or a text file (.txt, .md, .csv, .json, code)"
# The same picture endings without the dot ("png", "jpg"...), which is how a document's `kind` is stored.
IMAGE_KINDS = {e.lstrip(".") for e in IMAGE_EXTS}
_ocr = None                                                                 # the text reader is loaded on first use (it takes a second)


def warm_ocr():
    """Load the picture reader ahead of time (the app does this in the background when it starts), so the first picture isn't slow. Quietly does nothing if it isn't installed."""
    # `global` lets this function change the module-level variable _ocr (the one shared reader object).
    global _ocr
    try:
        if _ocr is None:
            # Imported here because the package is optional; a missing package must not stop the app starting.
            from rapidocr_onnxruntime import RapidOCR
            _ocr = RapidOCR()
    # Any failure just means "no OCR": picture reading will report that later.
    except Exception:
        pass


def ocr_image(data):
    """The text in a picture, read top to bottom. The models can't see pictures yet; this is what lets a screenshot of text be used."""
    global _ocr
    try:
        # PIL (Pillow) opens and changes pictures. Both packages are optional extras, so they are imported only here.
        from PIL import Image
        if _ocr is None:
            from rapidocr_onnxruntime import RapidOCR
            _ocr = RapidOCR()
    # "from None" hides the technical import error and shows only our plain message.
    except ImportError:
        raise ValueError("Reading text in pictures needs one extra package on the computer that runs the app: pip install rapidocr-onnxruntime") from None
    try:
        # Open the picture from the uploaded bytes and make it plain RGB colour.
        img = Image.open(io.BytesIO(data)).convert("RGB")
        # Shrink very big pictures (over 3000 pixels on a side) so reading is fast; thumbnail keeps the shape.
        if max(img.size) > 3000:
            img.thumbnail((3000, 3000))
        # Save it as PNG bytes in memory, which is the form the reader takes. The reader returns a list of
        # [box corners, text, confidence] rows (and a timing value that is ignored).
        buf = io.BytesIO()
        img.save(buf, "PNG")
        result, _ = _ocr(buf.getvalue())
    # A damaged or unsupported picture.
    except Exception:
        raise ValueError("I couldn't open that picture. Is it a PNG, JPG or WebP?") from None
    # Put the pieces of text in reading order: the key is (line number, left position). The line number is the top edge divided by 12 pixels
    # and rounded, so pieces whose tops are within a few pixels count as one line; then they go left to right.
    rows = sorted(result or [], key=lambda r: (round(min(p[1] for p in r[0]) / 12), min(p[0] for p in r[0])))   # lines, then left to right
    return "\n".join(r[1] for r in rows)


# Pictures: STORE_SIDE = the longest side (in pixels) kept when saving; MODEL_SIDE = the longest side given to a model.
STORE_SIDE, MODEL_SIDE = 2048, 1536     # photo_fixes: the longest side kept, and the longest side a model looks at (more is slower and no more accurate)


def _open_picture(data):
    """A Pillow image of the picture, turned the right way up (phones save photos sideways with a note saying how to turn them). Raises ValueError."""
    from PIL import Image, ImageOps
    # Optional support for iPhone .heic photos: registering it teaches Pillow to open them.
    try:
        import pillow_heif                                                   # iPhone photos (.heic), when the package is there
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    try:
        img = Image.open(io.BytesIO(data))
        # open() reads lazily; load() forces the whole picture to be read now, so a broken file fails here, inside the try.
        img.load()
        # exif_transpose turns the picture upright using the camera's orientation note (EXIF). Returns the picture and its format name.
        return ImageOps.exif_transpose(img), img.format
    except Exception:
        raise ValueError("I couldn't open that picture. Send it as a JPG or PNG (on an iPhone: Settings > Camera > Formats > Most Compatible).") from None


def _encode(img, fmt, side):
    """The picture as JPEG (photos) or PNG (screenshots and drawings, so small text stays sharp), at most `side` pixels on its longest side."""
    from PIL import Image
    # Too big: shrink a copy (LANCZOS is a high-quality shrinking method) so the original object is not changed.
    if max(img.size) > side:
        img = img.copy()
        img.thumbnail((side, side), Image.LANCZOS)
    # Keep PNG (lossless) for screenshots and drawings: those have a PNG source or a palette/1-bit/greyscale mode.
    keep_png = fmt == "PNG" or img.mode in ("P", "1", "LA")
    # JPEG cannot hold see-through pixels, so they are put on a white background; any other mode is converted to plain RGB.
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        flat = Image.new("RGB", img.size, (255, 255, 255))
        flat.paste(img, mask=img.split()[-1])                                 # see-through parts on white (a model reads a black background as part of the picture)
        img = flat
    elif img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    # (An expression used as a statement: save as PNG or as JPEG at quality 90.) Returns the bytes and the matching file ending.
    img.save(buf, "PNG", optimize=True) if keep_png else img.save(buf, "JPEG", quality=90)
    return buf.getvalue(), ".png" if keep_png else ".jpg"


def clean_picture(name, data):
    """photo_fixes, at upload: (name, bytes) of a picture the models can open: right way up, JPEG or PNG (WebP, HEIC, BMP and GIF are converted;
    the models' picture loader opens only JPEG, PNG, BMP and GIF), at most STORE_SIDE pixels. Anything else is returned unchanged."""
    # Not a picture: nothing to do.
    if _ext(name) not in IMAGE_EXTS:
        return name, data
    img, fmt = _open_picture(data)
    # Already fine (JPEG/PNG, small enough, upright): keep the original bytes untouched.
    if fmt in ("JPEG", "PNG") and max(img.size) <= STORE_SIDE and not _rotated(data):
        return name, data
    # Otherwise re-encode, and swap the file ending in the name to match (r"\.[A-Za-z0-9]+$" = the dot and letters at the very end).
    out, ext = _encode(img, fmt, STORE_SIDE)
    return re.sub(r"\.[A-Za-z0-9]+$", "", name) + ext, out


def _rotated(data):
    """True when the photo carries a note to turn it (EXIF orientation other than 1)."""
    try:
        from PIL import Image
        # 0x0112 is the EXIF "Orientation" tag; 1 (or missing) means the picture is already upright.
        return Image.open(io.BytesIO(data)).getexif().get(0x0112, 1) not in (1, None)
    except Exception:
        return False


def picture_for_model(data):
    """photo_fixes, when a model looks at a picture: right way up, JPEG or PNG, at most MODEL_SIDE pixels. The bytes unchanged when Pillow cannot open them."""
    try:
        img, fmt = _open_picture(data)
    # Cannot open it (or Pillow is missing): hand back the original bytes and let the model's own loader deal with it.
    except (ValueError, ImportError):
        return data
    if fmt in ("JPEG", "PNG") and max(img.size) <= MODEL_SIDE and not _rotated(data):
        return data
    return _encode(img, fmt, MODEL_SIDE)[0]


def _ext(name):
    """The file ending of `name` in lower case with its dot (".pdf"), or "" if there is none."""
    # The dot plus letters/digits at the very end of the name.
    m = re.search(r"\.[A-Za-z0-9]+$", name or "")
    return m.group(0).lower() if m else ""


def _clean(text):
    """Tidy extracted text: remove invisible control characters, use "\\n" line ends, drop spaces at line ends and squeeze 3+ blank lines to one."""
    # First make all line endings "\n" (Windows "\r\n" and old Mac "\r"), then delete control characters (keeping tab and newline).
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text.replace("\r\n", "\n").replace("\r", "\n"))
    # Spaces or tabs just before a line end are dropped.
    text = re.sub(r"[ \t]+\n", "\n", text)
    # Three or more newlines in a row become exactly two (one blank line).
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _decode(data):
    """Bytes of a text file -> text. Tries UTF-16 (only if the file starts with its marker), then UTF-8, then Windows Western (cp1252)."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):                         # only a byte-order mark says UTF-16 (otherwise old Western text would read as garbage)
        try:
            return data.decode("utf-16")
        except UnicodeError:
            pass
    # utf-8-sig is UTF-8 that also removes an invisible start marker if there is one.
    try:
        return data.decode("utf-8-sig")
    # Not valid UTF-8: assume the older Windows encoding; "replace" swaps any unknown byte for a placeholder rather than failing.
    except UnicodeDecodeError:
        return data.decode("cp1252", "replace")


# The stand-in text stored for a picture that has no words in it.
PICTURE_ONLY = "[A picture with no readable text]"      # a photo with no words in it: accepted only when the picture reader can look at it


def extract_text(name, data, allow_picture=False):
    """Plain text of an uploaded file. A problem with the file is a ValueError with a message for the person.

    name: the file name (its ending decides how it is read). data: the file's bytes. allow_picture: if a picture has no readable text, return
    PICTURE_ONLY instead of an error (a model that can look at the picture will use it).
    """
    if not data:
        raise ValueError("That file is empty.")
    # Too big: the message shows both sizes in whole megabytes.
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"That file is too big ({len(data) // 1_000_000} MB). The limit is {MAX_FILE_BYTES // 1_000_000} MB.")
    ext = _ext(name)
    # One branch per kind of file; each ends with `text` holding the plain text.
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ValueError("Reading PDFs needs one extra package on the computer that runs the app: pip install pypdf") from None
        try:
            reader = PdfReader(io.BytesIO(data))
            # A PDF can be locked with a password. Try the empty password (some PDFs are "locked" but open freely); if that fails, say so.
            if getattr(reader, "is_encrypted", False):
                if not reader.decrypt(""):
                    raise ValueError("This PDF is password protected. Remove the password and add it again.")
            # Take the text of each page and label it "[Page N]" so answers can say which page. Pages with no text (scans) are skipped.
            pages = []
            for i, page in enumerate(reader.pages, 1):
                t = (page.extract_text() or "").strip()
                if t:
                    pages.append(f"[Page {i}]\n{t}")
        # Our own plain messages (the password one) pass through unchanged; any other failure means a damaged file.
        except ValueError:
            raise
        except Exception:
            raise ValueError("I couldn't read that PDF. It may be damaged.") from None
        text = "\n\n".join(pages)
        # Not a single page had text: probably a scan, which this cannot read.
        if not text.strip():
            raise ValueError("This PDF has no readable text (it may be a scan or pictures). Try a text version of it.")
    elif ext == ".docx":
        try:
            from docx import Document
        except ImportError:
            raise ValueError("Reading Word files needs one extra package on the computer that runs the app: pip install python-docx") from None
        try:
            d = Document(io.BytesIO(data))
        except Exception:
            raise ValueError("I couldn't read that Word file. Is it a .docx (not the older .doc)?") from None
        # Paragraph texts first, then each table row as "cell | cell | cell".
        parts = [p.text for p in d.paragraphs if p.text.strip()]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text.strip() for c in row.cells))
        text = "\n".join(parts)
    elif ext in IMAGE_EXTS:
        # A picture: read the words in it (OCR).
        try:
            text = ocr_image(data)
        except ValueError:
            if not allow_picture:
                raise
            text = ""                                                     # no text reader on this computer, but a model can look at the picture
        if not text.strip() and allow_picture:                       # no words, but the picture reader can look at it when it is asked about
            return PICTURE_ONLY
        if not text.strip():
            raise ValueError("I couldn't find any text in that picture. Emvryx can read the words in a picture or screenshot, but it can't describe photos yet.")
        text = "[Text read from a picture]\n" + text
    elif ext in HTML_EXTS:
        raw = _decode(data)
        # Remove <script> and <style> blocks completely. (?is) = ignore capitals and let "." match line breaks; .*? = as little as possible;
        # \1 = the same tag name that was opened.
        raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
        # Line breaks and the ends of paragraphs, divs, list items, headings and table rows become real newlines.
        raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|tr)>", "\n", raw)
        # Then every remaining tag (<...>) becomes a space, "&amp;"-style codes are turned into characters, and runs of spaces shrink to one.
        text = re.sub(r"[ \t]{2,}", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw)))
    elif ext in TEXT_EXTS or ext == "":
        # Real text files have no zero bytes; finding one in the first 2 KB means it is a binary file (UTF-16 text is the exception, it has them).
        if b"\x00" in data[:2048] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
            raise ValueError(f"That doesn't look like a text file. I can read: {KINDS}.")
        text = _decode(data)
    else:
        raise ValueError(f"I can't read {ext} files yet. I can read: {KINDS}.")
    text = _clean(text)
    if not text:
        raise ValueError("I couldn't find any text in that file.")
    return text


class Library:
    """One person's documents, kept in a SQLite database: the text of each one, and the original bytes if it was a picture."""

    def __init__(self, path=":memory:", clock=time.time):
        """path: the database file (":memory:" = temporary, for tests). clock: returns the current time; tests pass a fake."""
        self.db = SafeDB(path)                                   # shared by the server's threads (safe_db.py)
        self.clock = clock
        self.db.execute("CREATE TABLE IF NOT EXISTS docs (id INTEGER PRIMARY KEY, name TEXT, kind TEXT, chars INTEGER, created REAL, text TEXT)")
        # Older databases have no "image" column: add it. If it is already there SQLite complains, which is fine and ignored.
        try:
            self.db.execute("ALTER TABLE docs ADD COLUMN image BLOB")          # a picture is kept as it was sent, so it can be shown and looked at
            self.db.commit()
        except sqlite3.OperationalError:
            pass
        self.db.commit()

    def add(self, name, data, allow_picture=False):
        """Read the file and save it. Returns its info dict plus "note" (a message if the text was cut). Raises ValueError for a bad or unwanted file."""
        # Clean the name: remove control characters and slashes (so it can never look like a path), cut to 120 characters, never empty.
        name = re.sub(r"[\x00-\x1f/\\]", "", str(name or "document")).strip()[:120] or "document"
        text = extract_text(name, data, allow_picture)
        note = ""
        # Keep only the first MAX_CHARS characters of a huge text, and tell the person.
        if len(text) > MAX_CHARS:
            text, note = text[:MAX_CHARS], f"Only the first {MAX_CHARS // 1000:,}K letters were kept."
        # The library is full.
        if self.db.execute("SELECT COUNT(*) FROM docs").fetchone()[0] >= MAX_DOCS:
            raise ValueError(f"You can keep {MAX_DOCS} documents. Delete one you no longer need first.")
        # Save the row. Pictures also keep their original bytes in the image column; for other files it is None (NULL).
        cur = self.db.execute("INSERT INTO docs (name, kind, chars, created, text, image) VALUES (?, ?, ?, ?, ?, ?)",
                              (name, _ext(name).lstrip(".") or "txt", len(text), self.clock(), text, data if _ext(name) in IMAGE_EXTS else None))
        self.db.commit()
        return dict(self.info(cur.lastrowid), note=note)

    def image(self, doc_id):
        """(bytes, mime type) of a picture that was added, or None."""
        r = self.db.execute("SELECT name, image FROM docs WHERE id = ?", (doc_id,)).fetchone()
        if not r or not r[1]:
            return None
        ext = _ext(r[0])
        # The "mime type" tells a browser or model what kind of picture the bytes are; PNG is assumed for an unknown ending.
        return bytes(r[1]), {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp"}.get(ext, "image/png")

    def info(self, doc_id):
        """The description of one document (id, name, kind, chars, created) without its text, or None if there is no such document."""
        r = self.db.execute("SELECT id, name, kind, chars, created FROM docs WHERE id = ?", (doc_id,)).fetchone()
        return dict(zip(("id", "name", "kind", "chars", "created"), r)) if r else None

    def list(self):
        """Every document's description, newest first (no text)."""
        rows = self.db.execute("SELECT id, name, kind, chars, created FROM docs ORDER BY id DESC").fetchall()
        return [dict(zip(("id", "name", "kind", "chars", "created"), r)) for r in rows]

    def text(self, doc_id):
        """The full extracted text of a document, or None."""
        r = self.db.execute("SELECT text FROM docs WHERE id = ?", (doc_id,)).fetchone()
        return r[0] if r else None

    def delete(self, doc_id):
        """Delete one document. Returns True if it existed."""
        n = self.db.execute("DELETE FROM docs WHERE id = ?", (doc_id,)).rowcount
        self.db.commit()
        return bool(n)

    def clear(self):
        """Delete all documents."""
        self.db.execute("DELETE FROM docs")
        self.db.commit()


# ------------------------------------------------------------------ choosing the passages for a question
# Very common words that tell us nothing about what a passage is about; they are ignored when matching a question to passages.
STOP = set("the a an of to in on at for and or is are was were be been do does did what who whom when where which why how can could will would should it its this "
           "that these those with as by from about me my you your i tell give name please document file pdf text say says said".split())
# A question that wants the whole document ("summarize", "main points", "what is this about"): passages are then spread over the document.
OVERVIEW = re.compile(r"\b(summari[sz]e|summary|overview|main (points?|ideas?)|key (points?|takeaways?|ideas?)|tl;?dr|outline|what is (this|it|the document|the file) about|"
                      r"what does (this|it) (say|cover|contain)|explain (this|the) (document|file|paper|article|text)|give me the gist|in short)\b", re.I)


def chunks(text, size=1200):
    """Pieces of about `size` letters, cut at paragraph or sentence ends."""
    # out = finished pieces; cur = the piece being built.
    out, cur = [], ""
    # Split into paragraphs: at blank lines (\n{2,} = two or more newlines) or at a newline just before a "[Page N]" mark
    # ((?=...) peeks ahead without removing the mark).
    for para in re.split(r"\n{2,}|\n(?=\[Page \d+\])", text):
        para = para.strip()
        if not para:
            continue
        while len(para) > size * 1.5:                               # a very long paragraph: cut at a sentence end near `size`
            # Find the last sentence end (". ") or line break before `size`; if none is far enough in (past a third of size), cut at `size`.
            cut = max(para.rfind(". ", 0, size), para.rfind("\n", 0, size))
            cut = cut + 1 if cut > size // 3 else size
            piece, para = para[:cut].strip(), para[cut:].strip()
            if cur:
                out.append(cur)
                cur = ""
            out.append(piece)
        # Adding this paragraph would make the piece too big: close the piece and start a new one; otherwise join with a blank line.
        if len(cur) + len(para) + 2 > size and cur:
            out.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    # Don't lose the last piece being built.
    if cur:
        out.append(cur)
    return out


def _words(text):
    """The meaningful words of a text: lower-case words/numbers of 3+ letters that are not in STOP."""
    return [w for w in re.findall(r"[a-z0-9']+", text.lower()) if len(w) > 2 and w not in STOP]


def pick(pieces, question, budget):
    """Indexes of the pieces to show, in document order, within `budget` letters."""
    # Everything fits: show it all.
    if sum(len(p) for p in pieces) <= budget:
        return list(range(len(pieces)))
    # want = the meaningful words of the question; chosen = indexes picked so far; used = letters picked so far.
    want = set(_words(question))
    chosen, used = [], 0
    if OVERVIEW.search(question) or not want:                       # spread over the whole document: the start, then evenly
        # n = how many average-sized pieces fit in the budget; take n pieces at even steps through the document, always including the first.
        n = max(1, min(len(pieces), budget // max(1, int(sum(len(p) for p in pieces) / len(pieces)))))
        step = len(pieces) / n
        order = sorted({min(len(pieces) - 1, int(i * step)) for i in range(n)} | {0})
    else:
        # Score every piece by the question words it contains, like a simple search engine (TF-IDF):
        # df[w] = in how many pieces word w appears (a word found in few pieces is more telling).
        df = {}
        toks = [_words(p) for p in pieces]
        for t in toks:
            for w in set(t) & want:
                df[w] = df.get(w, 0) + 1
        scores = []
        for i, t in enumerate(toks):
            # tf[w] = how often question word w appears in this piece.
            tf = {}
            for w in t:
                if w in want:
                    tf[w] = tf.get(w, 0) + 1
            # Each word adds (1 + ln(times it appears)) x ln(1 + pieces / pieces-containing-it): repeats help, with diminishing returns,
            # and rare words count more. -i makes earlier pieces win ties.
            s = sum((1 + math.log(c)) * (math.log(1 + len(pieces) / df[w])) for w, c in tf.items())
            scores.append((s, -i))
        # Piece indexes from best score to worst, leaving out pieces that share no word with the question (score 0).
        order = [i for (s, _), i in sorted(((sc, i) for i, sc in enumerate(scores)), reverse=True) if s > 0]
        if not order:                                               # nothing shares a word with the question: the start of the document
            order = list(range(len(pieces)))
    # Take pieces in that order until the budget is used up. A piece that does not fit is skipped (but the very first pick is always taken).
    for i in order:
        if used + len(pieces[i]) > budget and chosen:
            continue
        chosen.append(i)
        used += len(pieces[i])
        if used >= budget:
            break
    # Back into document order so the notes read naturally.
    return sorted(chosen)


def notes_for(library, doc_ids, question, budget=8000):
    """Notes ([{"title", "text"}]) from the attached documents for this question, within `budget` letters in all."""
    # Look up each document; ones that were deleted or have no text are dropped.
    docs = [(i, library.info(i), library.text(i)) for i in doc_ids]
    docs = [(i, info, text) for i, info, text in docs if info and text]
    if not docs:
        return []
    # Each document gets an equal share of the budget, but at least 1500 letters.
    per = max(1500, budget // len(docs))
    notes = []
    for _, info, text in docs:
        if info.get("kind") in IMAGE_KINDS:                    # a picture is not a document: its words go in as what the picture says, with no file name to cite
            words = text.replace("[Text read from a picture]", "").strip()
            if words and not words.startswith(PICTURE_ONLY):
                notes.append({"title": "Words in the picture", "text": words[:per]})
            continue
        # Cut the text into pieces and choose the ones that matter for this question.
        pieces = chunks(text)
        idx = pick(pieces, question, per)
        whole = len(idx) == len(pieces)
        # Everything fits: one note with the whole document. Otherwise one note per chosen piece, saying which part it is.
        if whole:
            notes.append({"title": f"Document: {info['name']}", "text": "\n\n".join(pieces)})
        else:
            for i in idx:
                notes.append({"title": f"Document: {info['name']} (part {i + 1} of {len(pieces)})", "text": pieces[i]})
    return notes


# The messages saved in the chat when a person sends only a picture or only a file (nothing typed).
PICTURE_ONLY_TEXT = "(sent a picture)"        # what is saved when only a picture is sent; the page shows just the picture
FILE_ONLY_TEXT = "(sent a file)"              # ...and when only a file is sent (the model then sums it up)


# Instructions for a model that can see a picture: how to reply (set out as lines of a list). Quoted pieces side by side are joined into one string.
PICTURE_PLAYBOOK = (
    "How to reply, the way a friend who can see the picture would:\n"
    "- Open by showing you got it, in their tone: name what it is and react (\"Caleb's back!\", \"Oof, that error\"). No \"The picture shows\".\n"
    "- Then add something they did not say: what it means, useful context, or your honest take. Two to four short sentences, not a list.\n"
    "- Fit the kind of picture: news or a post: react and add context. An error or code: say what is wrong and how to fix it. Homework, a form "
    "or a bill: help with it. A chart: the main takeaway. A photo: comment on what stands out. A meme: get the joke. A product: what to know before buying.\n"
    "- End with one short question or next step only when it fits naturally.\n"
    "- Do not read out or list its text, do not describe the phone screen around it, and never add sources or file names in brackets.")
# Reminds the model to address the person as "you" (small models sometimes talk about the user in the third person).
TALK_TO_THEM = ("Talk to the user directly as \"you\". If you know their name, it is the name of the person you are talking to: never talk about them as "
                "someone else, and never guess what they will say. Plain, natural sentences.")


# Extra instructions (used when photo_fixes is on) to stop the model inventing details that are not visible in the picture.
PICTURE_ACCURACY = ("Be exact about the picture: say only what you can really see. Never make up names, numbers, brands, places or words that are not "
                    "visible; when something is too small, blurry or cut off to be sure, say so in a few words instead of guessing. When they ask what it says "
                    "or for the details, give them fully and copy any text word for word. Count things one by one before giving a number. A screenshot of an account, "
                    "a balance, a bill, a schedule or a form: give every key number with its label exactly as shown (all the balances, dates and amounts), "
                    "not a summary like \"a few days\". When several pictures are in the chat, answer about the one just sent.")


def picture_hint(only_picture=False, earlier=False, accurate=False):
    """The instruction for a model that looks at the picture itself: answer like Claude or ChatGPT do with a picture (react, add value, fit the
    kind of picture), not like a text reader quoting a document. `earlier`: the picture came with an earlier message, and the user is now just
    talking: answer what they said first.

    only_picture: no text was typed with the picture. accurate: add the PICTURE_ACCURACY rules. Returns text for the model only (never saved in the chat).
    """
    # The picture came with an earlier message: just continue the conversation.
    if earlier:
        return ("[Earlier in this chat the user you are talking with shared the picture you can see here. Now reply to what they just said, like a friend: "
                "react to it first (share their excitement, answer their question, give your take), and bring in the picture only where it helps. Keep it short. "
                "Do not repeat the picture's text and never add sources or file names in brackets. " + TALK_TO_THEM + (" " + PICTURE_ACCURACY if accurate else "") + "]")
    # The opening line differs: a picture alone, or a picture with a comment.
    lead = ("[The user you are talking with sent you a picture with no message. You can see it.\n" if only_picture else
            "[The user you are talking with sent you a picture and said something about it. You can see it. Answer what they said first, using what you see.\n")
    # Assemble: opening line, the playbook, the optional accuracy rules, the "talk to them as you" rule, and the closing bracket.
    return lead + PICTURE_PLAYBOOK + "\n" + (PICTURE_ACCURACY + "\n" if accurate else "") + TALK_TO_THEM + "]"


def picture_words_hint():
    """For a model that cannot see pictures: it only gets the words read from the picture, and must still talk about it as a picture."""
    return ("[The user you are talking with sent you a picture. You cannot see it, but the notes hold the words in it. Talk about it as their picture, never "
            "as a document or file, and reply like a friend: react first, then add something useful. Do not repeat its text, and never add sources or file "
            "names in brackets. " + TALK_TO_THEM + "]")


def hint(names):
    """The instruction for the model while documents are attached (never saved in the chat)."""
    # Name at most the first 5 documents, each in double quotes.
    shown = ", ".join(f'"{n}"' for n in names[:5])
    return (f"[The person attached {shown}. The notes hold the relevant parts of it. Answer from the document, quote a short phrase when it helps "
            "(and say which page or part if it is shown), and say plainly if the document does not contain the answer instead of guessing.]")
