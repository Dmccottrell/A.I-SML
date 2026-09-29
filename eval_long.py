"""
eval_long.py - Does the model really USE a long context? (the long-context tests)

WHAT THIS FILE DOES
    A model can accept 100,000 tokens and still ignore most of them. These tests check that it
    doesn't. The pass/fail rules are the table in docs/LONG_CONTEXT.md; this file applies them.

      needle      Hide a made-up fact ("The secret code for the vault is amber-falcon-4821.")
                  inside real text, at 10/25/50/75/90% of the way in, then ask for it back.
      multi       Two made-up facts about one person, hidden at different places; one question
                  needs both.
      code        A one-line function (def get_port_xxxx(): return 48213) hidden in the text; ask
                  what it returns.
      position    Loss on real text by position. If more context helps, the loss keeps falling
                  as we go further into a document; if it rises, the model is confused by length.

    They work on PRETRAINED models (no chat tuning): each question is a text the model must
    continue, answered greedily. The filler is real text from <data_dir>/val.bin (held out from
    training), or --filler_text FILE.

    WHEN TO RUN (see docs/LONG_CONTEXT.md)
      * baseline, before stretching:   python eval_long.py --version v3
      * during a stretch (quick):      python eval_long.py --version v3 --ckpt latest.pt --quick
      * after a stretch (the gate):    python eval_long.py --version v3 --seq_len 8192 --rope_theta 2000000
      * control (must FAIL):           the unstretched model at a longer length:
                                       python eval_long.py --version v3 --seq_len 8192 --control

Options:
    --lengths      lengths to test, comma separated (default: the model's own context length)
    --seq_len      make the model accept this many tokens (default: what the checkpoint was trained for)
    --rope_theta   RoPE base to use (default: what the checkpoint was trained with). A stretched
                   checkpoint must be tested with the same value it was stretched with.
    --tests        which tests: needle,multi,code,position (default: all)
    --trials       tries per depth (default 20)
    --quick        needle + position only, 5 tries per depth (for use during a run)
    --control      expect the needle test to FAIL (proves the test can tell a model that can't do it)
    --out          save the numbers as JSON
"""
import argparse
import json
import os
import random

import torch

DEPTHS = (0.10, 0.25, 0.50, 0.75, 0.90)
ANSWER_ROOM = 24            # tokens kept free after the question for the answer

# Pass/fail rules: the table in docs/LONG_CONTEXT.md
NEEDLE_PASS, NEEDLE_FAIL = 0.95, 0.90
MULTI_PASS, MULTI_FAIL = 0.80, 0.70
CODE_PASS, CODE_FAIL = 0.70, 0.60
LOSS_FALLING, LOSS_RISING = -0.02, 0.05      # change in loss, late text vs. the 20-30% mark

WORDS_A = ["amber", "silver", "crimson", "quiet", "brave", "lunar", "copper", "wild", "misty", "golden"]
WORDS_B = ["falcon", "harbor", "maple", "comet", "river", "lantern", "meadow", "anchor", "willow", "ember"]


def verdict(value, pass_at, fail_below):
    return "PASS" if value >= pass_at else ("FAIL" if value < fail_below else "BORDERLINE")


# ---------------- building the questions ----------------

def random_code(rng):
    return f"{rng.choice(WORDS_A)}-{rng.choice(WORDS_B)}-{rng.randint(1000, 9999)}"


def insert_at(ids, pieces):
    """Insert token lists into ids at the given fractional depths (0-1); returns the new list."""
    out, last = [], 0
    for depth, piece in sorted(pieces, key=lambda p: p[0]):
        cut = int(len(ids) * depth)
        out += ids[last:cut] + piece
        last = cut
    return out + ids[last:]


def needle_case(tok, filler, length, depth, rng):
    """(prompt ids, the code the model must write)"""
    code = random_code(rng)
    fact = tok.encode(f"\n\nThe secret code for the vault is {code}.\n\n", allow_special=False)
    ask = tok.encode("\n\nQuestion: What is the secret code for the vault?\nAnswer: The secret code for the vault is",
                     allow_special=False)
    room = length - ANSWER_ROOM - len(fact) - len(ask)
    return insert_at(filler[:room], [(depth, fact)]) + ask, code


def multi_case(tok, filler, length, depth, rng):
    """Two facts, one before and one after `depth`; the answer needs both. Returns (ids, [answers])."""
    number, town = str(rng.randint(1000, 9999)), rng.choice(WORDS_B) + "ford"
    f1 = tok.encode(f"\n\nMira's favorite number is {number}.\n\n", allow_special=False)
    f2 = tok.encode(f"\n\nMira's home town is {town}.\n\n", allow_special=False)
    ask = tok.encode("\n\nQuestion: What is Mira's favorite number and what is her home town?\n"
                     "Answer: Mira's favorite number is", allow_special=False)
    room = length - ANSWER_ROOM - len(f1) - len(f2) - len(ask)
    d1, d2 = max(0.02, depth - 0.15), min(0.98, depth + 0.15)
    return insert_at(filler[:room], [(d1, f1), (d2, f2)]) + ask, [number, town]


