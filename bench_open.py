"""
bench_open.py - Run the standard public benchmarks (EleutherAI's lm-evaluation-harness) on an open model, plain base versus base + our LoRA adapter.

WHAT THIS FILE DOES
    exam_open.py scores HellaSwag; evaluate_open.py runs our own test sheets. This runs the well-known public tests so Emvryx's numbers can sit next to published ones:
      core   ARC-Challenge, WinoGrande, MMLU, GSM8K, TruthfulQA
      hard   MMLU-Pro, GPQA-Diamond, IFEval, MATH level 5, MuSR, BBH
      code   HumanEval, MBPP   (they RUN the model's code: only with --allow-code, only in a sandbox such as the cloud machine)
    It builds the `lm_eval` commands, runs them (or just prints them with --dry-run), reads the results and prints one table: base, tuned, difference.
    The task names are the ones in lm-evaluation-harness 0.4.13 (`python -m lm_eval ls tasks`); if you use another version, check them.

Usage:  python bench_open.py --model flare-2.5 --suite core --limit 200 --dry-run      (see what it would run)
        python bench_open.py --model flare-2.5 --suite core --limit 200                (a fast check: 200 questions per task)
        python bench_open.py --model equinox-2 --suite core,hard --tuned-only          (full, only our tuned model)
        python bench_open.py --model solstice-2 --suite code --allow-code
    Needs:  pip install lm_eval peft datasets      (GPQA also needs a Hugging Face login and accepting the dataset's terms)
"""
import argparse
import json
import os
import subprocess
import tempfile
import sys

# task -> (what it tests, metrics to read in order of preference, run with the chat template?, note)
TASKS = {
    "arc_challenge": ("Multi-hop science reasoning (filters out questions that word overlap can answer)", ["acc_norm,none", "acc,none"], False, ""),
    "winogrande": ("Adversarial commonsense: pronoun disambiguation", ["acc,none"], False, ""),
    "mmlu": ("Broad knowledge across 57 subjects (5-shot)", ["acc,none"], False, "about 14,000 questions: slow without --limit"),
    "gsm8k_cot": ("Grade-school maths, multi-step (8-shot chain of thought)", ["exact_match,strict-match", "exact_match,flexible-extract"], True, "writes long answers: slow"),
    "truthfulqa_mc2": ("Resisting common falsehoods and misconceptions", ["acc,none"], False, ""),
    "mmlu_pro": ("Harder MMLU: 10 choices, reasoning-heavy", ["exact_match,custom-extract", "acc,none"], True, "about 12,000 questions: slow"),
    "leaderboard_gpqa_diamond": ("Expert-level science written to defeat web search (198 questions)", ["acc_norm,none", "acc,none"], False, "gated dataset: log in to Hugging Face and accept its terms"),
    "ifeval": ("Following verifiable instructions (word limits, casing, forbidden words, JSON)", ["prompt_level_strict_acc,none", "inst_level_strict_acc,none"], True, ""),
    "leaderboard_math_hard": ("Competition maths, level 5, final boxed answer", ["exact_match,none"], True, "small models score very low: expected"),
    "leaderboard_musr": ("Multi-step reasoning inside long narratives", ["acc_norm,none", "acc,none"], False, ""),
    "leaderboard_bbh": ("BIG-Bench Hard: algorithmic and logic tasks (3-shot)", ["acc_norm,none", "acc,none"], False, ""),
    "humaneval_instruct": ("Writing Python functions, checked by unit tests (pass@1; the chat-model version of HumanEval)", ["pass@1,create_test", "pass@1,none"], True, "RUNS model-written code"),
    "mbpp": ("Writing Python from a description, checked by tests (pass@1)", ["pass_at_1,none", "pass@1,none"], True, "RUNS model-written code"),
}
SUITES = {
    "core": ["arc_challenge", "winogrande", "mmlu", "gsm8k_cot", "truthfulqa_mc2"],
    "hard": ["mmlu_pro", "leaderboard_gpqa_diamond", "ifeval", "leaderboard_math_hard", "leaderboard_musr", "leaderboard_bbh"],
    "code": ["humaneval_instruct", "mbpp"],
}
CODE_TASKS = {"humaneval_instruct", "mbpp"}
ALIASES = {"humaneval": "humaneval_instruct"}      # plain `humaneval` gives a chat model 0%: it expects a bare code completion, not a chat reply
FEWSHOT = {"mmlu": 5}


