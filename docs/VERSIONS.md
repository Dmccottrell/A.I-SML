# Version Comparison

All versions side by side. v1 is finished, v2 is training, and v3's groundwork is built.
v3.5 and v4 are planned: their numbers are estimates and will change once v3's results are in.
Details: [V2.md](V2.md), [V3.md](V3.md), [ROADMAP.md](ROADMAP.md). Settings live in `config.py`.

**Two kinds of jumps:** v1 → v2 → v3 → v3.5 each give the model a **bigger brain and more to
read**. v4 is different: it keeps v3.5's 1B brain and adds **abilities around it** (specialist
skill packs, tools, voice, your own app). It's the jump from "a model" to "an assistant".

## Size and design

| | **v1** ✅ | **v2** 🛠️ | **v3** 🧱 | **v3.5** (planned) | **v4** (planned) |
|---|---|---|---|---|---|
| Parameters | 29.5M | 88M | 394M | **~1B** | ~1B base + skill packs (a few MB each) |
| Shape | 512 wide × 8 layers | 768 wide × 12 layers | 1024 wide × 32 layers | ~2048 wide × 22 layers | Same as v3.5 |
| Memory (context) | 512 tokens | 1,024 tokens | 2,048 tokens | 2,048 tokens | 2,048 tokens + saved notes about you |
| Vocabulary | 8,192 | 16,384 | 32,768 | 32,768 | 32,768 |
| Attention | Standard | Grouped-query (faster on phones) | Grouped-query | Grouped-query | Grouped-query |

## Training

| | **v1** | **v2** | **v3** | **v3.5** | **v4** |
|---|---|---|---|---|---|
| **Data to prepare** | 467M tokens (TinyStories) | 2.8B tokens | **12B tokens** | **~20B tokens** | Skill datasets: a few thousand examples per skill |
| Data mix | 100% children's stories | 80% web, 15% Wikipedia, 5% stories | 72% web, 15% Wikipedia, 10% Python, 3% stories | Like v3, bigger slice | Study, stories, IT help, fact checking, coding, tool use |
| Disk space | ~1 GB | ~6 GB | ~24 GB | ~40 GB | < 1 GB |
| Batch per step | 65,536 tokens | 131,072 tokens | 262,144 tokens | 262,144 tokens | Small (fine-tuning) |
| **Steps** | 20,000 | 20,000 | **45,000** | **~76,000** | ~1–2k per skill pack |
| Total reading | 1.3B tokens | 2.6B tokens | 11.8B tokens | ~20B tokens | No new pretraining |
| Reading per parameter | ~44 | ~30 | ~30 | ~20 | — |
| **Training time (RTX 4070)** | **~4 hours** | **~20 hours** | **~18 days** (~23 with gradient checkpointing) | **~3–4 months** (pausable) | **< 1 hour per skill pack** + writing the app code |
| Electricity | < $1 | ~$1 | ~$20 | ~$100–120 | < $5 |
| Chat fine-tuning | 5k single messages, ~10 min | ~105k multi-turn chats, ~1–2 hrs | Multi-turn + lookup + "I don't know" data | Same as v3 | Skill packs (LoRA) + router + tool-use examples |
| New code needed | — | Pause/resume, KV cache | Pilot runs, gradient checkpointing | 8-bit optimizer | Router, tools, voice, coding harness, app/website |

v1 read its small dataset about **2.8 times over**; v2 and v3 read their data about once, which is
better for learning general knowledge.

## Results

| | **v1** | **v2** | **v3** | **v3.5** | **v4** |
|---|---|---|---|---|---|
| Final val loss | **1.279** | ~2.8–3.0 expected | Measured when trained | Measured when trained | Same base as v3.5 |
| Phone file | 32 MB | ~94 MB | ~420 MB (Q8) or **~240 MB (Q4)** | ~1.1 GB (Q8) or **~600 MB (Q4)** | v3.5's file + a few MB per skill pack |
| Test sheet (`evaluate.py`, /20) | Only identity and story questions | Baseline (after fine-tuning) | Goal: clearly beat v2 | Goal: beat v3 | Goal: beat v3.5, plus new tests for tools and skills |

