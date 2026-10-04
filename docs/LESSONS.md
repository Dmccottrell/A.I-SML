# Lessons learned (Oct 2026)

Notes from finishing v3's pretraining and starting its chat tuning. Each item says what happened,
what we do about it, and which versions it affects. Numbers here were measured on the real runs unless
marked "guess". The settings every later version should start from are in
[VERSIONS.md, Settings carried forward](VERSIONS.md#settings-carried-forward-by-version).

## v3's pretraining result
- Finished at step **45,000**; validation loss about **2.68**.
- HellaSwag on a 2,000-question sample: **`final.pt` 37.1%** vs the **average of the last snapshots 36.9%**,
  so **keep `final.pt`**. The mini-exam read 40.2% at step 44,000 (the 500-question mini-exam is ~5 points
  easier than the whole test; that is why v3.5+ spread the questions over the whole file).
- `final.pt` is backed up on Hugging Face (private repo) and on the PC.
- **For later versions:** averaging snapshots did not help at 394M. Each snapshot is a full copy of the
  weights (1.6 GB at v3, 4.5 GB at v3.5, ~12 GB at 3B), so v5+ should skip them or keep few.
- Measured speed per step: 4070 **25.8 s**, rented 3090 **17.5 s**, rented 5090 **6.9 s**.

## The Wikipedia lookup index
- Built from the `wikimedia/wikipedia` `20231101.en` snapshot: **13,296,822 passages from 6,407,814 articles**
  (~10 GB). **The snapshot is from November 2023**, so it is stale for anything that changes (office holders,
  sports, recent events). Stable facts are fine. Web mode (`--web`) covers the rest. Refresh the snapshot
  when a newer one is checked and there is time for the multi-hour build.
- **Some big articles were missing** from the finished index: "Illinois", "Chicago" and "Paris" had 0
  passages while "France", "Abraham Lincoln", "Albert Einstein" and "Springfield, Illinois" had 3 each.
  Cause **not found**. `python wiki_index.py add Illinois Chicago Paris` fetches missing articles from live
  Wikipedia. **Check a list of well-known titles after any rebuild** (count passages per title) before trusting it.
- Passages end with Wikipedia **category lists** ("Men's association football forwards Bosnia and Herzegovina
  ..."). That clutter is probably why list-like junk passages rank so high in search. **Strip trailing
  category lines in `split_passages()` before the next build.**
- **Plain keyword search is not good enough** for questions like "capital of Illinois": millions of passages
  mention both words. Five rounds of keyword-scoring changes (title index, title+body candidates, word order,
  tense, proximity) fixed my synthetic tests but, on the real index, the "Illinois" article ranked first while
  unrelated pages (a pollution control board, a village) still outranked "Springfield, Illinois". **Stop
  hand-tuning.** The plan: a small separate **reranker** (a helper beside the model, allowed by the README's
  weights policy) that scores each candidate passage against the question. Build it after v3's chat tuning,
  once `evaluate.py --lookup` shows whether search is what holds v3 back.
- The lookup **training** lessons do not depend on search: the teacher writes each question from a known
  passage. Search quality only matters at chat time.

## The teacher
- **Local is free and fast enough.** Qwen2.5-7B-Instruct (Q4) on the 4070 with the llama.cpp **CUDA 12** build
  (b11392): **instructions ~0.35 s per lesson** (about 4 per second), **lookups ~0.6 s**, with 4 slots
  (`-np 4`). Kept after the rule checks: **19 of 20** instruction lessons, **13 of 20** lookups (65%,
  as the docs predicted). The old "1–2 days" estimate was too slow; the first batch ran at ~4 lessons/second.
  These come from small samples.
- Quality check done by reading lessons: instruction answers follow the exact instruction; lookup questions
  match the passage, the answer ends with `(Source: ...)`, the wrong answer is plausible.
- Get the **CUDA** build **and** the matching CUDA DLL zip into the same folder (the DLLs were missing
  at first). The CPU build is far too slow. Pause training on the same GPU while the teacher runs.
- **Hosted Gemini was not free.** The API answered `402: prepayment credits depleted` even with a
  $300 Google Cloud trial credit linked; the model the first command used (`gemini-2.5-flash`) was
  retired for new accounts (404). Free tiers have small daily caps. Use the local teacher.
- **Never paste an API key into chat or a screenshot.** Three keys were exposed this way and had to be
  replaced. Set keys in PowerShell with hidden input (`Read-Host -AsSecureString`) or leave them in an
  environment variable, and keep `$env:...` lines out of screenshots.

## Sampling (temperature) per model
- Flare 3 had **no tuned sampling** of its own, so Auto effort could push it to temperature **1.0**, too hot
  for a 394M model. Every model entry in `models.json` now has `sampling`, `temperature_bounds` and
  `max_reply_tokens`. The numbers for Flare 3 / 3.5 / Equinox / Solstice / Apogee are **starting guesses**
  (smaller model = lower temperature and a narrower range). Tune each with
  `python evaluate.py --version vN --prompts eval/constraints.jsonl --temperature 0.3` against `0.6`.
- When a lookup supplies notes, answers should be steadier than free chat (lower temperature).
  Not built yet.

## How we work (process mistakes to avoid)
- **Run the whole test suite before every merge.** A change to Flare 3's settings broke two tests on `main`
  because only three test files were run. (Fixed in the next PR.)
- **A synthetic test that passes on the old code proves nothing.** Check that a new test fails on the previous
  version, and say so when a test cannot reproduce a real-data failure.
- PowerShell gotchas that cost time: `<placeholders>` typed literally; a missing closing quote
  (a `>>` prompt, then Ctrl+C throws the whole line away); `Measure-Command` hides the script's own output;
  a new window needs `cd` to the project and the venv activated; Windows PowerShell 5.1 shows UTF-8
  text garbled (check with Python `encoding='utf-8'` before assuming the file is bad).

## Long-context baseline on v3's `final.pt` (cloud 5090, Oct 2026)
`python eval_long.py --version v3` at the native 2,048 tokens, before any stretching:

| Test | Result |
|---|---|
| Needle in a haystack | 95%, 90%, 95%, 95%, 100% at depths 10-90% (borderline: the bar is 95% everywhere, no depth under 90%) |
| Multi-fact (number **and** town) | **0% at every depth** |
| Long code (`get_port_xxxx()`) | 0%, 0%, 10%, 25%, 45% (better the later the function appears) |
| Loss by position | pass (-0.400) |
| Verdict | `FAILED (stop here)`, so the chained cloud job stopped before the pilot run |

- **What it does show:** the needle test works and v3 finds a single hidden fact at 2K. The long-training data
  was built (2,100,326,823 tokens).
- **What it probably means (not confirmed):** the 0% on multi-fact is exactly 0 at every depth, which looks like
  a *format* problem, not a memory problem. The prompt ends `Answer: Mira's favorite number is`, and the model
  must write the number and then, unprompted, `and her home town is ...` within 16 tokens. A base model has never
  seen that question format. The long data's "recall practice" (5%) teaches exactly that format, so the stretched
  model may pass where the baseline cannot. The code test's rise with depth looks like plain recency (the latest
  text is easiest to copy).
- **So a baseline FAIL on multi/code does not block stretching,** and the docs' assumption that the 2K baseline
  "should pass" every test was wrong. Judge the ladder by what the 8K step scores after training.
- **Open risk:** if multi-fact is still ~0% after the 8K step, change the test (give a template, or allow more
  answer tokens) or add more recall practice before blaming the stretch.
- `eval_long.py` exits with an error whenever a test fails, so a command chain joined with `&&` stops there.
  Run the pilot as its own command.