def resolve_tasks(suites):
    """Task names for a comma-separated list of suites and/or task names, in order, without repeats."""
    out = []
    for item in [ALIASES.get(s.strip(), s.strip()) for s in suites.split(",") if s.strip()]:
        names = SUITES.get(item) or ([item] if item in TASKS else None)
        if names is None:
            raise ValueError(f"{item!r} is not a suite ({', '.join(SUITES)}) or a known task ({', '.join(TASKS)})")
        out += [n for n in names if n not in out]
    return out


def build_commands(model_id, tasks, adapter=None, limit=None, output=None, device=None, python=None, allow_code=False):
    """[(chat template used, env additions, argv)]: one lm_eval run per group (plain tasks, chat-template tasks)."""
    if set(tasks) & CODE_TASKS and not allow_code:
        raise ValueError("humaneval and mbpp run code the model wrote: add --allow-code, and only do that in a sandbox (the cloud machine)")
    model_args = f"pretrained={model_id},dtype=bfloat16" + (f",peft={adapter}" if adapter else "")
    commands = []
    for chat in (False, True):
        group = [t for t in tasks if TASKS[t][2] == chat]
        if not group:
            continue
        argv = [python or sys.executable, "-m", "lm_eval", "--model", "hf", "--model_args", model_args, "--tasks", ",".join(group),
                "--batch_size", "auto"]
        if chat:
            argv += ["--apply_chat_template"]
        if limit:
            argv += ["--limit", str(limit)]
        if device:
            argv += ["--device", device]
        if output:
            argv += ["--output_path", output]
        for t in group:
            if t in FEWSHOT and len(group) == 1:
                argv += ["--num_fewshot", str(FEWSHOT[t])]
        env = {}
        if set(group) & CODE_TASKS:
            env["HF_ALLOW_CODE_EVAL"] = "1"
            argv += ["--confirm_run_unsafe_code"]
        commands.append((chat, env, argv))
    return commands


def pick(results, task):
    """(metric name, value as a fraction) for a task from lm_eval's results dict, or None."""
    row = results.get(task)
    if not row:
        return None
    for key in TASKS[task][1]:
        if isinstance(row.get(key), (int, float)):
            return key, float(row[key])
    for key, value in row.items():
        if isinstance(value, (int, float)) and "stderr" not in key:
            return key, float(value)
    return None


def load_results(path):
    """The results of one lm_eval output folder (it writes results_*.json inside, maybe in a sub-folder per model)."""
    found = []
    for root, _, files in os.walk(path):
        found += [os.path.join(root, f) for f in files if f.startswith("results") and f.endswith(".json")]
    merged = {}
    for f in sorted(found):
        with open(f, encoding="utf-8") as fh:
            merged.update(json.load(fh).get("results", {}))
    return merged


def table(tasks, base, tuned):
    """Markdown rows: task, base, tuned, difference (in points)."""
    lines = ["| Benchmark | What it tests | Plain base | Tuned | Difference |", "|---|---|---|---|---|"]
    for t in tasks:
        b = pick(base, t) if base else None
        u = pick(tuned, t) if tuned else None
        fmt = lambda x: f"{x[1] * 100:.1f}%" if x else "-"
        diff = f"{(u[1] - b[1]) * 100:+.1f}" if (b and u) else "-"
        lines.append(f"| {t} | {TASKS[t][0]} | {fmt(b)} | {fmt(u)} | {diff} |")
    return "\n".join(lines)


