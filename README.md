# A.I-SML — Build Your Own Small Language Model

A ~30M-parameter Llama-style language model built completely from scratch: your own
tokenizer, your own transformer, your own training run. No pretrained weights. The
finished model (~32MB as Q8_0 GGUF) runs on your PC and fully offline on your phone.

## Files

| File | Phase | What it does |
|---|---|---|
| `bigram.py` | 1 | Warm-up: tiny character model that learns from `input.txt` |
| `tokenizer.py` | 2 | Byte-level BPE tokenizer written from scratch |
| `model.py` | 3 | The transformer (RMSNorm, RoPE, attention, SwiGLU) |
| `prepare_data.py` | 4 | Downloads TinyStories, trains the tokenizer, writes `data/train.bin` / `val.bin` |
| `train.py` | 5 | Pretraining loop (run overnight on your GPU) |
| `generate.py` | 6 | Generate text or chat with your model |
| `finetune.py` | 7 | Teach it a chat format using `data/chat.jsonl` |
| `export_hf.py` | 8 | Save in standard Llama layout (safetensors + tokenizer.json) |
| `to_gguf.py` | 8 | Convert to GGUF with llama.cpp for phone apps |
| `examples/chat_sample.jsonl` | 7 | Example fine-tuning data format |

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

Then promote a good checkpoint: copy `checkpoints/dev/ckpt.pt` to `checkpoints/staging/`.

## Fine-tuning and phone (Phases 7-8)

```bash
copy examples\chat_sample.jsonl data\chat.jsonl     # then add a few thousand of your own examples
python finetune.py
python generate.py --ckpt checkpoints/dev/chat.pt --chat
# copy chat.pt to checkpoints/staging/, then:
python export_hf.py --ckpt checkpoints/staging/chat.pt --out export/my-ai
git clone https://github.com/ggml-org/llama.cpp ../llama.cpp
pip install ../llama.cpp/gguf-py sentencepiece
python to_gguf.py --llama_cpp ../llama.cpp --model export/my-ai --out my-ai-f16.gguf
llama-quantize my-ai-f16.gguf my-ai-q8_0.gguf Q8_0
```

In your phone app (e.g. PocketPal AI), set the chat template to `<|user|>` before your
message and `<|assistant|>` before the reply, with `<|endoftext|>` as the stop token.

## Dev → Staging → Production

Training always writes to `checkpoints/dev/`. Copy checkpoints you've tested and like to
`checkpoints/staging/`. Export only from staging, and put the `.gguf` that works well on
your phone in `checkpoints/production/`. `data/`, `checkpoints/` and `export/` are
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
