# Version Comparison

All versions side by side. v1 is finished, v2 is training, and v3's groundwork is built.
v3.5, v4 and v5 are planned: their numbers are estimates and will change once v3's results are in.
Details: [V2.md](V2.md), [V3.md](V3.md), [ROADMAP.md](ROADMAP.md). Settings live in `config.py`.

**Two kinds of jumps:** v1 → v2 → v3 → v3.5 each give the model a **bigger brain and more to
read**. v4 is different: it keeps v3.5's 1B brain and adds **abilities around it** (specialist
skill packs, tools, voice, your own app). It's the jump from "a model" to "an assistant".
v5 goes back to a bigger brain (3B), and it's the first version that needs the cloud.

## Size and design

| | **v1** ✅ | **v2** 🛠️ | **v3** 🧱 | **v3.5** (planned) | **v4** (planned) | **v5** (planned) |
|---|---|---|---|---|---|---|
| Parameters | 29.5M | 88M | 394M | **~1B** | ~1B base + skill packs (a few MB each) | **~3B** |
| Shape | 512 wide × 8 layers | 768 wide × 12 layers | 1024 wide × 32 layers | ~2048 wide × 22 layers | Same as v3.5 | ~3072 wide × 28 layers |
| Memory (context) | 512 tokens | 1,024 tokens | 2,048 tokens | 2,048 tokens | 2,048 tokens + saved notes about you | 4,096 tokens |
| Vocabulary | 8,192 | 16,384 | 32,768 | 32,768 | 32,768 | 65,536 |
| Attention | Standard | Grouped-query (faster on phones) | Grouped-query | Grouped-query | Grouped-query | Grouped-query |

## Training

| | **v1** | **v2** | **v3** | **v3.5** | **v4** | **v5** |
|---|---|---|---|---|---|---|
| **Data to prepare** | 467M tokens (TinyStories) | 2.8B tokens | **12B tokens** | **~20B tokens** | Skill datasets: a few thousand examples per skill | **~60B tokens** |
| Data mix | 100% children's stories | 80% web, 15% Wikipedia, 5% stories | 72% web, 15% Wikipedia, 10% Python, 3% stories | Like v3, bigger slice | Study, stories, IT help, fact checking, coding, tool use | Like v3.5, much bigger slice (plus more code and math) |
| Disk space | ~1 GB | ~6 GB | ~24 GB | ~40 GB | < 1 GB | ~120 GB |
| Batch per step | 65,536 tokens | 131,072 tokens | 262,144 tokens | 262,144 tokens | Small (fine-tuning) | ~1M tokens (across several GPUs) |
| **Steps** | 20,000 | 20,000 | **45,000** | **~76,000** | ~1–2k per skill pack | **~60,000** |
| Total reading | 1.3B tokens | 2.6B tokens | 11.8B tokens | ~20B tokens | No new pretraining | ~60B tokens |
| Reading per parameter | ~44 | ~30 | ~30 | ~20 | — | ~20 |
| **Training time (RTX 4070)** | **~4 hours** | **~20 hours** | **~18 days** (~23 with gradient checkpointing) | **~3–4 months** (pausable) | **< 1 hour per skill pack** + writing the app code | Doesn't fit in 12 GB: **cloud, ~4–7 days on 8 rented GPUs** |
| Cost | < $1 | ~$1 | ~$20 | ~$100–120 | < $5 | **~$800–2,500** cloud rental (or $0, see below) |
| Chat fine-tuning | 5k single messages, ~10 min | ~105k multi-turn chats, ~1–2 hrs | Multi-turn + lookup + "I don't know" data | Same as v3 | Skill packs (LoRA) + router + tool-use examples | Everything from v3–v4, redone on the 3B brain |
| New code needed | — | Pause/resume, KV cache | Pilot runs, gradient checkpointing | 8-bit optimizer | Router, tools, voice, coding harness, app/website | Multi-GPU training (FSDP), streaming data shards |

v1 read its small dataset about **2.8 times over**; v2 and v3 read their data about once, which is
better for learning general knowledge.

## Results

| | **v1** | **v2** | **v3** | **v3.5** | **v4** | **v5** |
|---|---|---|---|---|---|---|
| Final val loss | **1.279** | ~2.8–3.0 expected | Measured when trained | Measured when trained | Same base as v3.5 | Measured when trained |
| Phone file | 32 MB | ~94 MB | ~420 MB (Q8) or **~240 MB (Q4)** | ~1.1 GB (Q8) or **~600 MB (Q4)** | v3.5's file + a few MB per skill pack | ~3.2 GB (Q8) or **~1.8 GB (Q4)** |
| Test sheet (`evaluate.py`, /20) | Only identity and story questions | Baseline (after fine-tuning) | Goal: clearly beat v2 | Goal: beat v3 | Goal: beat v3.5, plus new tests for tools and skills | Goal: beat v4, plus harder reasoning and coding tests |