def neutral(argv, base):
    """The same command with paths made absolute, so it can run from another folder. lm_eval must NOT run from the project folder: `python -m`
    puts the current folder first on the import path, and our evaluate.py / config.py then shadow the libraries of the same name (HumanEval and
    MBPP load Hugging Face's `evaluate`, and failed with our argument parser's usage message)."""
    out = list(argv)
    for i, a in enumerate(out):
        if a == "--output_path" and i + 1 < len(out):
            out[i + 1] = os.path.abspath(os.path.join(base, out[i + 1]))
        if a == "--model_args" and i + 1 < len(out):
            parts = []
            for kv in out[i + 1].split(","):
                key, _, val = kv.partition("=")
                if key == "peft" and val and os.path.exists(os.path.join(base, val)):
                    kv = "peft=" + os.path.abspath(os.path.join(base, val))
                parts.append(kv)
            out[i + 1] = ",".join(parts)
    return out


def run(argv, env_extra):
    env = {**os.environ, **env_extra}
    env.pop("PYTHONPATH", None)
    here = os.getcwd()
    argv = neutral(argv, here)
    print("+", " ".join(argv), flush=True)
    with tempfile.TemporaryDirectory(prefix="lm_eval_") as work:
        return subprocess.run(argv, env=env, cwd=work).returncode


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default="flare-2.5", help="a preset, a Hugging Face id, or a local folder")
    p.add_argument("--adapter", default=None, help="our LoRA adapter (default: found from the preset name)")
    p.add_argument("--suite", default="core", help=f"{', '.join(SUITES)} or task names, comma separated")
    p.add_argument("--limit", type=int, default=None, help="questions per task (a fast check; scores are rougher)")
    p.add_argument("--tuned-only", action="store_true", help="skip the plain base")
    p.add_argument("--base-only", action="store_true", help="only the plain base")
    p.add_argument("--allow-code", action="store_true", help="allow humaneval / mbpp, which RUN the model's code")
    p.add_argument("--out", default="logs/bench", help="folder for lm_eval's raw results and the report")
    p.add_argument("--dry-run", action="store_true", help="print the commands and stop")
    a = p.parse_args(argv)

    import open_models
    from exam_open import find_adapter
    preset, cfg = open_models.resolve(a.model)
    model_id = cfg["hf"] if preset and not os.path.isdir(a.model) else a.model
    name = preset or os.path.basename(model_id.rstrip("/\\")).lower()
    tasks = resolve_tasks(a.suite)
    adapter = None if a.base_only else (a.adapter or find_adapter(name, model_id))
    if not a.base_only and not adapter:
        sys.exit("no adapter found for the tuned model: pass --adapter <folder>, or use --base-only")
    plans = []
    if not a.tuned_only:
        plans.append(("base", None))
    if not a.base_only:
        plans.append(("tuned", adapter))
    results = {}
    for tag, ad in plans:
        out_dir = os.path.join(a.out, name, tag)
        for chat, env, argv_ in build_commands(model_id, tasks, ad, a.limit, out_dir, allow_code=a.allow_code):
            if a.dry_run:
                print("+", " ".join(f"{k}={v}" for k, v in env.items()), " ".join(argv_))
            elif run(argv_, env) != 0:
                sys.exit(f"lm_eval failed for the {tag} model ({'chat' if chat else 'plain'} tasks): see the output above")
        if not a.dry_run:
            results[tag] = load_results(out_dir)
    if a.dry_run:
        return 0
    text = f"# {name}: {', '.join(tasks)}" + (f" (first {a.limit} questions of each)" if a.limit else "") + "\n\n" + table(tasks, results.get("base"), results.get("tuned"))
    print("\n" + text)
    os.makedirs(os.path.join(a.out, name), exist_ok=True)
    with open(os.path.join(a.out, name, "report.md"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
