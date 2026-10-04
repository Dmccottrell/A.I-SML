"""
wiki_index.py - A searchable copy of Wikipedia, for looking things up (v3+).

WHAT THIS FILE DOES
    A small model can't remember every fact ("the capital of Illinois is
    Springfield"). Instead of remembering, v3 LOOKS IT UP: our code searches
    this index for the question, and the best passages are put in front of
    the question as "notes" (see chat.py). The model is trained to answer
    from the notes and to name the source.

    build   Streams English Wikipedia, splits each article into short
            passages (~120 words), keeps the first few of each article (the
            opening sections hold most of the key facts), and stores them in
            a SQLite database with a full-text search index (FTS5).
            Resumable: if it stops, run the same command again.

    search  Finds the passages that best match a question, using keyword
            search (BM25: rarer words count more, and words in the article
            TITLE count extra). No AI model is needed for searching.

Usage:
    python wiki_index.py build                     full index -> data/wiki/wiki.db (~10 GB, several hours)
    python wiki_index.py build --test              20,000 articles -> data/wiki-test/wiki.db (minutes)
    python wiki_index.py search "What is the capital of Illinois?"
    (before the full index exists, search uses the test index automatically)
"""
import argparse
import itertools
import os
import re
import sqlite3
import sys
import threading
import time

DEFAULT_DB = os.path.join("data", "wiki", "wiki.db")
PASSAGE_WORDS = 120        # target passage length
MIN_WORDS = 15             # shorter pieces (headings, stubs) are skipped

# Common words that don't help find the right article
STOPWORDS = set("""
a an the is are was were be been being am of in on at to for from by with about as into like
through after over between out against during without before under around among and or but if
then than so that this these those it its it's what which who whom whose when where why how
do does did doing done can could should would will shall may might must have has had having
i me my we our you your he him his she her they them their there here not no yes any some all
each every more most other such only own same too very just tell please give explain describe
name list know much many one
""".split())


# ------------------------------------------------------------------ passages
def split_passages(text, max_words=PASSAGE_WORDS):
    """Split an article into passages of up to ~max_words words.

    Paragraphs are packed together until adding the next one would go over
    the limit. A paragraph that's too long on its own is split at sentence
    ends. Very short pieces (section headings like "History") are dropped.
    """
    passages, current = [], []
    for para in (p.strip() for p in text.split("\n")):
        words = para.split()
        # Skip empty lines and section headings ("History", "Early life and education"):
        # short lines that don't end like a sentence
        if len(words) < 4 or (len(words) < 10 and not para.endswith((".", "!", "?", ":", '"', ")"))):
            continue
        if len(words) > max_words:             # split long paragraphs by sentence
            sentences = re.split(r"(?<=[.!?])\s+", para)
            chunks, chunk = [], []
            for s in sentences:
                if chunk and len(chunk) + len(s.split()) > max_words:
                    chunks.append(" ".join(chunk)); chunk = []
                chunk += s.split()
            if chunk:
                chunks.append(" ".join(chunk))
        else:
            chunks = [para]
        for c in chunks:
            n = len(c.split())
            if current and sum(len(x.split()) for x in current) + n > max_words:
                passages.append(" ".join(current)); current = []
            current.append(c)
    if current:
        passages.append(" ".join(current))
    return [p for p in passages if len(p.split()) >= MIN_WORDS]


def load_articles():
    """Yield (title, text) for every English Wikipedia article (streamed)."""
    from datasets import load_dataset
    ds = load_dataset("wikimedia/wikipedia", "20231101.en", split="train", streaming=True)
    for row in ds:
        yield row["title"], row["text"]


