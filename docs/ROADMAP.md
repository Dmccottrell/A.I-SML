# Roadmap

Where this project is going, and why. Plans past v2 are a **direction, not a promise**: each
version's test-sheet results decide what the next one focuses on.

## At a glance

| Version | Theme | Brain | Main new abilities | Where it trains | Cost |
|---|---|---|---|---|---|
| **v1** ✅ | Learn the pipeline | 30M | Tells children's stories; runs offline on the phone | RTX 4070, 4 hours | $0 |
| **v2** ✅ | Knowledge | 88M | General Q&A, explanations, multi-turn chat | RTX 4070, ~18 hours | $0 |
| **v3** 🛠️ | Accuracy | ~400M | Looks things up (RAG), says "I don't know", handles corrections, exact instructions, preference training, basic code | RTX 4070, ~13–14 days nonstop (pilot: ~25 s/step with `torch.compile`) | ~$15–20 electricity |
| **v3.5** | Scale at home | **~1.05B** | Same features as v3 on a much bigger brain; reads 30B tokens | RTX 4070, ~3.5–4.5 months nonstop (pausable) | ~$110–270 electricity |
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
| **lm-evaluation-harness** | Standard AI exams (HellaSwag, ARC, MMLU, GSM8K...) | **v3** | Works with `export_hf.py`'s output. Scores v2 and v3 on the same public tests |
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

## v2: Knowledge ✅

88M-parameter model trained on ~2.8B tokens (80% FineWeb-Edu, 15% Wikipedia, 5% TinyStories),
fine-tuned on ~105k multi-turn conversations. Details: [V2.md](V2.md).

**Done when:** it answers simple general questions, holds a conversation, runs on the phone,
and has a test-sheet score recorded as the **baseline** for v3. ✅ All done.

### v2 results

| Measure | Result |
|---|---|
| Val loss (pretraining) | 2.929 best, 2.984 final (20,000 steps, ~17.5–18 hours; data prep ~30 minutes) |
| Test sheet (`evaluate.py`) | **18/20** (identity 2/2, facts 7/8, explain 5/5, advice 2/2, writing 1/1, stories 1/2) |
| HellaSwag (`exam.py`) | **28.4%** (random 25%, GPT-2 124M ~29–31%) |
| Phone | 89 MB (Q8_0), ~210–245 tokens/second in PocketPal, fully offline |

### What testing on the phone taught us

| What happened | Why | Fix |
|---|---|---|
| "The capital of Illinois is **Paris**", then **Chicago** with better settings | 88M can't store rarer facts; it picks the most common pattern | v3 lookups (Wikipedia notes) |
| Repeated "Paris" three times when told it was wrong | Its own mistake stays in the chat, and it never practiced being corrected | v3 correction and "I don't know" lessons |
| "List 3 fruits" → 10 looping items, then **exactly 3** after changing settings | Repeat penalty was off (1.0) and answers had no length limit | Settings (repeat penalty 1.25, max 256 tokens) + v3 exact-instruction lessons |
| "Largest planet" → **Mercury**, then **Jupiter** after the settings change | Temperature 0.7 was too random | Temperature 0.4–0.5 |
| Answered spaghetti and planet questions about **Illinois** | v2's chat lessons almost never switch topics | v3 topic-switch lessons, 2× memory, v4 app trims old messages |
| Same paragraph for "Who are you?" and "What can you do?" | One identity answer for all questions | v3: a separate answer for each |
| "Whats up" → it invented its own question ("What does 'suprem' mean?") and answered it | It never saw casual slang in its chat lessons | v3 small-talk lessons (typed casually too: "whats up", "ty") |

**Lesson for every version: test the settings before judging the model.** Half of what looked like
"the model is bad" was the phone app's settings.

---

## v3: Accuracy (in progress)

**Status:** phase 1 (pretraining upgrades) and phase 2 (Wikipedia lookups, teacher script, chat
lessons for every v2 phone mistake, 39-question test sheet) are built and tested. Next: data prep,
the teacher run, then pretraining. Phase 3 (DPO) comes after the chat model exists.

