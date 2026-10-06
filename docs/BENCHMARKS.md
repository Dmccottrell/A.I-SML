# Benchmarks: what we measure, what we can add, and what each needs

Numbers marked "(memory)" are published figures I recalled, not ours. Nothing in the "not run" columns has been measured. Public benchmarks are scored with different prompts and settings by different people, so a number is only comparable with another run of the **same tool and settings**: that is why `bench_open.py` runs the plain base and our tuned model side by side.

## 1. What we have measured so far
| Model | HellaSwag | Identity sheet (16) | Lookup sheet (41) | Rules sheet (30) | Test sheet (20) |
|---|---|---|---|---|---|
| Ember 2 (v2) | 28.4% (full) | n/a | not run | not run | 18/20 |
| Flare 2 (v3) | 36.2% pretrained, 34.8% after chat tuning (full) | n/a | 26-29 (with Wikipedia notes) | 10-11 | not run |
| Flare 2.5 | 67.2% (2,000-question sample; plain Qwen 2.5 1.5B 65.6%) | 16/16 | not run | not run | not run |
| Equinox 2, Solstice 2, Apogee 2 | pending | pending | pending | pending | pending |
Tools: `exam.py` / `exam_open.py` (HellaSwag), `evaluate.py` / `evaluate_open.py` (our sheets, `eval/*.jsonl`).

## 2. Public knowledge, reasoning and code benchmarks: `bench_open.py` (lm-evaluation-harness 0.4.13)
`python bench_open.py --model flare-2.5 --suite core --limit 200` (a fast check), then without `--limit` for the real number. It runs the plain base and base + our adapter and prints the difference.

| Suite | Task name in the harness | Type and metric | What it tests | Notes |
|---|---|---|---|---|
| core | `arc_challenge` | 4-choice, acc_norm | Multi-hop science reasoning | |
| core | `winogrande` | 2-choice, acc | Adversarial commonsense (pronouns) | |
| core | `mmlu` | 4-choice, 5-shot, acc | 57 subjects of knowledge | about 14,000 questions: slow |
| core | `gsm8k_cot` | 8-shot chain of thought, exact match | Grade-school maths | writes long answers: slow |
| core | `truthfulqa_mc2` | multi-select, probability | Resisting common falsehoods | |
| hard | `mmlu_pro` | 10-choice, accuracy | Harder, reasoning-heavy MMLU | about 12,000 questions |
| hard | `leaderboard_gpqa_diamond` | 4-choice, acc_norm | Expert-level science (198 questions) | gated dataset: log in to Hugging Face and accept the terms |
| hard | `ifeval` | rule-checked generation, strict accuracy | Following verifiable instructions | |
| hard | `leaderboard_math_hard` | competition maths, exact match | Level 5 maths, final boxed answer | small models score very low: expected |
| hard | `leaderboard_musr` | accuracy | Multi-step reasoning in long stories | |
| hard | `leaderboard_bbh` | 3-shot, exact match / acc_norm | BIG-Bench Hard logic and algorithms | |
| code | `humaneval` | Python generation, pass@1 | Writing functions that pass unit tests | **runs the model's code** |
| code | `mbpp` | Python generation, pass@1 | Writing Python from a description | **runs the model's code** |
Names differ from the common ones in a few places (`openai_humaneval` is `humaneval`; MATH, MuSR, BBH and GPQA are the `leaderboard_*` versions): they were checked against the installed tool, not from memory. Run the code suite only with `--allow-code` and only on the cloud machine, never on your PC.
Rough cost (an estimate, not measured): `--limit 200` on a 1.5B model takes minutes; the full core suite on a 1.5B to 8B model is probably under an hour each on the 5090, the hard suite longer. Each costs a few cents to a few dollars at about $0.51 an hour.
What to expect: a small fine-tune should leave these scores about where the base is (Flare 2.5 on HellaSwag: +1.6). GPQA, MATH level 5 and MuSR will be low for 1.5B to 14B models; that is normal, so look at the **difference** between base and tuned.

## 3. Agentic coding benchmarks (not built; plan)
These test an agent that works in a real repository or terminal, which is what VryxCode is for ([VRYXCODE.md](VRYXCODE.md)). None can run until VryxCode has been proven on a real model, and most need Docker.

| Benchmark | What it is | Resolved by | What it needs |
|---|---|---|---|
| **SWE-bench Verified** | 500 human-checked real GitHub issues in 12 Python projects | the agent's patch passes the hidden tests without breaking others | Docker (one environment image per project, tens to hundreds of GB), a mode where the agent produces a patch for a repo checked out at the right commit, many model calls per issue |
| **SWE-bench Lite** | 300 smaller, steadier issues | same | same, but smaller and cheaper: the first one to try |
| **SWE-bench Pro** | harder multi-file, multi-language fixes in larger code bases | same | same, plus more languages and bigger repos |
| **Terminal-Bench** | tasks in a live Linux shell (set-up, build fixes, dependency conflicts) | the final terminal state is checked | Docker and the benchmark's own harness; our sandbox allows only a short list of programs, so it would need widening |
| **Aider benchmark** | 133 Exercism Python exercises: edit files so the tests pass, two tries | percent passing, and percent with valid edits | the aider benchmark harness (it runs in Docker); the cheapest of these |
| **LiveCodeBench** | fresh competitive-programming problems with test execution | pass@1 | its own harness (not in lm-evaluation-harness) and a place to run code safely |

**Honest expectations (not measured):** the published scores for these come from large agents. Models of 4B to 14B usually resolve far fewer issues, so treat any number as a trend to track, not a target. Standard Vast instances are containers and often cannot run Docker (from memory): check before planning to run SWE-bench there; a machine that supports Docker, or a VM-type instance, may be needed.
**Order I'd do them in:** (1) the `core` suite, (2) `code` suite, (3) the Aider benchmark, (4) LiveCodeBench, (5) SWE-bench Lite and Terminal-Bench, (6) Verified and Pro. Before 3 to 6: give VryxCode a patch mode and run it against a few scripted tasks first.

## 4. Cautions
- Don't compare our numbers with a published table unless the tool, prompts, few-shot count and chat template match.
- Some test sets leak into training data: a big jump on one benchmark with no gain elsewhere is suspect.
- One run is a sample. Use `--limit` for speed, then the full set for any number you will quote.
