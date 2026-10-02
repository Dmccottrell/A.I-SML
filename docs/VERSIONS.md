# Version Comparison

All versions side by side. v1 and v2 are finished and run on the phone. v3's code and data are ready (13.3B tokens prepared) and its training started on 28 September (pilot: ~25.6 s/step, about 13.4 days nonstop).
v3.5, v4, v5, v6 and v6.5 are planned: their numbers are estimates and will change once v3's results are in.
Details: [V2.md](V2.md), [V3.md](V3.md), [ROADMAP.md](ROADMAP.md). Settings live in `config.py`.

**The app and the model family are called Yuvra** (working name, Yuvra.AI; see [APP.md](APP.md)). Each model is the
umbrella name plus one of **four role names** plus a generation number (checked by web search only; no trademark search yet):
**Yuvra Flare 3** (v3, phone-lite), **Yuvra Equinox 3.5** (v3.5) and **Yuvra Equinox 4** (v4: the same size, trained longer, with
skills added), **Yuvra Solstice 5** (v5), **Yuvra Apogee 6** (v6) and **Yuvra Apogee 6.5** (v6.5), then **Yuvra Apogee 7** and
**8** (the 13B+ models). Flare = smallest and fastest, Equinox = balanced everyday, Solstice = stronger (PC / online), Apogee =
most capable. Each name has its own number, which only goes up when that model is updated (so the numbers differ, like
Flare 3, Equinox 4, Solstice 5, Apogee 6 at the same time); older ones move to "Other models" in the app's picker. "+" and grown models get decimals (Flare 3.1, Flare 3.5; a grown
Flare 3 becomes Flare 4.1): see the number table in ROADMAP.md.
(Earlier Norse working names: Rune = Flare, Skald = Equinox, Saga = Solstice, Edda = Apogee. A second set, Nova, Pulsar, Quasar
and Supernova, was dropped because known AI models already use those names.)
**Tier** = which model, **version** = which generation, **effort** = how long it thinks; see the roadmap.

**Two kinds of jumps:** v1 → v2 → v3 → v3.5 each give the model a **bigger brain and more to
read**. v4 is different: it keeps v3.5's ~1.12B size but **trains it longer** (it continues from v3.5's
`pre_decay.pt` with 15–30B more tokens, so ~1.5–2× the reading), and adds **abilities around it** (specialist
skill packs, tools, thinking with effort levels, voice, your own app). The PC trains v4's brain while the app
and skills are being built, so no GPU time is wasted. It's the jump from "a model" to "an assistant".
v5 goes back to a bigger brain (3B), and it's the first version that needs the cloud.
v6 (5B) and v6.5 (7B) keep growing toward medium size, mainly for the PC and online mode.

## Size and design

|  | **v1** ✅ | **v2** ✅ | **v3** 🛠️ | **v3.5** (planned) | **v4** (planned) | **v5** (planned) | **v6** (planned) | **v6.5** (planned) |
|---|---|---|---|---|---|---|---|---|
| Model name | – | – | Yuvra Flare 3 | Yuvra Equinox 3.5 | Yuvra Equinox 4 | Yuvra Solstice 5 | Yuvra Apogee 6 | Yuvra Apogee 6.5 |
| Parameters | 29.5M | 88M | 394M | **~1.12B** | ~1.12B base + LoRA skill packs (small add-on weights, a few MB each, switched by a router) | **~3B** | **~5B** | **~7B** |
| Shape | 512 wide × 8 layers | 768 wide × 12 layers | 1024 wide × 32 layers | 2048 wide × 24 layers | Same as v3.5 | ~3072 wide × 28 layers | ~3584 wide × 36 layers | 4096 wide × 32 layers |
| Memory (context length) | 512 tokens | 1,024 tokens | 2,048 tokens; **v3-long: 8K → 16K → 32K** (stretched after training, if the tests pass) | 2,048, then stretched to **32K, goal 75K–100K** | Same as v3.5's stretched length + saved notes about you | **Goal 128K** (built for long text from the start) | **Goal 256K** | **Goal 500K** |
| Vocabulary | 8,192 | 16,384 | 32,768 | 32,768 | 32,768 | 65,536 | 65,536 | 65,536 |
| Attention | Standard | Grouped-query (faster on phones) | Grouped-query | Grouped-query | Grouped-query | Grouped-query | Grouped-query | Grouped-query |
| Download size (Q4) | ~20 MB | 89 MB | ~240 MB | ~700 MB | ~700 MB + packs | ~1.8 GB | ~3 GB | ~4 GB |
| Runs on (estimate) | Phone, PC | Phone, PC, browser | Phone, PC, browser, Raspberry Pi 5 | Phone, PC, Pi 5 (slow) | Phone, PC, Pi 5 (slow) | PC, Mac, high-end phone | PC or Mac with 8 GB+ RAM | PC or Mac with 8 GB+ RAM |

