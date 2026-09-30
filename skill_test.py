"""
skill_test.py - Does the skill pack actually help? The same questions with and without it.

WHAT THIS FILE DOES
    Asks every question in eval/skills/<skill>.jsonl twice: once with the plain chat model, once with the
    skill pack switched on, and checks each answer against the skill's format rules. For the Study helper:

        quick check   ends with a "Quick check: ...?" question for the student
        example       gives an example or numbered steps
        length        40-300 words (explains, but doesn't ramble)
        finished      ends properly instead of running out of room

    It also checks the Beta router: does each message go to the right pack (or to none: "hi", a printer
    question, a poem)? The pack passes when it beats the plain model on the format rules; the test sheet
    (evaluate.py with --skill) checks it didn't make everyday answers worse.

    Report: <ckpt_dir>/skills/<skill>_test.md (every answer side by side, to read yourself).

Usage:
    python skill_test.py --version v3 --skill study
    python skill_test.py --version v3 --skill study --router_only      (no model needed)
"""
import argparse
import json
import os
import re

import torch

WORDS = re.compile(r"\S+")


def study_checks(text, finished):
    """{rule: passed} for one Study helper answer."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    low = text.lower()
    quick = any(l.lower().startswith("quick check") and "?" in l for l in lines[-2:]) if lines else False
    example = ("for example" in low or "example:" in low or "for instance" in low
               or sum(bool(re.match(r"^(\d+[.)]|step \d)", l.lower())) for l in lines) >= 2)
    n = len(WORDS.findall(text))
    return {"quick check": quick, "example": example, "length": 40 <= n <= 300, "finished": finished}


CHECKS = {"study": study_checks}


def router_report(tests, available):
    """(right, total, [(prompt, expected, got)]) for the router on the test sheet."""
    from skills import route
    wrong, right = [], 0
    for t in tests:
        got = route(t["prompt"], available)
        exp = t.get("route")
        if got == exp:
            right += 1
        else:
            wrong.append((t["prompt"], exp, got))
    return right, len(tests), wrong


def summarize(results):
    """{rule: share passed} over [{rule: bool}]."""
    rules = results[0].keys() if results else []
    return {r: sum(x[r] for x in results) / len(results) for r in rules}


def main():
    from config import add_version_arg, get_version
    from skills import SKILLS, load_pack, pack_path
    p = argparse.ArgumentParser()
    add_version_arg(p)
    p.add_argument("--skill", required=True, choices=list(CHECKS))
    p.add_argument("--ckpt", default=None, help="the chat model (default: <ckpt_dir>/chat.pt)")
    p.add_argument("--tokens", type=int, default=320)
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--repetition_penalty", type=float, default=1.15)
    p.add_argument("--router_only", action="store_true")
    p.add_argument("--any_base", action="store_true", help="use the pack even if it was trained on another chat.pt")
    a = p.parse_args()
    V = get_version(a.version)
    with open(os.path.join("eval", "skills", f"{a.skill}.jsonl"), encoding="utf-8") as f:
        tests = [json.loads(l) for l in f if l.strip()]
    right, total, wrong = router_report(tests, [a.skill])
    print(f"router: {right}/{total} messages sent to the right place")
    for prompt, exp, got in wrong:
        print(f"  {prompt!r}: expected {exp}, got {got}")
    if a.router_only:
        return

    from chat import build_prompt, special_ids
    from lora import set_lora_enabled
    from model import load_checkpoint
    from tokenizer import BPETokenizer
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, _ = load_checkpoint(a.ckpt or os.path.join(V.ckpt_dir, "chat.pt"), device)
    tok = BPETokenizer.load(os.path.join(V.data_dir, "tokenizer.json"))
    _, _, eot = special_ids(tok)
    pack = load_pack(model, pack_path(V.ckpt_dir, a.skill), strict_base=not a.any_base)
    check = CHECKS[a.skill]
    skill_tests = [t for t in tests if t.get("route") == a.skill]
    rows = {"plain": [], "pack": []}
    answers = []
    for i, t in enumerate(skill_tests):
        ids = build_prompt(tok, [{"role": "user", "content": t["prompt"]}], model.cfg.max_seq_len - a.tokens)
        pair = {}
        for mode in ("plain", "pack"):
            set_lora_enabled(model, mode == "pack")
            torch.manual_seed(1000 + i)                      # same randomness for both, so it's a fair comparison
            idx = torch.tensor([ids], device=device)
            out = model.generate(idx, a.tokens, a.temperature, 50, stop_id=eot,
                                 repetition_penalty=a.repetition_penalty)
            new = out[0, idx.size(1):].tolist()
            finished = bool(new) and new[-1] == eot
            text = tok.decode(new).replace("<|endoftext|>", "").strip()
            rows[mode].append(check(text, finished))
            pair[mode] = text
        answers.append((t["prompt"], pair))
        print(f"{i + 1}/{len(skill_tests)} done", flush=True)

    plain, packed = summarize(rows["plain"]), summarize(rows["pack"])
    lines = [f"# {pack['title']} ({pack.get('status')}) on {V.name}", "",
             f"Router: {right}/{total} right.", "", "| Rule | Plain chat model | With the pack |", "|---|---|---|"]
    for r in plain:
        lines.append(f"| {r} | {plain[r] * 100:.0f}% | {packed[r] * 100:.0f}% |")
    avg_plain, avg_pack = sum(plain.values()) / len(plain), sum(packed.values()) / len(packed)
    verdict = ("PASS: the pack follows the skill's format better" if avg_pack > avg_plain + 0.1
               else "NOT YET: the pack doesn't clearly beat the plain model (more lessons, another epoch, or rank 32)")
    lines += ["", f"**{verdict}** (average {avg_plain * 100:.0f}% -> {avg_pack * 100:.0f}%)", ""]
    print("\n".join(lines))
    for prompt, pair in answers:
        lines += [f"## {prompt}", "", "**Plain:**", "", pair["plain"], "", "**With the pack:**", "", pair["pack"], ""]
    report = os.path.join(V.ckpt_dir, "skills", f"{a.skill}_test.md")
    with open(report, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"every answer side by side: {report}")
    print(f"also check everyday answers didn't get worse:  python evaluate.py --version {V.name} --skill {a.skill}")


if __name__ == "__main__":
    main()
