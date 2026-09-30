"""
make_skill_data.py - Turn the teacher's lessons into a skill pack's training file.

WHAT THIS FILE DOES
    Reads <teacher dir>/<skill>.jsonl (make_teacher_data.py --task <skill>) and writes chat
    conversations for train_skill.py:

        <data_dir>/skills/<skill>/train.jsonl   ~95%
        <data_dir>/skills/<skill>/val.jsonl     ~5% (never trained on: shows if the pack really learned)

    Teacher assistant examples become one chat each: the teacher's request and the finished document.
    Study helper lessons become two kinds of chats:
      * the question and the explained answer ending in "Quick check: ...?"
      * the same, plus the student's try and the helper's feedback (right or wrong)
    Some of the general chat lessons (<data_dir>/chat.jsonl) are mixed in ("replay", 20% by default) so
    the pack keeps the model's everyday manners: if the router picks it by mistake, it still chats normally.

Usage:
    python make_skill_data.py --version v3 --skill study
    python make_skill_data.py --version v3 --skill study --replay 0.3
"""
import argparse
import json
import os
import random

from config import add_version_arg, get_version

BUILDERS = {}


def builder(name):
    def wrap(fn):
        BUILDERS[name] = fn
        return fn
    return wrap


@builder("study")
def study_chats(lessons, rng, followup=0.5):
    """Chats from study lessons: every lesson gives one chat, about half of them with the quick-check follow-up."""
    out = []
    for rec in lessons:
        msgs = [{"role": "user", "content": rec["question"]}, {"role": "assistant", "content": rec["answer"]}]
        if rng.random() < followup:
            msgs += [{"role": "user", "content": rec["student_reply"]},
                     {"role": "assistant", "content": rec["feedback"]}]
        out.append({"messages": msgs, "kind": "study_followup" if len(msgs) > 2 else "study"})
    return out


@builder("teacher")
def teacher_chats(lessons, rng):
    """Chats from teacher-assistant examples: the teacher's request and the finished document."""
    return [{"messages": [{"role": "user", "content": rec["request"]}, {"role": "assistant", "content": rec["answer"]}],
             "kind": f"teacher_{rec['spec']['type']}"} for rec in lessons]


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def replay_chats(chat_path, n, rng):
    """n general chat lessons (to keep everyday manners). Lessons with notes are kept: lookups must keep working."""
    if n <= 0 or not os.path.exists(chat_path):
        return []
    chats = read_jsonl(chat_path)
    rng.shuffle(chats)
    return [{**c, "kind": "replay"} for c in chats[:n]]


def build(skill, lessons, chat_path, rng, replay=0.2, val_frac=0.05):
    """(train, val) lists of chats. Validation holds only skill chats (it measures the skill)."""
    if skill not in BUILDERS:
        raise SystemExit(f"no data builder for {skill!r} yet (have: {', '.join(BUILDERS)})")
    skill_chats = BUILDERS[skill](lessons, rng)
    rng.shuffle(skill_chats)
    n_val = max(1, int(len(skill_chats) * val_frac)) if len(skill_chats) > 1 else 0
    val, train = skill_chats[:n_val], skill_chats[n_val:]
    train += replay_chats(chat_path, int(len(train) * replay / max(1e-9, 1 - replay)), rng)
    rng.shuffle(train)
    return train, val


def main():
    p = argparse.ArgumentParser()
    add_version_arg(p)
    p.add_argument("--skill", required=True)
    p.add_argument("--teacher_dir", default=None, help="default: <data_dir>/teacher, else v3's (lessons are shared)")
    p.add_argument("--replay", type=float, default=0.2, help="share of general chat lessons mixed in")
    p.add_argument("--seed", type=int, default=5)
    a = p.parse_args()
    V = get_version(a.version)
    tdir = a.teacher_dir or os.path.join(V.data_dir, "teacher")
    if not os.path.exists(os.path.join(tdir, f"{a.skill}.jsonl")):
        tdir = os.path.join(get_version("v3").data_dir, "teacher")      # later versions reuse v3's lessons
    src = os.path.join(tdir, f"{a.skill}.jsonl")
    if not os.path.exists(src):
        raise SystemExit(f"no lessons at {src}: run  python make_teacher_data.py --task {a.skill} --n 3000  first")
    lessons = read_jsonl(src)
    rng = random.Random(a.seed)
    train, val = build(a.skill, lessons, os.path.join(V.data_dir, "chat.jsonl"), rng, a.replay)
    out = os.path.join(V.data_dir, "skills", a.skill)
    os.makedirs(out, exist_ok=True)
    for name, rows in (("train", train), ("val", val)):
        with open(os.path.join(out, f"{name}.jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    kinds = {}
    for r in train:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    print(f"{len(lessons):,} lessons -> {out}: {len(train):,} training chats {kinds}, {len(val):,} validation chats")


if __name__ == "__main__":
    main()
