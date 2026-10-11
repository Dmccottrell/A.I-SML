"""
make_thinking_lessons.py - Make thinking lessons by letting a model solve problems whose answers can be checked, and keeping only the checked ones.

    # 1. start llama-server with the model you are about to tune (the plain Qwen3.5 gguf), with several slots so it can work on a few problems at once:
    #      llama-server -m qwen3.5-4b-q4_k_m.gguf -ngl 99 -c 16384 --parallel 4 --jinja --port 8099
    # 2. python data_prep/make_thinking_lessons.py --server http://127.0.0.1:8099 --n 3000

Why: Qwen3.5 thinks by default, and tuning it only on answers-without-thinking can wear that skill down. This keeps it in shape with lessons written in the
model's OWN style of reasoning (not copied from another AI), and a lesson is kept only when the final answer is right. Wrong or rambling solutions are
thrown away (rejection sampling). It is a small share of the lessons (about 10%) and is optional: evaluation/thinking_check.py says whether it is needed.

Output (default data\\v3\\thinking_lessons.jsonl): {"messages": [{"role": "user", "content": question, "thinking": true}, {"role": "assistant",
"content": "<think>\\n...\\n</think>\\n\\nthe answer"}], "kind": "thinking"}. Run it again to carry on: problems already in the file are skipped.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import reasoning_problems as RP
import style_check

MIN_THINK, MAX_THINK = 40, 6000          # characters of reasoning: shorter is not really thinking, longer is rambling


def make_lesson(problem, reply, tries_used=1):
    """A lesson dict from a model reply, or (None, why) when the reply is not good enough."""
    thinking, answer = reply["thinking"], reply["answer"]
    if not answer:
        return None, "no_answer"
    if not (MIN_THINK <= len(thinking) <= MAX_THINK):
        return None, "thinking_length"
    if not RP.check_answer(problem, answer):
        return None, "wrong_answer"
    row = {"messages": [{"role": "user", "content": problem["question"], "thinking": True},
                        {"role": "assistant", "content": "<think>\n" + thinking + "\n</think>\n\n" + answer}],
           "kind": "thinking", "problem": problem["id"], "checked": True}
    if any(sev == "hard" for _, sev in style_check.check_lesson(row)):
        return None, "style"
    return row, ""


def solve(problem, server, tries, temperature, max_tokens, ask=RP.ask):
    why = "no_try"
    for t in range(tries):
        try:
            reply = ask(server, problem["question"], True, temperature, max_tokens)
        except Exception as e:                                           # noqa: BLE001  (a busy or restarting server: count it and go on)
            why = "server_error: " + str(e)[:80]
            time.sleep(1)
            continue
        row, why = make_lesson(problem, reply, t + 1)
        if row:
            return row, ""
    return None, why


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="http://127.0.0.1:8099")
    ap.add_argument("--n", type=int, default=3000, help="problems to try")
    ap.add_argument("--tries", type=int, default=3, help="attempts per problem before giving up on it")
    ap.add_argument("--workers", type=int, default=4, help="problems at once (match llama-server --parallel)")
    ap.add_argument("--temperature", type=float, default=0.6)
    ap.add_argument("--max-tokens", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", default=os.path.join("data", "v3", "thinking_lessons.jsonl"))
    a = ap.parse_args(argv)
    done = set()
    if os.path.exists(a.out):
        with open(a.out, encoding="utf-8") as f:
            done = {json.loads(l).get("problem") for l in f if l.strip()}
    todo = [p for p in RP.make_problems(a.n, a.seed) if p["id"] not in done]
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    lock, kept, why_counts, t0 = threading.Lock(), 0, {}, time.time()

    def work(p):
        nonlocal kept
        row, why = solve(p, a.server, a.tries, a.temperature, a.max_tokens)
        with lock:
            if row:
                with open(a.out, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                kept += 1
            else:
                key = why.split(":")[0]
                why_counts[key] = why_counts.get(key, 0) + 1
            total = kept + sum(why_counts.values())
            if total % 25 == 0:
                print(f"{total}/{len(todo)} tried, {kept} kept ({(time.time() - t0) / 60:.1f} min)", flush=True)

    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        list(ex.map(work, todo))
    print(f"kept {kept:,} of {len(todo):,} new problems; thrown away: {why_counts or 'none'}; file: {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
