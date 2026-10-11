"""
thinking_check.py - Did tuning keep the model's thinking intact? Same problems, thinking on and off, plain base versus tuned.

    # for each model, one after the other (a llama-server of that model on port 8099):
    python evaluation/thinking_check.py --server http://127.0.0.1:8099 --label base --n 140
    python evaluation/thinking_check.py --server http://127.0.0.1:8099 --label tuned --n 140
    # then compare:
    python evaluation/thinking_check.py --compare logs/thinking-base.json logs/thinking-tuned.json

Problems are made by code (data_prep/reasoning_problems.py) with a seed different from the lessons', so the model has not seen them. Every problem has one
checked numeric answer. 140 problems wobble by about 4 points, so only a bigger drop counts. Run it with nothing else using the card, never during training.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "data_prep"))
import argparse
import json
import time

import reasoning_problems as RP

WOBBLE = 4.0            # percentage points: a thinking score that drops by more than this against the base means the tuning wore it down


def run(server, n, seed, label, ask=RP.ask, modes=(True, False)):
    problems = RP.make_problems(n, seed)
    out = {"label": label, "n": n, "seed": seed, "modes": {}}
    for thinking in modes:
        right, toks, errors, t0 = 0, 0, 0, time.time()
        by_kind = {}
        for p in problems:
            try:
                r = ask(server, p["question"], thinking, 0.3, 3000)
            except Exception:                                    # noqa: BLE001
                errors += 1
                continue
            ok = RP.check_answer(p, r["answer"])
            right += ok
            toks += r["tokens"]
            k = by_kind.setdefault(p["kind"], [0, 0])
            k[0] += ok
            k[1] += 1
        done = n - errors
        out["modes"]["thinking" if thinking else "direct"] = {
            "accuracy": round(100 * right / max(1, done), 1), "answered": done, "errors": errors, "avg_tokens": round(toks / max(1, done)),
            "seconds": round(time.time() - t0), "by_kind": {k: round(100 * v[0] / v[1], 1) for k, v in by_kind.items()}}
    return out


def compare(base, tuned):
    """(verdict text, needs_thinking_lessons)"""
    lines, needs = [f"{'':<10}{'base':>10}{'tuned':>10}{'change':>10}   (accuracy %, then average tokens)"], False
    for mode in ("thinking", "direct"):
        if mode not in base["modes"] or mode not in tuned["modes"]:
            continue
        b, t = base["modes"][mode], tuned["modes"][mode]
        d = round(t["accuracy"] - b["accuracy"], 1)
        lines.append(f"{mode:<10}{b['accuracy']:>10}{t['accuracy']:>10}{d:>+10}   tokens {b['avg_tokens']} -> {t['avg_tokens']}")
        if mode == "thinking" and d < -WOBBLE:
            needs = True
    if needs:
        lines.append(f"\nThe tuned model thinks WORSE than the base (more than {WOBBLE:g} points down): add thinking lessons "
                     "(data_prep/make_thinking_lessons.py, about 10% of the mix) and tune again, or lower the learning rate.")
    else:
        lines.append(f"\nThinking is intact (within {WOBBLE:g} points of the base). Thinking lessons are not needed for this model.")
    if "direct" in base["modes"] and "direct" in tuned["modes"] and tuned["modes"]["direct"]["accuracy"] < base["modes"]["direct"]["accuracy"] - WOBBLE:
        lines.append(f"Warning: answers without thinking got worse by more than {WOBBLE:g} points: check the lessons.")
    return "\n".join(lines), needs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="http://127.0.0.1:8099")
    ap.add_argument("--label", default="model")
    ap.add_argument("--n", type=int, default=140)
    ap.add_argument("--seed", type=int, default=777)
    ap.add_argument("--out", default=None, help="default: logs/thinking-<label>.json")
    ap.add_argument("--compare", nargs=2, metavar=("BASE.json", "TUNED.json"))
    a = ap.parse_args(argv)
    if a.compare:
        base, tuned = (json.load(open(p, encoding="utf-8")) for p in a.compare)
        text, needs = compare(base, tuned)
        print(text)
        return 2 if needs else 0
    res = run(a.server, a.n, a.seed, a.label)
    path = a.out or os.path.join("logs", f"thinking-{a.label}.json")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    for mode, m in res["modes"].items():
        print(f"{mode}: {m['accuracy']}% of {m['answered']} ({m['avg_tokens']} tokens each, {m['seconds']} s) {m['by_kind']}")
    print("saved", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
