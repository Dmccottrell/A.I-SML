# Emvryx 2.x: models built on open bases (Flare 2.5 = Qwen 2.5 1.5B, 32K context)

This is how the first open-base Emvryx model, **Flare 2.5** (the slot that was v3.5), is made; the open-base models are the **2.x series** (generation 2): Flare 2.5 and 2.5, Equinox 2, Solstice 2, Apogee 2. It carries the Emvryx name, but it is **not trained from scratch**: it starts from
Qwen 2.5's open weights and is fine-tuned here. Say so wherever provenance is described, and keep `NOTICE` (Qwen's licence) with any copy of the weights you share.
The from-scratch line (v2, v3, v3.5) is unaffected.

Why: v3.5 from scratch costs about $183 for a forecast ~41-45% on HellaSwag; Qwen 2.5 1.5B scores roughly 65% on the same kind of test, and
a LoRA fine-tune costs a few dollars (or runs free on the RTX 4070). The numbers are from memory: measure with `benchmarks.py` before relying on them.

## Facts
| | |
|---|---|
| Base | `Qwen/Qwen2.5-1.5B-Instruct` (28 layers, 1536 wide, 2 KV heads) |
| Licence | Apache 2.0 (check the model page before sharing anything). Keep the licence notice; say "built on Qwen 2.5"; don't imply Qwen endorses it |
| Context | 32,768 tokens natively; the app starts llama-server with `context: 32768` |
| Memory for context | about 28 KB per token, so 32K is about 0.9 GB |
| Training length | `--max_len 4096` (the lessons are short; the 32K comes from the base model) |

## What changed in the code
- `open_tokenizer.py`: wraps Qwen's `tokenizer.json` behind the calls `chat.py` uses; typed text can't inject control tokens.
- `chat.py`: a ChatML branch (`<|im_start|>user ... <|im_end|>`), used when the tokenizer says `chatml = True`. Notes go in as plain text. Our own models are unchanged.
- `finetune_open.py`: LoRA (rank 64, all attention and MLP layers), loss only on the assistant's answers, resume with the same command, `--merge` writes a normal Hugging Face folder.
- `app_server.py`: a model entry with `"open": true` loads this tokenizer.
- Not carried over: "save to memory" tool calls (Qwen has no tool tokens in our format).

## Steps on the PC (RTX 4070, 12 GB)
```
git pull origin main
pip install peft                     # once (transformers is already installed)
python finetune_open.py --pilot      # 3 steps: shows peak memory and s/step. If it runs out of memory: --batch_tokens 4096 --grad_accum 16
python finetune_open.py              # trains; Ctrl+C saves; run the same command to resume
python finetune_open.py --merge      # -> export\open\flare-2\my-ai
python ..\llama.cpp\convert_hf_to_gguf.py export\open\flare-2\my-ai --outfile export\open\flare-2\my-ai-f16.gguf --outtype f16
..\llama.cpp\build\bin\Release\llama-quantize export\open\flare-2\my-ai-f16.gguf export\open\flare-2\my-ai-q4_k_m.gguf Q4_K_M
```
A run started before the presets existed saved to `checkpoints/dev/open/qwen2.5-1.5b-instruct`; the code still finds it (resume and `--merge` work), and new runs use `checkpoints/dev/open/flare-2`.
The lessons file is `data\v3\chat.jsonl` (`python make_chat_data_v3.py`), the same lessons v3 learned, now on a stronger base.

