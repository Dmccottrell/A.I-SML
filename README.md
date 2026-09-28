# A.I-SML — Build Your Own Small Language Model

Llama-style language models built completely from scratch: your own tokenizer, your own
transformer, your own training run. No pretrained weights. The finished models run on your
PC and fully offline on your phone.

| Version | What it is | Status |
|---|---|---|
| **v1** | 30M story-teller trained on TinyStories (~32MB on the phone) | ✅ Done: runs offline on the phone |
| **v2** | 88M mini assistant: web text + Wikipedia + multi-turn chat (89MB on the phone) | ✅ Done: 18/20 test sheet, HellaSwag 28.4%, runs offline on the phone. See **[docs/V2.md](docs/V2.md)** |
| **v3** | 394M accuracy-focused assistant: + code and math, 2,048-token memory (~240MB on the phone as Q4) | 🧱 Groundwork built: see **[docs/V3.md](docs/V3.md)** |

Every script takes `--version v1` (the default) or `--version v2`. Settings for each version
live in `config.py`.

> **Current stage: DEVELOPMENT.** Every script reads and writes only `checkpoints/dev/`
> and `export/dev/` (set in `stage.py`). Nothing touches staging or production until you
> promote it by hand.

## Pretrained weights policy

**Every model in this project (v1 to v6.5) is trained from scratch.** Each one starts as random
numbers and learns only from the text we give it. No one else's pretrained weights are ever
loaded into, merged with, or used to start one of these models.

Other people's open models may be used as **helpers beside the model, never inside it**:

| Helper | What it does | Inside our model? |
|---|---|---|
| **Teacher model** (an open ~7B, from v3) | Writes practice chat examples and grades our model's answers for DPO. Only its written text is used, like a tutor's worksheets | ❌ No |
| **Search model** (optional, from v3) | Finds Wikipedia passages by meaning for lookups. Keyword search needs no model at all | ❌ No, runs beside it |
| **Whisper and Piper** (v4) | Speech-to-text and text-to-speech for voice | ❌ No, separate programs |
| **A fine-tuned open model** (optional) | A smarter daily assistant in the app while our own models grow | ❌ No, a separate model, always labeled as not ours |

Rules for helpers:
- Only models and datasets whose licenses allow this use. Check each license before using it.
- Never use the ChatGPT, Claude or Gemini APIs to write training data; their terms restrict
  using outputs to build competing models.
- Some training data (for example the smol-smoltalk conversations) was written by other AIs. It
  shapes the chat *style*, but the model's weights are still trained 100% here.

This keeps every result honest: when a version improves, it's because of this project's own
data, code and training.

## Files

| File | Phase | What it does |
|---|---|---|
| `stage.py` | all | Sets the working stage (`dev`) and its folders |
| `config.py` | all | Settings for each version (model size, folders, training) |
| `chat.py` | 6–8 | The chat format, shared by fine-tuning, chat and export |
| `bigram.py` | 1 | Warm-up: tiny character model that learns from `input.txt` |
| `tokenizer.py` | 2 | Byte-level BPE tokenizer written from scratch |
| `model.py` | 3 | The transformer (RMSNorm, RoPE, attention, SwiGLU) |
| `prepare_data.py` | 4 | v1 data: downloads TinyStories, trains the tokenizer, writes `data/train.bin` / `val.bin` |
| `prepare_web_data.py` | 4 | v2+ data: streams FineWeb-Edu + Wikipedia (+ code for v3) + TinyStories into `data/<version>/` (resumable) |
| `prepare_data_v2.py` | 4 | Shortcut for `prepare_web_data.py --version v2` |
| `train.py` | 5 | Pretraining loop. Ctrl+C pauses; run again to resume |
| `generate.py` | 6 | Generate text or chat with your model |
| `make_chat_data.py` | 7 | v1: builds `data/chat.jsonl` fine-tuning examples automatically |
| `make_chat_data_v2.py` | 7 | v2: builds `data/v2/chat.jsonl` (multi-turn conversations) |
| `finetune.py` | 7 | Teach it a chat format using the version's `chat.jsonl`. Ctrl+C pauses; run again to resume |
| `evaluate.py` + `eval/prompts.jsonl` | 6–7 | 20-question test sheet that scores a chat model |
| `exam.py` | 6 | HellaSwag, a public common-sense test (works on pretrained models; compare versions) |
| `wiki_index.py` | v3 | Searchable copy of Wikipedia for lookups (build + search) |
| `make_teacher_data.py` | v3 | The teacher model (Qwen2.5-7B via llama.cpp) writes practice examples |
| `make_chat_data_v3.py` | 7 | v3: chat lessons that fix v2's mistakes (lookups, "I don't know", corrections, instructions, topic switches) |
| `benchmarks.py` | 4–6 | Downloads the public test sets (HellaSwag, GSM8K), used by `exam.py` and to keep them out of training data |
| `export_hf.py` | 8 | Save in standard Llama layout (safetensors + tokenizer.json) |
| `to_gguf.py` | 8 | Convert to GGUF with llama.cpp for phone apps |
| `examples/chat_sample.jsonl` | 7 | Example fine-tuning data format |

