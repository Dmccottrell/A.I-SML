# Roadmap

Where this project is going, and why. Plans past v2 are a **direction, not a promise**: each
version's test-sheet results decide what the next one focuses on.

## At a glance

| Version | Theme | Brain | Main new abilities | Where it trains | Cost |
|---|---|---|---|---|---|
| **v1** ✅ | Learn the pipeline | 30M | Tells children's stories; runs offline on the phone | RTX 4070, 4 hours | $0 |
| **v2** 🛠️ | Knowledge | 88M | General Q&A, explanations, multi-turn chat | RTX 4070, ~20 hours | $0 |
| **v3** | Accuracy | ~400M | Looks things up (RAG), says "I don't know", preference training, basic code | RTX 4070, ~2.5–3 weeks | ~$20 electricity |
| **v3.5** | Scale at home | **1B** | Same features as v3 on a much bigger brain | RTX 4070, ~3–4 months (pausable) | ~$100–120 electricity |
| **v4** | Abilities | Best base so far (1B) | Specialist skill packs + router, tools, voice, own app | RTX 4070 | $0 |
| **v5** | Scale | 3B | Genuinely capable assistant | Cloud (from scratch) **or** RTX 4070 (fine-tune an open 3B) | ~$1,500+ **or** $0 |
| **v6** | Bigger small | **5B** | Stronger reasoning, coding and knowledge; 8k memory; powers online mode | Cloud (or grown from v5) | ~$4,000–6,000 (less with growth or a grant) |
| **v6.5** | Borderline medium | **7B** | The best model for PC and server; the app's online brain | Cloud (or grown from v6) | ~$8,000–12,000 (less with growth or a grant) |

Guiding rules:
- **Cheapest over fastest.** Time isn't a constraint, so everything that fits on the RTX 4070
  trains there (electricity is far cheaper than cloud rental). Only 3B needs the cloud.
- **Grow about 3× per step, with pilot runs.** Before each long run, train 5–10% of the steps
  first to catch problems cheaply.
- **Better data beats a bigger model.** Most quality gains come from what the model reads.
- **Measure everything.** Every version is scored on `eval/prompts.jsonl` (`evaluate.py`) and
  compared with the last.
- **Dev → staging → production.** New versions never overwrite the one you rely on.

---

## Tools by version

Free, open-source tools the wider AI world uses (PyTorch is the same core library OpenAI and
Meta use). Each one is added when a version actually needs it, and several can start in v3.