## Adding it to the app
`models.json` already has the entries (status `planned`, generation 2). When a model's GGUF exists, set its status to `beta`; each entry has `"open": true`, `"tokenizer": "checkpoints/dev/open/flare-2/tokenizer/tokenizer.json"`,
`"context": 32768`, `"local_gguf": ["export/open/flare-2/my-ai-q4_k_m.gguf"]`, `"kv_kb_per_token": 28`, and `"base": "Qwen2.5-1.5B-Instruct"` (provenance for the docs; the model's name in the app is just Emvryx + its name and number).

## Measured on one RTX 5090 (Oct 5 2026, stand-in file of 2,972 chats, `--batch_tokens 8192 --grad_accum 8 --pilot`)
- **7.1-7.4 s per optimizer step** (8 micro-batches of up to 8,192 tokens), **18.6 GB peak** of 32 GB, loss about 0.9-1.0 (Qwen Instruct already writes this kind of chat well).
- One pass over 2,972 chats is about 38 steps, roughly 5 minutes, so about 0.1 s per chat: 100,000 chats is about 2.5 hours (about $1.30 at $0.51/h). Re-estimate with the real `chat.jsonl` line count.
- The first try crashed with out of memory only because the stopped from-scratch run was still holding 24 GB of the GPU (the `run_training.py` supervisor had not exited): check `nvidia-smi` shows about 0 MiB before starting.
- With `--batch_tokens 16384` the output layer alone wants about 10 GB (Qwen has 152,000 tokens), so stay at 8,192 unless the GPU is empty and the pilot passes.

## The exam after training (`exam_open.py`)
The same HellaSwag test and scoring as `exam.py` (so it is comparable with Ember 2 at 28.4% and Flare 2 / v3 at 36.2%), for Hugging Face models:
```
python exam_open.py --model flare-2.5 --compare              # the plain base, then base + our adapter, and the difference
python exam_open.py --model flare-2.5 --compare --n 2000 --spread   # a faster check that matches the full-test score
python exam_open.py --model export/open/flare-2.5/my-ai      # a merged model folder
```
- Run `--compare` on the machine that trained it (the adapter is in `checkpoints/dev/open/...`; a run started before the presets existed is found too).
  A run takes a few minutes on a 5090 for 10,042 questions (an estimate, not measured). It needs `datasets` and `peft`.
- **What to look for:** the tuned model should be at least as good as the base. Fine-tuning can make it forget things, so a drop of more than a point or so
  means the lessons or the learning rate are too strong (lower `--lr`, or mix more general chat into the lessons).
- HellaSwag only checks common sense. The things our lessons teach are checked with the test sheets (lookup sheet of 41, rules sheet of 30, `evaluate.py`),
  which still need a runner for open models (next to build).

## Not tested yet
The code is tested with a tiny offline model (`tests/test_open_model.py`), and the pilot above ran on the real Qwen weights on a 5090. Nobody has trained on the real lessons yet: compare on `benchmarks.py` and the lookup test sheet before trusting it.

## Suggested bases for the later models (suggestions, not chosen; checked from memory, Oct 2026)
Check the licence page and look for newer releases before picking: open models change every few months.

| Model | Suggested base | Size | Licence (check) | Where it trains | Notes |
|---|---|---|---|---|---|
| Equinox 2 | Qwen3-4B | 4B | Apache 2.0 | One RTX 5090 (LoRA), or a 4070 with 4-bit (QLoRA) | Same ChatML format, so `open_tokenizer.py` and `chat.py` carry over |
| Solstice 2 | Qwen3-8B | 8B | Apache 2.0 | One RTX 5090 (QLoRA); runs on a 4070 at Q4 (about 5 GB) | Strong reasoning for its size |
| Apogee 2 | Qwen3-14B, or Phi-4 (14B, MIT) | 14B | Apache 2.0 / MIT | A rented 5090 (QLoRA) or a 48 GB card | Q4 is about 9 GB: tight on a 4070, fine on a rented or always-on GPU |

Why one family: the same tokenizer and chat format mean the training and export code (`finetune_open.py`, `open_tokenizer.py`) work for every rung with a changed model name.
Avoid for now: Qwen2.5-3B (its licence is not Apache 2.0), and Llama (naming and "Built with Llama" rules).
Qwen3 can write `<think>` reasoning blocks: decide whether to keep or strip them before it becomes a model in the app.

## Upgrades: "+" and growth on an open base
The numbering is in [ROADMAP.md](ROADMAP.md) ("Numbers for "+" and grown models"). Times below are **estimates** (compute scales roughly with parameters from the measured
Flare 2.5 run: 7.1 s/step on one RTX 5090 at 1.5B, 988 steps, about 2 hours and $1). Real numbers come from a `--pilot` on the base you pick.

### "+" (same weights' size, better lessons): the normal upgrade
1. **Collect what to fix**: test the model (`benchmarks.py`, the lookup sheet, phone tests) and write down its mistakes.
2. **Make new lessons** for those mistakes (`make_chat_data_v3.py` and friends, with the teacher model on the PC, hours of PC time), and optionally DPO pairs.
3. **Train**: `python finetune_open.py --data <new lessons>`; start from the saved adapter to continue it, or from the base with all lessons together.
4. **Test it beats the old one** (`compare.py`), merge, convert to GGUF, add to the app. Number: Flare 2.5 becomes **2.5**; the old one moves to "Other models".

| Base | Rough training time (988 steps) | Rented cost at about $0.51/h | Needs |
|---|---|---|---|
| 1.5B (Flare 2.5) | about 2 h (measured) | about $1 | one 5090 or the 4070 (slower) |
| 4B (Equinox 2) | about 5 h | about $3 | one 5090 |
| 8B (Solstice 2) | about 10 h | about $5-6 | one 5090 (bf16 weights are 16 GB) |
| 14B (Apogee 2) | about 20-25 h | about $10-13 | 4-bit weights (QLoRA) on a 5090, or a 48 GB card |
Add the time to make the lessons and the tests. Skill packs (small LoRA add-ons) are trained the same way and cost less.

### Growth (more layers, bigger model): only if no open model of the size exists
1. **Pick a base** and a target (for example Qwen3-8B, 36 layers, grown to about 48 layers, roughly 10-11B).
2. **Grow it**: copy a block of its layers into the stack (like `grow.py` does for our own models; this needs a version for the open model's layer names, written and tested on a tiny model first). Width, tokenizer and embeddings stay the same.
3. **Right after growing it is slightly worse** (the copies were not trained to work together). It needs continued training to recover and then beat the original: either train all weights (needs far more memory than LoRA) or train only the new layers.
4. **Compare against the plain base and against the next bigger open base.** Only keep the grown model if it wins at a price you accept. Number: the next whole number plus .1 (Equinox 2.1).

| Growth example | Continued training (about 1B tokens, a small amount) | Cost at about $0.51/h |
|---|---|---|
| 1.5B to about 2B | about 40 h on one 5090 | about $20 |
| 8B to about 11B | about 200+ h on one 5090, and the memory does not fit: needs a 48-80 GB card or several GPUs | $100 to several hundred |
These are order-of-magnitude guesses: growth quality depends on how many tokens of continued training it gets, and 1B tokens is on the small side.

**Recommendation:** use "+" as the routine upgrade; skip growth until a base of the right size is missing. Every "+" or grown copy still carries `NOTICE` (the base's licence).

## Prepared for one RTX 5090 (Oct 2026): Equinox 2, Solstice 2, Apogee 2, and longer context
`open_models.py` holds one preset per model, and `python finetune_open.py --model equinox-4` (or `solstice-5`, `apogee-6`, `flare-3.5`) uses it.
The first guesses below were not run on the real weights (this sandbox cannot download them): **run `--pilot` first** and adjust `--batch_tokens` / `--grad_accum`.
The loss now runs the 152,000-word output layer only on the learned tokens, a chunk at a time (`chunked_loss`), which is what lets an 8B model fit.

| Model | Base | Weights in memory | Settings (micro-batch tokens × accumulation, LoRA rank) | Estimated time for 988 steps | Rented cost |
|---|---|---|---|---|---|
| Flare 2.5 | Qwen 2.5 1.5B | bf16, 3 GB | 8192 × 8, rank 64 (**measured**: 7.1 s/step, 18.6 GB) | about 2 h | about $1 |
| Equinox 2 | Qwen3-4B | bf16, 8 GB | 4096 × 16, rank 64 | about 5 h (18 s/step) | about $2.60 |
| Solstice 2 | Qwen3-8B | bf16, 16 GB | 2048 × 32, rank 32 | about 10 h (38 s/step) | about $5 |
| Apogee 2 | Qwen3-14B | 4-bit (QLoRA), about 9 GB | 2048 × 32, rank 32, `--quant4` (needs `pip install bitsandbytes`) | about 24 h (89 s/step, 4-bit is slower) | about $12 |

Each run: `python finetune_open.py --model <name> --pilot` (3 steps; prints peak memory), then `python finetune_open.py --model <name>`, then `--merge`.
If the pilot runs out of memory, halve `--batch_tokens` and double `--grad_accum` (the step stays the same size).
A QLoRA adapter (Apogee) merges onto the full-precision base, so `--merge` needs about 30 GB of memory for 14B: do it on the 5090 or a bigger machine.

### Context windows (increased)
| Model | Default | Longest | How | Memory for the longest (fp16 cache) |
|---|---|---|---|---|
| Flare 2.5 (Qwen 2.5 1.5B) | 32,768 | 32,768 | native; Qwen documents no longer setting for the 1.5B | 0.9 GB |
| Equinox 2 (Qwen3-4B) | 32,768 | **131,072** | YaRN scaling, factor 4 | 18 GB (9 GB with a q8_0 cache) |
| Solstice 2 (Qwen3-8B) | 32,768 | **131,072** | YaRN, factor 4 | 18 GB (9 GB with q8_0) |
| Apogee 2 (Qwen3-14B) | 32,768 | **131,072** | YaRN, factor 4 | 20 GB (10 GB with q8_0) |

- The server options come from `open_models.llama_args("equinox-4")`: `-c 131072 --rope-scaling yarn --rope-scale 4 --yarn-orig-ctx 32768` (add `-fa on -ctk q8_0 -ctv q8_0` for the smaller cache). Pass them with `app_server.py --llama-args "..."`.
- The weights are the same; YaRN is an inference setting. Qwen notes that it can slightly hurt short inputs, so use the longer window only when you need it, and test long inputs on your own tasks before trusting them (`eval_long.py` is for our own models and does not run these yet).
- On the RTX 4070 (12 GB) a 4B model at 128K does not fit (4B at Q4 is about 2.5 GB, plus 9 GB of cache even with q8_0): use 32K-64K there. The longer windows are for the 5090 or a rented/always-on server.
- Training stays on short chats (`--max_len 4096`). Teaching a model to use long inputs well is a later "+" step: new long-document lessons and a longer `--max_len` (more memory per step).
- Qwen3 can write `<think>` blocks; our lessons have none, so training pushes it to answer directly. Check it before it goes in the app.

## Flare 2 (v3, from scratch) versus the open-base models, and what the switch makes possible
Figures marked "(memory)" are published numbers from memory: verify them, and measure ours with `exam.py` / the test sheets after training.

| | **Flare 2** (v3, trained from scratch) | **Flare 2.5 and later** (open bases, fine-tuned here) |
|---|---|---|
| Size | 394M parameters | 1.5B (Flare 2.5), about 4B, 8B, 14B (Equinox, Solstice, Apogee) |
| Reading before our lessons | 11.8B tokens we chose | Trillions of tokens by the base's maker (memory: Qwen 2.5 about 18T, Qwen3 about 36T) |
| What we train | Everything: tokenizer, all weights | A small LoRA add-on (about 74M parameters, 4.6%) on top of frozen weights |
| General knowledge | HellaSwag 36.2% (measured) | the base is about 65% or more (memory); ours measured after training |
| Memory (context) | 2,048 tokens (stretching it needs extra work) | 32,768 native; up to 131,072 on the Qwen3 models (YaRN) |
| Vocabulary | 32,768 (our own, mostly English) | 151,936 (Qwen's: many languages, code, symbols) |
| Languages | Mostly English | Many (memory: Qwen 2.5 covers about 29, Qwen3 about 119) |
| Code and math | Basic | Much stronger |
| Following instructions | Only what our lessons teach | The base is already instruction-tuned, then our lessons shape it (lookups, "I don't know", rules, style) |
| Cost to train or refresh | About $50-70 | About $1 (1.5B) to $12 (14B) per run |
| Phone file (Q4) | about 240 MB | about 1 GB, 2.5 GB, 5 GB, 9 GB |
| Speed on a phone or the 4070 | Fastest | Slower, in proportion to size |
| Ownership | 100% ours, no licence strings | Apache 2.0 base: keep `NOTICE`, say what it is built on |
| Chat format | Our own tokens (`<\|user\|>`, notes, memory tool calls) | Qwen's ChatML; notes as plain text; "save to memory" tool calls not carried over yet |

**Lost or changed by the switch:** the "everything is ours" claim for the 2.5+ models; our custom control tokens (notes, tool calls), so memory saving needs
re-teaching in Qwen's own tool format; the chat's token counts now come from Qwen's tokenizer (the app does this per model already).

**New things the switch makes possible (to build later; each needs its own test)**
1. **Long documents and chats**: summarize a whole PDF or a very long conversation (32K-128K) without "forgetting" the start.
2. **Real tool calling**: Qwen already has a native tool-call format, a better base for the v4 tools (calculator, clock, files, web, coding loop) and for re-teaching "save to memory".
3. **A real thinking dial**: Qwen3 can think step by step or answer straight away, which maps onto Quick / Balanced / Deep (effort levels).
4. **Many languages and translation.**
5. **Much better code and maths**: the coding helper and agentic loops become practical.
6. **Skill packs as LoRA add-ons on one base**: study helper, teacher assistant and more, swapped per question (needs a PEFT version of `skills.py`; ours is for our own model).
7. **Better lookup**: the same family has embedding and reranker models (memory: Qwen3-Embedding / Qwen3-Reranker), the reranker idea we had listed for facts.
8. **Faster big models**: a small Qwen can draft for a big one (speculative decoding, same tokenizer) in llama.cpp.
9. **Structured answers (JSON)** for app features, which small from-scratch models handle poorly.
10. **Pictures and voice**: sibling vision-language models exist (memory: Qwen-VL line), so the "see pictures through a helper" plan gets easier; check licences first.
11. **Our own teacher**: Apogee 2 can write practice lessons for the smaller models, replacing the outside teacher model (our own model's output, no third-party terms to check).
12. **Cheaper iteration**: a "+" refresh costs dollars, so you can test, fix and re-release often.

## Order of work: all the 2.0 builds first, then the improved 2.5 releases (decided Oct 2026)
1. **First builds** (same 109,917 lessons, each tested with `exam_open.py` and the test sheets): **Flare 2.5** (Qwen 2.5 1.5B, training now), then **Equinox 2** (Qwen3-4B), **Solstice 2** (Qwen3-8B), **Apogee 2** (Qwen3-14B, 4-bit). Each one starts only when the budget allows and the one before it tested well.
2. **Improved releases, after all the first builds are done:** **Equinox 2.5, Solstice 2.5, Apogee 2.5**. Each is made the same way: collect the first build's mistakes, write new lessons for them, add DPO, then
   the extras (skill packs, the thinking dial, long-document lessons, tool calling in Qwen's format, a reranker for lookups, and for Apogee possibly a bigger base), train, compare against the first build and plain Qwen, and release. The 2.0 version moves to "Other models".
3. Check for newer open models before each build, because better bases may exist by then. Nothing is bought or started without the owner's approval.

### Running the next model straight after (`chain_open.sh`)
On the cloud machine, after `git pull origin main`: `bash chain_open.sh` (inside tmux). It waits for the running Flare 2.5 fine-tune to end, then merges it, runs the exam
(base versus tuned), backs it up to Hugging Face, and runs **Equinox 2**: a 3-step pilot, then the full run, merge, exam and backup. It pings your phone (ntfy `v35-AI`)
at each step and **stops** with a message if anything fails (an out-of-memory pilot, for example) instead of carrying on. Add more names to run more models
(`bash chain_open.sh equinox-2 solstice-2`), but only the ones you have budget for. It never stops the Vast instance: when it pings "all done", press Stop yourself.
Start it only while the Flare run is running or finished: it merges whatever the last save was.

### Identity: fixing the "trained from scratch" answers (found Oct 2026)
The v3 lessons say the model "was trained from scratch on a home computer". That is false for a Qwen-based model, so:
- `finetune_open.py` now **drops those lessons and adds 1,000 corrected identity chats by default** (`--keep_old_identity` turns it off, only right for from-scratch models). Equinox 2 and later get it automatically.
- **Flare 2.5's first run (started before this fix) learned the old answers.** `chain_open.sh` fixes it with a short extra pass:
  `python identity_lessons.py --name "Flare 2.5" --lessons data/v3/chat.jsonl --out data/v3/identity_patch.jsonl`, then
  `python finetune_open.py --model flare-2.5 --patch --data data/v3/identity_patch.jsonl` (continues the saved adapter, mixed with ordinary lessons so it does not forget). **The first attempt (Oct 2026) did almost nothing**: the patch chats are so short that one pass was only a few steps at a low learning rate, and the identity sheet still scored 8/16 with the old answers. `--patch` now defaults to 3 passes, a small step (`--grad_accum 2`) and a learning rate of 1e-4, and warns when it would run fewer than 20 steps..
- Check the result with `python evaluate_open.py --model flare-2.5 --tuned` (identity sheet, `eval/identity_open.jsonl`); other sheets work too (`--prompts eval/constraints.jsonl`).
See [IDENTITY.md](IDENTITY.md) for the voice and the ways to make it ours.

## Results: Flare 2.5 (Qwen 2.5 1.5B, trained Oct 5-6 2026)
- **Training:** 988 steps over 109,917 chats on one RTX 5090 (7.2 s/step, about 2 hours, final loss about 0.75). The first run learned the old "trained from scratch" identity answers (identity sheet 8/16), so it got an identity fix.
  The first fix did almost nothing (a few steps); the second (`--patch`, 189 steps, about 6 minutes) gave **identity 16/16** (`eval/identity_open.jsonl`).
- **HellaSwag (2,000 questions spread over the test, `exam_open.py --compare`):** plain Qwen 2.5 1.5B **65.6%**, Flare 2.5 **67.2%** (+1.6 points, so the lessons did not make it forget anything). Our own models: Ember 2 28.4%, Flare 2 (v3) 36.2%.
  A 2,000-question sample, not the full 10,042.
- **Caveat:** the identity questions are close to the lessons it was trained on, so 16/16 shows it learned them, not how it handles other wordings. Test rephrased questions next.
- **Backed up:** `Dmccottrell/aisml-checkpoints` (private): `flare-2.5/my-ai` (the merged model) and `flare-2.5/adapter`.
- **Not done yet:** the lookup sheet (41) and rules sheet (30) on Flare 2.5, the GGUF for the app, and the app entry (still `planned` in `models.json`).

### Window settings in the app (Oct 2026)
`models.json` sets **context_tested = 32,768** for Equinox 2, Solstice 2 and Apogee 2 (Qwen reads 32K natively; none of them has been through our own long-input test yet, so treat it as the maker's figure).
The app still picks the smallest of: that number, what fits in your free memory (Apogee 2 will come out far smaller on a 12 GB card), the plan, and the window mode: **"everyday" caps the window at 8,192 tokens; choose "long" in Settings to use more.**
The 128K YaRN windows are not switched on in the app (they need extra llama-server options, `open_models.llama_args`, and about 18 GB of memory). Ember 2 (1,024) and Flare 2 (2,048) cannot be raised: their position range was trained that short, and stretching it needs the long-context ladder.
**Flare 2.5 stays at 8,192** (the owner's choice) until a long-input test shows more is safe. **Training length is separate from the window:** the fine-tunes train on short chats (`--max_len 4096`, most lessons are well under 1,000 tokens), while the window is only a setting for chatting. The base Qwen model's 32K ability is not removed by the fine-tune; teaching the model to *use* long inputs well is a later "+" step with long-document lessons.

## Later generations: 3.x on Qwen3.5, 4.x on Qwen3.8 or the newest (planned, Oct 2026)
A web search on 2026-10-06 found newer open bases than the ones the 2.x series uses (check again before each build; releases move fast):
- **Qwen3.5** (Feb to Mar 2026): small sizes **0.8B, 2B, 4B, 9B**; medium **27B, 35B-A3B, 122B-A10B, 397B-A17B** (A = how many parameters are active per word, a mixture of experts). Apache 2.0 like the Qwen3 family.
- **Qwen3.8** (Aug 2026): built on the Qwen3.5 design; **27B** dense and a 2.4T-A95B mixture; 262,144-token context; Apache 2.0.

| Generation | Flare | Equinox | Solstice | Apogee | Base family |
|---|---|---|---|---|---|
| **2.x** (now) | 2.5: Qwen2.5-1.5B | 2: Qwen3-4B | 2: Qwen3-8B | 2: Qwen3-14B | Qwen2.5 / Qwen3 |
| **3.x** (planned) | 3: Qwen3.5-2B (or 0.8B) | 3: Qwen3.5-4B | 3: Qwen3.5-9B | 3: Qwen3.5-27B | Qwen3.5 |
| **4.x** (planned) | newest small | newest 4B-class | newest 9B-class | Qwen3.8-27B or newer | Qwen3.8 or newer |
"x.0 = the first build on a new base generation, x.5 = its improved release" still holds. Nothing here is decided: pick each base when its turn comes.

**Before any 3.x build, run a short pilot on the 5090** (`python finetune_open.py --model Qwen/Qwen3.5-2B --pilot`, then the 4B) and check:
1. The tools understand the new design: the trainer (transformers and peft), `open_tokenizer.py` (ChatML special tokens), and llama.cpp's converter for the GGUF. Newer designs sometimes need newer versions of all three. Not tested here: this sandbox cannot download them.
2. Memory and speed (add a preset to `open_models.py` with the real layer counts and `llama_args`).
3. The chat template: newer Qwen models can think by default, and our lessons have no thinking text.
4. The exam (`exam_open.py --compare`) and the identity sheet, as for every model.
Hardware: the 27B models do not fit a 12 GB card even in 4 bits (about 16 GB), so Apogee 3 needs a rented GPU or offloading to memory; the 35B-A3B mixture runs only 3B per word but still needs about 20 GB to hold the weights.