Goal: **accurate when it answers, honest when it doesn't.** No AI is completely accurate
(not even the largest ones), but small models can get much more reliable with the right design.

| Feature | What it does | Why |
|---|---|---|
| **Look things up (RAG)** | Searches a local library (Wikipedia, your own documents) and answers from what it finds, naming the source | The biggest accuracy win: the model reads facts instead of trying to remember them |
| **"I don't know" training** | Chat examples where the correct answer is admitting uncertainty | Fewer confident wrong answers |
| **Handling corrections** | Examples where the user says "that's wrong" and the AI rechecks its notes, fixes the answer, or admits it's unsure | v2 repeats its mistake when corrected (e.g. "the capital of Illinois is Paris", three times) |
| **Better identity answers** | Separate answers for "Who are you?", "What can you do?" and "Are you ChatGPT?" | v2 gives the same identity paragraph to all of them |
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

**Ready for later features without retraining:** the 20 spare special tokens are planned for thinking
(start and end) and the three effort levels, so v3 can learn to think in a fine-tune. See
[Thinking, effort levels and analytical steps](#thinking-effort-levels-and-analytical-steps).

Details and commands: [V3.md](V3.md).

---

## v3.5: ~1.05B on the RTX 4070

Goal: the biggest brain that can realistically be trained at home, as cheaply as possible.
(700M was considered and skipped: 1B costs more time but not more money.)

| | |
|---|---|
| Size | **~1.05B** parameters: 2048 wide × 22 layers, feed-forward 5,632, grouped-query attention (4 key/value heads), 32k vocabulary. All sizes are multiples of 256, so the phone's Q4 format works |
| Reading | **30B tokens** (~29 per parameter) + a 3B-token anneal set; ~66 GB on disk |
| Steps | ~115,000 at 262,144 tokens each |
| Time | **~3.5–4.5 months running 24/7** (estimated from v3's measured 26.5 s/step: ~70 s/step by scaling, ~84–96 s with the memory tricks below). At 16 hours a day: ~5–6.5 months; 12 hours: ~7–9 months. Pause with Ctrl+C for gaming, resume anytime; only the hours the GPU trains count |
| Cost | **~$110–270** electricity (~$140–180 at $0.20/kWh): about 700–900 kWh at ~270 W for the whole PC (GPU ~165 W plus the rest), so multiply by your own rate. Less with a GPU power limit of ~80% |
| Memory | Needs **both CPU offload** (the optimizer lives in system RAM; ~16 GB free RAM) **and gradient checkpointing** on part or all of the layers. v3's measured 10.2 GB shows offload alone isn't enough: fp32 weights + gradients alone are ~8.4 GB at 1.04B parameters, and activations grow ~1.4× |
| Phone file | ~650 MB (Q4) or ~1.1 GB (Q8) |
| Features | Everything from v3 (lookups, "I don't know", corrections, preference training) |
| **Code** | **Several languages** instead of Python only (see below) |

**Why 30B tokens instead of 20B:** ~20 tokens per parameter is the most *efficient* use of
training time, but models keep improving with more reading. 30B gives a model roughly as good as a
~1.3–1.5B one trained the standard way, while staying 1B-sized on the phone (same speed and file
size). The extra ~1.5 months and ~$50 are paid once. If more is wanted later, the run can continue
from `pre_decay.pt` (e.g. to 40B) instead of starting over.

**Why ~1.05B and not 1.15B or 1.3B:** training needs the weights, gradients and optimizer on a 12 GB
card at once. ~1.05B fits with CPU offload plus gradient checkpointing; 1.15B is tighter (+1–2 test points, +15% time); 1.3B
needs 16-bit-only training (+3–4 points, +30% time). The v3.5 pilot runs confirm memory and speed;
if there's clear headroom, 1.15B can still be chosen then.

### v3.5's data (~33B tokens to prepare)

**Main reading: 30B tokens**

| Share | Tokens | Source | Notes |
|---|---|---|---|
| 63% | 18.9B | Educational web pages (FineWeb-Edu `sample-100BT`) | The bigger slice, so no page is read twice (v3 used `sample-10BT`) |
| 15% | 4.5B | Wikipedia | About one full read of English Wikipedia (it's only ~4–5B tokens), so its share drops from v3's 20% |
| 13% | 3.9B | Code, several languages | Python ~1.9B, JavaScript/HTML/CSS ~0.9B, C# or Java ~0.5B, SQL ~0.3B, shell/PowerShell ~0.3B |
| 7.5% | 2.25B | Math (FineMath) | Up from 5%: helps step-by-step reasoning |
| 1.5% | 0.45B | Stories (TinyStories) | Nearly all of TinyStories |

**Anneal set: 3B tokens** (read during the last 10% of steps)

| Share | Tokens | Source |
|---|---|---|
| 40% | 1.2B | Top-rated web pages (FineWeb-Edu score 4–5) |
| 25% | 0.75B | Wikipedia |
| 15% | 0.45B | Math |
| 15% | 0.45B | Code |
| 5% | 0.15B | Stories |

**Preparing it:** ~33B tokens, ~66 GB, about **3.5–5 hours** at the ~2.6M tokens/second measured for
v3 (the code dataset may be slower). Test questions are removed as in v3. A new 32k tokenizer is
trained on a sample that includes every code language. **Disk tip:** v3's 27 GB of data can be
deleted once v3 has finished training.

**Multi-language code.** v3 reads only Python (a small brain learns one language well rather than
many thinly). With 1B parameters there's room for more:

| Language | Why |
|---|---|
| Python | Still the largest share: readable, and the v4 coding helper's main language |
| JavaScript, HTML/CSS | Websites, including your own app's website (v4) |
| SQL | Databases and data questions |
| Shell / PowerShell | Everyday computer tasks and scripts (IT help) |
| C# or Java | Common in apps and at work |

- **Data:** a permissively licensed multi-language code dataset (e.g. The Stack or StarCoder data).
  These require accepting their terms on Hugging Face and logging in with a token.

**Built so far (tested on CPU with a tiny model; the real memory and speed need the RTX 4070 pilot):**
- `v3.5` entry in `config.py` (1.036B parameters, 115,000 steps, `python train.py --version v3.5 --pilot`)
- `offload_optim.py`: optimizer in system RAM (`optimizer="adamw_cpu"`); gives the same numbers as normal AdamW and resumes correctly
- `checkpoint_every` setting: protect every block (1) or every 2nd block (2) with gradient checkpointing
- `optimizer="adamw8bit"` (bitsandbytes) as a fallback (untested here)

- **Data prep for v3.5** (`python prepare_web_data.py --version v3.5`): the bigger FineWeb-Edu slice
  (`sample-100BT`, main and score 4-5 anneal versions) and `code_multi`: Python 49%, JavaScript 14%,
  HTML 5%, CSS 4%, Java 7%, C# 6%, SQL 8%, shell 5%, PowerShell 2% from The Stack, mixed by character
  share so the tokenizer sees every language, and skipping minified/generated files. Tested end to end
  with fake sources (Hugging Face isn't reachable from where I build); **not** tested against the real
  datasets. The Stack needs a free Hugging Face account: accept its terms once and run
  `hf auth login` (older versions: `huggingface-cli login`).

**Still to build:** the pilot runs on your PC, and checking the real dataset names and speeds on the first
`--test` run (`python prepare_web_data.py --version v3.5 --test`, 20M tokens, minutes).

**Code needed** (added when we get there):
- **CPU offload for the optimizer** (and the 8-bit optimizer, bitsandbytes, as a fallback), **plus gradient checkpointing** (all layers, or every other layer for about half the time cost): together they bring GPU memory to ~10–11 GB
- **Gradient checkpointing**: saves working memory for ~30% more time
- **Micro-batches of 1–2 sequences** with more gradient accumulation (same results)
- **Bigger data prep**: the same resumable streaming with the bigger FineWeb-Edu slice and the
  multi-language code source
- **Step-by-step math in the chat data**: the teacher model writes worked word problems (GSM8K
  style) for fine-tuning. Keep the real GSM8K questions for testing only, so the test stays fair.
- **Mandatory pilot runs**: ~1.05B (and 1.15B if memory allows), to confirm memory, speed and falling loss

**While it trains:** the GPU is busy, so this is the time to *write* v4's code (the coding
harness, router, website) and test it on small models, then train the skill packs afterwards.

**Checkpoints:** keep `latest.pt` backed up (`--backup_dir`). A five-month run is worth protecting.
---

## v4: Abilities

Goal: turn the model into a **personal assistant** with specialist skills.

### Specialists (skill packs + router)

```
                        ┌─► Study helper    (explains school topics)
                        ├─► Story writer    (the v1 skill)
You ─► Router ─► Base ──┼─► IT helper       (printers, networks, troubleshooting)
      (picks)   model   ├─► Fact checker    (looks things up, cites sources)
                        ├─► Document helper (summarizes, rewrites, drafts, makes to-do lists)
                        └─► Coding helper   (works in a loop, small tasks)
```

- **One base model** (v3.5's 1B, or v3 until it's ready) holds general language and knowledge.
- **Skill packs (LoRA adapters):** small add-ons of a few MB each, trained in under an hour
  each. Adding one never breaks the others. llama.cpp supports them.
- **Router:** a small classifier that picks the right skill pack for each question.
- **Tiers:** the router also picks the model size: Lite for easy messages, Standard for harder ones. See [Model tiers](#model-tiers-lite-standard-pro-max).

### Tools, voice, memory
- **Tools:** calculator (exact math), date/time, search your files, reminders. The model decides
  when to call a tool, and our code runs it.
- **Web search (optional online mode):** our code searches the web (e.g. the free Wikipedia API
  or a search API's free tier), puts the top results in front of the model, and it answers from
  them with the source named. The same idea as v3's offline lookups, pointed at the internet for
  up-to-date facts. Off by default, so the AI stays private and offline unless you switch it on.
  Prefer trusted sites: a small model believes whatever it reads.
- **Agent mode:** multi-step tasks ("read my notes, summarize them, make a to-do list").
- **Coding helper:** the same loop for code (see [Agentic coding](#agentic-coding-a-coding-helper-that-works-in-a-loop)).
- **Voice:** Whisper turns your voice into text and Piper reads the answer aloud. Both are small,
  open source and offline, and run alongside the AI.
- **Personal memory:** saved notes about you that it looks up in later chats.

### Agentic coding (a coding helper that works in a loop)

Instead of answering once, the model works in a loop, like Claude Code but for small tasks:

```
task -> model asks to read a file -> our code reads it -> model proposes an edit
     -> our code applies it and runs the tests -> model sees the failure -> tries again ...
```

The loop, file access and safe place to run code are ordinary code we write (the **harness**). The
model only learns to ask for tools in the right format and to use what comes back. The tokens for
this (`<|tool_call|>`, `<|tool_result|>`) are already reserved in v3's tokenizer.

| Step | What | When |
|---|---|---|
| 1 | ✅ **Built and tested (`harness.py`):** read file, edit file, run command, run tests, all inside a **sandbox** (a temporary folder, no internet, time and memory limits, nothing outside it can be touched) | While v3.5 trains (CPU work) |
| 2 | **Training data:** a coding-focused open teacher (e.g. Qwen2.5-Coder-7B, license to be checked) works through small coding tasks in the harness. Keep only runs where the **tests really pass** (checked by running them) | After v3.5 |
| 3 | **Fine-tune** a "coding" skill pack (LoRA) on those runs | v4 |
| 4 | **Measure** on a small test set of real tasks (fix this bug, add this function) | v4 |

**What to expect at each size:**

| Model | What it can do |
|---|---|
| v3 (394M) | Autocomplete only, no agent work |
| v3.5 / v4 (~1.05B) | Small, simple tasks: fix an obvious bug in one short file, write a small function, run a command and read the result |
| v5 (3B) | Small multi-step jobs: a few files, a couple of retries |
| v6.5 (7B) | Real everyday scripting help |

Public agentic-coding benchmarks (like Terminal-Bench) are far beyond a ~1B model.

**The real bottleneck is memory, not skill.** A task needs the file, the error output and the
model's own edits in context at once. v3.5's 2,048 tokens fills up after about two small files, so
longer context (8,192 tokens at v6, or extending v3.5 with extra training: v3 uses RoPE 500,000 for
this reason) matters more for agent work than extra brain size.

**Safety first:** model-written code only runs inside the sandbox, and the harness is built and
tested before any model is allowed to use it.

### Thinking, effort levels and analytical steps

How the model handles hard questions. It's built from four pieces:

```
question -> router picks effort (Quick / Balanced / Deep) + size (Lite / Standard / Pro) + skill pack
         -> thinking, with a budget (none / short / long)
         -> tool loop (lookup, calculator, files, code sandbox), with error recovery
         -> check (recompute, or vote across a few tries)
         -> answer
```

| Piece | How it works | Needs training? | When |
|---|---|---|---|
| **Adaptive and extended thinking** | The model writes its reasoning between two special tokens before it answers. They come from the 20 spare tokens already reserved in v3's tokenizer (planned: `<|reserved_0|>` = start of thinking, `<|reserved_1|>` = end), so nothing about v3's pretraining changes | **Yes, a fine-tune.** The teacher writes step-by-step solutions, and we keep only the ones whose final answer is *verified* correct (math answers, code tests) | Trial on v3, real at v3.5/v4, longer at v5+ |
| **Dynamic effort allocation** | A Quick / Balanced / Deep switch in the app, and the v4 router choosing automatically. A **thinking budget** cuts thinking off at a limit and forces an answer. Effort tokens: `<|reserved_2|>` to `<|reserved_4|>` | Mostly code, plus examples with short thinking for easy questions and longer for hard ones | v4 |
| **Multi-step analytical framework** | Plan, split into sub-questions, look up or calculate each one, check, then combine. Our harness runs the steps; the model does each one. Checking can be a recalculation, or a vote across a few tries (self-consistency), which costs time, not training | Little: format examples | v4 |
| **Agency and tool integration** | A tool registry with a fixed call format, error recovery, confirmation before risky actions, and the sandbox. Extends the calculator, files, web search and coding loop | **Yes**, on verified tool-use runs | v4, expanding at v5+ |

**Effort levels (starting values, tuned by testing):**

| Level | Thinking | Tier | Use for |
|---|---|---|---|
| **Quick** | None | Lite | Small talk, simple facts, quick lists |
| **Balanced** | Up to ~150 tokens | Standard | Everyday questions, explanations |
| **Deep** | Up to ~500 tokens (more once memory grows) | Standard or Pro | Math, multi-step problems, analysis |
| **Auto** | The router decides | The router decides | The default |

**The cheapest first experiment (thinking-lite, on v3):** after v3's chat fine-tuning, a small
fine-tune where the teacher (Qwen) solves math problems that come with known answers, keeping only
correct solutions. Then score v3 on the held-out test. If it helps at 394M, scale it up at v3.5.
The real GSM8K *test* questions stay out of training. Nothing about pretraining changes.

**Later improvement (v5+):** sample several answers, keep the verified-correct ones, fine-tune on
those, and repeat. This is a cheap, home-friendly version of how big labs train reasoning.

**Honest limits:**
- Thinking helps math, logic and multi-step questions, and does little for plain facts (those need lookups).
- Small models can ramble or loop in long thinking, so we cap the budget and keep it short at ~1B.
- Thinking uses memory: at 2,048 tokens, Deep mode leaves less room. Longer context (v6) matters here.
- It's slower, which is why effort levels exist.
- Humanity's Last Exam-style questions stay out of reach at our sizes. The machinery is the same as the
  big models', but I can't promise how big the gains are until we measure them.
- Some phone apps already understand thinking sections (PocketPal's settings have an "Include thinking
  in context" toggle). We'll check which tags they recognize and match them.

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

**Vision helper (new in v5):** a small open image-to-text model runs beside ours to describe photos,
screenshots and charts, and our model reads the description. It's a helper, not part of our weights
(see the README's pretrained weights policy). This covers chart and screenshot questions without
training a vision model.

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
  `growth_test.py` measures how much this really saves (v2's 12 layers grown to 24, against a 24-layer model
  from scratch with the same total compute; ~20 hours on the 4070, run when the GPU is free).
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

## Beyond v6.5: v7, v8 and Max

The plan is to keep scaling, and the top of the lineup is the **Max** tier. Nothing here is committed:
each step happens only if the one before it shows a clear gain **and** the money is there.

| Step | Size | Tokens read | Rough cost | Runs on |
|---|---|---|---|---|
| v6.5 | 7B | ~210B | ~$8-18k | PC, server |
| **v7: "upper small" (Max preview)** | ~13B | ~390B | ~$40-65k | Server; PC with a 24 GB GPU (Q4 ~7.5 GB) |
| **v8: "medium" (Max)** | ~30B | ~900B | ~$230-340k | Server (Q4 ~17 GB) |

*Estimates from compute = 6 x parameters x tokens on rented H100s at $2-3/hour. Real prices swing.*

**Max is online-only at first** (the app's online mode, or your own PC). Phones keep Lite and
Standard offline. Each query costs real server money, so a hosted Max needs a budget, per-user
limits, or a paid plan. That is a product decision for later.

**Where "drastic improvements" come from (size is only part of it):**
- **Better data:** cleaner, more targeted, more code/math/reasoning.
- **After-training:** teaching from a bigger model (distillation), preference training (DPO), and
  reinforcement with answers that can be *verified* (tests, calculators, math answers).
- **Mixture-of-experts:** more capacity for the same compute (worth testing at v7).
- **Thinking, tools, lookups and the coding harness**, all already planned.

**The payoff loop:** Max teaches Pro, Standard and Lite. Every step up makes the whole family
better without training the small ones from scratch. The Qwen teacher stays until Max replaces it.

**Engineering changes at this size:** many-GPU and multi-machine training with automatic recovery
from failures, terabyte-scale data pipelines, a broader test suite (MMLU, GSM8K, coding tasks, safety
checks), and sturdier server hosting (vLLM).

**Money:** compute grants (Google's TPU Research Cloud, academic and startup credits), sponsors, or
paying users. A documented project with results from v1-v6.5 is a strong application.

---

## How big-model benchmarks map to ours

Public benchmarks such as Terminal-Bench, GDPval, Humanity's Last Exam, OSWorld and Chartography
are built for the largest models; ours would score near zero on most, which tells us nothing. Each
skill is still in the plan, measured with yardsticks that fit our size.

| Skill (big-model benchmark) | In the plan? | Realistic for our models | Our yardstick |
|---|---|---|---|
| **Agentic coding** (Terminal-Bench, FrontierCode, CursorBench) | ✅ v4 coding helper | Small, simple tasks at ~1B | A small set of real tasks (fix this bug, add this function) and the agent test set |
| **Knowledge work** (GDPval, Briefcase) | ✅ Document helper skill pack (v4), lookups, tools | Short summaries, rewrites, drafts, to-do lists. Longer documents need the 8k memory (v6) | Summaries and rewrites judged against the teacher's answers |
| **Multidisciplinary reasoning** (Humanity's Last Exam, with tools) | ⚠️ Thinking, effort levels, calculator and lookups (v3.5/v4) | Near zero on that exam; real gains on grade-school math and multi-step questions | GSM8K-style math, ARC and MMLU through lm-evaluation-harness |
| **Computer use** (OSWorld) | ⚠️ Not screen-based. Tool calls for phone and PC actions (set a reminder, open a file, run a command) in v4 agent mode | Simple actions through tools | "Did it call the right tool and finish the task?" |
| **Visual chart recognition** (Chartography) | ⚠️ **Vision helper** (v5): a small open image-to-text model beside ours describes a picture or chart, and our model reads the text. It follows the pretrained weights policy (a helper beside the model, never inside it) | Basic chart and screenshot questions | A small chart and screenshot set |

Training our own vision model from scratch is possible later (v6+) but needs image datasets and a
lot more training, so it isn't planned.

---

## Tiers, versions and effort: three different things

| Word | Means | Example |
|---|---|---|
| **Tier** | *Which model*: its size class (small and fast, balanced, most capable, top) | "the small tier" |
| **Version** | *Which generation*: a better recipe, more data, new abilities. Each generation can come in several tiers | v3.5, v4, v5 |
| **Effort** | *How long the model thinks* before answering, for a more detailed or complex answer or solution. It does not change the model. Any tier can use any effort level | Low / Medium / High / Max |

Effort is independent of tier: a small model on High effort and a large model on Low effort are both
valid. The router (and the user) choose the tier and the effort separately. Effort costs time and
battery, not a bigger download.

**How the versions line up with tiers** (like a lab's small, mid and large model families):

| Tier class | Working name | Size | Versions |
|---|---|---|---|
| Phone-lite | **Rune** | ~400M | v3 |
| Small and fast | **Skald** | ~1B | **v3.5**, then **v4 = "Skald 2"**: the same size, now with skill packs, the router, tools, thinking, effort levels and the app |
| Balanced | **Saga** | ~3B | v5 (needs cloud training) |
| Most capable | **Edda** | 5-7B | v6, v6.5 |
| Top | **Norn** | 13-30B | v7, v8 (see [Beyond v6.5](#beyond-v65-v7-v8-and-max)) |

So v4 (Skald 2) is a new *generation* of the small tier, not a bigger model. It keeps v3.5's brain (no cloud cost).
Optional, if time allows: a short "skill-aware" extra reading round on v3.5's weights (a few billion
tokens with tool calls, thinking steps and code-with-tests mixed in) so the skill packs start from a base
that already knows those formats.

**Names (working names):** a family of Norse storytelling words, since these are language models. A *rune* is
a small written character, a *skald* a Norse poet, a *saga* a long story, the *Eddas* the great collections
of Norse tales, and the *Norns* the three fates who weave everything. They are placeholders: **no trademark
check has been done**, so search each name (and its domain) before a public launch, and rename if there is a
conflict. In this document, the older placeholder names map as: Lite = Rune, Standard = Skald,
Pro = Saga and Edda, Max = Norn.

## Model tiers (Lite, Standard, Pro, Max)

Like the big labs' model families, tiers are **the same family at different sizes**: the same
reading mix, chat lessons, personality and features, but different sizes, so you can pick
speed or smarts.

| Tier | Size | Runs on | Good for | Arrives |
|---|---|---|---|---|
| **Lite = Rune** | ~400M (v3-size) | Any phone, offline, very fast | Quick questions, small talk, simple lookups | With v3.5 |
| **Standard = Skald** | ~1B (v3.5, v4) | Phones and PCs | Everyday use: lookups, explanations, advice | v3.5 |
| **Pro = Saga, Edda** | 3B (v5), 5-7B (v6-v6.5) | PC or a server (the app's online mode) | Harder questions, coding, long writing | v5+ |
| **Max = Norn** | 13B, later ~30B ("upper small", then "medium"; see [Beyond v6.5](#beyond-v65-v7-v8-and-max)) | A server, or a PC with a 24 GB GPU for 13B; online mode | The hardest questions: deep reasoning, real coding help, long documents. Also the teacher for every smaller tier | After v6.5, if funded |

The names are working names (see above).

**How they're made:**
- **Same recipe for every tier:** same tokenizer, data mix and chat lessons, so they behave alike
  and differ mainly in how much they know and how well they reason.
- **The big tier teaches the small ones:** once v3.5's 1B exists, it becomes the teacher for Lite
  (instead of Qwen). Small models trained this way get noticeably smarter for their size, and there
  are no license questions because every model is yours.
- **Automatic choice (v4):** the router sends easy messages ("hi", "list 3 fruits") to Lite and hard
  ones to Standard or Pro, like an "auto" mode.
- **Offline + online:** Lite and Standard run on the phone offline; Pro runs on the PC or a server
  when online mode is on.

**Timeline:** v2 and v3 are two sizes but different *generations*, so they aren't tiers of one family.
The first real tiers (Lite + Standard) come right after v3.5; the three-tier lineup with v5–v6.5;
Max after that, when money and results allow.

---

## Where the models can run (beyond phones)

Every model is exported as a **GGUF** file (`to_gguf.py`). That one format already works with
**llama.cpp, Ollama, LM Studio, llamafile** (one double-clickable file) and, in a browser, **wllama**
(llama.cpp compiled to WebAssembly). So nothing extra needs building per platform. We are *not*
planning an ONNX/WebLLM version: it would mean a second conversion path for little gain.

| Size | Realistic targets | Not realistic |
|---|---|---|
| v1-v2 (30-88M) | Phones, PCs, browsers | Microcontrollers (an ESP32 has ~0.5 MB of RAM, the file alone is 20+ MB) and smartwatches |
| v3-v4 (0.4-1.05B) | Phones, PCs, browsers, Raspberry Pi 5 (a few words per second), old laptops | Pi Zero / Pico |
| v5-v6.5 (3-7B) | PCs with a GPU or 8 GB+ RAM, Apple Silicon Macs, servers; high-end phones for 3B | Older phones |

Downloads are quantized (Q4 by default), not 16-bit: a 7B model is ~4 GB in Q4 but ~14 GB in 16-bit.

**Longer memory later:** v5-v6.5 are planned at 4,096-8,192 tokens. They can be stretched to
16-32k with a short extra training run on long documents (RoPE stretching), but the cost is real: the
"notebook" of past text (KV cache) for a 7B model at 64k tokens is ~8 GB *on top of* the model, more
than most home PCs have to spare. So longer memory is added when a use needs it (long documents,
agentic coding), not as a headline number.

**Sharing state between devices** (the phone hands a task to the PC) is a v4+ app feature: the saved
notes about you are plain text, so syncing them is easy; running one chat across two models is not
planned yet.

---

## One app for phone and PC (the plan for the website and app)

Goal: the same AI, with the same name, chats and notes, on the phone and the PC, offline or online.

**The trick: build the app once.** Write the chat screen and the "brain around the model" (chat
format, lookups, notes, tools, effort levels) in **one web codebase (TypeScript/JavaScript)**, then
package it several ways:

| Where | How it's packaged | Model runs with |
|---|---|---|
| Website (any browser) | The site itself. Also **installable as an app** (a "PWA": works offline once the model file is cached) | wllama (llama.cpp in the browser) for small models; a server for bigger ones |
| Android | Wrapped with **Capacitor** (same web code in an app shell) | llama.cpp through a native plugin |
| Windows / Mac PC | Wrapped with **Tauri** (small) or Electron | llama.cpp (`llama-server`) or wllama |
| iPhone | Same Capacitor wrapper; needs a Mac + Xcode ($99/year to keep installed) | llama.cpp |

**Same files everywhere:** one `.gguf` per model size, exactly what `to_gguf.py` already makes. The
chat format and prompts live in one shared file, so a chat behaves the same on every device.

**Things that differ between phone and PC (decide early):**
- **Wikipedia lookups:** the full index is ~10 GB, too big for a phone. Plan: the PC keeps the full
  index; the phone gets a small one (the most-read few hundred thousand articles, ~1-2 GB) or, when
  online, asks the PC/server to search. The "notes" format is the same either way.
- **Model size per device:** the app picks the tier by device (Lite on phones, Standard/Pro on PCs), or
  the router picks per question when online.
- **Saved notes about you** are a plain text file, so syncing is simple: first **export/import**, then
  optional sync through a small server or your own cloud storage. Everything stays yours; no accounts
  are needed for offline use.
- **Online mode:** a hard question can go to a bigger model on the PC (at home) or a server; the app
  says so on screen ("answered by the big model"), so nothing happens silently.

**Build order (cheapest first):**
1. A chat page on the local llama.cpp web server (works today with v2/v3)
2. The same page as a website with the model running in the browser, and as an installable PWA
3. Wrap it for Android (Capacitor) and PC (Tauri)
4. Notes sync + online mode + lookups against the small phone index
5. iPhone build, if wanted

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
