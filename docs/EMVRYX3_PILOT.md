# Emvryx 3 pilot: Flare 3, Equinox 3, Solstice 3 (plan, Oct 11, 2026)

> The commands are now scripts: see [EMVRYX3_RUNBOOK.md](EMVRYX3_RUNBOOK.md) (`scripts/emvryx3_preflight.py`, `scripts/emvryx3_pilot.py`, `scripts/chain_home.py`). The text below explains what is being tested and why.

Nothing here has been run. Nothing is rented or bought until the owner says yes. The rule for the whole of Emvryx 3: **every model must run on the owner's RTX 4070 (12 GB) by itself.** Apogee is not part of this pilot except as an optional challenger (see the end).

## What is being tested
| Slot | Today (the one to beat) | New candidate | Also try |
|---|---|---|---|
| Flare 3 | Flare 2.5 (Qwen2.5-1.5B) | Qwen3.5 2B | Qwen3.5 0.8B (if even faster is wanted) |
| Equinox 3 | Equinox 2 (Qwen3-4B) | Qwen3.5 4B | Gemma 4 E4B |
| Solstice 3 | Solstice 2 (Qwen3-8B) | Qwen3.5 9B | DeepSeek-R1-0528-Qwen3-8B (a thinking comparison) |

The Hugging Face names above must be checked on the official model cards first (they were found by web search, not confirmed). Also check each licence page.

## Step 1: does it load and train? (on the owner's RTX 4070, free)
**Decided Oct 11, 2026: all of it, training included, is done at home on the 4070. Nothing is rented.** The presets `flare-3`, `equinox-3` and `solstice-3` in `core/open_models.py` are set up for it (4-bit loading, small micro-batches so a step is still the same size) and flagged *untried*.

```
git pull origin main
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"      # must say True and the 4070
pip install -U transformers peft bitsandbytes accelerate           # the new designs need recent versions
python training/finetune_open.py --model flare-3 --pilot           # 3 steps: peak memory and seconds per step
python training/finetune_open.py --model equinox-3 --pilot
python training/finetune_open.py --model solstice-3 --pilot
```
If a pilot runs out of memory, halve `--batch_tokens` and double `--grad_accum`. The pilot prints the real layer counts: fix the numbers in the presets afterwards. The first run downloads the model (about 4 GB for the 2B, 9 GB for the 4B and 19 GB for the 9B at full precision: have about 40 GB free).
**What the pilot decides:** how long a full run takes (seconds per step times about 1,000 steps), and whether the 9B fits at all. If it does not, Solstice 3 uses the 4B-class model with more lessons, or waits.

**Training time at home (an estimate from the measured 5090 run, which the pilot replaces):** the 4070 is roughly 3 times slower, and 4-bit loading adds more. Expect about 6 to 8 hours for the 2B, 15 to 20 hours for the 4B and 40 to 50 hours for the 9B on the full lesson set, plus preference training afterwards. While training, the PC cannot run the app's models or games, and the tests must wait (no benchmarks during training). Options to cut it: train on a well-chosen part of the lessons (quality over amount), and run overnight.
1. `git pull origin main`, then upgrade `transformers`, `peft` and `bitsandbytes` (newer designs often need newer versions).
2. For each candidate: `python training/finetune_open.py --model <hf name> --pilot` (3 steps; prints memory and speed, saves nothing).
3. Check that `core/open_tokenizer.py` accepts the tokenizer and that the chat template works with our lessons (ChatML for the Qwen models; Gemma needs a conversion).
4. Decide what to do about built-in "thinking" text: keep, hide, or tie to the Deep effort level. Our lessons have no thinking text.
5. Add a preset to `core/open_models.py` with the real layer counts the pilot prints.

## Step 2: does it run on the 4070? (free, at home)
1. Convert to GGUF (llama.cpp converter) and make a 4-bit file. Confirm the newest `llama-server` loads it.
2. Measure at 8K, 16K and 32K words of conversation: graphics memory used and words per second. Pass: fits in 12 GB with room to spare, and at least about as fast as the model it replaces.
3. Measure what is left for a game (graphics memory with the model loaded).

## Step 3: is it smarter? (our own tests, one model at a time, never during training)
Same tests for the old and the new model, in thinking and non-thinking mode:
- `evaluation/exam_open.py --compare` (HellaSwag) and `evaluation/bench_open.py` (ARC, WinoGrande, MMLU, GSM8K, TruthfulQA; 200 questions each wobble about 3 to 4 points)
- `evaluation/quality_check.py` (everyday questions and past reports) and the identity sheet (`evaluation/evaluate_open.py`)
- `coding/bench_languages.py` and the VryxCode exercises (coding)
- a long-document test, and a picture test for the models that see pictures
**Pass:** better than the model it replaces by more than the wobble (about 4 points) on average, with nothing important worse (identity, honesty, following rules), at the same speed or faster.

## Step 4: decide
Per slot, the winner is trained for real (about $1 to $5 each by the earlier estimates) with the 2.5 improvements built in (new lessons from reported mistakes, DPO, tool calling, thinking dial, identity). It then goes into Admin > Models as a **preview**, and the regression guard (planned) must pass before it is published. The old version moves to Other models.

## Apogee
Stays on Qwen3-14B and gets its 2.5 release. Gemma 4 12B and Qwen3.5 9B (thinking) can be added to Step 3 as challengers; Apogee only changes base if one clearly wins on our own tests and fits the 4070 comfortably.
