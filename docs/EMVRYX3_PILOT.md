# Emvryx 3 pilot: Flare 3, Equinox 3, Solstice 3 (plan, Oct 11, 2026)

Nothing here has been run. Nothing is rented or bought until the owner says yes. The rule for the whole of Emvryx 3: **every model must run on the owner's RTX 4070 (12 GB) by itself.** Apogee is not part of this pilot except as an optional challenger (see the end).

## What is being tested
| Slot | Today (the one to beat) | New candidate | Also try |
|---|---|---|---|
| Flare 3 | Flare 2.5 (Qwen2.5-1.5B) | Qwen3.5 2B | Qwen3.5 0.8B (if even faster is wanted) |
| Equinox 3 | Equinox 2 (Qwen3-4B) | Qwen3.5 4B | Gemma 4 E4B |
| Solstice 3 | Solstice 2 (Qwen3-8B) | Qwen3.5 9B | DeepSeek-R1-0528-Qwen3-8B (a thinking comparison) |

The Hugging Face names above must be checked on the official model cards first (they were found by web search, not confirmed). Also check each licence page.

## Step 1: does it load and train? (rented GPU, minutes, cents each)
Needs the owner's approval first; a 5090 costs roughly $0.5 to $1 an hour, and a pilot is a few minutes per model, so expect a few dollars in total (an estimate, not a quote).
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
