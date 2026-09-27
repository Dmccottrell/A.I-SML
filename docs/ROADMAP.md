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
| **Bigger test sheet** | More questions, plus scoring for "admitted uncertainty correctly" | Proves accuracy actually improved |

Also: a `--pilot` option in `train.py` (speed, memory and finish-time report before the long run)
and optional gradient checkpointing. Details and commands: [V3.md](V3.md).

---

## v3.5: 1B on the RTX 4070

Goal: the biggest brain that can realistically be trained at home, as cheaply as possible.
(700M was considered and skipped: 1B costs more time but not more money.)

| | |
|---|---|
| Size | ~1B parameters (e.g. dim 2048, 20–22 layers, grouped-query attention) |
| Reading | ~20B tokens (a larger FineWeb-Edu slice + Wikipedia + code + stories), ~40GB on disk |
| Time | ~3–4 months of GPU time; pause with Ctrl+C for gaming, resume anytime |
| Cost | ~$100–120 electricity (less with a GPU power limit of ~80%) |
| Features | Everything from v3 (lookups, "I don't know", preference training) |

**Code needed** (added when we get there):
- **8-bit optimizer** (bitsandbytes): cuts optimizer memory ~75%, so 1B fits in 12GB
- **Gradient checkpointing**: saves working memory for ~30% more time
- **Micro-batches of 1–2 sequences** with more gradient accumulation (same results)
- **Bigger data prep**: the same resumable streaming, with a larger token budget
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
- **Agent mode:** multi-step tasks ("read my notes, summarize them, make a to-do list").
- **Voice:** speech-to-text in, text-to-speech out, using small speech models alongside the AI.
- **Personal memory:** saved notes about you that it looks up in later chats.

### Your own app
See [Using your AI](#using-your-ai-apps) below.

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
