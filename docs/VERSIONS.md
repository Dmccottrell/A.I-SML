# Version Comparison

All versions side by side. v1 is finished, v2 is training, and v3's groundwork is built.
Details: [V2.md](V2.md), [V3.md](V3.md), [ROADMAP.md](ROADMAP.md). Settings live in `config.py`.

## Size and design

| | **v1** ✅ | **v2** 🛠️ | **v3** 🧱 |
|---|---|---|---|
| Parameters | 29.5M | 88M | 394M |
| Shape | 512 wide × 8 layers | 768 wide × 12 layers | 1024 wide × 32 layers |
| Memory (context) | 512 tokens | 1,024 tokens | 2,048 tokens |
| Vocabulary | 8,192 | 16,384 | 32,768 |
| Attention | Standard | Grouped-query (faster on phones) | Grouped-query |

## Training

| | **v1** | **v2** | **v3** |
|---|---|---|---|
| **Data to prepare** | 467M tokens (TinyStories) | 2.8B tokens | **12B tokens** |
| Data mix | 100% children's stories | 80% web, 15% Wikipedia, 5% stories | 72% web, 15% Wikipedia, 10% Python, 3% stories |
| Disk space | ~1 GB | ~6 GB | ~24 GB |
| Batch per step | 65,536 tokens | 131,072 tokens | 262,144 tokens |
| **Steps** | 20,000 | 20,000 | **45,000** |
| Total reading | 1.3B tokens | 2.6B tokens | 11.8B tokens |
| Reading per parameter | ~44 | ~30 | ~30 |
| **Training time (RTX 4070)** | **~4 hours** | **~20 hours** | **~18 days** (~23 with gradient checkpointing) |
| Electricity | < $1 | ~$1 | ~$20 |
| Chat fine-tuning | 5k single messages, ~10 min | ~105k multi-turn chats, ~1–2 hrs | Multi-turn + lookup + "I don't know" data |

v1 read its small dataset about **2.8 times over**; v2 and v3 read their data about once, which is
better for learning general knowledge.

## Results

| | **v1** | **v2** | **v3** |
|---|---|---|---|
| Final val loss | **1.279** | ~2.8–3.0 expected | Measured when trained |
| Phone file | 32 MB | ~94 MB | ~420 MB (Q8) or **~240 MB (Q4)** |
| Test sheet (`evaluate.py`, /20) | Only identity and story questions | Baseline (after fine-tuning) | Goal: clearly beat v2 |

**Val losses can't be compared across versions.** Each uses a different tokenizer and different
data, and kids' stories are far easier to predict than Wikipedia and code. The test sheet
(`eval/prompts.jsonl`) is the fair comparison.

## What each version achieves

| Ability | **v1** | **v2** (expected) | **v3** (goal) |
|---|---|---|---|
| Children's stories | ✅ Good | ✅ Good | ✅ Good |
| Grammar and fluency | Simple | Good | Better |
| General knowledge (from memory) | ❌ None | ⚠️ Basic, often wrong | ✅ Better, still imperfect |
| Accurate facts (with lookups) | ❌ | ❌ | ✅ Reads the answer from Wikipedia and cites it |
| Says "I don't know" | ❌ | ❌ | ✅ Trained to admit uncertainty |
| Explaining things | ❌ | ⚠️ Simple explanations | ✅ Clearer explanations |
| Conversations | One message at a time | ✅ Remembers the chat | ✅ Longer conversations (2× memory) |
| Code | ❌ | ❌ | ⚠️ Basic Python autocomplete |
| Answer quality and style | Basic | Basic | ✅ Improved by preference training |
| Math and reasoning | ❌ | ❌ | ⚠️ Still weak |

## In one line each

- **v1:** a children's story-teller that runs on your phone
- **v2:** a mini assistant with basic general knowledge and real conversations
- **v3:** an **accurate, honest** assistant that looks facts up, admits when it doesn't know, and
  handles basic code

## Update log

Fill in real numbers as each version finishes:

| Version | Final val loss | Test sheet | Notes |
|---|---|---|---|
| v1 | 1.279 | — | Runs on the phone (PocketPal, 32 MB) |
| v2 | | | |
| v3 | | | |
