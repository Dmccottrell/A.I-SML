# Version Comparison

All versions side by side. v1 and v2 are finished and run on the phone, and v3's phase 1 and 2 code is built and tested.
v3.5, v4, v5, v6 and v6.5 are planned: their numbers are estimates and will change once v3's results are in.
Details: [V2.md](V2.md), [V3.md](V3.md), [ROADMAP.md](ROADMAP.md). Settings live in `config.py`.

**Two kinds of jumps:** v1 → v2 → v3 → v3.5 each give the model a **bigger brain and more to
read**. v4 is different: it keeps v3.5's ~1.05B brain and adds **abilities around it** (specialist
skill packs, tools, voice, your own app). It's the jump from "a model" to "an assistant".
v5 goes back to a bigger brain (3B), and it's the first version that needs the cloud.
v6 (5B) and v6.5 (7B) keep growing toward medium size, mainly for the PC and online mode.

## Size and design

|  | **v1** ✅ | **v2** ✅ | **v3** 🧱 | **v3.5** (planned) | **v4** (planned) | **v5** (planned) | **v6** (planned) | **v6.5** (planned) |
|---|---|---|---|---|---|---|---|---|
| Parameters | 29.5M | 88M | 394M | **~1.05B** | ~1.05B base + skill packs (a few MB each) | **~3B** | **~5B** | **~7B** |
| Shape | 512 wide × 8 layers | 768 wide × 12 layers | 1024 wide × 32 layers | 2048 wide × 22 layers | Same as v3.5 | ~3072 wide × 28 layers | ~3584 wide × 36 layers | 4096 wide × 32 layers |
| Memory (context) | 512 tokens | 1,024 tokens | 2,048 tokens | 2,048 tokens | 2,048 tokens + saved notes about you | 4,096 tokens | 8,192 tokens | 8,192 tokens |
| Vocabulary | 8,192 | 16,384 | 32,768 | 32,768 | 32,768 | 65,536 | 65,536 | 65,536 |
| Attention | Standard | Grouped-query (faster on phones) | Grouped-query | Grouped-query | Grouped-query | Grouped-query | Grouped-query | Grouped-query |

## Training

