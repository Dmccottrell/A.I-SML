# A.I-SML — Build Your Own Small Language Model

A ~30M-parameter Llama-style language model built completely from scratch: your own
tokenizer, your own transformer, your own training run. No pretrained weights. The
finished model (~32MB as Q8_0 GGUF) runs on your PC and fully offline on your phone.

> **Current stage: DEVELOPMENT.** Every script reads and writes only `checkpoints/dev/`
> and `export/dev/` (set in `stage.py`). Nothing touches staging or production until you
> promote it by hand.

## Files

| File | Phase | What it does |
|---|---|---|
| `stage.py` | all | Sets the working stage (`dev`) and its folders |
| `bigram.py` | 1 | Warm-up: tiny character model that learns from `input.txt` |
| `tokenizer.py` | 2 | Byte-level BPE tokenizer written from scratch |
| `model.py` | 3 | The transformer (RMSNorm, RoPE, attention, SwiGLU) |
| `prepare_data.py` | 4 | Downloads TinyStories, trains the tokenizer, writes `data/train.bin` / `val.bin` |
| `train.py` | 5 | Pretraining loop (run overnight on your GPU) |
| `generate.py` | 6 | Generate text or chat with your model |
| `make_chat_data.py` | 7 | Builds `data/chat.jsonl` fine-tuning examples automatically |
| `finetune.py` | 7 | Teach it a chat format using `data/chat.jsonl` |
| `export_hf.py` | 8 | Save in standard Llama layout (safetensors + tokenizer.json) |
| `to_gguf.py` | 8 | Convert to GGUF with llama.cpp for phone apps |
| `examples/chat_sample.jsonl` | 7 | Example fine-tuning data format |

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
