# A personal open-model fine-tune (Qwen 2.5 1.5B, 32K context)

**This is not an Emvryx model.** Emvryx's own models (v1 to v6.5) are trained from scratch and stay that way (README, "Pretrained weights
policy"). This is a separate model for the owner's own use, built on someone else's open weights. Don't call it Emvryx or ship it.

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

## Adding it to the app (personal copy, don't commit it as Emvryx)
Add an entry to your own `models.json` like the existing ones, with `"open": true`, `"tokenizer": "checkpoints/dev/open/qwen2.5-1.5b-instruct/tokenizer/tokenizer.json"`,
`"context": 32768`, `"local_gguf": ["export/open/qwen2.5-1.5b-instruct/my-ai-q4_k_m.gguf"]`, `"kv_kb_per_token": 28`, and a name that says it is Qwen-based (for example "Qwen 1.5B (personal)").

## Not tested yet
Everything here is tested with a tiny offline model (`tests/test_open_model.py`). Nobody has run it on the real Qwen weights or a GPU: do the `--pilot`
first, and compare on `benchmarks.py` and the lookup test sheet before trusting it.