Key: ✅ finished · 🛠️ in progress · (planned) not started. Context goals beyond 2,048 tokens only count once
the long-context tests pass at that length (docs/LONG_CONTEXT.md). "Memory (context length)" is how much text the model can read at once, counted in tokens (a token is roughly three-quarters of a word).

## Training

|  | **v1** | **v2** | **v3** | **v3.5** | **v4** | **v5** | **v6** | **v6.5** |
|---|---|---|---|---|---|---|---|---|
| **Data to prepare** | 467M tokens (TinyStories) | 2.8B tokens | **12B + 1.3B anneal** (done in 1h26m) | **40B + 4.1B anneal** (~5–8 hours) | **15–30B new tokens** (more of FineWeb-Edu's `sample-100BT`, code and math that v3.5 didn't read, with tool calls, thinking steps and code-with-tests mixed in) + a new anneal set; plus the skill datasets: a few thousand examples per skill, teacher-written reasoning and tool-use runs kept only when verified correct | **~60B tokens** | **~100B tokens** (minimum) | **~140B tokens** (minimum) |
| Data mix | 100% children's stories | 80% web, 15% Wikipedia, 5% stories | 63% web, 20% Wikipedia, 10% Python, 5% math, 2% stories | 47.5% educational web (FineWeb-Edu `sample-100BT`), **17.5% everyday web (DCLM)**, 11% Wikipedia, 12.5% code in **9 languages**, 7.5% math, 4% textbook-style (Cosmopedia); no stories; final phase adds human-written Q&A | Like v3.5 (new pages, nothing repeated), plus a few % skill-aware text; then skill packs: study, stories, IT help, fact checking, coding, tool use | Like v3.5, much bigger slice (plus more code and math) | Like v5 (web, Wikipedia, multi-language code, math), bigger slice | Same as v6, bigger slice |
| Disk space | ~1 GB | ~6 GB | ~27 GB | ~88 GB (~170 GB free while building) | ~30–60 GB (can reuse v3.5's freed space) | ~120 GB | ~200 GB | ~280 GB |
| Batch per step | 65,536 tokens | 131,072 tokens | 262,144 tokens | 262,144 tokens | 262,144 tokens (then small for skill packs) | ~1M tokens (across several GPUs) | ~1M tokens (across several GPUs) | ~1M tokens (across several GPUs) |
| **Steps** | 20,000 | 20,000 | **45,000** | **152,600** | **~57,000–115,000 more**, continuing v3.5 from `pre_decay.pt`; ~1–2k per skill pack | **~60,000** | **~100,000** | **~140,000** |
| Total reading | 1.3B tokens | 2.6B tokens | 11.8B tokens | 40B tokens | ~55–70B tokens (v3.5's 40B + 15–30B more) | ~60B tokens | ~100B tokens | ~140B tokens |
| Reading per parameter | ~44 | ~30 | ~30 | ~36 | **~49–62** | ~20 | ~20 | ~20 |
| **Training time** | **~4 hours** | **~17.5–18 hours** (measured; data prep ~30 min) | **~13–14 days nonstop on the 4070** (measured: ~25.8 s/step); ran as PC afternoons + a rented RTX 3090 overnight (17.5 s/step), then from step 6,054 on a rented **RTX 5090 (6.9 s/step, measured)**: done ~Oct 3 | **2× RTX 5090 with Muon: ~14–18 days** (or Muon with its memory in RAM (`muon_cpu`) on the 4070, ~5–6.5 months; a run can move between the two) | **~1.5–2 months (+15B) or ~3–4 months (+30B)** at 70–95 s/step, while the app and skills are being built; faster with cloud nights or Muon. Then < 1 hour per skill pack | Doesn't fit in 12 GB: **cloud, ~4–7 days on 8 rented GPUs** | Cloud: **~11 days on 8 GPUs** (~2,000 GPU-hours) | Cloud: **~3 weeks on 8 GPUs** (~4,000 GPU-hours) |
| Cost | < $1 | ~$1 | ~$50–70 (3090 nights, then the RTX 5090 at ~$0.51/hr, + electricity) | **~$290–380** rented (2× RTX 5090 at ~$0.87/hr) | ~$55–270 electricity (half to one v3.5 run), a bit more with cloud nights | **~$800–2,500** cloud rental (or $0, see below) | **~$4,000–6,000** (less if grown from v5 or with a grant) | **~$8,000–12,000** (less if grown from v6 or with a grant) |
| Chat fine-tuning | 5k single messages, ~10 min | ~105k multi-turn chats, ~1–2 hrs | Multi-turn + lookup + "I don't know" + memory + reply-suggestion lessons, NEFTune, then DPO on rule-checked answer pairs | Same as v3 | Skill packs (LoRA) + router + tool-use and thinking examples | Everything from v3–v4, redone on the 3B brain | Same lessons; QLoRA fits on the 4070 | Same lessons; QLoRA fits on the 4070 |
| Teacher model (a bigger open AI helping) | — | — (its chat data was partly written by bigger AIs) | **Yes:** a ~7B open model (or a hosted one) writes lookup and "I don't know" examples; DPO pairs are scored by checkable rules | Same, plus worked step-by-step math problems for the chat lessons | Writes skill-pack, reasoning and tool-use examples (checked by running tests or comparing to known answers) | Same, bigger teacher possible in the cloud | Same; the bigger tiers teach the smaller ones | Same |
| Main tools added | PyTorch, CUDA, llama.cpp | Hugging Face `datasets` | Keyword search (SQLite FTS5), FAISS (optional), lm-evaluation-harness, TensorBoard, 8-bit optimizer (optional), a rented cloud GPU (Vast.ai), phone alerts (ntfy), Hugging Face Hub (off-machine backup), a small embedding model (memory search), web search (online mode) | **Muon optimizer** (won `muon_test.py`), 2 GPUs (DDP), new data: DCLM, Cosmopedia, Stack Exchange Q&A | LoRA, tool calling, sandbox, web search, Whisper + Piper (voice) | FSDP (multi-GPU) | vLLM or llama.cpp server (online mode) | Same as v6 |
| New code needed | — | Pause/resume, KV cache | Pilot runs, gradient checkpointing, lookup index, teacher script, DPO, NEFTune, checkpoint averaging, memory, suggestions, context meter, `compare.py`, PC/cloud handoff, off-machine backup, long-context tools, Muon (to test) | CPU offload for the optimizer, gradient checkpointing, multi-language code data | Router with effort levels (thinking budget), tool registry, sandbox, voice, coding harness, app/website | Multi-GPU training (FSDP), streaming data shards, vision helper | Model growth (up-scaling from v5), 8k-token training, server setup | Growth from v6 |

**Reading per parameter** is total tokens ÷ parameters: v3 reads 11.8B tokens with 394M parameters, **about 30 per parameter** (v2 ~30, v3.5 ~29). "Compute-optimal" is about 20; today's best small models read far more (SmolLM2-360M ~11,000 per parameter), which is the main reason they score higher. See [Speed and safety experiments](ROADMAP.md#speed-and-safety-experiments).

v1 read its small dataset about **2.8 times over**; v2, v3 and v3.5 read their data about once, which is
better for learning general knowledge. v3.5 needs ~18.9B tokens of web text, more than the 10B in
the FineWeb-Edu slice v2 and v3 use, so it switches to the bigger `sample-100BT` slice. Its 15%
Wikipedia share (~4.5B tokens) is about one full read of English Wikipedia. v3.5 reads 40B tokens
(~36 per parameter) rather than the "efficient" 22B: a better model at the same size and phone speed.
Everyday web pages (DCLM) are added on top of the educational ones, and TinyStories are dropped (written
by GPT-3.5/4). Full breakdown: [ROADMAP.md](ROADMAP.md#v35s-data-44b-tokens-to-prepare).

**Fair testing:** worked math problems for the chat lessons are written by the teacher model. The
real GSM8K questions (a well-known math test) are kept for testing only, never for training.

## Results

|  | **v1** | **v2** | **v3** | **v3.5** | **v4** | **v5** | **v6** | **v6.5** |
|---|---|---|---|---|---|---|---|---|
| Final val loss | **1.279** | **2.929** (best), 2.984 at the last step | Measured when trained | Measured when trained | Measured when trained | Measured when trained | Measured when trained | Measured when trained |
| Phone file | 32 MB | **89 MB** | ~420 MB (Q8) or **~240 MB (Q4)** | ~1.2 GB (Q8) or **~700 MB (Q4)** | v3.5's file + a few MB per skill pack | ~3.2 GB (Q8) or **~1.8 GB (Q4)** | ~3 GB (Q4): high-end phones only | ~4–4.5 GB (Q4): mainly PC and server |
| Test sheet (`evaluate.py`, /20) | Only identity and story questions | **18/20** (baseline) | Goal: clearly beat v2 | Goal: beat v3 | Goal: beat v3.5, plus new tests for tools and skills | Goal: beat v4 | Goal: beat v5 | Goal: beat v6 |
| v3 test sheet (`prompts_v3.jsonl`, /41) | — | Run to set the baseline* | Goal: clearly beat v2, most of all on facts_hard, instructions, topic_switch, honesty, correction | Goal: beat v3 | Goal: beat v3.5, plus thinking and tool-use tests | Goal: beat v4 | Goal: beat v5 | Goal: beat v6 |
| Phone speed (PocketPal, Q8_0) | — | **~210–245 tokens/s**, first word in <0.1 s | Slower (4.5× bigger); measured when done | Slower again (~2.7× v3); measured when done | Same as v3.5 (skill packs add little) | Slower; measured when done | Slow on phones; fast on PC | PC and server |
| HellaSwag (`exam.py`, full test, random = 25%) | — | **28.4%** (baseline) | **31.7% at step 15,000** (full test; the 500-question mini-exam reads ~5 points high); forecast **~34–38%** | Forecast **~44–51%** (1.12B, 40B tokens with everyday web) | Forecast **~46–54%** (v3.5 + 2–3 points from the extra reading) | Goal: beat v4, plus harder reasoning and coding tests | Goal: beat v5 | Goal: beat v6 |
| Public yardsticks (`lm-evaluation-harness`: ARC, MMLU; small GSM8K-style math) | — | Run to set the baseline | Goal: beat v2 | Goal: beat v3 | Measured with thinking on and off | Goal: beat v4 | Goal: beat v5 | Goal: beat v6 |
| Tool, thinking and coding tests (v4+) | — | — | — | — | New: right tool called, task finished, thinking on vs off, small coding tasks | Goal: beat v4 | Goal: beat v5 | Goal: beat v6 |

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
| Conversations | One message at a time | ✅ Remembers the chat | ✅ ~7–12 turns with lookups (old notes dropped); v3-long: 35–130+ | ✅ Hundreds of turns once stretched | ✅ Same, plus remembers you between chats | ✅ Very long chats (128K goal) | ✅ Longer still | ✅ Longest |
| Remembers you (saved facts, earlier chats) | ❌ | ❌ | ✅ Saves facts itself ("my name is ..."), finds earlier chats by meaning, never saves passwords | ✅ Better judgement about what to save | ✅ Memory screen in the app | ✅ Summarizes old chats into memories | ✅ | ✅ |
| Reply suggestions | ❌ | ❌ | ✅ Suggests what you might ask next (simple) | ✅ Sharper suggestions | ✅ Greyed-out in the app; teacher-written follow-ups if needed | ✅ | ✅ | ✅ |
| Shows what it remembers (context meter) | ❌ | ❌ | ✅ `context` / `window` in the chat | ✅ | ✅ A meter in the app | ✅ | ✅ | ✅ |
| Code | ❌ | ❌ | ⚠️ Basic Python autocomplete | ⚠️ Small functions, several languages | ✅ Coding helper (agentic, small tasks): reads files, suggests fixes, runs tests in a loop inside a sandbox | ✅ Real coding help: multi-file changes, explains code | ✅ Stronger coding help across languages | ✅ Best coding help of all versions |
| Answer quality and style | Basic | Basic | ✅ Improved by preference training | ✅ | ✅ Picks the right specialist per question | ✅ Clearly better | ✅ Clearly better | ✅ Best |
| Math | ❌ | ❌ | ⚠️ Some step-by-step math (5% math reading), still error-prone | ⚠️ Better: also learns from worked math problems, still error-prone | ✅ **Exact**, using a calculator tool | ✅ Exact with tools, word problems work | ✅ Exact with tools, harder word problems | ✅ Exact with tools, harder word problems |
| Reasoning | ❌ | ❌ | ⚠️ Still weak | ⚠️ Better | ⚠️ Better with adaptive thinking and agent mode (still limited by 1B) | ✅ Decent multi-step reasoning for its size | ✅ Stronger multi-step reasoning | ✅ Strongest: closest to a mini Claude for everyday tasks |
| Tools (calculator, date, your files, reminders) | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ Uses tools more reliably | ✅ | ✅ |
| Voice (talk and listen) | ❌ | ❌ | ❌ | ❌ | ✅ With small speech models alongside | ✅ | ✅ | ✅ |
| Where you use it | PocketPal | PocketPal | PocketPal | PocketPal | ✅ **Your own website and app** | Phone (Q4) + server-hosted website | PC, high-end phones, the app's online mode | PC and server (the app's online brain) |
| Thinking (adaptive and extended) | ❌ | ❌ | ⚠️ Trial: short step-by-step math (a fine-tune, no retraining) | ⚠️ Short thinking on math and multi-step questions | ✅ Adaptive thinking | ✅ Longer thinking (4,096-token memory) | ✅ Extended thinking | ✅ Extended thinking (best) |
| Effort levels (Quick / Balanced / Deep) | ❌ | ❌ | ❌ | ❌ | ✅ You choose, or Auto picks | ✅ | ✅ | ✅ |
| Documents (summaries, rewrites, drafts) | ❌ | ❌ | ⚠️ Short texts | ✅ Short documents | ✅ Document helper skill pack | ✅ Longer documents | ✅ Long documents (8,192 tokens) | ✅ Long documents |
| Images (charts, screenshots) | ❌ | ❌ | ❌ | ❌ | ❌ | ⚠️ Through a vision helper (image to text) | ⚠️ Same, better | ⚠️ Same, best |
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

v3.5 → v4 won't feel like "smarter" the way v2 → v3 does. It will feel like **it can do more**, on a
brain that is also a bit sharper:

- **A better-read brain, same size.** v4's brain is v3.5 trained longer (15–30B more tokens, ~43–58 per
  parameter instead of ~29), so it knows more and slips less, with the same phone speed and file size.
  Forecast: ~2–3 HellaSwag points above v3.5.

- **Right tool for the job.** Ask "what's 1,847 × 392?" and it calls the calculator, so the
  answer is exact every time. Ask "what's today's date?" and it checks the clock instead of guessing.
- **Specialists.** A router reads your question and switches on the right skill pack: study help,
  stories, IT troubleshooting, fact checking or coding. Each pack is trained separately (under an
  hour), so adding one never breaks the others.
- **Coding help.** A small harness lets it work in a loop: read a file, propose a change, run the
  tests, see the result and try again, inside a safe sandbox. It's in the same spirit as Claude Code,
  but only for small, simple tasks (a ~1B model can't do the big benchmark tasks). Its memory is the
  limit: 2,048 tokens fills up after about two small files. Details: [ROADMAP.md](ROADMAP.md#agentic-coding-a-coding-helper-that-works-in-a-loop).
- **It thinks before hard questions.** For math and multi-step problems it writes out its reasoning
  first. You choose **Quick, Balanced or Deep**, or leave it on Auto and the router decides. Easy
  questions stay fast. It uses the same steps the big models use (plan, look up or calculate, check,
  answer), and it's slower on Deep. Memory is the limit: thinking eats into 2,048 tokens.
- **Documents.** A document helper skill pack summarizes, rewrites, drafts and turns notes into
  to-do lists (short documents at first).
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
- **It can "see" through a helper.** A small open image-to-text model beside ours describes photos,
  screenshots and charts, and our model reads the description. Our own vision model isn't planned.
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
| Memory (context length) | 4,096 tokens | 8,192 tokens | 8,192 tokens |
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
- **v3 (Yuvra Flare 3):** an **accurate, honest** assistant that looks facts up, admits when it doesn't know, and
  handles basic code
- **v3.5 (Yuvra Equinox 3.5):** v3's features on a **~1.12B brain** that reads 40B tokens (educational and everyday web, code, math)
- **v4 (Yuvra Equinox 4):** v3.5's brain **trained longer**, turned into a **personal assistant**: specialist skills, exact math with tools, a Quick / Balanced / Deep
  thinking dial, coding help, documents, voice, and your own app
- **v5 (Yuvra Solstice 5):** a **genuinely capable** 3B assistant: the first version trained in the cloud, and the first
  that can "see" pictures through a helper
- **v6 (Yuvra Apogee 6):** a **5B bigger small** model: stronger reasoning and coding, powering the PC and online mode
- **v6.5 (Yuvra Apogee 6.5):** a **7B borderline medium** model: the strongest version so far and the app's online brain
- **v7, v8 (Yuvra Apogee 7 and 8):** the future top tier, ~13B then ~30B, if funding and results allow (online mode)

## Update log

Fill in real numbers as each version finishes:

| Version | Final val loss | Test sheet | Notes |
|---|---|---|---|
| v1 | 1.279 | — | Runs on the phone (PocketPal, 32 MB) |
| v2 | 2.929 best, 2.984 final | 18/20 (identity 2/2, facts 7/8, explain 5/5, advice 2/2, writing 1/1, stories 1/2) | HellaSwag 28.4% (ckpt.pt), about GPT-2 (124M) level. 20,000 steps at ~3.5 s/step on the RTX 4070; chat fine-tuning ~1.5 hours. Phone: 89 MB, ~210–245 tokens/s. The test sheet checks key words, so answers can pass with wrong details. Phone tests found wrong rare facts (Illinois), no self-correction, topic stickiness and settings problems (see above) |
| v3 | | Pending: run after training | Data ready: 12.0B training tokens + 1.3B anneal tokens + 10M val; 222 documents with test questions removed (193 web, 14 math, 10 top-rated web, 5 anneal math); prepared in 1 hour 26 minutes (~2.6M tokens/s on average). Pilot (RTX 4070, 394.3M parameters): `torch.compile` works once its cache folder is short (Windows 260-character path limit); ~25 s/step compiled vs ~30–38 s without, identical loss, GPU memory ~10.2 GB vs ~11.1 GB; so the full run is ~13–14 days. Cloud pilot (rented RTX 3090): 17.5 s/step, 10.1 GB. Pretraining started; resumed on the cloud at step 1,383; step 1,000 val 3.755, step 1,500 val 3.457, **step 2,000 val 3.426 and HellaSwag 33.4%** (500-question mini-exam, ±2 points; v2 finished at 28.4%); step 3,000 val 3.194, step 3,500 val 2.947, **step 4,000 val 2.900 and HellaSwag 35.6%**, ahead of the forecast (final forecast raised from 37–42% to ~40–45%). Added while it trains: the first skill packs (**Study helper** and **Teacher assistant**, Betas, with a router, an access toggle and PDF/Word export; see SKILLS.md), reply suggestions, remembering you (saved facts, earlier chats, search by meaning), the context meter, old lookup notes dropped (7–12 turns instead of 2–3), and the long-context tools for v3-long Moved to a rented **RTX 5090** at step 6,054 (6.9 s/step). Mini-exam (first 500 questions): 33.6% at 6,000, 36.6% at 8,000, 37.0% at 10,000, 38.0% at 14,000, 36% at 16,000, **39.4% at 18,000**; **full test (all 10,042): 31.7% at step 15,000** (37% on the first 500, which are ~5 points easier; v2: 28.4%). Best val loss **2.636 at step 17,500**. Added while it trains: web search (online mode) with web-reading lessons, honest answers about other AIs, the spread-out exam for v3.5, and the app design (APP.md) |
| v3.5 | | | Plan locked (Oct 2): 1.12B, 40B tokens with everyday web, Muon (won `muon_test.py`: AdamW's final loss in ~33% fewer steps, 3.809 vs 3.933 at the end), 2× RTX 5090. Data built on the PC in ~3.5 hours (~3.6M tokens/s). First the v3plus vs v3plus-edu A/B test of the new mix |
| v4 | | | Brain = v3.5 continued from `pre_decay.pt` (+15–30B tokens), trained while the app and skills are built |
| v5 | | | |
| v6 | | | |
| v6.5 | | | |
