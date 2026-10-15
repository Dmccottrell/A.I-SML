"""
general_lessons.py - Turn an open assistant dataset into general "LLM lessons" in the Emvryx lesson format, to mix in next to the Emvryx lessons.

    hf download databricks/databricks-dolly-15k --repo-type dataset --local-dir data\\open\\dolly
    python data_prep/general_lessons.py --input data\\open\\dolly\\databricks-dolly-15k.jsonl --format dolly --source dolly-15k --licence cc-by-sa-3.0 --max 5000
    python data_prep/format_lessons_3x.py --general data\\v3\\general.jsonl --general-share 0.3 --keep 0.4

What it does to each lesson: reads it (--format messages = {"messages":[{"role","content"}]}, pairs = {"prompt","response"} or {"instruction","output"},
dolly = {"instruction","context","response"}), keeps normal question-and-answer chats (up to 6 turns, replies of 20 to 2,500 characters (the Emvryx length cap, so the models are not taught to ramble)), and DROPS anything that
breaks a HARD style rule (claims to be ChatGPT/Qwen/Claude..., "as an AI language model", stray thinking tags: data_prep/style_check.py), any lesson that
mentions an email address or phone number, and duplicates. The soft voice rules (filler openers, length) are not applied: general lessons teach range, not voice.
Every kept lesson carries "kind": "general", its source and its licence. The Emvryx identity, honesty and correction lessons are never touched: they stay in
the main file and format_lessons_3x.py always keeps them.

LICENCE RULES: the licence must be one of ALLOWED_LICENCES (or add --allow-other-licence after reading it yourself). Read the dataset's page first. Datasets whose
answers were written by another company's AI (ChatGPT, Claude, Gemini ...) may be limited by that company's terms for training other models: prefer human-written
ones, and say so with --synthetic if a dataset is model-written so it is recorded. Nothing is downloaded here.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import argparse
import glob
import hashlib
import json
import random
import re

import style_check

ALLOWED_LICENCES = ("apache-2.0", "mit", "cc0-1.0", "cc-by-4.0", "cc-by-sa-3.0", "cc-by-sa-4.0", "odc-by")
MAX_TURNS, MIN_REPLY, MAX_REPLY = 6, 20, 2500          # 2,500 characters: the same cap as the Emvryx voice (data_prep/style_check.py), so general lessons do not teach long-windedness
PII_RX = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+|\b\+?\d[\d\s().-]{8,}\d\b")


def to_messages(row, fmt):
    """The row as [{"role","content"}...], or None when it doesn't have that shape."""
    try:
        if fmt == "messages":
            msgs = [{"role": m["role"], "content": str(m["content"])} for m in row["messages"] if m["role"] in ("user", "assistant")]
        elif fmt == "dolly":
            q = row["instruction"].strip()
            if (row.get("context") or "").strip():
                q += "\n\n" + row["context"].strip()
            msgs = [{"role": "user", "content": q}, {"role": "assistant", "content": row["response"]}]
        elif fmt == "pairs":
            q = row.get("prompt") or row.get("instruction")
            a = row.get("response") or row.get("output")
            if row.get("input"):
                q += "\n\n" + row["input"]
            msgs = [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
        else:
            raise ValueError(f"unknown format {fmt}")
    except (KeyError, TypeError, AttributeError):
        return None
    return msgs


def good_shape(msgs):
    if not msgs or msgs[0]["role"] != "user" or msgs[-1]["role"] != "assistant":
        return False
    if any(a["role"] == b["role"] for a, b in zip(msgs, msgs[1:])):
        return False
    if sum(1 for m in msgs if m["role"] == "user") > MAX_TURNS:
        return False
    return all(m["content"].strip() for m in msgs) and all(MIN_REPLY <= len(m["content"].strip()) <= MAX_REPLY for m in msgs if m["role"] == "assistant")


EMPTY_THINK_RX = re.compile(r"<think>\s*</think>\s*")


def row_allowed(row, filters=(), row_licences=()):
    """(ok, reason). filters = [("reasoning", "off")...] (a row field must equal the value); row_licences = licences a row's own "license" field may have."""
    for key, value in filters:
        if str(row.get(key, "")).strip().lower() != value.lower():
            return False, "filtered_out"
    if row_licences:
        own = licence_key(row.get("license") or row.get("licence"))
        if own and own not in {licence_key(x) for x in row_licences}:     # no label on the row: the dataset's own licence applies
            return False, "row_licence"
    return True, ""


def licence_key(name):
    """A licence name as letters and digits only, so "CC BY 4.0", "cc-by-4.0" and "CC_BY_4.0" are the same."""
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def clean_row(row, fmt, source, licence, synthetic=False):
    """(lesson or None, reason it was dropped)."""
    msgs = to_messages(row, fmt)
    if msgs is not None:
        msgs = [dict(m, content=EMPTY_THINK_RX.sub("", m["content"])) if m["role"] == "assistant" else m for m in msgs]
    if msgs is None:
        return None, "wrong_shape"
    msgs = [{"role": m["role"], "content": m["content"].strip()} for m in msgs]
    if not good_shape(msgs):
        return None, "wrong_shape"
    if any(PII_RX.search(m["content"]) for m in msgs):
        return None, "personal_details"
    lesson = {"kind": "general", "source": source, "licence": licence, "messages": msgs}
    if synthetic:
        lesson["synthetic"] = True
    hard = [rid for rid, sev in style_check.check_lesson(lesson) if sev == "hard"]
    if hard:
        return None, hard[0]
    return lesson, ""


def convert(rows, fmt, source, licence, synthetic=False, limit=None, seed=1337, filters=(), row_licences=()):
    """(lessons, {reason: count, ..., "kept": n}). With `limit`, a random sample of that many good lessons is kept (reservoir sampling: rows are streamed,
    so a multi-gigabyte file never has to fit in memory). `rows` can be any iterable."""
    stats, seen, out, good = {}, set(), [], 0
    rng = random.Random(seed)
    for row in rows:
        ok, why = row_allowed(row, filters, row_licences)
        if why == "row_licence" and len(stats.setdefault("licences_seen", {})) < 8:
            lic = str(row.get("license") or row.get("licence"))
            stats["licences_seen"][lic] = stats["licences_seen"].get(lic, 0) + 1          # shown when everything is dropped, to see what the rows say
        lesson = None
        if ok:
            lesson, why = clean_row(row, fmt, source, licence, synthetic)
        if lesson is None:
            stats[why] = stats.get(why, 0) + 1
            continue
        key = hashlib.sha1(json.dumps(lesson["messages"], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if key in seen:
            stats["duplicate"] = stats.get("duplicate", 0) + 1
            continue
        seen.add(key)
        good += 1
        if not limit or len(out) < limit:
            out.append(lesson)
        else:
            j = rng.randrange(good)
            if j < limit:
                out[j] = lesson
    rng.shuffle(out)
    stats["kept"] = len(out)
    return out, stats


def read_rows(patterns):
    """Rows from .jsonl and .parquet files (a pattern like data\\open\\nemotron-v2\\data\\math-* works), streamed."""
    files = sorted(f for p in patterns for f in glob.glob(p))
    if not files:
        sys.exit("no files match " + " ".join(patterns))
    for path in files:
        if path.endswith(".parquet"):
            try:
                import pyarrow.parquet as pq
            except ImportError:
                sys.exit("reading .parquet files needs pyarrow: pip install pyarrow")
            for batch in pq.ParquetFile(path).iter_batches(batch_size=1000):
                yield from batch.to_pylist()
        else:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        yield json.loads(line)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, nargs="+", help="the dataset's .jsonl or .parquet files (downloaded already); patterns with * work")
    ap.add_argument("--filter", action="append", default=[], metavar="FIELD=VALUE", help="keep only rows whose field equals the value, e.g. reasoning=off (can be repeated)")
    ap.add_argument("--row-licences", default="", help="comma list: keep only rows whose own license field is one of these, e.g. cc-by-4.0")
    ap.add_argument("--format", required=True, choices=("messages", "pairs", "dolly"))
    ap.add_argument("--source", required=True, help="a short name, kept in every lesson")
    ap.add_argument("--licence", required=True, help="the dataset's licence, e.g. apache-2.0")
    ap.add_argument("--allow-other-licence", action="store_true")
    ap.add_argument("--synthetic", action="store_true", help="the answers were written by an AI (recorded in each lesson)")
    ap.add_argument("--max", type=int, default=None, help="keep at most this many lessons")
    ap.add_argument("--out", default=os.path.join("data", "v3", "general.jsonl"))
    ap.add_argument("--append", action="store_true", help="add to --out instead of replacing it (to combine several datasets)")
    a = ap.parse_args(argv)
    licence = a.licence.lower()
    if licence not in ALLOWED_LICENCES and not a.allow_other_licence:
        sys.exit(f"licence '{a.licence}' is not on the allowed list {ALLOWED_LICENCES}. Read the dataset's page; if it is fine, add --allow-other-licence.")
    filters = []
    for item in a.filter:
        if "=" not in item:
            sys.exit(f"--filter {item!r} must look like field=value")
        k, v = item.split("=", 1)
        filters.append((k.strip(), v.strip()))
    row_licences = tuple(x.strip().lower() for x in a.row_licences.split(",") if x.strip())
    lessons, stats = convert(read_rows(a.input), a.format, a.source, licence, a.synthetic, a.max, filters=filters, row_licences=row_licences)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "a" if a.append else "w", encoding="utf-8") as f:
        for l in lessons:
            f.write(json.dumps(l, ensure_ascii=False) + "\n")
    seen = stats.pop("licences_seen", {})
    dropped = {k: v for k, v in stats.items() if k != "kept"}
    print(f"kept {stats['kept']:,}; dropped {sum(dropped.values()):,} {dropped or ''}")
    if seen:
        print("  licences on the dropped rows (first kinds seen): " + ", ".join(f"{k!r} x{v}" for k, v in seen.items()))
    print(f"wrote to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
