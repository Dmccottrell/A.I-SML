# Benchmarks: what we measure, what we can add, and what each needs

Numbers marked "(memory)" are published figures I recalled, not ours. Nothing in the "not run" columns has been measured. Public benchmarks are scored with different prompts and settings by different people, so a number is only comparable with another run of the **same tool and settings**: that is why `bench_open.py` runs the plain base and our tuned model side by side.

## 1. What we have measured so far
| Model | HellaSwag | Identity sheet (16) | Lookup sheet (41) | Rules sheet (30) | Test sheet (20) |
|---|---|---|---|---|---|
| Ember 2 (v2) | 28.4% (full) | n/a | not run | not run | 18/20 |
| Flare 2 (v3) | 36.2% pretrained, 34.8% after chat tuning (full) | n/a | 26-29 (with Wikipedia notes) | 10-11 | not run |
| Flare 2.5 | 67.2% (2,000-question sample; plain Qwen 2.5 1.5B 65.6%) | 16/16 | not run | not run | not run |
| Equinox 2 | 68.5% (2,000-question sample; plain Qwen3-4B 64.8%) | 16/16 | not run | not run | not run |
| Solstice 2 | 73.6% (2,000-question sample; plain Qwen3-8B 71.9%) | 16/16 | not run | not run | not run |
| Equinox 2, Solstice 2, Apogee 2 | pending | pending | pending | pending | pending |
Tools: `exam.py` / `exam_open.py` (HellaSwag), `evaluate.py` / `evaluate_open.py` (our sheets, `eval/*.jsonl`).

**One script runs the quick versions of everything on the cloud machine: `bash bench_all.sh`** (rules sheets, quick core and code benchmarks for Flare 2.5, Equinox 2 and Solstice 2, then the VryxCode exercise test on Qwen2.5-Coder-14B, Solstice 2 and Equinox 2). Estimated 4 to 6 hours, about $2 to $3; `MAX_HOURS=4` sets a spending guard. It has not been run yet.

**Rules sheet (30 questions: lookups, rules, honesty), Oct 6 2026, from `bench_all.sh` step 1 (tuned vs the plain open base):** Flare 2.5 **22/30 vs 23/30**, Equinox 2 **24/30 vs 7/30**, Solstice 2 **26/30 vs 9/30**. Read the Qwen3 gaps with care: the plain Qwen3 bases probably score so low partly because they do not follow our notes-and-rules format (and may write `<think>` reasoning first), which the sheet marks wrong (not checked); that measures how well the tuning teaches Emvryx's way of answering, not general intelligence. Flare 2.5 shows no gain on this sheet (-1), which is worth a look (one possible reason: Qwen 2.5 1.5B may already follow the format better than Qwen3; not checked). The next pings (core benchmarks, code, VryxCode exercises) are still running.
**Core public benchmarks, quick version (200 questions each, so about 3 to 4 points of wobble), Oct 6 2026, Flare 2.5 tuned / plain Qwen 2.5 1.5B base:** ARC-Challenge 47.5 / 46.0, WinoGrande 65.5 / 65.0, MMLU 61.3 / 62.5, GSM8K (chain of thought) **42.5 / 21.5**, TruthfulQA mc2 47.1 / 46.6. Everything is within the wobble except GSM8K, where the tuned model solves about twice as many maths word problems (likely because the lessons teach it to show steps). MMLU is 1.2 points lower, inside the wobble but worth watching on a full-size run. Solstice 2 is still running.

**Equinox 2 core (same setup, tuned / plain Qwen3-4B base):** ARC-Challenge 54.0 / 54.5, WinoGrande **74.0 / 66.5**, MMLU 72.4 / 71.4, GSM8K (chain of thought) **76.5 / 0.5**, TruthfulQA mc2 51.7 / 53.0. WinoGrande is +7.5, about twice the wobble, so probably real. The base's 0.5% on GSM8K is almost certainly a measurement problem, not real ability: plain Qwen3 starts with a long `<think>` block and likely runs out of answer room or fails the answer-format check, so do not quote "76.5 vs 0.5" as a gain; quote 76.5% for Equinox 2 and say the base was not fairly measured (re-run the base with thinking off, or a larger token limit, to compare).

**Code benchmarks (50 questions each, so about 5 to 7 points of wobble), Oct 6 2026, tuned / plain base:** MBPP: Flare 2.5 **38.0 / 40.0**, Equinox 2 **62.0 / 0.0**, Solstice 2 **66.0 / 0.0**. HumanEval (the chat version, `humaneval_instruct`): Solstice 2 **92.0 / 96.0**; Flare 2.5 and Equinox 2 read 0.0 / 0.0 only because they ran with the old plain `humaneval` task (invalid, see below), so they are to be re-run. The Qwen3 bases' 0.0% on MBPP is very likely the same measuring problem as their 0.5% on GSM8K (long hidden reasoning, failed answer format), so do not quote it as a gain. Solstice's HumanEval is 4 points under its base, which is 2 questions out of 50: inside the wobble, but worth re-checking at full size.

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
| code | `humaneval_instruct` | Python generation, pass@1 | Writing functions that pass unit tests | **runs the model's code** |
| code | `mbpp` | Python generation, pass@1 | Writing Python from a description | **runs the model's code** |
Names differ from the common ones in a few places (`openai_humaneval` is `humaneval_instruct` here: the plain `humaneval` task scored 0.0% on both Flare 2.5 and its base probably because chat models answer in a chat format that task cannot read (not confirmed); MATH, MuSR, BBH and GPQA are the `leaderboard_*` versions): they were checked against the installed tool, not from memory. Run the code suite only with `--allow-code` and only on the cloud machine, never on your PC.
Rough cost (an estimate, not measured): `--limit 200` on a 1.5B model takes minutes; the full core suite on a 1.5B to 8B model is probably under an hour each on the 5090, the hard suite longer. Each costs a few cents to a few dollars at about $0.51 an hour.
What to expect: a small fine-tune should leave these scores about where the base is (Flare 2.5 on HellaSwag: +1.6). GPQA, MATH level 5 and MuSR will be low for 1.5B to 14B models; that is normal, so look at the **difference** between base and tuned.