|  | **v1** | **v2** | **v3** | **v3.5** | **v4** | **v5** | **v6** | **v6.5** |
|---|---|---|---|---|---|---|---|---|
| **Data to prepare** | 467M tokens (TinyStories) | 2.8B tokens | **12B + 1.3B anneal** (done in 1h26m) | **30B + 3B anneal** (~3.5–5 hours) | Skill datasets: a few thousand examples per skill | **~60B tokens** | **~100B tokens** (minimum) | **~140B tokens** (minimum) |
| Data mix | 100% children's stories | 80% web, 15% Wikipedia, 5% stories | 63% web, 20% Wikipedia, 10% Python, 5% math, 2% stories | 63% web, 15% Wikipedia, 13% code in **several languages** (Python, JavaScript, HTML/CSS, SQL, shell, C#/Java), 7.5% math, 1.5% stories; web from FineWeb-Edu's bigger `sample-100BT` slice so nothing repeats | Study, stories, IT help, fact checking, coding, tool use | Like v3.5, much bigger slice (plus more code and math) | Like v5 (web, Wikipedia, multi-language code, math), bigger slice | Same as v6, bigger slice |
| Disk space | ~1 GB | ~6 GB | ~27 GB | ~66 GB | < 1 GB | ~120 GB | ~200 GB | ~280 GB |
| Batch per step | 65,536 tokens | 131,072 tokens | 262,144 tokens | 262,144 tokens | Small (fine-tuning) | ~1M tokens (across several GPUs) | ~1M tokens (across several GPUs) | ~1M tokens (across several GPUs) |
| **Steps** | 20,000 | 20,000 | **45,000** | **~115,000** | ~1–2k per skill pack | **~60,000** | **~100,000** | **~140,000** |
| Total reading | 1.3B tokens | 2.6B tokens | 11.8B tokens | 30B tokens | No new pretraining | ~60B tokens | ~100B tokens | ~140B tokens |
| Reading per parameter | ~44 | ~30 | ~30 | ~29 | — | ~20 | ~20 | ~20 |
| **Training time (RTX 4070)** | **~4 hours** | **~17.5–18 hours** (measured; data prep ~30 min) | **~15–18 days** (estimated from v2: ~20× the work; the pilot run gives the exact time) | **~4.5–5.5 months** (pausable) | **< 1 hour per skill pack** + writing the app code | Doesn't fit in 12 GB: **cloud, ~4–7 days on 8 rented GPUs** | Cloud: **~11 days on 8 GPUs** (~2,000 GPU-hours) | Cloud: **~3 weeks on 8 GPUs** (~4,000 GPU-hours) |
| Cost | < $1 | ~$1 | ~$20 | ~$150–180 | < $5 | **~$800–2,500** cloud rental (or $0, see below) | **~$4,000–6,000** (less if grown from v5 or with a grant) | **~$8,000–12,000** (less if grown from v6 or with a grant) |
| Chat fine-tuning | 5k single messages, ~10 min | ~105k multi-turn chats, ~1–2 hrs | Multi-turn + lookup + "I don't know" data | Same as v3 | Skill packs (LoRA) + router + tool-use examples | Everything from v3–v4, redone on the 3B brain | Same lessons; QLoRA fits on the 4070 | Same lessons; QLoRA fits on the 4070 |
| Teacher model (a bigger open AI helping) | — | — (its chat data was partly written by bigger AIs) | **Yes:** a ~7B open model on the 4070 writes lookup and "I don't know" examples and grades answers for DPO | Same, plus worked step-by-step math problems for the chat lessons | Writes skill-pack and tool-use examples | Same, bigger teacher possible in the cloud | Same; the bigger tiers teach the smaller ones | Same |
| Main tools added | PyTorch, CUDA, llama.cpp | Hugging Face `datasets` | Keyword search (SQLite FTS5), FAISS (optional), lm-evaluation-harness, TensorBoard, 8-bit optimizer (optional) | CPU offload for the optimizer (bitsandbytes as a fallback) | LoRA, tool calling, web search, Whisper + Piper (voice) | FSDP (multi-GPU) | vLLM or llama.cpp server (online mode) | Same as v6 |
| New code needed | — | Pause/resume, KV cache | Pilot runs, gradient checkpointing, lookup index, teacher script, DPO | CPU offload for the optimizer, multi-language code data | Router, tools, voice, coding harness, app/website | Multi-GPU training (FSDP), streaming data shards | Model growth (up-scaling from v5), 8k-token training, server setup | Growth from v6 |

