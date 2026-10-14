# Emvryx 3 runbook: Flare 3, Equinox 3, Solstice 3 on the RTX 4070 (planned for the end of October 2026)

Everything here runs on the owner's PC (RTX 4070, 12 GB, 32 GB RAM). Nothing is rented. The preparation code was written and tested on Oct 11, 2026 without the real models (the sandbox cannot download them), so **expect the first pilot to find small things to fix**: that is what the pilot is for. Background and choices: [ROADMAP.md](ROADMAP.md) ("Emvryx 3"), [EMVRYX3_PILOT.md](EMVRYX3_PILOT.md).

## Decided: the bases for Flare, Equinox and Solstice 3 (bake-off of Oct 13, 2026, on the RTX 4070)
The hard sheet (52 questions), 4-bit, after the graphics card was fixed (llama-server had been running on the processor because the CUDA runtime files were missing):

| Slot | Today | Candidate | Decision |
|---|---|---|---|
| Flare 3 | Flare 2.5: 23/52, 191 tokens/s | Qwen3.5 2B: **28/52, 207 tokens/s** | Qwen3.5 2B (wins the rule) |
| Equinox 3 | Equinox 2: 28/52, 98 tokens/s | Qwen3.5 4B: **39/52, 106 tokens/s** | Qwen3.5 4B (wins by 11) |
| Solstice 3 | Solstice 2: 40/52, 64 tokens/s | Qwen3.5 9B: 40/52, 68 tokens/s | **Qwen3.5 9B, the owner's choice**: a tie on the sheet (so the rule alone keeps Solstice 2), chosen for the same family as Flare and Equinox 3 (one lesson set, one chat format) and slightly faster |

These are the presets `flare-3`, `equinox-3` and `solstice-3` in `core/open_models.py`.

**Conversation size (the needle test, same night):** all three new bases fit a 128K window on the 4070 and found the hidden code 3/3 at 8K, 32K, 64K and 128K (graphics memory at 128K: 2B 5.0 GB, 4B 8.5 GB, 9B 10.5 GB; reading a full 128K document took 12, 36 and 44 s). Today's Flare 2.5, Equinox 2 and Solstice 2 top out at 32K (beyond that they spill past the card). So the v3 models get a 128K window.