## 3. Agentic coding benchmarks
These test an agent that works in a real repository or terminal, which is what VryxCode is for ([VRYXCODE.md](VRYXCODE.md)). Two tools exist; **neither has run with a real model yet** (only with scripted stand-ins), and most of the real benchmarks need Docker.

**Built (Oct 2026), no Docker needed**
- **`bench_exercises.py`: an Aider-style exercise benchmark.** For each Exercism Python exercise, VryxCode edits the solution file; we run the tests; if they fail it gets the failing output and tries once more. Reports pass on the first try, pass after the second try, and how many attempts changed nothing (a sign the model could not use the tools). Get the exercises with `git clone https://github.com/exercism/python`, then `python bench_exercises.py --exercises python/exercises/practice --model solstice-2 --limit 20`. It is **not** the official Aider benchmark (that asks for diff-format edits and runs in Docker), so compare only our own runs with each other.
- **`vryx_swe.py`: SWE-bench-style predictions.** For each issue it copies the repository at the right commit, lets VryxCode edit it (never seeing the hidden tests), and saves the change as a patch in the SWE-bench predictions format. The official SWE-bench checker, on a machine with Docker, then scores it. Limit: our sandbox runs only Python and a short list of programs with no network, and a project's dependencies are usually missing, so the agent often cannot run the project's tests and edits from reading the code: treat the score as a floor.

**Still not built** (they need Docker or their own harness): the official SWE-bench scoring, Terminal-Bench, the official Aider harness, LiveCodeBench.

| Benchmark | What it is | Resolved by | What it needs |
|---|---|---|---|
| **SWE-bench Verified** | 500 human-checked real GitHub issues in 12 Python projects | the agent's patch passes the hidden tests without breaking others | Docker (one environment image per project, tens to hundreds of GB), a mode where the agent produces a patch for a repo checked out at the right commit, many model calls per issue |
| **SWE-bench Lite** | 300 smaller, steadier issues | same | same, but smaller and cheaper: the first one to try |
| **SWE-bench Pro** | harder multi-file, multi-language fixes in larger code bases | same | same, plus more languages and bigger repos |
| **Terminal-Bench** | tasks in a live Linux shell (set-up, build fixes, dependency conflicts) | the final terminal state is checked | Docker and the benchmark's own harness; our sandbox allows only a short list of programs, so it would need widening |
| **Aider benchmark** | 133 Exercism Python exercises: edit files so the tests pass, two tries | percent passing, and percent with valid edits | the aider benchmark harness (it runs in Docker); the cheapest of these |
| **LiveCodeBench** | fresh competitive-programming problems with test execution | pass@1 | its own harness (not in lm-evaluation-harness) and a place to run code safely |

**Honest expectations (not measured):** the published scores for these come from large agents. Models of 4B to 14B usually resolve far fewer issues, so treat any number as a trend to track, not a target. Standard Vast instances are containers and often cannot run Docker (from memory): check before planning to run SWE-bench there; a machine that supports Docker, or a VM-type instance, may be needed.
**Order I'd do them in:** (1) the `core` suite, (2) `code` suite, (3) `bench_exercises.py`, (4) `vryx_swe.py` on SWE-bench Lite with scoring on a Docker machine, (5) LiveCodeBench and Terminal-Bench, (6) Verified and Pro. Before any of them: connect VryxCode to a real trained model and try a few tasks by hand.

## 4. Long-context test: `bench_long.py`

Before spending anything on long-text training, measure what the models already do. The test hides one made-up sentence ("The secret code for project X is NNNNN.") inside a long made-up document, at the start, middle and end, and asks for the code. It prints a table by length and depth.

Start the model with the window you want to test, using the settings from `open_models.llama_args`. Qwen3 models are native to 32K; 64K and 128K use YaRN, for example:

    llama-server -m equinox-2.gguf -c 65536 --rope-scaling yarn --rope-scale 2 --yarn-orig-ctx 32768 --port 8090
    python bench_long.py --llama http://127.0.0.1:8090 --label equinox-2 --lengths 8192,16384,32768,65536

Results go to `logs/long/<label>.md` and `.json`. Weak at 32K means a short long-text fine-tune is worth it; strong means just raise the setting. Flare 2.5 stays at 8K by choice. The test is free to run on the PC (a few minutes per length).

## 5. Cautions
- Don't compare our numbers with a published table unless the tool, prompts, few-shot count and chat template match.
- Some test sets leak into training data: a big jump on one benchmark with no gain elsewhere is suspect.
- One run is a sample. Use `--limit` for speed, then the full set for any number you will quote.
