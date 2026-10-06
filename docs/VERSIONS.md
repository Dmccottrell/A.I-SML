# Version Comparison

All versions side by side. v1 and v2 are finished and run on the phone. v3's pretraining finished at step 45,000 (October 2026; HellaSwag 37.1% on a 2,000-question sample, validation loss about 2.68); its chat tuning is next.
v3.5, v4, v5, v6 and v6.5 are planned: their numbers are estimates and will change once v3's results are in.
> **Update (Oct 2026): Emvryx moves to open bases, as the 2.x series.** The whole family is the 2.x series: **Ember 2** (v2) and **Flare 2** (v3) were trained from scratch, and the open-base models are **Flare 2.5** (was v3.5), **Equinox 2** (was v4), **Solstice 2** (was v5), **Apogee 2** (was v6); a "+" refresh takes the next decimal (Flare 2.6). Generation 1 (Ember 2, Flare 2) was trained from scratch. From v3.5 on, models are fine-tuned from an open model instead of trained from scratch
> (cheaper and stronger: about $183 for a forecast ~41-45% from scratch versus a few dollars for roughly 65% on a 1.5B open model).
> They carry the Emvryx name only; the base and its licence are credited in `NOTICE`, and the docs never call a fine-tuned model "from scratch".
> **v1, v2 and v3 (Ember 2, Flare 2) stay from scratch**, and the from-scratch v3.5 run was **stopped** (step recorded in `docs/V3_5.md`). **Flare 2.5 is
> Qwen 2.5 1.5B with a 32K context** ([OPEN_MODEL.md](OPEN_MODEL.md)). Later rungs (suggestions, not chosen): Equinox 2 about a 4B base,
> Solstice 2 about an 8B base, Apogee 2 about a 14B base on rented GPUs; pick each base when its turn comes, because better open models will exist.
> **Order of work:** all the 2.0 builds first (Flare 2.5, Equinox 2, Solstice 2, Apogee 2), then the improved Equinox 2.5, Solstice 2.5 and Apogee 2.5 (see [OPEN_MODEL.md](OPEN_MODEL.md)).
> The rest of this file was written for the from-scratch plan: where it says a version's brain is trained from scratch or grown from v3.5, read it with this update.

Details: [V2.md](V2.md), [V3.md](V3.md), [ROADMAP.md](ROADMAP.md), [LESSONS.md](LESSONS.md) (what we learned). Settings live in `config.py`.

**The app and the model family are called Emvryx** (working name, Emvryx.AI; see [APP.md](APP.md)). Each model is the
umbrella name plus one of **five role names** plus a generation number (checked by web search only; no trademark search yet):
**Emvryx Ember 2** (v2: the small first assistant, 88M) and **Emvryx Flare 2** (v3, 394M) were trained from scratch (generation 1). The open-base
**2.x series** (generation 2) is **Emvryx Flare 2.5** (Qwen 2.5 1.5B; was v3.5), **Emvryx Equinox 2** (about 4B; was v4),
**Emvryx Solstice 2** (about 8B; was v5) and **Emvryx Apogee 2** (about 14B; was v6). Ember = small and quick (the lowest name), Flare = fast and light,
Equinox = balanced everyday, Solstice = stronger (PC / online), Apogee = most capable. Each name has its own number, which only goes up when that model
is updated; a newer generation takes the main spot in the app's picker. A "+" refresh takes the next decimal (Flare 2.6):
see the number table in ROADMAP.md.
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

## Flare 2.5 as built now (Qwen 2.5 1.5B base, Oct 2026; the version slot was v3.5)

The tables below show this version in the Flare 2.5 column (the old v3.5 slot). The from-scratch plan it replaced (1.12B, 8K context, 75,000 steps, about $183) is recorded in [V3_5.md](V3_5.md).