**Val losses can't be compared across versions.** Each uses a different tokenizer and different
data, and kids' stories are far easier to predict than Wikipedia and code. The test sheet
(`eval/prompts.jsonl`) is the fair comparison.

## What each version achieves

| Ability | **v1** | **v2** (expected) | **v3** (goal) | **v3.5** (goal) | **v4** (goal) | **v5** (goal) |
|---|---|---|---|---|---|---|
| Children's stories | ✅ Good | ✅ Good | ✅ Good | ✅ Good | ✅ Story-writer skill pack | ✅ Richer, longer stories |
| Grammar and fluency | Simple | Good | Better | ✅ Natural | ✅ Natural | ✅ Natural |
| General knowledge (from memory) | ❌ None | ⚠️ Basic, often wrong | ✅ Better, still imperfect | ✅ Noticeably better | ✅ Same as v3.5 | ✅ Much broader |
| Accurate facts (with lookups) | ❌ | ❌ | ✅ Reads the answer from Wikipedia and cites it | ✅ Better at using what it reads | ✅ Fact-checker skill pack | ✅ Combines several sources |
| Says "I don't know" | ❌ | ❌ | ✅ Trained to admit uncertainty | ✅ | ✅ | ✅ |
| Explaining things | ❌ | ⚠️ Simple explanations | ✅ Clearer explanations | ✅ Multi-step explanations | ✅ Study-helper skill pack | ✅ Detailed, well-organized |
| Conversations | One message at a time | ✅ Remembers the chat | ✅ Longer conversations (2× memory) | ✅ Stays on topic longer | ✅ Remembers you between chats | ✅ Longer chats (4,096 tokens) |
| Code | ❌ | ❌ | ⚠️ Basic Python autocomplete | ⚠️ Small functions | ✅ Coding helper: reads files, suggests fixes, runs tests | ✅ Real coding help: multi-file changes, explains code |
| Answer quality and style | Basic | Basic | ✅ Improved by preference training | ✅ | ✅ Picks the right specialist per question | ✅ Clearly better |
| Math | ❌ | ❌ | ⚠️ Still weak | ⚠️ Simple arithmetic | ✅ **Exact**, using a calculator tool | ✅ Exact with tools, word problems work |
| Reasoning | ❌ | ❌ | ⚠️ Still weak | ⚠️ Better | ⚠️ Multi-step tasks in agent mode (still limited by 1B) | ✅ Decent multi-step reasoning for its size |
| Tools (calculator, date, your files, reminders) | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ Uses tools more reliably |
| Voice (talk and listen) | ❌ | ❌ | ❌ | ❌ | ✅ With small speech models alongside | ✅ |
| Where you use it | PocketPal | PocketPal | PocketPal | PocketPal | ✅ **Your own website and app** | Phone (Q4) + server-hosted website |

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

## The v5 jump: what you should see

v5 is the first **genuinely capable** assistant: a 3B brain, about 3× v3.5, reading about 3× more.

- **Noticeably smarter everywhere.** Better reasoning, fewer mistakes, better code, longer and
  better-organized answers. Skill packs, tools and lookups from v3–v4 all carry over and work
  better on a bigger brain.
- **Still runs on a phone.** ~1.8 GB as Q4, which modern phones handle (slower than v2–v4).
- **Needs the cloud to train.** 3B doesn't fit in the RTX 4070's 12 GB for training. Two routes:

| Route | How | Time | Cost |
|---|---|---|---|
| **From scratch** (fully yours) | Rent cloud GPUs (Vast.ai interruptible is cheapest; `train.py` already resumes). v3.5's 1B run at home is the rehearsal | ~4–7 days on 8 GPUs | ~$800–2,500 |
| **Free TPU grant** | Apply to Google's TPU Research Cloud (code would need porting) | Varies | $0 if approved |
| **Fine-tune an open 3B** | QLoRA on the RTX 4070, then add everything from v3–v4 | Hours | ~$0 |

The fine-tune route gets a smart 3B cheaply, but its brain isn't trained by you. The from-scratch
route keeps the project's rule of "100% trained by you".

What v5 **still won't** be: Claude or ChatGPT. Those are hundreds of times bigger. A 3B model is
a capable personal assistant, not a replacement for them.

## In one line each

- **v1:** a children's story-teller that runs on your phone
- **v2:** a mini assistant with basic general knowledge and real conversations
- **v3:** an **accurate, honest** assistant that looks facts up, admits when it doesn't know, and
  handles basic code
- **v3.5:** v3's features on a **1B brain**: the biggest model trained at home
- **v4:** a **personal assistant**: specialist skills, exact math with tools, coding help, voice,
  and your own app
- **v5:** a **genuinely capable** 3B assistant: the first version trained in the cloud

## Update log

Fill in real numbers as each version finishes:

| Version | Final val loss | Test sheet | Notes |
|---|---|---|---|
| v1 | 1.279 | — | Runs on the phone (PocketPal, 32 MB) |
| v2 | | | |
| v3 | | | |
| v3.5 | | | |
| v4 | — (same base as v3.5) | | |
| v5 | | | |