# ------------------------------------------------------------------ building
def open_db(path):
    """Open (or create) the index database with its tables."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    db = sqlite3.connect(path)
    try:
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5("
                   "title, text, content='passages', content_rowid='id', tokenize='porter unicode61')")
    except sqlite3.OperationalError as e:
        if "fts5" in str(e).lower():
            raise SystemExit("Your Python's SQLite has no FTS5 full-text search. "
                             "Install Python from python.org (it includes FTS5).")
        raise
    db.execute("CREATE TABLE IF NOT EXISTS passages ("
               "id INTEGER PRIMARY KEY, title TEXT, part INTEGER, text TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    return db


def build(path, articles, passages_per_article=3, max_articles=None, batch=2000):
    """Fill the index from `articles` (an iterable of (title, text)), resumably.

    Every batch of articles is written in ONE transaction together with the
    number of articles done, so a crash never leaves a half-written batch.
    """
    db = open_db(path)
    row = db.execute("SELECT value FROM meta WHERE key='articles_done'").fetchone()
    done = int(row[0]) if row else 0
    if done:
        print(f"resuming after {done:,} articles")
    total = db.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
    it = itertools.islice(articles, done, max_articles)
    t0 = time.time()
    while True:
        chunk = list(itertools.islice(it, batch))
        if not chunk:
            break
        rows = []
        for title, text in chunk:
            for part, p in enumerate(split_passages(text)[:passages_per_article]):
                rows.append((title, part, p))
        with db:                                   # one transaction
            cur = db.execute("SELECT COALESCE(MAX(id), 0) FROM passages").fetchone()[0]
            ids = range(cur + 1, cur + 1 + len(rows))
            db.executemany("INSERT INTO passages (id, title, part, text) VALUES (?, ?, ?, ?)",
                           [(i, t, pt, x) for i, (t, pt, x) in zip(ids, rows)])
            db.executemany("INSERT INTO passages_fts (rowid, title, text) VALUES (?, ?, ?)",
                           [(i, t, x) for i, (t, _, x) in zip(ids, rows)])
            done += len(chunk)
            db.execute("INSERT OR REPLACE INTO meta VALUES ('articles_done', ?)", (str(done),))
        total += len(rows)
        rate = done / max(time.time() - t0, 1e-9)
        print(f"  {done:,} articles, {total:,} passages ({rate:.0f} articles/s)")
    with db:
        db.execute("INSERT INTO passages_fts(passages_fts) VALUES ('optimize')")   # faster searches
    print(f"done: {total:,} passages from {done:,} articles in {path}")
    db.close()


# ------------------------------------------------------------------ searching
def keywords(question):
    """The words of a question worth searching for ("capital", "illinois")."""
    words = re.findall(r"[a-z0-9]+", question.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


CANDIDATES = 40            # passages gathered per query before re-ranking


def _prose_ratio(text):
    """Share of words that are everyday function words ("the", "is", "of"). Real
    sentences score ~0.3+; category dumps and name lists ("Defunct baseball teams
    in Illinois 2001 disestablishments") score near 0."""
    words = re.findall(r"[a-z']+", text.lower())
    return sum(w in STOPWORDS for w in words) / len(words) if words else 0.0


def _score(r, words, q):
    """Higher = a better note for the question."""
    title_words = set(re.findall(r"[a-z0-9]+", r["title"].lower()))
    body = set(re.findall(r"[a-z0-9]+", r["text"].lower()))
    covered = sum(w in body or w in title_words for w in words) / len(words)
    base = re.sub(r"\s*\(.*\)$", "", r["title"]).lower()          # "Abraham Lincoln (captain)" -> "abraham lincoln"
    base_words = " ".join(re.findall(r"[a-z0-9]+", base))
    named = bool(base_words) and f" {base_words} " in f" {q} "
    score = 4.0 * covered                                          # answers the whole question
    if named:
        score += 3.0 if base == r["title"].lower() else 2.0       # the article the question is about
    if r.get("part") == 0:
        score += 1.0                                               # the opening passage holds the key facts
    score += 2.0 * min(_prose_ratio(r["text"]) / 0.3, 1.0) - 1.0  # sentences, not lists
    if len(r["text"].split()) < 25:
        score -= 1.0
    return score


class WikiIndex:
    """Search the index built by build(). Example:

        wiki = WikiIndex()
        for note in wiki.search("What is the capital of Illinois?"):
            print(note["title"], note["text"])
    """

    def __init__(self, path=DEFAULT_DB):
        if not os.path.exists(path):
            raise SystemExit(f"no Wikipedia index at {path}. Build it with: python wiki_index.py build")
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()      # one query at a time (the teacher script uses threads)

    def _query(self, match, k):
        # bm25(): lower = better match. Title words count 5x as much as body words.
        sql = ("SELECT p.id, p.title, p.text, p.part FROM passages_fts f JOIN passages p ON p.id = f.rowid "
               "WHERE passages_fts MATCH ? ORDER BY bm25(passages_fts, 5.0, 1.0) LIMIT ?")
        with self.lock:
            return [{"id": i, "title": t, "text": x, "part": pt} for i, t, x, pt in self.db.execute(sql, (match, k))]

    def _title_leads(self, word, n):
        """Opening passages of articles whose TITLE contains `word` (shortest titles first).

        Plain BM25 over 13M passages favours short list-like passages that repeat
        the keywords; the article the question is really about ("Illinois") never
        makes the shortlist. Looking at titles directly finds it.
        """
        sql = ("SELECT p.id, p.title, p.text, p.part FROM passages_fts f JOIN passages p ON p.id = f.rowid "
               "WHERE passages_fts MATCH ? AND p.part = 0 ORDER BY bm25(passages_fts, 5.0, 0.0) LIMIT ?")
        with self.lock:
            return [{"id": i, "title": t, "text": x, "part": pt}
                    for i, t, x, pt in self.db.execute(sql, (f'title:"{word}"', n))]

    def search(self, question, k=3):
        """The k passages that best match `question` (a list of {"id", "title", "text"}).

        Gathers candidates two ways: passages containing ALL the question's
        keywords (any keyword if too few), plus the opening passages of articles
        whose title holds a keyword. Then re-ranks them (see _score) so the main
        article about the subject, written as real sentences and covering the
        keywords, goes first: for "Who was Abraham Lincoln?", "Abraham Lincoln"
        beats "Abraham Lincoln (captain)".
        """
        words = keywords(question)
        if not words:
            return []
        quoted = [f'"{w}"' for w in words]
        pool = CANDIDATES
        results = self._query(" AND ".join(quoted), pool)
        if len(results) < k and len(words) > 1:
            results += self._query(" OR ".join(quoted), pool)
        for w in words:
            results += self._title_leads(w, 15)
        seen, unique = set(), []
        for r in results:
            if r["id"] not in seen:
                seen.add(r["id"])
                unique.append(r)
        q = " ".join(re.findall(r"[a-z0-9]+", question.lower()))
        ranked = sorted(unique, key=lambda r: -_score(r, words, q))      # stable: ties keep search order
        return ranked[:k]

    def random_passages(self, n, rng, lead_only=True):
        """n random passages (by default the opening passage of an article)."""
        with self.lock:
            max_id = self.db.execute("SELECT MAX(id) FROM passages").fetchone()[0]
        out, tries = [], 0
        while len(out) < n and tries < n * 20:
            tries += 1
            with self.lock:
                row = self.db.execute("SELECT id, title, part, text FROM passages WHERE id = ?",
                                      (rng.randint(1, max_id),)).fetchone()
            if row and (row[2] == 0 or not lead_only):
                out.append({"id": row[0], "title": row[1], "text": row[3]})
        return out


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the index from Wikipedia")
    b.add_argument("--out", default=DEFAULT_DB)
    b.add_argument("--passages_per_article", type=int, default=3)
    b.add_argument("--max_articles", type=int, default=None)
    b.add_argument("--test", action="store_true", help="20,000 articles into data/wiki-test/wiki.db")
    s = sub.add_parser("search", help="search the index")
    s.add_argument("question")
    s.add_argument("--db", default=DEFAULT_DB)
    s.add_argument("-k", type=int, default=3)
    a = p.parse_args()
    if a.cmd == "build":
        if a.test:
            a.out, a.max_articles = os.path.join("data", "wiki-test", "wiki.db"), 20_000
        build(a.out, load_articles(), a.passages_per_article, a.max_articles)
    else:
        test_db = os.path.join("data", "wiki-test", "wiki.db")
        if a.db == DEFAULT_DB and not os.path.exists(DEFAULT_DB) and os.path.exists(test_db):
            print(f"(no full index yet; searching the test index {test_db})\n")
            a.db = test_db
        for i, r in enumerate(WikiIndex(a.db).search(a.question, a.k), 1):
            print(f"[{i}] {r['title']}: {r['text'][:300]}\n")


if __name__ == "__main__":
    sys.exit(main())
