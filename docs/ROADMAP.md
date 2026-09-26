# Roadmap

Where this project is going, and why. Plans past v2 are a **direction, not a promise**: each
version's test-sheet results decide what the next one focuses on.

## At a glance

| Version | Theme | Brain | Main new abilities | Where it trains | Cost |
|---|---|---|---|---|---|
| **v1** ✅ | Learn the pipeline | 30M | Tells children's stories; runs offline on the phone | RTX 4070, 4 hours | $0 |
| **v2** 🛠️ | Knowledge | 88M | General Q&A, explanations, multi-turn chat | RTX 4070, ~20 hours | $0 |
| **v3** | Accuracy | ~300M | Looks things up (RAG), says "I don't know", preference training | RTX 4070, ~1 week | $0 |
| **v4** | Abilities | ~300M, upgraded | Specialist skill packs + router, tools, voice, own app | RTX 4070 | $0 |
| **v5** | Scale | 3B | Genuinely capable assistant | Cloud (from scratch) **or** RTX 4070 (fine-tune an open 3B) | ~$1,500+ **or** $0 |

Guiding rules:
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
| **Bigger brain (~300M)** | 3–4× v2 | More room for language and knowledge |
| **Bigger test sheet** | More questions, plus scoring for "admitted uncertainty correctly" | Proves accuracy actually improved |

Also: a `--pilot` option in `train.py` to run a slice of the steps before the full week-long run.

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

- **One base model** (v3) holds general language and knowledge.
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

Two routes:

| Route | How | Time | Cost |
|---|---|---|---|
| **From scratch** | Rent cloud GPUs (~8 × H100). Do a **1B** run first (~$200–300) to test multi-GPU training and data streaming, then the 3B run | ~4 days | ~$1,500–2,500 |
| **Fine-tune an open 3B model** | QLoRA on the RTX 4070, then add everything from v3/v4 (lookups, skill packs, personality, tools) | Hours | ~$0 |

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
| **Your own web app** | PC/phone browser on your network | ✅ Small | A simple chat page (Python backend + HTML), with your AI's name and look. A good first app project |
| **Your own Android app** | Phone | ✅ Medium | Based on llama.cpp's Android example (Android Studio, Kotlin). Free to install on your own phone |
| **Your own iPhone app** | Phone | ✅ Medium–hard | Needs a Mac + Xcode. Free for your own phone (re-sign weekly), or $99/year Apple developer account to keep it installed or publish |

Recommended order: **PocketPal (now) → llama.cpp web chat (instant PC version) → your own web
app (v4) → your own phone app (v4 or later)**. Building the app is a separate skill from
training the model, and it only makes sense once the model is worth using every day.

**Updating models in an app:** whichever app you use, a new version is just a new `.gguf` file
copied over. Train → export → quantize → promote to `checkpoints/production` → load it in the app.