| Tool | What it does | Starts in | Notes |
|---|---|---|---|
| **PyTorch + CUDA** | The math engine and the GPU layer | ✅ v1 | Already the core of the project |
| **Hugging Face `datasets`** | Streams huge public datasets | ✅ v2 | Already used by the data scripts |
| **llama.cpp / GGUF** | Runs the model on phones and PCs | ✅ v1 | Already used for the phone file |
| **Keyword search** (SQLite FTS5 / BM25) | Finds the right Wikipedia passage by its words | **v3** | No extra AI model needed, tiny, works offline on a phone. The simplest start for lookups |
| **FAISS + sentence-transformers** | Finds passages by *meaning* ("heart pump" finds "cardiac muscle") | **v3** (upgrade) | Uses a small pretrained search model (~22M), only for searching; the brain stays yours |
| **A local teacher model** (llama.cpp) | A bigger open model that writes practice data and grades answers | **v3** | See [Learning from a bigger AI](#learning-from-a-bigger-ai-distillation) |
| **lm-evaluation-harness** | Standard AI exams (HellaSwag, ARC, GSM8K...) | **v3** | Works with `export_hf.py`'s output. Scores v2 and v3 on the same public tests |
| **TensorBoard** | Live graphs of loss and speed while training | **v3** | Local and free. Handy for an 18-day run |
| **bitsandbytes** (8-bit optimizer) | Cuts optimizer memory ~75% | v3 (optional) → **v3.5** (needed) | In v3 it could replace gradient checkpointing if the pilot runs out of memory, and it's a rehearsal for 1B |
| **TRL-style DPO** | "Which answer is better" training | **v3** | Small enough to write ourselves, like the rest of the training code |
| **PEFT / LoRA** | Small add-on skill packs | Try on v3 → **v4** | A first skill pack can be tested cheaply on v2/v3 |
| **Tool calling (MCP-style)** | The model asks for a tool, our code runs it | v3 (lookups) → **v4** | v3's "look it up" is the first tool; v4 adds calculator, clock, files, web search |
| **Whisper** (OpenAI, open source) | Speech-to-text | **v4** (can try any time) | Independent of the brain, so it can be tested early |
| **Text-to-speech** (e.g. Piper) | Speaks the answers | **v4** | Small, offline, open source |
| **FSDP** (inside PyTorch) | Splits training across many GPUs | Written during v3.5 → **v5** | Needed for 3B in the cloud, and for v6/v6.5 |
| **vLLM / llama.cpp server** | Serves a big model to many users at once | **v6** | The online mode's server |

---

## Learning from a bigger AI (distillation)

A bigger AI (the **teacher**) helps train ours (the **student**). The student's brain is still
trained from scratch by us; the teacher supplies better practice material. It's one of the
biggest boosts for small models, and the teacher can run **on the RTX 4070** with llama.cpp, so
it costs only electricity.

### Three ways to learn from a teacher

| Way | How it works | Fits this project? |
|---|---|---|
| **1. Teacher writes the practice** | We give the teacher thousands of questions; its answers become chat training data. It can also write "read these notes, then answer" and "I don't know" examples | ✅ **Yes, from v3.** v2 already learns partly this way: smol-smoltalk was written by bigger AIs |
| **2. Teacher grades the answers** | Our model answers each question twice; the teacher picks the better answer. Those pairs feed DPO | ✅ **Yes, v3 phase 3** |
| **3. Student copies the teacher's guesses** | During training, the student learns the teacher's full list of next-word guesses ("Paris 72%, Lyon 2%...") instead of only the right word | ❌ Not for now. It needs the same tokenizer as the teacher, and running both models at once |

Way 3 is the classic form, but ways 1 and 2 get most of the benefit for much less work.

### What it looks like in practice

```
questions.jsonl ─► teacher (7B open model, llama.cpp on the 4070) ─► answers
                                                                       │
                                  filter: drop wrong, too long or unsafe answers
                                                                       │
                                                                       ▼
                                             chat.jsonl ─► finetune.py ─► student
```

- **Teacher size:** a ~7B open model as a Q4 GGUF fits in 12 GB and writes roughly 40–60 words a
  second. With several answers in parallel, ~50,000 answers takes about a day or two, and costs a
  few dollars of electricity.
- **Pick a teacher whose license allows training on its outputs.** Good candidates use permissive
  licenses such as Apache 2.0 (for example OLMo, Mistral 7B, Qwen2.5-7B, or OpenAI's gpt-oss).
  Check each license before using it.
- **Don't use the ChatGPT, Claude or Gemini APIs as teachers.** Their terms restrict using outputs
  to build competing models.
- **The student can't beat the teacher at what it copies**, and it copies the teacher's mistakes,
  so filter the answers and keep lookups (RAG) for facts.

---

## v2: Knowledge (in progress)

88M-parameter model trained on ~2.8B tokens (80% FineWeb-Edu, 15% Wikipedia, 5% TinyStories),
fine-tuned on ~105k multi-turn conversations. Details: [V2.md](V2.md).

**Done when:** it answers simple general questions, holds a conversation, runs on the phone,
and has a test-sheet score recorded as the **baseline** for v3.

---

## v3: Accuracy

Goal: **accurate when it answers, honest when it doesn't.** No AI is completely accurate
(not even the largest ones), but small models can get much more reliable with the right design.

| Feature | What it does | Why |
|---|---|---|
| **Look things up (RAG)** | Searches a local library (Wikipedia, your own documents) and answers from what it finds, naming the source | The biggest accuracy win: the model reads facts instead of trying to remember them |
| **"I don't know" training** | Chat examples where the correct answer is admitting uncertainty | Fewer confident wrong answers |
| **Preference training (DPO)** | Pairs of answers ("this one is better"); the model learns to prefer accurate, honest, helpful ones | The same idea the big labs use to make assistants helpful |
| **Bigger brain (~400M)** | 394M: 1024 wide × 32 layers, 2,048-token memory, 32k vocabulary | More room for language and knowledge |
| **Code in the training mix** | 10% Python (codeparrot-clean) | Basic code autocomplete and better structure/logic |
| **More Wikipedia** | 20% of the reading (up from 15%), stories down to 2% | Wikipedia packs the most facts per word. A small boost to what it remembers; lookups do the heavy lifting |
| **Math in the training mix** | 5% FineMath (web pages that explain math step by step) | Better with numbers, word problems and step-by-step thinking |
| **Bigger test sheet** | More questions, plus scoring for "admitted uncertainty correctly" | Proves accuracy actually improved |

**Tools starting in v3:** keyword search for lookups (FAISS as an upgrade), a local teacher model
that writes the lookup and "I don't know" examples and grades answers for DPO, standard AI exams
(lm-evaluation-harness), TensorBoard graphs, and optionally the 8-bit optimizer. See
[Tools by version](#tools-by-version).

**Built into v3's pretraining (ready):**
- **Reserved special tokens** for lookups, tools, system prompts and 20 spares, so the tokenizer never changes later
- **Decontamination:** training documents containing HellaSwag or GSM8K test questions are skipped
- **"Study the best material last":** a steady learning rate, then a fade over the last 10% of steps
  while reading a higher-quality anneal set (top-rated web pages, Wikipedia, math)
- **Longer-memory ready:** RoPE setting 500,000, so stretching to 8k tokens later is easier
- **Mini-exam** (HellaSwag, 500 questions) every 2,000 steps, plus `exam.py` for the full test
- **metrics.csv + TensorBoard graphs**, **torch.compile** speed-up (automatic fallback), and
  **`--backup_dir`** copies of `latest.pt`
- A `--pilot` option (speed, memory and finish-time report) and optional gradient checkpointing

Details and commands: [V3.md](V3.md).

---

## v3.5: 1B on the RTX 4070

Goal: the biggest brain that can realistically be trained at home, as cheaply as possible.
(700M was considered and skipped: 1B costs more time but not more money.)

| | |
|---|---|
| Size | ~1B parameters (e.g. dim 2048, 20–22 layers, grouped-query attention) |
| Reading | ~20B tokens (a larger FineWeb-Edu slice + Wikipedia + code + math + stories), ~40GB on disk |
| Time | ~3–4 months of GPU time; pause with Ctrl+C for gaming, resume anytime |
| Cost | ~$100–120 electricity (less with a GPU power limit of ~80%) |
| Features | Everything from v3 (lookups, "I don't know", preference training) |

**Code needed** (added when we get there):
- **8-bit optimizer** (bitsandbytes): cuts optimizer memory ~75%, so 1B fits in 12GB
- **Gradient checkpointing**: saves working memory for ~30% more time
- **Micro-batches of 1–2 sequences** with more gradient accumulation (same results)
- **Bigger data prep**: the same resumable streaming, with a larger token budget. **Switch FineWeb-Edu
  to its `sample-100BT` slice:** v3.5's web share (~12.6B tokens at 63%) is more than the 10B
  in `sample-10BT`, and reading the same pages twice helps less than fresh ones. Wikipedia at 20%
  (~4B tokens) is about one full read of English Wikipedia, so it doesn't repeat; stay near 20%.
- **Step-by-step math in the chat data**: the teacher model writes worked word problems (GSM8K
  style) for fine-tuning. Keep the real GSM8K questions for testing only, so the test stays fair.
- **Mandatory pilot run**: ~1–2 days first, to confirm memory, speed and falling loss

**While it trains:** the GPU is busy, so this is the time to *write* v4's code (the coding
harness, router, website) and test it on small models, then train the skill packs afterwards.

**Checkpoints:** keep `latest.pt` backed up (e.g. copy it to another drive weekly). A three-month
run is worth protecting.

---

## v4: Abilities

Goal: turn the model into a **personal assistant** with specialist skills.

### Specialists (skill packs + router)

```
                        ┌─► Study helper    (explains school topics)
You ─► Router ─► Base ──┼─► Story writer    (the v1 skill)
      (picks)   model   ├─► IT helper       (printers, networks, troubleshooting)
                        └─► Fact checker    (looks things up, cites sources)
```

- **One base model** (v3.5's 1B, or v3 until it's ready) holds general language and knowledge.
- **Skill packs (LoRA adapters):** small add-ons of a few MB each, trained in under an hour
  each. Adding one never breaks the others. llama.cpp supports them.
- **Router:** a small classifier that picks the right skill pack for each question.

### Tools, voice, memory
- **Tools:** calculator (exact math), date/time, search your files, reminders. The model decides
  when to call a tool, and our code runs it.
- **Web search (optional online mode):** our code searches the web (e.g. the free Wikipedia API
  or a search API's free tier), puts the top results in front of the model, and it answers from
  them with the source named. The same idea as v3's offline lookups, pointed at the internet for
  up-to-date facts. Off by default, so the AI stays private and offline unless you switch it on.
  Prefer trusted sites: a small model believes whatever it reads.
- **Agent mode:** multi-step tasks ("read my notes, summarize them, make a to-do list").
- **Voice:** Whisper turns your voice into text and Piper reads the answer aloud. Both are small,
  open source and offline, and run alongside the AI.
- **Personal memory:** saved notes about you that it looks up in later chats.

### Your own app (offline + online)
One app and one website that work offline and online. See
[Offline and online](#offline-and-online-the-goal-for-the-app-and-website) and
[Using your AI](#using-your-ai-apps) below.

---

## v5: Scale (3B)

Three routes:

| Route | How | Time | Cost |
|---|---|---|---|
| **From scratch** | Rent cloud GPUs. The cheapest route: Vast.ai (or similar) interruptible GPUs, since `train.py` already resumes after interruptions. v3.5's 1B run at home is the rehearsal | ~4–7 days on 8 rented GPUs (longer on fewer) | ~$800–2,500 depending on GPU and pricing |
| **Free (if approved)** | Apply to Google's TPU Research Cloud for free TPU time (the code would need porting to JAX or PyTorch/XLA) | Varies | $0 |
| **Fine-tune an open 3B model** | QLoRA on the RTX 4070, then add everything from v3/v4 (lookups, skill packs, personality, tools) | Hours | ~$0 |

**PC + cloud: the cheapest from-scratch plan**

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

Code changes needed for from-scratch: multi-GPU training (FSDP), streaming data straight from
disk shards, a larger tokenizer. v2's pause/resume and resumable data prep already carry over.

**Hardware note:** past ~300–500M parameters, the 12GB RTX 4070 is the bottleneck. If an upgrade
ever makes sense, VRAM matters most; a used RTX 3090 (24GB) is the best value.

---

## v6 and v6.5: Bigger small (5B → 7B)

Goal: the step from "small" toward "medium". The **phone keeps a small model for offline use**,
and these bigger models power the PC and the **online mode** of your app and website (the way
Gemini runs a small model on phones and a big one in the cloud).

| | **v6** | **v6.5** |
|---|---|---|
| Brain | **~5B** (~3584 wide × 36 layers) | **~7B** (4096 wide × 32 layers) |
| Memory (context) | 8,192 tokens | 8,192 tokens |
| Vocabulary | 65,536 (same as v5, so it can grow from v5) | 65,536 |
| Reading (minimum, ~20 per parameter) | ~100B tokens (~200 GB of data) | ~140B tokens (~280 GB) |
| Training | Cloud: ~2,000 H100-hours (~11 days on 8 GPUs) | Cloud: ~4,000 H100-hours (~3 weeks on 8 GPUs) |
| Cost | **~$4,000–6,000** (less if grown from v5 or with a grant) | **~$8,000–12,000** (less if grown from v6 or with a grant) |
| Phone file (Q4) | ~3 GB: high-end phones only, slowly | ~4–4.5 GB: mainly PC and server |
| Runs on the RTX 4070 | ✅ Yes (Q4/Q8) | ✅ Yes (Q4/Q8) |
| Chat fine-tuning at home | ✅ QLoRA fits in 12 GB | ✅ QLoRA fits in 12 GB |

**Ways to keep the cost down:**
- **Grow instead of starting over:** start v6 from v5's weights (copy and stack its layers,
  "depth up-scaling"), and v6.5 from v6. This is why they share v5's tokenizer.
- **Free compute grants:** Google's TPU Research Cloud and similar programs. A documented
  project with results from v1–v5 is a strong application.
- **The same PC + cloud split as v5:** data prep, pilots, chat training, DPO, skill packs,
  testing and export at home; only pretraining is rented.
- **The open-model route:** fine-tune an open 7–8B with QLoRA on the 4070 for ~$0, then add
  your lookups, tools and app. Much smarter for the money, but the brain isn't trained by you.

**Reading more makes them smarter.** The minimums above work, but open 7B models read ~1T+
tokens. Reading 1T tokens would cost roughly 7–10× more, so it only makes sense with a grant.

**Code needed:** everything from v5 (FSDP, streaming shards), plus model growth (up-scaling),
longer-context training (8,192 tokens), and a server setup (llama.cpp server or vLLM) for the
app's online mode.

**Hardware note:** a used RTX 3090 (24 GB) would run v6.5 comfortably at Q8 and fine-tune it
more easily, but the 4070 can already run both at Q4.

---

## Using your AI (apps)

"Production" means **the version you rely on day to day**. You don't have to build an app to use
it. Build one only if you want your own name, look or features.

| Option | Where | Build needed? | Notes |
|---|---|---|---|
| **PocketPal AI** (current) | Phone | ❌ No | Load the `.gguf`, set the context size. Works today for v1 and v2 |
| **llama.cpp web chat** | PC browser | ❌ No | `llama-server.exe -m model.gguf -c 1024`, then open http://localhost:8080. It comes in the same llama.cpp download used for quantizing |
| **Your own web app (home)** | PC/phone browser on your network | ✅ Small | A simple chat page (Python backend + HTML), with your AI's name and look. A good first app project |
| **Public website, AI runs in the visitor's browser** | Any browser, anywhere | ✅ Medium | The page downloads the `.gguf` (~94MB for v2) and runs it on the visitor's device with llama.cpp compiled to WebAssembly. Free static hosting (e.g. Vercel, GitHub Pages), private, no server bills. Best fit for small models |
| **Public website, AI runs on a server** | Any browser, anywhere | ✅ Medium | Like Claude.ai: a server runs the model. ~$5–20/month for a small CPU server, or a free tier such as Hugging Face Spaces. Needed for bigger models (3B) |
| **Your own Android app** | Phone | ✅ Medium | Based on llama.cpp's Android example (Android Studio, Kotlin). Free to install on your own phone |
| **Your own iPhone app** | Phone | ✅ Medium–hard | Needs a Mac + Xcode. Free for your own phone (re-sign weekly), or $99/year Apple developer account to keep it installed or publish |

### Offline and online (the goal for the app and website)

The finished app and website should work **both offline and online**, switching automatically:

| | **Offline mode** (default) | **Online mode** (when connected and switched on) |
|---|---|---|
| Where the AI runs | On your device: the phone app, or in the browser on the website | Same device model, or a bigger model on a server (v5's 3B) |
| Facts | Saved Wikipedia slice + your own notes | Plus **live web search** for news and anything recent |
| Privacy | Nothing leaves the device | Search questions go to the search service; chats go to your server if it's used |
| Works in airplane mode | ✅ Yes | ❌ Falls back to offline mode automatically |
| Cost | $0 | Free tiers for search; ~$5–20/month if a server runs the bigger model |

Design rule: **offline first.** Everything works without internet, and online mode only adds
fresh facts and (later) a bigger brain. The app shows which mode it's in, and online mode is a
switch the user controls.

Built in steps: v3 gives offline lookups, v4 adds the web search tool and the online/offline
switch in your own app and website, and v5 can add the server-hosted 3B for online mode while
the phone keeps a Q4 copy for offline.

Recommended order: **PocketPal (now) → llama.cpp web chat (instant PC version) → your own
website, AI running in the browser (v4) → your own phone app (v4 or later) → server-hosted
website for bigger models (v5)**. Building the app is a separate skill from
training the model, and it only makes sense once the model is worth using every day.

**Before going public:** show a clear "small experimental AI, it makes mistakes" notice, expect
people to try misusing it (v3 preference training should include declining harmful requests;
consider a simple content filter), and prefer in-browser models so popularity can't create a
server bill.

**Updating models in an app:** whichever app you use, a new version is just a new `.gguf` file
copied over. Train → export → quantize → promote to `checkpoints/production` → load it in the app.