def code_case(tok, filler, length, depth, rng):
    name = "get_port_" + "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(4))
    value = str(rng.randint(10000, 99999))
    fn = tok.encode(f"\n\ndef {name}():\n    return {value}\n\n", allow_special=False)
    ask = tok.encode(f"\n\nQuestion: In the code above, what does {name}() return?\nAnswer: It returns",
                     allow_special=False)
    room = length - ANSWER_ROOM - len(fn) - len(ask)
    return insert_at(filler[:room], [(depth, fn)]) + ask, value


def random_window(filler_all, n, rng):
    start = rng.randint(0, max(0, len(filler_all) - n))
    return [int(t) for t in filler_all[start:start + n]]


# ---------------- running the tests ----------------

def run_case(answer_fn, make, tok, filler_all, length, depth, rng, trials, need_all=True):
    """Fraction of `trials` in which the answer contains the wanted text."""
    ok = 0
    for _ in range(trials):
        filler = random_window(filler_all, length, rng)
        ids, want = make(tok, filler, length, depth, rng)
        text = answer_fn(ids).lower()
        wants = want if isinstance(want, list) else [want]
        ok += all(w.lower() in text for w in wants)
    return ok / trials


def run_retrieval(name, make, answer_fn, tok, filler_all, length, trials, seed, pass_at, fail_below, out):
    rng = random.Random(seed)
    per_depth = {}
    for d in DEPTHS:
        per_depth[d] = run_case(answer_fn, make, tok, filler_all, length, d, rng, trials)
        print(f"    {name:<7} depth {int(d * 100):>2}%  {per_depth[d] * 100:5.0f}%", flush=True)
    worst = min(per_depth.values())
    v = verdict(worst, pass_at, fail_below)
    out[name] = {"per_depth": {str(k): v_ for k, v_ in per_depth.items()}, "worst": worst, "verdict": v}
    print(f"  {name}: worst depth {worst * 100:.0f}%  ->  {v}")
    return v


def position_buckets(losses, n=10):
    size = len(losses) // n
    return [sum(losses[i * size:(i + 1) * size]) / size for i in range(n)]


def position_verdict(buckets):
    """Compare the last quarter of the text with the 20-30% mark: is more context still helping?"""
    late = sum(buckets[-3:]) / 3
    change = late - buckets[2]
    if change <= LOSS_FALLING:
        return "PASS", change
    return ("FAIL" if change > LOSS_RISING else "WARN"), change


@torch.no_grad()
def token_losses(model, ids, device, chunk=2048):
    """Loss of every token of one sequence, computed in chunks so a 100K-token text doesn't need
    a 100K x vocabulary table at once."""
    x_ids = torch.tensor([ids[:-1]], device=device)
    y = torch.tensor(ids[1:], device=device)
    T = x_ids.size(1)
    x = model.embed(x_ids)
    cos, sin = model.rope_cos[:T].to(x.dtype), model.rope_sin[:T].to(x.dtype)
    for block in model.blocks:
        x = block(x, cos, sin, None)
    x = model.norm(x)[0]
    out = []
    for i in range(0, T, chunk):
        logits = model.lm_head(x[i:i + chunk]).float()
        out += torch.nn.functional.cross_entropy(logits, y[i:i + chunk], reduction="none").tolist()
    return out


def run_position(model, filler_all, length, windows, seed, device, out):
    rng = random.Random(seed)
    sums = None
    for _ in range(windows):
        losses = token_losses(model, random_window(filler_all, length, rng), device)
        b = position_buckets(losses)
        sums = b if sums is None else [a + c for a, c in zip(sums, b)]
    b = [s / windows for s in sums]
    v, change = position_verdict(b)
    print("    loss by position (each tenth of the text):  " + "  ".join(f"{x:.2f}" for x in b))
    print(f"  position: last quarter vs 20-30% mark {change:+.3f}  ->  {v}")
    out["position"] = {"buckets": b, "change": change, "verdict": v}
    return v


# ---------------- loading ----------------