| | **Flare 2.5 (Qwen 2.5 1.5B base)** |
|---|---|
| Base | `Qwen/Qwen2.5-1.5B-Instruct`, Apache 2.0, credited in `NOTICE`; **not trained from scratch** |
| Brain | 1.54B parameters (28 layers, 1536 wide, 2 KV heads); we train 73.9M LoRA parameters on top (4.6%) |
| Memory (context length) | **32,768 tokens** (about 28 KB per token, so about 0.9 GB for 32K) |
| What it learns here | The same lessons v3 learned (`data/v3/chat.jsonl`: 109,917 chats: lookups, "I don't know", corrections, instructions, small talk, stories), shown in ChatML |
| Steps | **988** (one pass), 8 micro-batches of up to 8,192 tokens each, saved every 100 |
| Where / how long / cost | One RTX 5090, **7.1 s/step, 18.6 GB**, about 2 hours, about **$1** (the pilot; the full run is in progress) |
| Not carried over | Saving things to memory with tool calls (no tool tokens in the open format) |
| Quality | **HellaSwag 67.2%** (2,000-question sample; plain Qwen 2.5 1.5B 65.6%); identity test 16/16; the lookup and rules sheets are still to run |
| Phone file | about 1 GB at Q4 (an estimate; the real size comes after conversion) |
| Details | [OPEN_MODEL.md](OPEN_MODEL.md) |

## Size and design

|  | **v1** ✅ | **v2** ✅ | **v3** 🛠️ | **Flare 2.5** 🛠️ (was v3.5, Qwen base) | **Equinox 2** (was v4, Qwen3-4B) | **Solstice 2** (was v5, Qwen3-8B) | **Apogee 2** (was v6, Qwen3-14B) | **v6.5** (TBD base) |
|---|---|---|---|---|---|---|---|---|
| Model name | – | – | Emvryx Flare 2 | Emvryx Flare 2.5 | Emvryx Equinox 2 | Emvryx Solstice 2 | Emvryx Apogee 2 | Emvryx Apogee 2.5 or later |
| Parameters | 29.5M | 88M | 394M | **1.54B** (Qwen 2.5 base) + 73.9M LoRA we train | Qwen3-4B (4.0B) + LoRA skill packs (small add-on weights, a few MB each, switched by a router) | Qwen3-8B (8.2B) | Qwen3-14B (14.8B) | TBD (a bigger open base, chosen when it is time) |
| Shape | 512 wide × 8 layers | 768 wide × 12 layers | 1024 wide × 32 layers | 1536 wide × 28 layers | 2560 wide × 36 layers | 4096 wide × 36 layers | 5120 wide × 40 layers | TBD |
| Memory (context length) | 512 tokens | 1,024 tokens | 2,048 tokens; **v3-long: 8K → 16K → 32K** (stretched after training, if the tests pass) | **32,768 tokens** from the start (the base's own) | **32K default, up to 128K** (YaRN) + saved notes about you | **32K default, up to 128K** (YaRN) | **32K default, up to 128K** (YaRN) | TBD (the base's context) |
| Vocabulary | 8,192 | 16,384 | 32,768 | 151,936 (Qwen's) | 151,936 (Qwen's) | 151,936 | 151,936 | TBD |
| Attention | Standard | Grouped-query (faster on phones) | Grouped-query | Grouped-query (2 KV heads) | Grouped-query | Grouped-query | Grouped-query | Grouped-query |
| Download size (Q4) | ~20 MB | 89 MB | ~240 MB | ~1 GB (estimate) | ~2.5 GB (Q4) | ~5 GB (Q4) | ~9 GB (Q4) | TBD |
| Runs on (estimate) | Phone, PC | Phone, PC, browser | Phone, PC, browser, Raspberry Pi 5 | PC; phone with 4 GB+ memory (estimate) | Phone, PC, Pi 5 (slow) | PC, Mac, high-end phone | PC or Mac with 8 GB+ RAM | PC with a big GPU, or a server |

Key: ✅ finished · 🛠️ in progress · (planned) not started. Context goals beyond 2,048 tokens only count once
the long-context tests pass at that length (docs/LONG_CONTEXT.md). "Memory (context length)" is how much text the model can read at once, counted in tokens (a token is roughly three-quarters of a word).

## Training

