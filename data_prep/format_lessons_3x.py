"""
format_lessons_3x.py - Get the lessons ready for Flare 3, Equinox 3 and Solstice 3: remove what must not be taught, and keep the best part.

    python data_prep/format_lessons_3x.py                                   # data\\v3\\chat.jsonl -> data\\v3\\chat_3x.jsonl (everything that passes)
    python data_prep/format_lessons_3x.py --keep 0.4                        # a well-spread 40%: the training time scales by the same share
    python data_prep/format_lessons_3x.py --thinking data\\v3\\thinking_lessons.jsonl --thinking-share 0.1

What it does, in order:
  1. Drops exact duplicates.
  2. Drops lessons that break a HARD style rule (data_prep/style_check.py): claiming to be another AI, "as an AI language model", "trained from scratch",
     stray thinking tags or control tokens. With --strict the SOFT rules drop lessons too.
  3. With --keep, keeps a share of what is left, chosen evenly across kinds of lessons (looking things up, "I don't know", corrections, identity, long
     chats, short answers ...) so a smaller set is still balanced. The rare, important kinds (identity, honesty, corrections) are always kept.
  4. With --general, mixes in general lessons from open datasets (data_prep/general_lessons.py) as a share of the final set (--general-share, default 30%).
     The Emvryx lessons, including all identity, honesty and correction lessons, are kept exactly as before; the general ones only add range.
  5. With --thinking, mixes in verified thinking lessons (data_prep/make_thinking_lessons.py) as a share of the final set.
Nothing about the thinking format is baked into the file: the trainer adds the empty thinking block itself (the presets say think="empty").
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import argparse
import hashlib
import json
import random
import re

import style_check

IDENTITY_RX = re.compile(r"\b(who are you|who made you|who created you|what are you|your name|are you (?:chatgpt|qwen|gemma|gpt|claude)|which model|what model)\b", re.I)
HONESTY_RX = re.compile(r"\b(i don't know|i do not know|i'm not sure|i am not sure|i couldn't find|i could not find|not certain)\b", re.I)
CORRECTION_RX = re.compile(r"\b(that's wrong|that is wrong|that's not right|that is not right|you're wrong|you are wrong|incorrect|are you sure)\b", re.I)
ALWAYS_KEEP = ("identity", "honesty", "correction")


def messages_of(row):
    if "messages" in row:
        return row["messages"]
    return [{"role": "user", "content": row.get("prompt", "")}, {"role": "assistant", "content": row.get("response", "")}]


def kind_of(row):
    """A rough label for the kind of lesson, from its shape and wording (the lesson files do not all carry a label)."""
    msgs = messages_of(row)
    first_user = next((m.get("content", "") for m in msgs if m.get("role") == "user"), "")
    replies = " ".join(m.get("content", "") for m in msgs if m.get("role") == "assistant")
    if IDENTITY_RX.search(first_user):
        return "identity"
    if any(m.get("notes") for m in msgs):
        return "honesty" if HONESTY_RX.search(replies) else "lookup"
    if HONESTY_RX.search(replies):
        return "honesty"
    if any(CORRECTION_RX.search(m.get("content", "")) for m in msgs if m.get("role") == "user"):
        return "correction"
    turns = sum(1 for m in msgs if m.get("role") == "user")
    if turns >= 3:
        return "long_chat"
    if turns == 2:
        return "follow_up"
    n = len(replies)
    return "short_answer" if n < 200 else "medium_answer" if n < 800 else "long_answer"


def _fingerprint(row):
    return hashlib.sha1(json.dumps(messages_of(row), sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def select(rows, keep=1.0, strict=False, seed=1337):
    """(kept rows, stats). `keep` is the share of the (clean, de-duplicated) lessons to keep, spread evenly over kinds."""
    stats = {"read": len(rows), "duplicates": 0, "style_dropped": {}, "kept_by_kind": {}, "available_by_kind": {}}
    seen, clean = set(), []
    for row in rows:
        fp = _fingerprint(row)
        if fp in seen:
            stats["duplicates"] += 1
            continue
        seen.add(fp)
        bad = [rid for rid, sev in style_check.check_lesson(row) if sev == "hard" or (strict and sev == "soft")]
        if bad:
            for rid in bad:
                stats["style_dropped"][rid] = stats["style_dropped"].get(rid, 0) + 1
            continue
        clean.append(row)
    by_kind = {}
    for row in clean:
        by_kind.setdefault(kind_of(row), []).append(row)
    stats["available_by_kind"] = {k: len(v) for k, v in by_kind.items()}
    rng = random.Random(seed)
    kept = []
    if keep >= 1.0:
        kept = list(clean)
    else:
        target = max(1, int(len(clean) * keep))
        rare = [k for k in by_kind if k in ALWAYS_KEEP]
        for k in rare:
            kept += by_kind[k]
        rest = [k for k in by_kind if k not in rare]
        room = max(0, target - len(kept))
        quota = {k: min(len(by_kind[k]), room // max(1, len(rest))) for k in rest}      # an even share each...
        spare = room - sum(quota.values())
        for k in sorted(rest, key=lambda k: -len(by_kind[k])):                        # ...then what the small kinds could not use goes to the big ones
            extra = min(spare, len(by_kind[k]) - quota[k])
            quota[k] += extra
            spare -= extra
        for k in rest:
            pool = by_kind[k][:]
            rng.shuffle(pool)
            kept += pool[:quota[k]]
    for row in kept:
        k = kind_of(row)
        stats["kept_by_kind"][k] = stats["kept_by_kind"].get(k, 0) + 1
    rng.shuffle(kept)
    stats["kept"] = len(kept)
    return kept, stats


def mix_thinking(rows, thinking_rows, share, seed=1337):
    """Add thinking lessons so they are `share` of the final set (never more than we have)."""
    if not thinking_rows or share <= 0:
        return rows
    n = min(len(thinking_rows), int(len(rows) * share / (1 - share)))
    pool = thinking_rows[:]
    random.Random(seed).shuffle(pool)
    out = rows + pool[:n]
    random.Random(seed + 1).shuffle(out)
    return out


def mix_general(rows, general_rows, share, seed=1337):
    """Add general (open-dataset) lessons so they are `share` of the final set. The Emvryx lessons (identity, honesty, corrections...) are already in
    `rows` and are untouched; general lessons are only ever added next to them (never more than we have)."""
    if not general_rows or share <= 0:
        return rows
    n = min(len(general_rows), int(len(rows) * share / (1 - share)))
    pool = general_rows[:]
    random.Random(seed + 2).shuffle(pool)
    out = rows + pool[:n]
    random.Random(seed + 3).shuffle(out)
    return out


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=os.path.join("data", "v3", "chat.jsonl"))
    ap.add_argument("--out", default=os.path.join("data", "v3", "chat_3x.jsonl"))
    ap.add_argument("--keep", type=float, default=1.0, help="share of the lessons to keep, 0 to 1 (default: all that pass)")
    ap.add_argument("--strict", action="store_true", help="soft style rules drop lessons too")
    ap.add_argument("--thinking", default=None, help="a file of thinking lessons from make_thinking_lessons.py")
    ap.add_argument("--thinking-share", type=float, default=0.1)
    ap.add_argument("--general", default=None, help="a file of general lessons from general_lessons.py")
    ap.add_argument("--general-share", type=float, default=0.3, help="share of the final set that is general lessons (default 0.3)")
    ap.add_argument("--seed", type=int, default=1337)
    a = ap.parse_args(argv)
    if not 0 < a.keep <= 1:
        sys.exit("--keep must be above 0 and at most 1")
    if not os.path.exists(a.data):
        sys.exit(f"{a.data} not found. Build it first: python data_prep/make_chat_data_v3.py")
    rows, stats = select(read_jsonl(a.data), a.keep, a.strict, a.seed)
    emvryx_count = len(rows)
    if a.general:
        if not 0 <= a.general_share < 1:
            sys.exit("--general-share must be from 0 up to (not including) 1")
        rows = mix_general(rows, read_jsonl(a.general), a.general_share, a.seed)
        print(f"general lessons: {len(rows) - emvryx_count:,} added to {emvryx_count:,} Emvryx lessons (identity, honesty and corrections are all in the Emvryx part)")
    if a.thinking:
        rows = mix_thinking(rows, read_jsonl(a.thinking), a.thinking_share, a.seed)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"read {stats['read']:,}; duplicates {stats['duplicates']:,}; dropped for style {sum(stats['style_dropped'].values()):,} {stats['style_dropped'] or ''}")
    print("kept by kind: " + ", ".join(f"{k} {v:,}/{stats['available_by_kind'].get(k, 0):,}" for k, v in sorted(stats["kept_by_kind"].items())))
    print(f"wrote {len(rows):,} lessons to {a.out}" + (f" (including thinking lessons)" if a.thinking else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
