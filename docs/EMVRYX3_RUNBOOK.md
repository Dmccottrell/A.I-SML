# Emvryx 3 runbook: Flare 3, Equinox 3, Solstice 3 on the RTX 4070 (planned for the end of October 2026)

Everything here runs on the owner's PC (RTX 4070, 12 GB, 32 GB RAM). Nothing is rented. The preparation code was written and tested on Oct 11, 2026 without the real models (the sandbox cannot download them), so **expect the first pilot to find small things to fix**: that is what the pilot is for. Background and choices: [ROADMAP.md](ROADMAP.md) ("Emvryx 3"), [EMVRYX3_PILOT.md](EMVRYX3_PILOT.md).

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
| `scripts/chain_home.py` | Runs pilot, train, merge, convert, exam, identity and thinking check for each model, remembers where it is, pauses on a `PAUSE` file, can stop and restart the Emvryx app |

## The run, in order
**0. Before the day** (about 30 minutes)
```
git pull origin main
pip install -U transformers peft bitsandbytes accelerate datasets
python scripts/emvryx3_preflight.py --llama-bin C:\\Users\\Darry\\Downloads\\llama-b11392-bin-win-cuda-12.4-x64\\llama-server.exe --llama-cpp ..\\llama.cpp
```
Fix every FAIL it lists. You need a llama.cpp **source** folder (for `convert_hf_to_gguf.py` and `llama-quantize`) next to this one. About 60 GB free.

**1. Lessons** (minutes)
```
python data_prep/make_chat_data_v3.py                   # if data\\v3\\chat.jsonl is not there yet
python data_prep/style_check.py data/v3/chat.jsonl      # what would be dropped, with examples
python data_prep/format_lessons_3x.py --keep 0.4        # -> data\\v3\\chat_3x.jsonl
```
Read the style report. The wording rules are first guesses until the voice in EMVRYX_STYLE.md is decided.

**2. Pilot** (1 to 3 hours, mostly downloads the first time; free)
```
python scripts/emvryx3_pilot.py
```
Send me `logs\\emvryx3-pilot.md` (and the screen if it fails). It tells us: does each model load and train, does it fit, and how long a full run takes. **Decision point:** if Solstice 3 (9B) does not fit, it uses a smaller batch or is dropped for now.

**3. Train, one model at a time** (the app and games are off while it runs)
```
python scripts/chain_home.py --models flare-3 --keep 0.4 --llama-cpp ..\\llama.cpp --llama-bin C:\\...\\llama-server.exe --stop-app --restart-app
python scripts/chain_home.py --dry-run --models flare-3 equinox-3 solstice-3 --keep 0.4 --llama-cpp ..\\llama.cpp     # the whole plan, nothing run
```
Expected times at home (an estimate until the pilot measures it, for the full lessons; `--keep 0.4` is about 40% of this): Flare 3 about 6 to 8 hours, Equinox 3 about 15 to 20, Solstice 3 about 40 to 50, plus about a third more for preference training. **Ctrl+C stops training and saves; the same command resumes.** Create an empty file named `PAUSE` in the folder to make the chain wait before its next step. Set `NTFY_TOPIC` to get phone messages.

**4. Is it smarter and is the thinking intact?** (after training, nothing else running)
- The chain already ran the exam (base versus tuned), the identity sheet and the thinking check for the tuned model.
- Run the thinking check for the **plain base** once per model (a llama-server on the base .gguf, label `base`), then `python evaluation/thinking_check.py --compare logs\\thinking-<model>-base.json logs\\thinking-<model>-tuned.json`. If it says thinking got worse: make thinking lessons (`make_thinking_lessons.py` against the base server, about 3,000 problems) and train again with `--thinking data\\v3\\thinking_lessons.jsonl`.
- Also run the quality check and language benchmark against the old model in the same slot (`evaluation/quality_check.py`, `coding/bench_languages.py`), one model at a time.
- **Pass:** better than the model it replaces by more than the wobble (about 4 points) on average, nothing important worse (identity, honesty, rules), same speed or faster.

**5. Put it in the app as a preview**
Add the model to `models.json` with `"status": "preview"` and `"think": "empty"` (copy the Flare 2.5 entry; set `file`, `tokenizer` to `export\\open\\<model>\\my-ai\\tokenizer.json`, `context` 32768, sampling, and the memory figures the pilot measured). Restart the app: only you and admins see it, marked Preview. Try it on your phone. When happy: Admin > Models > Publish.

## Not built yet (known gaps, to do before or while the models are trained)
1. **Deep effort with thinking in the app:** send the newest question with `"thinking": true` (no empty block), pass the reply through `core/thinking.py`'s `ThinkFilter`, show "thinking..." while inside the block. The pieces and tests exist; wiring them into the chat stream waits until a model is here to try it on.
2. **llama-server settings for Qwen3.5** (`open_models.llama_args`): the memory the conversation takes is not layers x heads x size for this design; set it from the pilot's real figures.
3. **The regression guard** (a fixed set of everyday questions a new model must pass before Admin > Models lets it be published).
4. **Preference training (DPO)** from your reported answers: needs a corrected "better answer" for each report, not only the bad one.
5. **Idle unload and Gaming mode** in the app, so a big model does not hold the card while you play.
6. **Voice** (decided in the style guide, not yet written) and the Emvryx style pass over the lessons.

## If something goes wrong
- *Pilot says out of memory:* `python scripts/emvryx3_pilot.py --models solstice-3 -- --batch_tokens 512 --grad_accum 128`.
- *"model type not recognized" or a loading error:* upgrade `transformers` (`pip install -U transformers`), or the newest `peft`; send me the message.
- *The .gguf does not load in llama-server:* use a newer llama.cpp build; Qwen3.5 needs support for its hybrid design.
- *The PC is needed for something else:* Ctrl+C, do your thing, run the same command again.
