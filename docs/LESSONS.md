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

## Bulk search must be fast (found Oct 2026)
- `make_chat_data_v3.py` searches the 13M-passage index about **10,000 times** (once per lookup lesson). After the
  search was upgraded for chat quality (title+body pair queries), each call ran up to 12 extra queries that rank
  every matching passage, and the build sat for a long time with no output. `WikiIndex.search(..., deep=False)` skips
  those queries and is what the lesson builder uses; chat and evaluation keep `deep=True`. The builder now
  prints progress every 500 records.
- The first fix was not enough: the slow call was the **"any word" (OR) fallback** that runs when the strict "all words" query finds fewer than 3 passages, which matches millions of passages and ranks them all (seen in the traceback after Ctrl+C). `deep=False` now also skips that fallback, and every fast-mode query is cut off after 2 seconds (`FAST_QUERY_SECONDS`) so one slow question cannot stall the build.
- **Rule:** any script that calls search in a loop (lesson builders, DPO pairs) should either use `deep=False`
  or print its progress, and be timed on 100 questions first.
- **Measured (300,000-passage test index, ~1/44 of the real one):** `deep=False` takes **3-10 ms** per search; the default
  (deep) search takes **0.8-1.3 s**. The real build showed ~4 s per lookup record with the earlier fast mode (500 records in
  2,154 s). Fix: each lesson's search now gets one shared **time budget of 0.15 s** (`--search_seconds`; `0` skips searching
  and uses other records' passages as the extra notes), and any shortfall is filled with those passages.
- Fixed flaky test: `tests.test_app_server.Stopping.test_stop_button_ends_a_reply_and_keeps_what_was_written` failed about
  1 run in 8 with `'length' != 'stopped'`. The fake "forever" reply reached its length limit in milliseconds, before the
  test's Stop click arrived, and the test's "wait until running" loop was always true (`[None]` is truthy). The fake backend now
  takes a `pause` (10 ms a word) and the test waits for the reply to start. 30 of 30 runs pass, and 40 of 40 under 12-way load.
  The Stop button itself was fine.

## Chat tuning speed (found Oct 2026)
- `finetune.py --version v3` on the 4070 ran at **5.1-5.2 s per step** (4 conversations a step) = **~77-79 hours** for 2 passes over
  109,914 examples (54,958 steps). The "44.6 h" on the first line was the first step only; steps 20 and 40 settled at ~5.1 s.
- **Likely cause (not yet measured on the 4070):** every step padded its 4 conversations to the longest one and ran them
  together; with no gradient checkpointing, 4 sequences of up to 2,048 tokens on a 12 GB card probably spilled into
  slow shared GPU memory. Pretraining used one sequence at a time and fit in ~10 GB.
- **Fix:** `finetune_steps.train_batch` runs the batch one conversation at a time (`micro_batch=1` for v3 and v3.5) and adds
  up the gradients, each weighted by its share of the batch's answer tokens. This is the same gradient as the padded batch
  (`tests/test_finetune_steps.py` compares them, and fails if the weighting is wrong) with no padding and far less memory.
  v1 and v2 keep `micro_batch=0` (unchanged). `--micro_batch N` and `--epochs N` override the config.
- **Rule:** read the `ms/step` at step 20 and 40, not step 0, before trusting a time estimate; and tuning batches of very
  different lengths should not be padded together.

## First long-context stretch: v3-long-8k FAILED its gate (Oct 4 2026)
Trained 2,000 steps (0.52B tokens, 9.4 s/step on the rented 5090, ~5.2 h, ~$2.7), best val loss 1.950. Gate at 8,192 tokens:

| Test | Result |
|---|---|
| Needle (depth 10 / 25 / 50 / 75 / 90%) | 0 / 5 / 70 / 95 / 95% (bar: >= 95% each, none under 90%) |
| Multi-fact | 0% at every depth (test was broken: see below) |
| Long code | 0 / 0 / 0 / 5 / 35% |
| Loss by position | **+0.227 (FAIL)**; the 2K baseline was -0.400 |

- The model reads roughly the last 2-4K tokens and loses what is further back; its loss does not fall as context grows.
  The stretch is under-trained, or the position scaling (RoPE base 2M for 4x) is wrong. Not yet tested which.
- **The multi-fact test was a format test**, not a memory test (it needed "...number is X and her home town is Y" within 16 tokens;
  0% before and after the stretch). It now asks two separate questions on the same text and needs both right
  (`eval_long.multi_case`). Re-run `python eval_long.py --version v3 --tests multi` for a baseline, and the 8K weights
  (on Hugging Face as v3-long-8k/final.pt) to compare.
- `stretch_ladder.py` stopped at 8K as designed; v3 stays a 2,048-token model. Options: continue the 8K step for 2,000-4,000 more
  steps (~5-10 h), try a different RoPE base or YaRN-style scaling, add more recall-practice data, or accept a ~4K model.

## DPO pair-making speed (found Oct 2026)
- `make_dpo_pairs.py` timing test (20 questions x 2 answers, partly trained chat model) took **179 s** while another fine-tune
  was using the same 4070: ~4.5 s per answer, so ~8-10 h for the real 2,000 x 4. A GPU shared with training roughly halves
  speed or worse, so **time things with the GPU otherwise idle**.
- A second run printed **12.7 s** only because it **resumed from the first run's `dpo_pairs.jsonl.progress`** and had nothing
  left to do: a resumable script's timing run must start from a clean state (delete `data/v3/dpo_pairs.jsonl*`).
- `TinyLM.generate_many` now writes all answers to a question as one batch (the same tokens as `generate` for the same seed,
  tests/test_generate_many.py), expected to be around 3x faster on a mostly idle GPU. Not yet measured on the 4070.


## v3 chat results (Oct 5 2026) and what they mean for v3.5
Lookup test sheet (41 questions, with Wikipedia notes): `chat.pt` 26 (temperature 0.5) and 25 (0.1); `chat_dpo.pt` 27 and 29.
Rules sheet (`eval/constraints.jsonl`, 30): chat 11, DPO 10. DPO trained 57 steps on ~450 pairs (loss 0.677, margin +0.03): a gentle nudge,
a probable small gain on lookups, nothing on rules. (The HellaSwag exam comparison was still running when this was written.)
- **Strong:** exact counts and lists (instructions 4/4, lists 4/4), hard facts when the right passage is in the notes (6/6), small talk, advice.
- **Weak, both models:** topic switching 0/3, honesty ("I don't know") 1/3, plain facts 3-5/8, explanations 2/5, format and length rules
  (form 1/7, length 2/6, structured 0/2), rules held over several turns 3/8.
- **Why:** facts fail mostly when the search doesn't put the right passage in the notes; the rule failures are data and size, not decoding.

## v3.5 pilot on one RTX 5090 (Oct 5 2026)
The first pilot (`train.py --version v3.5 --cloud --pilot`, 8,192-token context, micro-batch 1 x 8,192, Muon on the GPU, no gradient
checkpointing) ran out of GPU memory at iteration 1 on a 32 GB card (iteration 0 took 14.9 s, mostly torch.compile). Fix: cloud mode now keeps
`grad_checkpoint=True` for v3.5 (about 30% slower per step). The whole data build (19.7B tokens + the final-phase set) finished in about 1 hour on 16 cores:
the early "17 hours for code" worry came from the tiny test's startup time.
