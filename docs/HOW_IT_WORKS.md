# How It Works: A Code Map

A guide for junior and intermediate programmers joining this project. It explains
how the files fit together. Each `.py` file also has a header docstring and a
docstring on every function with the details.

## The one idea behind everything

A language model does one thing: **given some tokens, predict the next token.**
Writing text is just that prediction repeated in a loop. Training is just
adjusting numbers until the predictions get good.

```
guess the next token -> measure how wrong (loss) -> compute gradients -> nudge weights -> repeat
```

`bigram.py` shows this loop in about 40 lines. Every other file is a bigger
version of it.

## The pipeline

```
 input text
     │
     ▼
 tokenizer.py ──────── text  <->  token IDs        (trained by prepare_data.py)
     │
     ▼
 prepare_data.py ───── data/train.bin, data/val.bin (all stories as token IDs)
     │
     ▼
 train.py  + model.py  checkpoints/dev/ckpt.pt     (the pretrained model)
     │
     ├──► generate.py  write stories / chat
     │
     ▼
 finetune.py ───────── checkpoints/dev/chat.pt     (learns the chat format)
     │
     ▼
 export_hf.py ──────── export/dev/my-ai/           (standard Llama files)
     │
     ▼
 to_gguf.py ────────── export/dev/my-ai-f16.gguf   (runs on phones via llama.cpp)
```

## Files at a glance

| File | Type | Key pieces | Read it when you want to understand... |
|---|---|---|---|
| `stage.py` | settings | `STAGE`, `CKPT_DIR`, `EXPORT_DIR` | where files are saved (dev / staging / production) |
| `bigram.py` | script | one table `W` | the training loop in its simplest form |
| `tokenizer.py` | library | `BPETokenizer.train/encode/decode/save/load`, `merge_ids` | how text becomes numbers |
| `model.py` | library | `TinyLM`, `Block`, `Attention`, `FeedForward`, `RMSNorm`, RoPE helpers | the neural network itself |
| `prepare_data.py` | script | `encode_split`, `encode_story`, `init_worker` | how the dataset is built |
| `train.py` | script | `get_batch`, `get_lr`, `estimate_loss`, main loop | how the model learns |
| `generate.py` | script | `run`, chat loop | how the model writes text |
| `finetune.py` | script | `make_batch`, loss mask | how the model learns to chat |
| `export_hf.py` | script | `export_tokenizer`, `export_model`, `bytes_to_unicode` | how files are converted to the standard format |
| `to_gguf.py` | script | patch of `get_vocab_base_pre` | how the phone file is made |

**Library** files are imported by others. **Script** files are run with `python <file>.py`.

## Suggested reading order

1. `bigram.py`: the whole idea in 40 lines.
2. `tokenizer.py`: start with `merge_ids`, then `train`, then `encode`.
3. `model.py`: read bottom-up: `TinyLM.forward` first, then `Block`, then `Attention` and `FeedForward`.
4. `train.py`: `get_batch` (note the one-token shift), then the main loop.
5. `generate.py`, then `TinyLM.generate` in `model.py`.
6. `finetune.py`: note how the loss mask ignores the question.

## Tensor shapes cheat sheet

Most bugs in ML code are shape bugs. These letters are used in comments:

| Letter | Meaning | Default |
|---|---|---|
| `B` | batch size (sequences processed at once) | 32 |
| `T` | sequence length (tokens per sequence) | up to 512 |
| `C` / `dim` | vector size per token | 512 |
| `heads` | attention heads | 8 |
| `head_dim` | size per head (`dim / heads`) | 64 |
| `V` / `vocab_size` | number of possible tokens | 8192 |

```
token IDs (B, T) → embed → (B, T, 512) → 8 × Block → (B, T, 512) → lm_head → logits (B, T, 8192)
```

## Glossary

- **Token**: a piece of text (a word or part of a word) with an integer ID.
- **Embedding**: a learned vector (list of 512 numbers) that represents a token.
- **Logits**: raw scores for every possible next token. Softmax turns them into probabilities.
- **Loss (cross-entropy)**: how surprised the model was by the correct answer. Lower is better. Random guessing ≈ 9.0.
- **Gradient**: for each weight, which direction to nudge it to lower the loss. `loss.backward()` computes it.
- **Optimizer (AdamW)**: the rule that applies the nudges.
- **Learning rate**: how big each nudge is.
- **Checkpoint**: a saved copy of the model's weights (`.pt` file).
- **Train vs. val loss**: loss on data the model learns from vs. data it never sees. If they drift apart, it's memorizing.
- **Pretraining**: learning language from lots of raw text (`train.py`).
- **Fine-tuning**: short extra training to teach a specific behavior, like chat (`finetune.py`).
