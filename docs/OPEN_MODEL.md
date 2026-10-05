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