**Apogee stays as it is for now (owner's decision).** Nothing beat Apogee 2 on the hard sheet: Apogee 2 43/52 (41 tokens/s; fails to load at 64K), Qwen3.5 9B 41/52 (61 tokens/s, 128K), Qwen3.8 27B at 2-bit 35/52 (35 tokens/s, too slow past 32K), DeepSeek-R1 14B 23/52 (thinks too long, 0/10 on maths). The table showed "-" for Apogee 2, the 27B and the 14B because a failure at a bigger window threw away the whole row; the scores above are added up from the by-category table, and the bake-off now keeps a model's score when only a bigger size fails. Revisit when a stronger model that fits 12 GB comes out. The scores are before training; the identity and thinking checks after training make sure tuning does not wear them down.

## What was prepared (all in the repository, all tested)
| Piece | What it does |
|---|---|
| `core/open_models.py` presets `flare-3`, `equinox-3`, `solstice-3` | The Qwen3.5 2B, 4B and 9B, set up for 4-bit training on a 12 GB card (flagged *untried*; the pilot prints the real figures) |
| `core/open_tokenizer.py` `think="empty"` | Every prompt ends with an empty thinking block (`<think>\\n\\n</think>\\n\\n`) so Quick and Balanced answer straight away; training uses the same format, so what is learned is what the app sends. A question marked `"thinking": true` leaves the block out (Deep: the model thinks first) |
| `core/thinking.py` | Hides `<think>...</think>` from the answer, streaming-safe, and tells the app when the model is thinking |
| `scripts/emvryx3_preflight.py` | Is the PC ready: CUDA, packages, disk, RAM, card in use, llama-server, lessons file |
| `scripts/emvryx3_pilot.py` | Runs the 3-step pilot for each model; writes `logs\\emvryx3-pilot.md` with peak memory, seconds per step, hours for a full pass, fits or not |
| `data_prep/style_check.py` + [EMVRYX_STYLE.md](EMVRYX_STYLE.md) | Finds lessons that do not sound like Emvryx (claiming to be another AI, "as an AI language model", ...) |
| `data_prep/format_lessons_3x.py` | De-duplicates, drops style failures, and keeps a balanced share (`--keep 0.4`) with the rare important kinds (identity, honesty, corrections) always kept |
| `data_prep/reasoning_problems.py`, `make_thinking_lessons.py` | Optional: thinking lessons the model writes itself and code checks (wrong ones are thrown away). Only if the thinking check says they are needed |
| `evaluation/thinking_check.py` | Same checked problems, thinking on and off, plain base versus tuned: did tuning wear the thinking down? |
| `scripts/chain_home.py` | Runs pilot, train, merge, convert, exam, identity and thinking check for each model, remembers where it is, pauses on a `PAUSE` file, can switch Gaming mode on for the run (or stop and restart the Emvryx app) |

## The run, in order
**0. Before the day** (about 30 minutes)
```
git pull origin main
pip install -U transformers peft bitsandbytes accelerate datasets
python scripts/emvryx3_preflight.py --llama-bin C:\\Users\\Darry\\Downloads\\llama-b11392-bin-win-cuda-12.4-x64\\llama-server.exe --llama-cpp ..\\llama.cpp
```
Fix every FAIL it lists. You need a llama.cpp **source** folder (for `convert_hf_to_gguf.py` and `llama-quantize`) next to this one. About 60 GB free.

**0b. The easy way: prepare everything in one command** (`scripts/emvryx3_prepare.py`, minutes; no GPU needed)
```
python scripts/emvryx3_prepare.py
```
It builds the Emvryx lessons if missing, converts the Nemotron files you downloaded (if they are in `data\open\nemotron-v2`) into general lessons, shows the style report, mixes and balances everything (`--keep 0.4` of the Emvryx lessons, identity, honesty and corrections always kept, general lessons as 30% of the final set), checks the result, estimates the hours for each model, and prints the commands to run next. `--dry-run` only says what it would do. After it, train with `chain_home.py ... --skip lessons --lessons data\v3\chat_3x.jsonl` so the chain uses exactly that file. Step 1 below is the same thing done by hand.

**1. Lessons** (minutes)
```
python data_prep/make_chat_data_v3.py                   # if data\\v3\\chat.jsonl is not there yet
python data_prep/style_check.py data/v3/chat.jsonl      # what would be dropped, with examples
python data_prep/format_lessons_3x.py --keep 0.4        # -> data\\v3\\chat_3x.jsonl
```
**General lessons (so the models are all-rounders, not only Emvryx-voiced):** the Emvryx lessons stay as they are, including every identity, honesty and correction lesson (those are always kept), and a share of general assistant lessons from open datasets is mixed in next to them. You choose each dataset after reading its page and licence (human-written ones are safest; answers written by another company's AI may be limited by that company's terms). Example with one human-written set (check its licence page first):
```
hf download databricks/databricks-dolly-15k --repo-type dataset --local-dir data\open\dolly
python data_prep/general_lessons.py --input data\open\dolly\databricks-dolly-15k.jsonl --format dolly --source dolly-15k --licence cc-by-sa-3.0 --max 5000
python data_prep/format_lessons_3x.py --general data\v3\general.jsonl --general-share 0.3 --keep 0.4
```
**The strongest free one found (Oct 2026): NVIDIA Nemotron-Post-Training-Dataset-v2** (licence cc-by-4.0; answers written by DeepSeek-R1-0528 and Qwen models, so read the card's note about the Qwen and DeepSeek licence terms). It is gated: on its Hugging Face page accept the terms (it asks for a company and an email), make a read token in your Hugging Face settings, and run `hf auth login` (paste the token into that prompt only, never in chat or in a file in the repo). Take only the English parts (about 8 GB; the multilingual parts are 18 GB each):
```
hf download nvidia/Nemotron-Post-Training-Dataset-v2 --repo-type dataset --include "data/math-*" "data/stem-*" "data/code-*" "data/chat-*" --local-dir data\open\nemotron-v2
python data_prep/general_lessons.py --input "data\open\nemotron-v2\data\math-*" --format messages --source nemotron-v2-math --licence cc-by-4.0 --filter reasoning=off --row-licences cc-by-4.0 --max 6000
python data_prep/general_lessons.py --input "data\open\nemotron-v2\data\stem-*" --format messages --source nemotron-v2-stem --licence cc-by-4.0 --filter reasoning=off --row-licences cc-by-4.0 --max 6000 --append
python data_prep/general_lessons.py --input "data\open\nemotron-v2\data\code-*" --format messages --source nemotron-v2-code --licence cc-by-4.0 --filter reasoning=off --row-licences cc-by-4.0 --max 6000 --append
python data_prep/general_lessons.py --input "data\open\nemotron-v2\data\chat-*" --format messages --source nemotron-v2-chat --licence cc-by-4.0 --filter reasoning=off --row-licences cc-by-4.0 --max 12000 --append
```
`--filter reasoning=off` keeps only answers without thinking traces (our models use an empty thinking block); `--row-licences cc-by-4.0` leaves out the few rows that carry a different licence (ODC-By, CC-BY-SA). Needs `pip install pyarrow` (parquet files). The chat part is 6 GB and takes a few minutes to scan.

`general_lessons.py` drops anything that claims to be another AI, "as an AI language model", personal details and duplicates, and does not apply the soft voice rules (filler openers, length) to general lessons. Use `--append` to combine several datasets into one general file. `--general-share` is the share of the final set (default 30%).

Read the style report. The wording rules are first guesses until the voice in EMVRYX_STYLE.md is decided.

**2. Pilot** (1 to 3 hours, mostly downloads the first time; free)
```
python scripts/emvryx3_pilot.py
```
Send me `logs\\emvryx3-pilot.md` (and the screen if it fails). It tells us: does each model load and train, does it fit, and how long a full run takes. **Decision point:** if Solstice 3 (9B) does not fit, it uses a smaller batch or is dropped for now.

**2b. The bake-off: which candidates earn a slot?** (about 2 to 4 hours, mostly downloads and waiting; free; nothing else may use the card)
Download the candidate `.gguf` files named in `eval\bakeoff_candidates.json` (Q4 for the small ones; Qwen3.8-27B at 2-bit (UD-IQ2_XXS) for Apogee 3) into `models\base\`, and make sure the model in each slot today (`flare-2.5`, `equinox-2`, `solstice-2`, `apogee-2`) has its `.gguf` listed as the baseline. Check each model page and licence first (the names and sizes in the file came from web searches). Then:
```
python scripts/emvryx3_bakeoff.py --llama-bin C:\...\llama-server.exe
python scripts/emvryx3_bakeoff.py --llama-bin C:\...\llama-server.exe --only apogee      (one slot at a time is fine)
```
For each candidate it measures graphics memory and speed at 8K, 16K and 32K tokens, and runs the 41 everyday questions. `logs\bakeoff.md` has a table per slot with a verdict against the model it would replace (smarter by more than 3 questions, not slower than 90% of the speed, and fits the card). **Send me `logs\bakeoff.md`.** The slot winners are the ones to train (Flare, Equinox, Solstice, Apogee 3); the 27B is Apogee 3 and runs untrained (it cannot be fine-tuned in 12 GB).

**The everyday sheet is nearly full marks for the 9B-class models, so it cannot tell them apart** (first Apogee run: Apogee 2 38/39, Qwen3.5 9B 39/39, Qwen3.8-27B at 2-bit 38/39, DeepSeek-R1 14B 34/39). For that, run the harder sheet too: 52 questions of multi-step maths, logic puzzles, reading Python output, strict formats, trick questions and honesty about what it cannot know (`eval\\hard.jsonl`, made by `eval/make_hard_sheet.py`):
```
python scripts/emvryx3_bakeoff.py --llama-bin "C:\\path\\to\\llama-server.exe" --only apogee --sheet eval\\hard.jsonl --quick
```
It is saved apart (`logs\\bakeoff-hard.md`), so the first report is not overwritten. `--quick` measures memory and speed at 8K only. **Memory columns stuck at about 1.3 to 1.6 GB mean the model ran on the processor, not the graphics card**: fix that first (see "If something goes wrong").

**How big a conversation can each v3 model hold?** Plan: start every v3 model at 32K, then measure how far it can go on the 4070 (Apogee 3 stays small, 8K to 16K, because the 27B at 2-bit leaves little room). Test 64K for Flare, Equinox and Solstice, and 128K for Solstice too (try it with the q8 conversation memory setting if it gets tight). `--needle` also hides a secret code in a full-length document at three depths and asks for it, so the table shows whether the model really finds things at that length, plus how long it took to read the document:
```
python scripts/emvryx3_bakeoff.py --llama-bin "C:\\path\\to\\llama-server.exe" --only solstice --contexts 8192,32768,65536,131072 --needle --label window
```
The **Window** column is the largest size that fits the card, answered, found the code every time and read the document in under a minute. Publish each model at its window (set `context` and `context_tested` in `models.json`). Only trust this once the memory columns show the card in use (not stuck near 1.3 GB). Do not run it while training.

**3. Train, one model at a time** (the app and games are off while it runs)
```
python scripts/chain_home.py --models flare-3 --keep 0.4 --llama-cpp ..\\llama.cpp --llama-bin C:\\...\\llama-server.exe --gaming
python scripts/chain_home.py --dry-run --models flare-3 equinox-3 solstice-3 --keep 0.4 --llama-cpp ..\\llama.cpp     # the whole plan, nothing run
```
Expected times at home (an estimate until the pilot measures it, for the full lessons; `--keep 0.4` is about 40% of this): Flare 3 about 6 to 8 hours, Equinox 3 about 15 to 20, Solstice 3 about 40 to 50, plus about a third more for preference training. **Ctrl+C stops training and saves; the same command resumes.** Create an empty file named `PAUSE` in the folder to make the chain wait before its next step. Set `NTFY_TOPIC` to get phone messages.

**4. Is it smarter and is the thinking intact?** (after training, nothing else running)
- The chain already ran the exam (base versus tuned), the identity sheet and the thinking check for the tuned model.
- Run the thinking check for the **plain base** once per model (a llama-server on the base .gguf, label `base`), then `python evaluation/thinking_check.py --compare logs\\thinking-<model>-base.json logs\\thinking-<model>-tuned.json`. If it says thinking got worse: make thinking lessons (`make_thinking_lessons.py` against the base server, about 3,000 problems) and train again with `--thinking data\\v3\\thinking_lessons.jsonl`.
- Also run the quality check and language benchmark against the old model in the same slot (`evaluation/quality_check.py`, `coding/bench_languages.py`), one model at a time.
- **Pass:** better than the model it replaces by more than the wobble (about 4 points) on average, nothing important worse (identity, honesty, rules), same speed or faster.

**5. Put it in the app as a preview**
Add the model to `models.json` with `"status": "preview"` and `"think": "empty"` (copy the Flare 2.5 entry; set `file`, `tokenizer` to `export\\open\\<model>\\my-ai\\tokenizer.json`, `context` 32768 and `context_tested` 32768 (VryxCode folds old steps at 70% of `context_tested`), sampling, and the memory figures the pilot measured). Restart the app: only you and admins see it, marked Preview. Try it on your phone. Then Admin > Models > **Run safety checks** (about 40 questions, a few minutes), and when it passes and you are happy: Publish.

## Not built yet (known gaps, to do before or while the models are trained)
1. **Deep effort with thinking in the app:** send the newest question with `"thinking": true` (no empty block), pass the reply through `core/thinking.py`'s `ThinkFilter`, show "thinking..." while inside the block. The pieces and tests exist; wiring them into the chat stream waits until a model is here to try it on.
2. **llama-server settings for Qwen3.5** (`open_models.llama_args`): the memory the conversation takes is not layers x heads x size for this design; set it from the pilot's real figures.
3. ~~The regression guard~~ (built Oct 12, 2026: Admin > Models > Run safety checks; Publish waits for it).
4. **Preference training (DPO)** from your reported answers: needs a corrected "better answer" for each report, not only the bad one.
5. ~~Idle unload and Gaming mode~~ (built Oct 12, 2026: Admin > PC; the chain's `--gaming` switches it on for the run).
6. **Voice** (decided in the style guide, not yet written) and the Emvryx style pass over the lessons.
7. ~~Pictures the model sees itself~~ (built Oct 14, 2026: the chain's **eyes** step puts the base's picture reader, `mmproj.gguf`, beside each Emvryx 3
   model and checks it reads a number off a picture; the app then sends pictures straight to the model. See docs/VISION.md.)
8. ~~Long memory kept after training~~ (built Oct 14, 2026: the chain's **long** step, `scripts/long_check.py`, hides a code at 32K, 64K and 128K;
   passed = the model's window is set to 128K when it is added; failed = retrain that model with some long lessons before publishing.)

## If something goes wrong
- *The bake-off shows 1.3 to 1.6 GB of memory and 3 to 12 words a second for every model:* llama-server is not using the graphics card. Run `llama-server.exe --list-devices`: it must list the RTX 4070. If not, unzip the matching `cudart-llama-bin-win-cuda-12.4-x64.zip` from the llama.cpp releases into the same folder (or use the newest CUDA build), and look in `logs\\bakeoff\\<model>-8192-server.log` for the line with "offloaded" (it must say all layers).
- *Pilot says out of memory:* `python scripts/emvryx3_pilot.py --models solstice-3 -- --batch_tokens 512 --grad_accum 128`.
- *"model type not recognized" or a loading error:* upgrade `transformers` (`pip install -U transformers`), or the newest `peft`; send me the message.
- *The .gguf does not load in llama-server:* use a newer llama.cpp build; Qwen3.5 needs support for its hybrid design.
- *The PC is needed for something else:* Ctrl+C, do your thing, run the same command again.