def load_model(path, device, seq_len=None, rope_theta=None):
    """Like model.load_checkpoint, but can change the context length / RoPE base before building."""
    from model import ModelConfig, TinyLM
    ckpt = torch.load(path, map_location="cpu")
    cfg = dict(ckpt["config"])
    if seq_len:
        cfg["max_seq_len"] = seq_len
    if rope_theta:
        cfg["rope_theta"] = rope_theta
    model = TinyLM(ModelConfig(**cfg))
    model.load_state_dict(ckpt["model"])
    return model.to(device).eval()


def load_filler(V, path):
    import numpy as np
    from tokenizer import BPETokenizer
    tok = BPETokenizer.load(os.path.join(V.data_dir, "tokenizer.json"))
    if path:
        return tok, tok.encode(open(path, encoding="utf-8").read(), allow_special=False)
    val = os.path.join(V.data_dir, "val.bin")
    if not os.path.exists(val):
        raise SystemExit(f"no {val}; build the data first, or pass --filler_text FILE")
    eot = tok.special["<|endoftext|>"]
    ids = np.memmap(val, dtype=np.uint16, mode="r")
    return tok, [int(t) for t in ids[:8_000_000] if int(t) != eot]


def main():
    from config import add_version_arg, get_version
    from exam import final_weights
    p = argparse.ArgumentParser()
    add_version_arg(p)
    p.add_argument("--ckpt", default=None)
    p.add_argument("--lengths", default=None)
    p.add_argument("--seq_len", type=int, default=None)
    p.add_argument("--rope_theta", type=float, default=None)
    p.add_argument("--tests", default="needle,multi,code,position")
    p.add_argument("--trials", type=int, default=20)
    p.add_argument("--windows", type=int, default=4, help="documents averaged for the position test")
    p.add_argument("--quick", action="store_true")
    p.add_argument("--control", action="store_true")
    p.add_argument("--filler_text", default=None)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default=None)
    args = p.parse_args()
    V = get_version(args.version)
    tests = args.tests.split(",")
    if args.quick:
        tests, args.trials, args.windows = ["needle", "position"], 5, 2
    if args.control:
        tests = ["needle"]
    ckpt = args.ckpt or final_weights(V)
    if not os.path.isabs(ckpt) and not os.path.exists(ckpt):
        ckpt = os.path.join(V.ckpt_dir, ckpt)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = load_model(ckpt, device, args.seq_len, args.rope_theta)
    tok, filler_all = load_filler(V, args.filler_text)
    eot = tok.special["<|endoftext|>"]
    lengths = [int(x) for x in args.lengths.split(",")] if args.lengths else [model.cfg.max_seq_len]
    print(f"{V.name}: {ckpt}\ncontext {model.cfg.max_seq_len:,} tokens, RoPE base {model.cfg.rope_theta:,.0f}")

    def answer(ids):
        idx = torch.tensor([ids], device=device)
        out = model.generate(idx, 16, temperature=1.0, top_k=1, stop_id=eot)
        return tok.decode(out[0, idx.size(1):].tolist())

    results, failed = {}, False
    for length in lengths:
        if length > model.cfg.max_seq_len:
            print(f"\nlength {length:,}: skipped (the model only accepts {model.cfg.max_seq_len:,}; use --seq_len)")
            continue
        print(f"\n=== length {length:,} tokens ===")
        out, verdicts = {}, []
        if "needle" in tests:
            verdicts.append(run_retrieval("needle", needle_case, answer, tok, filler_all, length, args.trials,
                                          args.seed, NEEDLE_PASS, NEEDLE_FAIL, out))
        if "multi" in tests:
            verdicts.append(run_retrieval("multi", multi_case, answer, tok, filler_all, length, args.trials,
                                          args.seed, MULTI_PASS, MULTI_FAIL, out))
        if "code" in tests:
            verdicts.append(run_retrieval("code", code_case, answer, tok, filler_all, length, args.trials,
                                          args.seed, CODE_PASS, CODE_FAIL, out))
        if "position" in tests:
            verdicts.append(run_position(model, filler_all, length, args.windows, args.seed, device, out))
        results[length] = out
        if args.control:
            ok = out["needle"]["verdict"] == "FAIL"
            print("CONTROL: " + ("the needle test correctly FAILED for a model that was not stretched"
                                 if ok else "WARNING: the model passed without being stretched, so this test "
                                            "can't tell stretched from unstretched; check the setup"))
        else:
            bad = [v for v in verdicts if v == "FAIL"]
            soft = [v for v in verdicts if v in ("BORDERLINE", "WARN")]
            failed |= bool(bad)
            print(f"RESULT at {length:,}: " + ("FAILED (stop here)" if bad else
                  "PASSED, but some lines are borderline: look at them" if soft else "PASSED"))
    print("\n('nothing got worse' is checked separately: python exam.py --version " + args.version + ")")
    if args.out:
        json.dump(results, open(args.out, "w"), indent=2)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
