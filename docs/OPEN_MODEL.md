# An Emvryx model built on Qwen 2.5 1.5B (32K context)

This is how the first open-base Emvryx model is made. It carries the Emvryx name, but it is **not trained from scratch**: it starts from
Qwen 2.5's open weights and is fine-tuned here. Say so wherever provenance is described, and keep `NOTICE` (Qwen's licence) with any copy of the weights you share.
The from-scratch line (v2, v3, v3.5) is unaffected.

Why: v3.5 from scratch costs about $183 for a forecast ~41-45% on HellaSwag; Qwen 2.5 1.5B scores roughly 65% on the same kind of test, and
a LoRA fine-tune costs a few dollars (or runs free on the RTX 4070). The numbers are from memory: measure with `benchmarks.py` before relying on them.

## Facts
| | |
|---|---|
| Base | `Qwen/Qwen2.5-1.5B-Instruct` (28 layers, 1536 wide, 2 KV heads) |
| Licence | Apache 2.0 (check the model page before sharing anything). Keep the licence notice; say "built on Qwen 2.5"; don't imply Qwen endorses it |
| Context | 32,768 tokens natively; the app starts llama-server with `context: 32768` |
| Memory for context | about 28 KB per token, so 32K is about 0.9 GB |
| Training length | `--max_len 4096` (the lessons are short; the 32K comes from the base model) |

## What changed in the code
- `open_tokenizer.py`: wraps Qwen's `tokenizer.json` behind the calls `chat.py` uses; typed text can't inject control tokens.
- `chat.py`: a ChatML branch (`<|im_start|>user ... <|im_end|>`), used when the tokenizer says `chatml = True`. Notes go in as plain text. Our own models are unchanged.
- `finetune_open.py`: LoRA (rank 64, all attention and MLP layers), loss only on the assistant's answers, resume with the same command, `--merge` writes a normal Hugging Face folder.
- `app_server.py`: a model entry with `"open": true` loads this tokenizer.
- Not carried over: "save to memory" tool calls (Qwen has no tool tokens in our format).

## Steps on the PC (RTX 4070, 12 GB)
```
git pull origin main
pip install peft                     # once (transformers is already installed)
python finetune_open.py --pilot      # 3 steps: shows peak memory and s/step. If it runs out of memory: --batch_tokens 4096 --grad_accum 16
python finetune_open.py              # trains; Ctrl+C saves; run the same command to resume
python finetune_open.py --merge      # -> export\open\qwen2.5-1.5b-instruct\my-ai
python ..\llama.cpp\convert_hf_to_gguf.py export\open\qwen2.5-1.5b-instruct\my-ai --outfile export\open\qwen2.5-1.5b-instruct\my-ai-f16.gguf --outtype f16
..\llama.cpp\build\bin\Release\llama-quantize export\open\qwen2.5-1.5b-instruct\my-ai-f16.gguf export\open\qwen2.5-1.5b-instruct\my-ai-q4_k_m.gguf Q4_K_M
```
The lessons file is `data\v3\chat.jsonl` (`python make_chat_data_v3.py`), the same lessons v3 learned, now on a stronger base.