v1 read its small dataset about **2.8 times over**; v2, v3 and v3.5 read their data about once, which is
better for learning general knowledge. v3.5 needs ~18.9B tokens of web text, more than the 10B in
the FineWeb-Edu slice v2 and v3 use, so it switches to the bigger `sample-100BT` slice. Its 15%
Wikipedia share (~4.5B tokens) is about one full read of English Wikipedia. v3.5 reads 30B tokens
(~29 per parameter) rather than the "efficient" 20B: a better model at the same size and phone speed.
Full breakdown: [ROADMAP.md](ROADMAP.md#v35s-data-33b-tokens-to-prepare).

**Fair testing:** worked math problems for the chat lessons are written by the teacher model. The
real GSM8K questions (a well-known math test) are kept for testing only, never for training.

## Results

|  | **v1** | **v2** | **v3** | **v3.5** | **v4** | **v5** | **v6** | **v6.5** |
|---|---|---|---|---|---|---|---|---|
| Final val loss | **1.279** | **2.929** (best), 2.984 at the last step | Measured when trained | Measured when trained | Same base as v3.5 | Measured when trained | Measured when trained | Measured when trained |
| Phone file | 32 MB | **89 MB** | ~420 MB (Q8) or **~240 MB (Q4)** | ~1.1 GB (Q8) or **~650 MB (Q4)** | v3.5's file + a few MB per skill pack | ~3.2 GB (Q8) or **~1.8 GB (Q4)** | ~3 GB (Q4): high-end phones only | ~4–4.5 GB (Q4): mainly PC and server |
| Test sheet (`evaluate.py`, /20) | Only identity and story questions | **18/20** (baseline) | Goal: clearly beat v2 | Goal: beat v3 | Goal: beat v3.5, plus new tests for tools and skills |  | Goal: beat v5 | Goal: beat v6 |
| v3 test sheet (`prompts_v3.jsonl`, /41) | — | Run to set the baseline* | Goal: clearly beat v2, most of all on facts_hard, instructions, topic_switch, honesty, correction |  |  |  |  |  |
| Phone speed (PocketPal, Q8_0) | — | **~210–245 tokens/s**, first word in <0.1 s | Slower (4.5× bigger); measured when done |  |  |  | Slow on phones; fast on PC | PC and server |
| HellaSwag (`exam.py`, random = 25%) | — | **28.4%** (baseline) | Goal: ~33–38% | Goal: higher than v3 | Same base as v3.5 | Goal: beat v4, plus harder reasoning and coding tests | Goal: beat v5 | Goal: beat v6 |

**Val losses can't be compared across versions.** Each uses a different tokenizer and different
data, and kids' stories are far easier to predict than Wikipedia and code. The test sheet
(`eval/prompts.jsonl`) is the fair comparison.

\* v2 on v3's bigger test sheet: `python evaluate.py --version v2 --prompts eval/prompts_v3.jsonl`.
It adds the mistakes found on the phone, so v2 is expected to score low on the new categories.

## v2 on the phone: what testing taught us

| Test | v2's answer | Fixed by |
|---|---|---|
| "What is the capital of Illinois?" | **Paris**, then **Chicago** after better settings (it's Springfield) | v3 lookups |
| "That's wrong." (after Paris) | Repeated Paris three times | v3 correction and "I don't know" lessons |
| "List 3 fruits" | 10 looping items → **exactly 3** after setting repeat penalty 1.25 | Settings + v3 exact-instruction lessons |
| "What is the largest planet?" | **Mercury** → **Jupiter** at temperature 0.4–0.5 | Settings |
| Spaghetti question after Illinois | Answered about Illinois again | v3 topic-switch lessons + 2× memory |
| "What can you do?" | Same paragraph as "Who are you?" | v3 separate identity answers |

**Half of the problems were the phone app's settings, not the model.** The tested settings are in
[V2.md](V2.md): temperature 0.4–0.5, repeat penalty 1.25, max tokens 256, a new chat per topic.

## What each version achieves

| Ability | **v1** | **v2** (expected) | **v3** (goal) | **v3.5** (goal) | **v4** (goal) | **v5** (goal) | **v6** (goal) | **v6.5** (goal) |
|---|---|---|---|---|---|---|---|---|
| Children's stories | ✅ Good | ✅ Good | ✅ Good | ✅ Good | ✅ Story-writer skill pack | ✅ Richer, longer stories | ✅ Long, well-written stories | ✅ Long, well-written stories |
| Grammar and fluency | Simple | Good | Better | ✅ Natural | ✅ Natural | ✅ Natural | ✅ Natural | ✅ Natural |
| General knowledge (from memory) | ❌ None | ⚠️ Basic, often wrong | ✅ Better, still imperfect | ✅ Noticeably better | ✅ Same as v3.5 | ✅ Much broader | ✅ Broad | ✅ Broadest of all versions |
| Accurate facts (with lookups) | ❌ | ❌ | ✅ Reads the answer from Wikipedia and cites it | ✅ Better at using what it reads | ✅ Fact-checker skill pack | ✅ Combines several sources | ✅ Combines sources, handles long documents | ✅ Combines sources, handles long documents |
| Says "I don't know" | ❌ | ❌ | ✅ Trained to admit uncertainty | ✅ | ✅ | ✅ | ✅ | ✅ |
| Explaining things | ❌ | ⚠️ Simple explanations | ✅ Clearer explanations | ✅ Multi-step explanations | ✅ Study-helper skill pack | ✅ Detailed, well-organized | ✅ Handles harder topics | ✅ Handles harder topics |
| Conversations | One message at a time | ✅ Remembers the chat | ✅ Longer conversations (2× memory) | ✅ Stays on topic longer | ✅ Remembers you between chats | ✅ Longer chats (4,096 tokens) | ✅ Long chats (8,192 tokens) | ✅ Long chats (8,192 tokens) |
| Code | ❌ | ❌ | ⚠️ Basic Python autocomplete | ⚠️ Small functions, several languages | ✅ Coding helper (agentic, small tasks): reads files, suggests fixes, runs tests in a loop inside a sandbox | ✅ Real coding help: multi-file changes, explains code | ✅ Stronger coding help across languages | ✅ Best coding help of all versions |
| Answer quality and style | Basic | Basic | ✅ Improved by preference training | ✅ | ✅ Picks the right specialist per question | ✅ Clearly better | ✅ Clearly better | ✅ Best |
| Math | ❌ | ❌ | ⚠️ Some step-by-step math (5% math reading), still error-prone | ⚠️ Better: also learns from worked math problems, still error-prone | ✅ **Exact**, using a calculator tool | ✅ Exact with tools, word problems work | ✅ Exact with tools, harder word problems | ✅ Exact with tools, harder word problems |
| Reasoning | ❌ | ❌ | ⚠️ Still weak | ⚠️ Better | ⚠️ Multi-step tasks in agent mode (still limited by 1B) | ✅ Decent multi-step reasoning for its size | ✅ Stronger multi-step reasoning | ✅ Strongest: closest to a mini Claude for everyday tasks |
| Tools (calculator, date, your files, reminders) | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ Uses tools more reliably | ✅ | ✅ |
| Voice (talk and listen) | ❌ | ❌ | ❌ | ❌ | ✅ With small speech models alongside | ✅ | ✅ | ✅ |
| Where you use it | PocketPal | PocketPal | PocketPal | PocketPal | ✅ **Your own website and app** | Phone (Q4) + server-hosted website | PC, high-end phones, the app's online mode | PC and server (the app's online brain) |
| Offline / online | Offline | Offline | Offline (lookups from a saved Wikipedia copy) | Offline | ✅ **Both:** offline by default, online adds live web search; switches automatically | ✅ Both: offline on the phone (Q4), online can use the 3B on a server | ✅ Both: offline on high-end phones and PCs, online as the server model | ✅ Both: mainly the online brain on a server; offline on the PC |

## v3 up close: lookups and the teacher

v3 phase 2 turns the model into a **system**: our code finds facts, and the model learns to answer
from them. **Built and tested** (`wiki_index.py`, `make_teacher_data.py` with Qwen2.5-7B-Instruct as
the teacher, `make_chat_data_v3.py`); it runs on your PC before and after pretraining (see [V3.md](V3.md)).

### What a chat will look like

```
You:  When did the Titanic sink?

      (our code searches the saved Wikipedia copy and finds:
       "RMS Titanic ... sank in the early hours of 15 April 1912 after striking an iceberg...")

AI:   The Titanic sank on 15 April 1912, a few hours after hitting an iceberg in the
      North Atlantic. (Source: Wikipedia, "RMS Titanic")
```

And when the notes don't have the answer:

```
You:  What did I have for breakfast?
AI:   I don't know. That isn't something I can look up, and I don't have any notes about it.
```

### How it works

```
question ─► search the Wikipedia index ─► top 3 passages ("notes")
                                                │
            <|user|> Notes: ... Question: ... <|assistant|>  ─► model answers from the notes
```

The model is trained on examples in exactly that shape, so it learns to **read the notes first**,
use them, name the source, and say "I don't know" when the notes don't cover the question.

### Where the training examples come from (the teacher)

| Step | What happens | Where | Time and cost |
|---|---|---|---|
| 1. Build the index | Wikipedia split into passages, stored in a SQLite keyword-search index | PC | A few hours, free |
| 2. Pick questions | Thousands of questions, from smol-smoltalk and generated from Wikipedia titles | PC | Minutes |
| 3. Teacher answers | A ~7B open model (llama.cpp) reads the notes and writes the answer. Some notes are swapped for unrelated ones, so the right answer is "I don't know" | PC (4070) | ~1–2 days for ~50,000 answers, a few dollars of power |
| 4. Filter | Drop answers that are wrong, too long, or don't use the notes | PC | Minutes |
| 5. Fine-tune | The new examples join v3's chat data | PC | A few hours |
| 6. DPO (phase 3) | v3 answers each question twice; the teacher picks the better one; v3 learns from the pairs | PC | ~1–2 days |

**On the phone:** the full Wikipedia index is ~20+ GB, so the phone gets a smaller one (the opening
sections of the most-read articles, ~1–2 GB). The PC version uses the full index.

## The v4 jump: what you should see

v3.5 → v4 won't feel like "smarter" the way v2 → v3 does. It will feel like **it can do more**:

- **Right tool for the job.** Ask "what's 1,847 × 392?" and it calls the calculator, so the
  answer is exact every time. Ask "what's today's date?" and it checks the clock instead of guessing.
- **Specialists.** A router reads your question and switches on the right skill pack: study help,
  stories, IT troubleshooting, fact checking or coding. Each pack is trained separately (under an
  hour), so adding one never breaks the others.
- **Coding help.** A small harness lets it work in a loop: read a file, propose a change, run the
  tests, see the result and try again, inside a safe sandbox. It's in the same spirit as Claude Code,
  but only for small, simple tasks (a ~1B model can't do the big benchmark tasks). Its memory is the
  limit: 2,048 tokens fills up after about two small files. Details: [ROADMAP.md](ROADMAP.md#agentic-coding-a-coding-helper-that-works-in-a-loop).
- **It remembers you.** Saved notes ("my printer is an HP", "I'm studying biology") get looked up
  in later chats.
- **Voice.** Speak to it and hear the answer. The speech parts are small separate models (open
  speech-to-text and text-to-speech), not your model.
- **Offline and online.** Works fully offline by default. When connected and switched on, it adds
  live web search, and falls back to offline automatically when the connection drops.
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
- **Needs the cloud to train.** 3B doesn't fit in the RTX 4070's 12 GB for training. Three routes:

| Route | How | Time | Cost |
|---|---|---|---|
| **From scratch** (fully yours) | Rent cloud GPUs (Vast.ai interruptible is cheapest; `train.py` already resumes). v3.5's 1B run at home is the rehearsal | ~4–7 days on 8 GPUs | ~$800–2,500 |
| **Free TPU grant** | Apply to Google's TPU Research Cloud (code would need porting) | Varies | $0 if approved |
| **Fine-tune an open 3B** | QLoRA on the RTX 4070, then add everything from v3–v4 | Hours | ~$0 |

The fine-tune route gets a smart 3B cheaply, but its brain isn't trained by you. The from-scratch
route keeps the project's rule of "100% trained by you".

### PC + cloud: the cheapest from-scratch plan

The RTX 4070 can't share the 3B **pretraining** run the way v2/v3 can move `latest.pt` between
machines: training 3B needs ~40–50 GB of GPU memory (the card has 12 GB), and even if it fit, the
run would take well over a year at home. So the split is by **job**, not by time:

| Job | Where | Why |
|---|---|---|
| Write and test the multi-GPU code on small models | 🏠 PC | Debugging on rented GPUs is where money gets wasted |
| Data prep (~60B tokens, ~120 GB) | 🏠 PC | CPU work that takes days, free at home. Upload the files when done (a few hours to overnight) |
| Pilot run (a shortened 3B, a few hundred steps) | 🏠 PC | Catches bugs before any money is spent |
| **Pretraining** | ☁️ Cloud | ~4–7 days on 8 GPUs: the only part you pay for |
| Chat fine-tuning, "I don't know" data, DPO, skill packs | 🏠 PC | These use LoRA (small add-ons), which fits a 3B model in 12 GB |
| Testing, export to GGUF, quantizing | 🏠 PC | Free |

About 95% of the steps happen at home; the cloud is one rental.

**The rental can be split over time too.** Rent 1–2 days, save `latest.pt`, stop paying, and
resume later (`train.py` already does this). The catch: a 3B checkpoint is ~35–40 GB with the
optimizer, so between rentals you either pay a little for cloud storage or download it (a few
hours).

What v5 **still won't** be: Claude or ChatGPT. Those are hundreds of times bigger. A 3B model is
a capable personal assistant, not a replacement for them.

## Beyond v5: v6 and v6.5 (future)

Planned later, after v5 (they're also in the main tables above). The phone keeps a small model for
offline use; these power the PC and the app's online mode. Details: [ROADMAP.md](ROADMAP.md#v6-and-v65-bigger-small-5b--7b).

| | **v5** | **v6** | **v6.5** |
|---|---|---|---|
| Class | Small | Bigger small | Borderline medium |
| Brain | ~3B | **~5B** | **~7B** |
| Shape | ~3072 wide × 28 layers | ~3584 wide × 36 layers | 4096 wide × 32 layers |
| Memory (context) | 4,096 tokens | 8,192 tokens | 8,192 tokens |
| Vocabulary | 65,536 | 65,536 (same, so it can grow from v5) | 65,536 |
| Reading (minimum) | ~60B tokens | ~100B tokens | ~140B tokens |
| Disk space | ~120 GB | ~200 GB | ~280 GB |
| Training (cloud) | ~4–7 days on 8 GPUs | ~11 days on 8 GPUs | ~3 weeks on 8 GPUs |
| Cost | ~$800–2,500 | ~$4,000–6,000 | ~$8,000–12,000 |
| Cheaper routes | PC + cloud split, TPU grant, or fine-tune an open 3B | Grow from v5, grant, or fine-tune an open 5–8B | Grow from v6, grant, or fine-tune an open 7–8B |
| Phone file (Q4) | ~1.8 GB | ~3 GB (high-end phones, slowly) | ~4–4.5 GB (mainly PC and server) |
| Main role | Phone + PC | Best offline model for high-end phones; PC; online mode | PC and the app's online brain |
| What you should see | Genuinely capable assistant | Clearly stronger reasoning, writing and coding; longer documents | The strongest version: closest to a "mini Claude" for everyday tasks, still far smaller than the real ones |

## In one line each

- **v1:** a children's story-teller that runs on your phone
- **v2:** a mini assistant with basic general knowledge and real conversations
- **v3:** an **accurate, honest** assistant that looks facts up, admits when it doesn't know, and
  handles basic code
- **v3.5:** v3's features on a **~1.05B brain** that reads 30B tokens: the biggest model trained at home
- **v4:** a **personal assistant**: specialist skills, exact math with tools, coding help, voice,
  and your own app
- **v5:** a **genuinely capable** 3B assistant: the first version trained in the cloud
- **v6:** a **5B bigger small** model: stronger reasoning and coding, powering the PC and online mode
- **v6.5:** a **7B borderline medium** model: the strongest version and the app's online brain

## Update log

Fill in real numbers as each version finishes:

| Version | Final val loss | Test sheet | Notes |
|---|---|---|---|
| v1 | 1.279 | — | Runs on the phone (PocketPal, 32 MB) |
| v2 | 2.929 best, 2.984 final | 18/20 (identity 2/2, facts 7/8, explain 5/5, advice 2/2, writing 1/1, stories 1/2) | HellaSwag 28.4% (ckpt.pt), about GPT-2 (124M) level. 20,000 steps at ~3.5 s/step on the RTX 4070; chat fine-tuning ~1.5 hours. Phone: 89 MB, ~210–245 tokens/s. The test sheet checks key words, so answers can pass with wrong details. Phone tests found wrong rare facts (Illinois), no self-correction, topic stickiness and settings problems (see above) |
| v3 | | | Data ready: 12.0B training tokens + 1.3B anneal tokens + 10M val; 222 documents with test questions removed (193 web, 14 math, 10 top-rated web, 5 anneal math); prepared in 1 hour 26 minutes (~2.6M tokens/s on average) |
| v3.5 | | | |
| v4 | — (same base as v3.5) | | |
| v5 | | | |
| v6 | | | |
| v6.5 | | | |