**Val losses can't be compared across versions.** Each uses a different tokenizer and different
data, and kids' stories are far easier to predict than Wikipedia and code. The test sheet
(`eval/prompts.jsonl`) is the fair comparison.

## What each version achieves

| Ability | **v1** | **v2** (expected) | **v3** (goal) | **v3.5** (goal) | **v4** (goal) |
|---|---|---|---|---|---|
| Children's stories | ✅ Good | ✅ Good | ✅ Good | ✅ Good | ✅ Story-writer skill pack |
| Grammar and fluency | Simple | Good | Better | ✅ Natural | ✅ Natural |
| General knowledge (from memory) | ❌ None | ⚠️ Basic, often wrong | ✅ Better, still imperfect | ✅ Noticeably better | ✅ Same as v3.5 |
| Accurate facts (with lookups) | ❌ | ❌ | ✅ Reads the answer from Wikipedia and cites it | ✅ Better at using what it reads | ✅ Fact-checker skill pack |
| Says "I don't know" | ❌ | ❌ | ✅ Trained to admit uncertainty | ✅ | ✅ |
| Explaining things | ❌ | ⚠️ Simple explanations | ✅ Clearer explanations | ✅ Multi-step explanations | ✅ Study-helper skill pack |
| Conversations | One message at a time | ✅ Remembers the chat | ✅ Longer conversations (2× memory) | ✅ Stays on topic longer | ✅ Remembers you between chats |
| Code | ❌ | ❌ | ⚠️ Basic Python autocomplete | ⚠️ Small functions | ✅ Coding helper: reads files, suggests fixes, runs tests |
| Answer quality and style | Basic | Basic | ✅ Improved by preference training | ✅ | ✅ Picks the right specialist per question |
| Math | ❌ | ❌ | ⚠️ Still weak | ⚠️ Simple arithmetic | ✅ **Exact**, using a calculator tool |
| Reasoning | ❌ | ❌ | ⚠️ Still weak | ⚠️ Better | ⚠️ Multi-step tasks in agent mode (still limited by 1B) |
| Tools (calculator, date, your files, reminders) | ❌ | ❌ | ❌ | ❌ | ✅ |
| Voice (talk and listen) | ❌ | ❌ | ❌ | ❌ | ✅ With small speech models alongside |
| Where you use it | PocketPal | PocketPal | PocketPal | PocketPal | ✅ **Your own website and app** |

## The v4 jump: what you should see

v3.5 → v4 won't feel like "smarter" the way v2 → v3 does. It will feel like **it can do more**:

- **Right tool for the job.** Ask "what's 1,847 × 392?" and it calls the calculator, so the
  answer is exact every time. Ask "what's today's date?" and it checks the clock instead of guessing.
- **Specialists.** A router reads your question and switches on the right skill pack: study help,
  stories, IT troubleshooting, fact checking or coding. Each pack is trained separately (under an
  hour), so adding one never breaks the others.
- **Coding help.** A small harness lets it read a file, propose a change and run the tests, in the
  same spirit as Claude Code, but for small, simple tasks.
- **It remembers you.** Saved notes ("my printer is an HP", "I'm studying biology") get looked up
  in later chats.
- **Voice.** Speak to it and hear the answer. The speech parts are small separate models (open
  speech-to-text and text-to-speech), not your model.
- **Your own app.** A website that runs the model in the visitor's browser (free hosting), then an
  Android app, with your AI's name and look.

What v4 **won't** fix: the brain is still 1B, so deep reasoning and long, complex code stay out of
reach. That's v5's job (3B).

## In one line each

- **v1:** a children's story-teller that runs on your phone
- **v2:** a mini assistant with basic general knowledge and real conversations
- **v3:** an **accurate, honest** assistant that looks facts up, admits when it doesn't know, and
  handles basic code
- **v3.5:** v3's features on a **1B brain**: the biggest model trained at home
- **v4:** a **personal assistant**: specialist skills, exact math with tools, coding help, voice,
  and your own app

## Update log

Fill in real numbers as each version finishes:

| Version | Final val loss | Test sheet | Notes |
|---|---|---|---|
| v1 | 1.279 | — | Runs on the phone (PocketPal, 32 MB) |
| v2 | | | |
| v3 | | | |
| v3.5 | | | |
| v4 | — (same base as v3.5) | | |