## Adding it to the app
Add an entry to `models.json` like the existing ones, with `"open": true`, `"tokenizer": "checkpoints/dev/open/qwen2.5-1.5b-instruct/tokenizer/tokenizer.json"`,
`"context": 32768`, `"local_gguf": ["export/open/qwen2.5-1.5b-instruct/my-ai-q4_k_m.gguf"]`, `"kv_kb_per_token": 28`, and `"base": "Qwen2.5-1.5B-Instruct"` (provenance for the docs; the model's name in the app is just Emvryx + its name and number).

## Measured on one RTX 5090 (Oct 5 2026, stand-in file of 2,972 chats, `--batch_tokens 8192 --grad_accum 8 --pilot`)
- **7.1-7.4 s per optimizer step** (8 micro-batches of up to 8,192 tokens), **18.6 GB peak** of 32 GB, loss about 0.9-1.0 (Qwen Instruct already writes this kind of chat well).
- One pass over 2,972 chats is about 38 steps, roughly 5 minutes, so about 0.1 s per chat: 100,000 chats is about 2.5 hours (about $1.30 at $0.51/h). Re-estimate with the real `chat.jsonl` line count.
- The first try crashed with out of memory only because the stopped from-scratch run was still holding 24 GB of the GPU (the `run_training.py` supervisor had not exited): check `nvidia-smi` shows about 0 MiB before starting.
- With `--batch_tokens 16384` the output layer alone wants about 10 GB (Qwen has 152,000 tokens), so stay at 8,192 unless the GPU is empty and the pilot passes.

## Not tested yet
The code is tested with a tiny offline model (`tests/test_open_model.py`), and the pilot above ran on the real Qwen weights on a 5090. Nobody has trained on the real lessons yet: compare on `benchmarks.py` and the lookup test sheet before trusting it.

## Suggested bases for the later models (suggestions, not chosen; checked from memory, Oct 2026)
Check the licence page and look for newer releases before picking: open models change every few months.

| Model | Suggested base | Size | Licence (check) | Where it trains | Notes |
|---|---|---|---|---|---|
| Equinox 4 | Qwen3-4B | 4B | Apache 2.0 | One RTX 5090 (LoRA), or a 4070 with 4-bit (QLoRA) | Same ChatML format, so `open_tokenizer.py` and `chat.py` carry over |
| Solstice 5 | Qwen3-8B | 8B | Apache 2.0 | One RTX 5090 (QLoRA); runs on a 4070 at Q4 (about 5 GB) | Strong reasoning for its size |
| Apogee 6 | Qwen3-14B, or Phi-4 (14B, MIT) | 14B | Apache 2.0 / MIT | A rented 5090 (QLoRA) or a 48 GB card | Q4 is about 9 GB: tight on a 4070, fine on a rented or always-on GPU |

Why one family: the same tokenizer and chat format mean the training and export code (`finetune_open.py`, `open_tokenizer.py`) work for every rung with a changed model name.
Avoid for now: Qwen2.5-3B (its licence is not Apache 2.0), and Llama (naming and "Built with Llama" rules).
Qwen3 can write `<think>` reasoning blocks: decide whether to keep or strip them before it becomes a model in the app.

## Upgrades: "+" and growth on an open base
The numbering is in [ROADMAP.md](ROADMAP.md) ("Numbers for "+" and grown models"). Times below are **estimates** (compute scales roughly with parameters from the measured
Flare 3.5 run: 7.1 s/step on one RTX 5090 at 1.5B, 988 steps, about 2 hours and $1). Real numbers come from a `--pilot` on the base you pick.

### "+" (same weights' size, better lessons): the normal upgrade
1. **Collect what to fix**: test the model (`benchmarks.py`, the lookup sheet, phone tests) and write down its mistakes.
2. **Make new lessons** for those mistakes (`make_chat_data_v3.py` and friends, with the teacher model on the PC, hours of PC time), and optionally DPO pairs.
3. **Train**: `python finetune_open.py --data <new lessons>`; start from the saved adapter to continue it, or from the base with all lessons together.
4. **Test it beats the old one** (`compare.py`), merge, convert to GGUF, add to the app. Number: Flare 3.5 becomes **3.6**; the old one moves to "Other models".

| Base | Rough training time (988 steps) | Rented cost at about $0.51/h | Needs |
|---|---|---|---|
| 1.5B (Flare 3.5) | about 2 h (measured) | about $1 | one 5090 or the 4070 (slower) |
| 4B (Equinox 4) | about 5 h | about $3 | one 5090 |
| 8B (Solstice 5) | about 10 h | about $5-6 | one 5090 (bf16 weights are 16 GB) |
| 14B (Apogee 6) | about 20-25 h | about $10-13 | 4-bit weights (QLoRA) on a 5090, or a 48 GB card |
Add the time to make the lessons and the tests. Skill packs (small LoRA add-ons) are trained the same way and cost less.

### Growth (more layers, bigger model): only if no open model of the size exists
1. **Pick a base** and a target (for example Qwen3-8B, 36 layers, grown to about 48 layers, roughly 10-11B).
2. **Grow it**: copy a block of its layers into the stack (like `grow.py` does for our own models; this needs a version for the open model's layer names, written and tested on a tiny model first). Width, tokenizer and embeddings stay the same.
3. **Right after growing it is slightly worse** (the copies were not trained to work together). It needs continued training to recover and then beat the original: either train all weights (needs far more memory than LoRA) or train only the new layers.
4. **Compare against the plain base and against the next bigger open base.** Only keep the grown model if it wins at a price you accept. Number: the next whole number plus .1 (Equinox 4.1).

| Growth example | Continued training (about 1B tokens, a small amount) | Cost at about $0.51/h |
|---|---|---|
| 1.5B to about 2B | about 40 h on one 5090 | about $20 |
| 8B to about 11B | about 200+ h on one 5090, and the memory does not fit: needs a 48-80 GB card or several GPUs | $100 to several hundred |
These are order-of-magnitude guesses: growth quality depends on how many tokens of continued training it gets, and 1B tokens is on the small side.

**Recommendation:** use "+" as the routine upgrade; skip growth until a base of the right size is missing. Every "+" or grown copy still carries `NOTICE` (the base's licence).

## Prepared for one RTX 5090 (Oct 2026): Equinox 4, Solstice 5, Apogee 6, and longer context
`open_models.py` holds one preset per model, and `python finetune_open.py --model equinox-4` (or `solstice-5`, `apogee-6`, `flare-3.5`) uses it.
The first guesses below were not run on the real weights (this sandbox cannot download them): **run `--pilot` first** and adjust `--batch_tokens` / `--grad_accum`.
The loss now runs the 152,000-word output layer only on the learned tokens, a chunk at a time (`chunked_loss`), which is what lets an 8B model fit.

| Model | Base | Weights in memory | Settings (micro-batch tokens × accumulation, LoRA rank) | Estimated time for 988 steps | Rented cost |
|---|---|---|---|---|---|
| Flare 3.5 | Qwen 2.5 1.5B | bf16, 3 GB | 8192 × 8, rank 64 (**measured**: 7.1 s/step, 18.6 GB) | about 2 h | about $1 |
| Equinox 4 | Qwen3-4B | bf16, 8 GB | 4096 × 16, rank 64 | about 5 h (18 s/step) | about $2.60 |
| Solstice 5 | Qwen3-8B | bf16, 16 GB | 2048 × 32, rank 32 | about 10 h (38 s/step) | about $5 |
| Apogee 6 | Qwen3-14B | 4-bit (QLoRA), about 9 GB | 2048 × 32, rank 32, `--quant4` (needs `pip install bitsandbytes`) | about 24 h (89 s/step, 4-bit is slower) | about $12 |

Each run: `python finetune_open.py --model <name> --pilot` (3 steps; prints peak memory), then `python finetune_open.py --model <name>`, then `--merge`.
If the pilot runs out of memory, halve `--batch_tokens` and double `--grad_accum` (the step stays the same size).
A QLoRA adapter (Apogee) merges onto the full-precision base, so `--merge` needs about 30 GB of memory for 14B: do it on the 5090 or a bigger machine.

### Context windows (increased)
| Model | Default | Longest | How | Memory for the longest (fp16 cache) |
|---|---|---|---|---|
| Flare 3.5 (Qwen 2.5 1.5B) | 32,768 | 32,768 | native; Qwen documents no longer setting for the 1.5B | 0.9 GB |
| Equinox 4 (Qwen3-4B) | 32,768 | **131,072** | YaRN scaling, factor 4 | 18 GB (9 GB with a q8_0 cache) |
| Solstice 5 (Qwen3-8B) | 32,768 | **131,072** | YaRN, factor 4 | 18 GB (9 GB with q8_0) |
| Apogee 6 (Qwen3-14B) | 32,768 | **131,072** | YaRN, factor 4 | 20 GB (10 GB with q8_0) |

- The server options come from `open_models.llama_args("equinox-4")`: `-c 131072 --rope-scaling yarn --rope-scale 4 --yarn-orig-ctx 32768` (add `-fa on -ctk q8_0 -ctv q8_0` for the smaller cache). Pass them with `app_server.py --llama-args "..."`.
- The weights are the same; YaRN is an inference setting. Qwen notes that it can slightly hurt short inputs, so use the longer window only when you need it, and test long inputs on your own tasks before trusting them (`eval_long.py` is for our own models and does not run these yet).
- On the RTX 4070 (12 GB) a 4B model at 128K does not fit (4B at Q4 is about 2.5 GB, plus 9 GB of cache even with q8_0): use 32K-64K there. The longer windows are for the 5090 or a rented/always-on server.
- Training stays on short chats (`--max_len 4096`). Teaching a model to use long inputs well is a later "+" step: new long-document lessons and a longer `--max_len` (more memory per step).
- Qwen3 can write `<think>` blocks; our lessons have none, so training pushes it to answer directly. Check it before it goes in the app.