Version side-by-side: [`docs/VERSIONS.md`](docs/VERSIONS.md). Where the project is heading: [`docs/ROADMAP.md`](docs/ROADMAP.md).

New to the code? Start with [`docs/HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md). Every function also has a docstring explaining what it does.

## Quick start on your PC (NVIDIA GPU, 8GB+ VRAM)

```bash
git clone https://github.com/dmccottrell/a.i-sml.git
cd a.i-sml

# Phase 0: setup
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # Mac/Linux
pip install torch --index-url https://download.pytorch.org/whl/cu124   # check pytorch.org for your exact command
pip install -r requirements.txt
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"

# Phases 1-3: sanity checks
python bigram.py        # loss drops, prints gibberish (expected!)
python tokenizer.py     # prints "tokenizer OK"
python model.py         # ~29.5M parameters, initial loss ~9.0

# Phase 4: data (~2GB download, 30-70 min total, run once)
python prepare_data.py

# Phase 5: train (5-10 hours on an 8GB card)
python train.py

# Phase 6: try it
python generate.py --prompt "Once upon a time"
```

Checkpoints land in `checkpoints/dev/`.

## Fine-tuning (Phase 7)

```powershell
python make_chat_data.py        # builds data/chat.jsonl (~5,000 examples) from TinyStories
python finetune.py              # ~5-10 min -> checkpoints/dev/chat.pt
python generate.py --ckpt checkpoints/dev/chat.pt --chat
```

`make_chat_data.py` turns stories into requests like *"Tell me a story about Lily."* and adds
greetings and "who are you?" answers (edit `BASICS` in the file to change its personality).
Add your own examples to `data/my_examples.jsonl` (same format as
`examples/chat_sample.jsonl`); they are included 3 times so they count more.

## Putting it on your phone (Phase 8)

**1. Export and convert (once per model version):**
```powershell
python export_hf.py                          # checkpoints/dev/chat.pt -> export/dev/my-ai
git clone https://github.com/ggml-org/llama.cpp ..\llama.cpp
pip install ..\llama.cpp\gguf-py sentencepiece
python to_gguf.py --llama_cpp ..\llama.cpp   # -> export/dev/my-ai-f16.gguf (~60MB)
```

**2. Shrink it (quantize):** download the latest Windows build from
<https://github.com/ggml-org/llama.cpp/releases> (the `llama-...-bin-win-cpu-x64.zip` file),
unzip it, then:
```powershell
<unzipped folder>\llama-quantize.exe export\dev\my-ai-f16.gguf export\dev\my-ai-q8_0.gguf Q8_0
```

**3. Copy `export\dev\my-ai-q8_0.gguf` (~32MB) to your phone:** USB cable, Google Drive,
OneDrive or emailing it to yourself all work.

**4. Load it in a GGUF app** such as PocketPal AI (iPhone and Android): add a model from local
files, pick the `.gguf`, then in its settings:
- **Context size: 512** (the model was trained on 512 tokens; larger values give garbage)
- The chat template is built into the file, so the app should pick up `<|user|>` /
  `<|assistant|>` automatically. If replies look wrong, set it by hand: `<|user|>` before your
  message, `<|assistant|>` before the reply, `<|endoftext|>` as the stop word.
- Temperature around 0.7-0.8.

**5. Test it in airplane mode.** When you're happy with it, copy the `.gguf` to
`checkpoints/production/`.

## Dev → Staging → Production

The project is currently in **development**: training, fine-tuning, generation and export
all use `checkpoints/dev/` and `export/dev/`. When a checkpoint passes your tests, copy it
to `checkpoints/staging/`; when a `.gguf` works well on your phone, copy it to
`checkpoints/production/`. To work from another stage later, change `STAGE` in `stage.py`. `data/`, `checkpoints/` and `export/` are
git-ignored because they're large.

## Troubleshooting

- **`torch.cuda.is_available()` is False**: you installed the CPU-only PyTorch. Uninstall torch and reinstall with the CUDA command.
- **Out of memory**: in `train.py`, halve `batch_size` and double `grad_accum` (e.g. 16 and 8).
- **Loss becomes NaN**: lower `lr_max` to `3e-4`.
- **Train loss far below val loss**: the model is memorizing; stop early or use more data.

## Progress checklist

- [ ] Phase 0: GPU verified in PyTorch
- [ ] Phase 1: `bigram.py` trains and generates
- [ ] Phase 2: `tokenizer.py` self-test passes
- [ ] Phase 3: `model.py` shows ~29.5M params, loss ~9.0
- [ ] Phase 4: `train.bin` and `val.bin` created
- [ ] Phase 5: val loss at or below ~1.5
- [ ] Phase 6: coherent stories from `generate.py`; checkpoint in staging
- [ ] Phase 7: chat mode answers in the right format
- [ ] Phase 8: GGUF runs on your phone offline; copied to production
- [ ] Phase 9: first model trained on your own data