|  | **v1** | **v2** | **v3** | **Flare 2.5** (was v3.5, Qwen base) | **Equinox 2** (was v4, Qwen3-4B) | **Solstice 2** (was v5, Qwen3-8B) | **Apogee 2** (was v6, Qwen3-14B) | **v6.5** (TBD base) |
|---|---|---|---|---|---|---|---|---|
| **Data to prepare** | 467M tokens (TinyStories) | 2.8B tokens | **12B + 1.3B anneal** (done in 1h26m) | **None new**: the v3 lessons (`data/v3/chat.jsonl`, 109,917 chats) | **None new**: the v3 lessons (109,917 chats) + new lessons for the mistakes found + long-document lessons | **None new** (same lessons, plus fixes) | **None new** (same lessons, plus fixes) | TBD |
| Data mix | 100% children's stories | 80% web, 15% Wikipedia, 5% stories | 63% web, 20% Wikipedia, 10% Python, 5% math, 2% stories | v3's chat lessons only; no pretraining here (the base's own pretraining is not ours) | Chat lessons only (lookups, "I don't know", corrections, instructions, small talk, stories); no pretraining here | Same | Same | TBD |
| Disk space | ~1 GB | ~6 GB | ~27 GB | ~3 GB model + 0.3 GB lessons | ~8 GB model + 0.3 GB lessons | ~17 GB model + 0.3 GB | ~30 GB model (bf16) + 9 GB for the 4-bit copy | TBD |
| Batch per step | 65,536 tokens | 131,072 tokens | 262,144 tokens | ~65K padded tokens (8 micro-batches of up to 8,192) | ~65K padded tokens (4096 × 16 micro-batches) | ~65K padded tokens (2048 × 32) | ~65K padded tokens (2048 × 32) | TBD |
| **Steps** | 20,000 | 20,000 | **45,000** | **988** (one pass over the lessons) | **~988** (one pass; guess) | **~988** (guess) | **~988** (guess) | TBD |
| Total reading | 1.3B tokens | 2.6B tokens | 11.8B tokens | 109,917 chats, one pass | ~110K chats, one pass | ~110K chats, one pass | ~110K chats, one pass | TBD |
| Reading per parameter | ~44 | ~30 | ~30 | n/a (fine-tune) | n/a (fine-tune) | n/a | n/a | TBD |
| **Training time** | **~4 hours** | **~17.5–18 hours** (measured; data prep ~30 min) | **~13–14 days nonstop on the 4070** (measured: ~25.8 s/step); ran as PC afternoons + a rented RTX 3090 overnight (17.5 s/step), then from step 6,054 on a rented **RTX 5090 (6.9 s/step, measured)**: done ~Oct 3 | **~2 hours** on one RTX 5090 (7.1 s/step, 18.6 GB); the RTX 4070 also works, slower | **~5 h** on one RTX 5090 (18 s/step, estimate) | **~10 h** on one RTX 5090 (38 s/step, estimate) | **~24 h** on one RTX 5090 with 4-bit weights (89 s/step, estimate) | TBD |
| Cost | < $1 | ~$1 | ~$50–70 (3090 nights, then the RTX 5090 at ~$0.51/hr, + electricity) | **~$1** rented (one RTX 5090 at ~$0.51/hr) | **~$2.60** rented (RTX 5090 at ~$0.51/hr) | **~$5** rented | **~$12** rented | TBD |
| Chat fine-tuning | 5k single messages, ~10 min | ~105k multi-turn chats, ~1–2 hrs | Multi-turn + lookup + "I don't know" + memory + reply-suggestion lessons, NEFTune, then DPO on rule-checked answer pairs | LoRA rank 64, learning rate 2e-4, one pass (`finetune_open.py`) | LoRA rank 64, learning rate 2e-4, one pass (`finetune_open.py --model equinox-4`) | LoRA rank 32 (`--model solstice-5`) | QLoRA rank 32, 4-bit base (`--model apogee-6`) | TBD |
| Teacher model (a bigger open AI helping) | — | — (its chat data was partly written by bigger AIs) | **Yes:** a ~7B open model (or a hosted one) writes lookup and "I don't know" examples; DPO pairs are scored by checkable rules | Same as v3 (the lessons already exist) | Same as v3 | Same as v3 | Same as v3 | TBD |
| Main tools added | PyTorch, CUDA, llama.cpp | Hugging Face `datasets` | Keyword search (SQLite FTS5), FAISS (optional), lm-evaluation-harness, TensorBoard, 8-bit optimizer (optional), a rented cloud GPU (Vast.ai), phone alerts (ntfy), Hugging Face Hub (off-machine backup), a small embedding model (memory search), web search (online mode) | `finetune_open.py`, `open_tokenizer.py`, a ChatML branch in `chat.py`, `NOTICE` | `open_models.py` presets, skill packs + router, tools, voice | Same presets | Same presets, `--quant4` (bitsandbytes) | TBD |
| New code needed | — | Pause/resume, KV cache | Pilot runs, gradient checkpointing, lookup index, teacher script, DPO, NEFTune, checkpoint averaging, memory, suggestions, context meter, `compare.py`, PC/cloud handoff, off-machine backup, long-context tools, Muon (to test) | Done and tested with a tiny model; the real run is in progress | Pilot on the real weights (first guesses not yet run) | Same pilot | Same pilot; merge needs ~30 GB | TBD |

## Settings carried forward by version

What each version trains with (v1–v3.5 are the real values in `config.py`) and what v4–v6.5 should **start
with**, given what changed for v3, v3.5 and v4. **v4 and later are starting guesses, not measured**: each one
is confirmed or changed by its own pilot run (`train.py --pilot`). Why each choice was made is in
[LESSONS.md](LESSONS.md).

| Setting | **v1** | **v2** | **v3** | **Flare 2.5** (was v3.5, Qwen base) | **Equinox 2** (was v4, Qwen3-4B) | **Solstice 2** (was v5, Qwen3-8B) | **Apogee 2** (was v6, Qwen3-14B) | **v6.5** (TBD base) |
|---|---|---|---|---|---|---|---|---|
| Optimizer | adamw | adamw | adamw | AdamW on the LoRA weights only | AdamW on the LoRA weights only | AdamW on the LoRA weights only | AdamW on the LoRA weights only | TBD |
| LR schedule | cosine | cosine | **wsd** (steady, then fade over the last 10%) | 30 warm-up steps, then cosine down to 10% | 30 warm-up steps, then cosine down to 10% | 30 warm-up steps, then cosine down to 10% | 30 warm-up steps, then cosine down to 10% | TBD |
| Steps (`max_iters`) | 20,000 | 20,000 | 45,000 | 988 | ~988 (guess) | ~988 (guess) | ~988 (guess) | TBD |
| Tokens per step | 65,536 | 131,072 | 262,144 | ~65K padded | ~65K padded | ~65K padded | ~65K padded | TBD |
| Warm-up steps | 1,000 | 1,000 | 1,000 | 30 | 30 | 30 | 30 | TBD |
| Peak learning rate | 6e-4 | 6e-4 | 4e-4 | 2e-4 | 2e-4 (lower it if the loss jumps) | 1e-4 to 2e-4 (to be tuned) | 1e-4 (QLoRA; to be tuned) | TBD |
| Final learning rate | 6e-5 | 6e-5 | 4e-5 | 2e-5 | 10% of peak | 10% of peak | 10% of peak | TBD |
| Fade length (`decay_frac`) | – | – | 10% | cosine over the whole run | cosine over the whole run | cosine over the whole run | cosine over the whole run | TBD |
| Mini-exam | off | off | every 2,000 steps, 500 questions, first N (≈5 points too easy) | after training (`benchmarks.py`) | after training (`benchmarks.py`) | after training (`benchmarks.py`) | after training (`benchmarks.py`) | TBD |
| Snapshots for averaging (`snapshot_every`) | off | off | 900 (5 in the fade) | none | none | none | none | TBD |
| Gradient checkpointing | off | off | off | on | on | on | on | TBD |
| Saves (`save_every`) | 250 | 200 | 100 | every 100 steps | every 100 steps | every 100 steps | every 100 steps | TBD |
| Chat tuning: passes / batch / learning rate | 3 / 16 / 5e-5 | 2 / 8 / 1e-4 | 2 / 4 / 5e-5 | this is the chat tuning: 1 pass / ~78 chats per step / 2e-4 | this is the chat tuning: 1 pass / ~65K tokens per step | this is the chat tuning: 1 pass / ~65K tokens per step | this is the chat tuning: 1 pass / ~65K tokens per step | TBD |
| NEFTune noise | – | – | 5 | off | off | off | off | TBD |
| Preference training (DPO) | – | – | β 0.1, rate 2e-6 | not yet | planned (DPO), a "+" step | planned (DPO), a "+" step | planned (DPO), a "+" step | TBD |
| Sampling in the app (temperature / allowed range) | – | **0.45 / 0.3–0.6** (Ember) | **0.6 / 0.2–0.8** (Flare 2) | 0.65 / 0.2–0.9 (to be re-tested on this model) | Qwen suggests ~0.7 for non-thinking chat (to be re-tested) | Qwen suggests ~0.7 for non-thinking chat (to be re-tested) | Qwen suggests ~0.7 for non-thinking chat (to be re-tested) | TBD |
| Step time measured | – | – | 4070 25.8 s; 3090 17.5 s; **5090 6.9 s** | **7.1 s** (one RTX 5090, 18.6 GB peak) | not yet (estimate 18 s) | not yet (estimate 38 s) | not yet (estimate 89 s) | TBD |

**How the guesses were made:**
- **Peak learning rate** falls with size as roughly `size^-0.27`: v2 (88M) 6e-4 → v3 (394M) 4e-4 → v3.5 (1.12B)
  3e-4 fits that line, so v5 (3B) ≈ 2.3e-4, v6 (5B) ≈ 2.0e-4, v6.5 (7B) ≈ 1.8e-4. The final rate is a tenth of the peak.
  This is a line through three points, and Muon sets its own step size for the weight matrices (`muon.py`), so each
  value is checked at the pilot.
- **Snapshot spacing** is the fade length (10% of the steps) divided by 5, like v3 (4,500 ÷ 5 = 900) and v3.5 (15,260 ÷ 5 ≈ 3,050).
- **Mini-exam from v3.5 on is spread over the whole test**, because v3's first-500 version read ~5 points high; v4+ use every question.
- **Muon's saving (~33% fewer steps for the same loss) was measured only on a 39M model** (`muon_test.py`),
  so v5's trim is an option, not a plan. Whether Muon works with FSDP is not known yet.
- **Sampling** starts lower and narrower for smaller models (Ember's 0.3–0.6 is the narrowest). These are in
  `models.json` and are tuned with `evaluate.py --temperature`.

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

|  | **v1** | **v2** | **v3** | **Flare 2.5** (was v3.5, Qwen base) | **Equinox 2** (was v4, Qwen3-4B) | **Solstice 2** (was v5, Qwen3-8B) | **Apogee 2** (was v6, Qwen3-14B) | **v6.5** (TBD base) |
|---|---|---|---|---|---|---|---|---|
| Final val loss | **1.279** | **2.929** (best), 2.984 at the last step | **≈2.68** (step 45,000) | Training loss 0.95 at the start, about 0.75 at the end (988 steps) | Measured when trained | Measured when trained | Measured when trained | TBD |
| Phone file | 32 MB | **89 MB** | ~420 MB (Q8) or **~240 MB (Q4)** | **~1 GB (Q4)** (estimate) | ~2.5 GB (Q4) | ~5 GB (Q4) | ~9 GB (Q4) | TBD |
| Test sheet (`evaluate.py`, /20) | Only identity and story questions | **18/20** (baseline) | Goal: clearly beat v2 | Measured after training | Goal: beat Flare 2.5 | Goal: beat Flare 2.5 | Goal: beat Flare 2.5 | TBD |
| v3 test sheet (`prompts_v3.jsonl`, /41) | — | Run to set the baseline* | Goal: clearly beat v2, most of all on facts_hard, instructions, topic_switch, honesty, correction | Goal: beat v3 | Goal: beat Flare 2.5 | Goal: beat Flare 2.5 | Goal: beat Flare 2.5 | TBD |
| Phone speed (PocketPal, Q8_0) | — | **~210–245 tokens/s**, first word in <0.1 s | Slower (4.5× bigger); measured when done | Slower than v3 (~4× bigger); measured when done | Slower than Flare 2.5 (~2.6× bigger); measured when done | ~5× bigger; measured when done | ~10× bigger; PC or server | TBD |
| HellaSwag (`exam.py`, full test, random = 25%) | — | **28.4%** (baseline) | **31.7% at step 15,000** (full test; the 500-question mini-exam reads ~5 points high); forecast **~34–38%** | **67.2%** (2,000-question sample; plain Qwen 2.5 1.5B 65.6%) | Not measured. Run `exam.py` after training | Not measured. Run `exam.py` after training | Not measured. Run `exam.py` after training | TBD |
| Public yardsticks (`lm-evaluation-harness`: ARC, MMLU; small GSM8K-style math) | — | Run to set the baseline | Goal: beat v2 | Goal: beat v3 | Base model, published and from memory: MMLU about 73% (ours measured after training) | Base model MMLU about 77% (from memory) | Base model MMLU about 81% (from memory) | TBD |
| Tool, thinking and coding tests (v4+) | — | — | — | — | Goal: tools and thinking from v4 on (see the roadmap) | Goal: tools and thinking from v4 on (see the roadmap) | Goal: tools and thinking from v4 on (see the roadmap) | TBD |

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

| Ability | **v1** | **v2** (expected) | **v3** (goal) | **Flare 2.5** (goal) | **v4** (goal) | **v5** (goal) | **v6** (goal) | **v6.5** (goal) |
|---|---|---|---|---|---|---|---|---|
| Children's stories | ✅ Good | ✅ Good | ✅ Good | ✅ Good | ✅ Story-writer skill pack | ✅ Richer, longer stories | ✅ Long, well-written stories | ✅ Long, well-written stories |
| Grammar and fluency | Simple | Good | Better | ✅ Natural | ✅ Natural | ✅ Natural | ✅ Natural | ✅ Natural |
| General knowledge (from memory) | ❌ None | ⚠️ Basic, often wrong | ✅ Better, still imperfect | ✅ Noticeably better | ✅ Same as v3.5 | ✅ Much broader | ✅ Broad | ✅ Broadest of all versions |
| Accurate facts (with lookups) | ❌ | ❌ | ✅ Reads the answer from Wikipedia and cites it | ✅ Better at using what it reads | ✅ Fact-checker skill pack | ✅ Combines several sources | ✅ Combines sources, handles long documents | ✅ Combines sources, handles long documents |
| Says "I don't know" | ❌ | ❌ | ✅ Trained to admit uncertainty | ✅ | ✅ | ✅ | ✅ | ✅ |
| Explaining things | ❌ | ⚠️ Simple explanations | ✅ Clearer explanations | ✅ Multi-step explanations | ✅ Study-helper skill pack | ✅ Detailed, well-organized | ✅ Handles harder topics | ✅ Handles harder topics |
| Conversations | One message at a time | ✅ Remembers the chat | ✅ ~7–12 turns with lookups (old notes dropped); v3-long: 35–130+ | ✅ Hundreds of turns once stretched | ✅ Same, plus remembers you between chats | ✅ Very long chats (128K goal) | ✅ Longer still | ✅ Longest |
| Remembers you (saved facts, earlier chats) | ❌ | ❌ | ✅ Saves facts itself ("my name is ..."), finds earlier chats by meaning, never saves passwords | ⚠️ Not in this version (the open format has no tool tokens for saving memory) | ✅ Memory screen in the app | ✅ Summarizes old chats into memories | ✅ | ✅ |
| Reply suggestions | ❌ | ❌ | ✅ Suggests what you might ask next (simple) | ✅ Sharper suggestions | ✅ Greyed-out in the app; teacher-written follow-ups if needed | ✅ | ✅ | ✅ |
| Shows what it remembers (context meter) | ❌ | ❌ | ✅ `context` / `window` in the chat | ✅ | ✅ A meter in the app | ✅ | ✅ | ✅ |
| Code | ❌ | ❌ | ⚠️ Basic Python autocomplete | ⚠️ Small functions, several languages; a first taste of the coding helper (tool format, asks before git commits, says "too big"; templated one-bug tasks) | ✅ Coding helper (agentic, small tasks): reads files, suggests fixes, runs tests in a loop inside a sandbox | ✅ Real coding help: multi-file changes, explains code | ✅ Stronger coding help across languages | ✅ Best coding help of all versions |
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
  tests, see the result and try again, inside a safe sandbox. Around the loop: git (commits ask first), project notes, hooks (tests must pass before it may finish), and folding of old steps when memory fills. It's in the same spirit as Claude Code,
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
- **v3 (Emvryx Flare 2):** an **accurate, honest** assistant that looks facts up, admits when it doesn't know, and
  handles basic code
- **Flare 2.5 (was v3.5):** v3's features on a **1.5B open base (Qwen 2.5)**, fine-tuned on Emvryx's own lessons, 32K memory (the from-scratch 1.12B plan was stopped)
- **Equinox 2 (was v4):** an **about 4B open base**, turned into a **personal assistant**: specialist skills, exact math with tools, a Quick / Balanced / Deep
  thinking dial, coding help, documents, voice, and your own app
- **Solstice 2 (was v5):** a **genuinely capable** about 8B assistant, fine-tuned on a rented GPU, and the first
  that can "see" pictures through a helper
- **Apogee 2 (was v6):** an **about 14B bigger small** model: stronger reasoning and coding, powering the PC and online mode
- **Later Apogee (was v6.5):** a bigger open base chosen when it is time: the strongest version and the app's online brain
- **Beyond:** a future top tier (about 30B class), if funding and results allow (online mode)

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
