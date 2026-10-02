# A.I-SML — Build Your Own Small Language Model

Llama-style language models built completely from scratch: your own tokenizer, your own
transformer, your own training run. No pretrained weights. The finished models run on your
PC and fully offline on your phone.

| Version | What it is | Status |
|---|---|---|
| **v1** | 30M story-teller trained on TinyStories (~32MB on the phone) | ✅ Done: runs offline on the phone |
| **v2** | 88M mini assistant: web text + Wikipedia + multi-turn chat (89MB on the phone) | ✅ Done: 18/20 test sheet, HellaSwag 28.4%, runs offline on the phone. See **[docs/V2.md](docs/V2.md)** |
| **v3** | 394M accuracy-focused assistant: + code and math, 2,048-token memory (~240MB on the phone as Q4), lookups, remembers you, reply suggestions | 🛠️ Pretraining (step 2,000 of 45,000: val 3.426, HellaSwag 33.4%, already above v2's final 28.4%). ~30 tokens read per parameter: PC afternoons + rented RTX 3090 overnight. See **[docs/V3.md](docs/V3.md)** |
| **v3-long** | v3 stretched to 8K → 16K → 32K tokens after it finishes (the rehearsal for v3.5's 75K–100K) | Code ready, tested on small models: see **[docs/LONG_CONTEXT.md](docs/LONG_CONTEXT.md)** |
| **v3.5** | ~1.04B, then stretched to 32K+ (goal 75K–100K) | Code ready: see **[docs/V3_5.md](docs/V3_5.md)** |

**After v3's pretraining:** average the last snapshots → chat fine-tune (with NEFTune) → DPO → `compare.py --old v2 --new v3`. Steps in [docs/V3.md](docs/V3.md).

**Every version builds on the last:** each new one keeps everything the previous could do (the
lessons, memory, suggestions, lookups and tests are shared code) and must score better on the same
tests before it replaces it. See [Every version builds on the last](docs/ROADMAP.md#every-version-builds-on-the-last).

Every script takes `--version` (`v1` is the default; `v2`, `v3`, `v3.5`, `v3-long-8k` ...). Settings for each version
live in `config.py`.

> **Current stage: DEVELOPMENT.** Every script reads and writes only `checkpoints/dev/`
> and `export/dev/` (set in `stage.py`). Nothing touches staging or production until you
> promote it by hand.

## Model family names (working names)

The app and the whole family are called **Yuvra** (Yuvra.AI). Each model is Yuvra + one of four names + its own version
number: **Yuvra Flare** (smallest, phone-lite), **Yuvra Equinox** (balanced everyday), **Yuvra Solstice** (stronger) and
**Yuvra Apogee** (most capable). So v3 = Yuvra Flare 3 (~400M), v3.5 = Yuvra Equinox 3.5 (~1.1B), v4 = Yuvra Equinox 4,
v5 = Yuvra Solstice 5 (~3B), v6 / v6.5 = Yuvra Apogee 6 / 6.5 (5-7B), and later Yuvra Apogee 7, 8 (13B+); each
name has its own number that goes up only when that model is updated (older ones stay available). They are placeholders: no
trademark check has been done yet. See `docs/ROADMAP.md` and `docs/APP.md`.

## Pretrained weights policy

**Every model in this project (v1 to v6.5) is trained from scratch.** Each one starts as random
numbers and learns only from the text we give it. No one else's pretrained weights are ever
loaded into, merged with, or used to start one of these models.

Other people's open models may be used as **helpers beside the model, never inside it**:

| Helper | What it does | Inside our model? |
|---|---|---|
| **Teacher model** (an open ~7B, from v3) | Writes practice chat examples and grades our model's answers for DPO. Only its written text is used, like a tutor's worksheets | ❌ No |
| **Search model** (optional, from v3) | Finds Wikipedia passages by meaning for lookups. Keyword search needs no model at all | ❌ No, runs beside it |
| **Whisper and Piper** (v4) | Speech-to-text and text-to-speech for voice | ❌ No, separate programs |
| **A fine-tuned open model** (optional) | A smarter daily assistant in the app while our own models grow | ❌ No, a separate model, always labeled as not ours |

Rules for helpers:
- Only models and datasets whose licenses allow this use. Check each license before using it.
- Never use the ChatGPT, Claude or Gemini APIs to write training data; their terms restrict
  using outputs to build competing models.
- Some training data (for example the smol-smoltalk conversations) was written by other AIs. It
  shapes the chat *style*, but the model's weights are still trained 100% here.

This keeps every result honest: when a version improves, it's because of this project's own
data, code and training.

## Files

| File | Phase | What it does |
|---|---|---|
| `stage.py` | all | Sets the working stage (`dev`) and its folders |
| `config.py` | all | Settings for each version (model size, folders, training) |
| `chat.py` | 6–8 | The chat format, shared by fine-tuning, chat and export |
| `bigram.py` | 1 | Warm-up: tiny character model that learns from `input.txt` |
| `tokenizer.py` | 2 | Byte-level BPE tokenizer written from scratch |
| `model.py` | 3 | The transformer (RMSNorm, RoPE, attention, SwiGLU) |
| `prepare_data.py` | 4 | v1 data: downloads TinyStories, trains the tokenizer, writes `data/train.bin` / `val.bin` |
| `prepare_web_data.py` | 4 | v2+ data: streams FineWeb-Edu + Wikipedia (+ code for v3) + TinyStories into `data/<version>/` (resumable) |
| `prepare_data_v2.py` | 4 | Shortcut for `prepare_web_data.py --version v2` |
| `train.py` | 5 | Pretraining loop. Ctrl+C pauses; run again to resume. Also trains on several GPUs of one machine (DDP, via torchrun or `run_training.py --gpus N`) |
| `run_training.py` | 5 | Runs `train.py` and restarts it automatically after a crash (for long runs) |
| `offload_optim.py` | 5 | AdamW that keeps its memory in system RAM, so a 1B model fits on a 12 GB GPU (v3.5) |
| `docs/CLOUD.md` | - | How to rent a GPU and train there when your PC is off (or for big runs) |
| `handoff.py` | 5 | Moves a training run between your PC and a rented cloud GPU (one command each way) |
| `hub_backup.py` | 5 | Off-machine backup of the checkpoint to a private Hugging Face repo (`--hub_backup`), so a rented machine going offline doesn't take the run with it |
| `notify.py` | 5 | Push messages to your phone about training progress, crashes and finish (free, via ntfy.sh); see `docs/PHONE.md` |
| `app_errors.py`, `app_engine.py`, `app_download.py` | app | The app's reliability layer: plain-language errors, model choice (too big / PC off), reply guard (length cap, loop detector, Stop), chats saved while they stream, the llama-server client, "Test connection", and resumable checksum-verified downloads |
| `models.json`, `models.py` | app | The app's model list (Flare, Equinox, Solstice, Apogee, each with its own version) and the "Select model" picker logic; see `docs/APP_SPEC.md` |
| `harness.py` | 6 | The coding helper's tools and loop (no model needed; tests in `tests/`): safe file/command tools, a safe git subset, syntax diagnostics, project notes (YUVRA.md / AGENTS.md), hooks with a finish gate, permissions (ask before commits), compaction of long runs, and a tool registry (where MCP tools plug in) |
| `agent_tasks.py`, `agent_lessons.py`, `make_agent_data.py` | 6 | Coding practice made by our own code: tiny bug-fix projects solved by a scripted solver through the real harness (only passing runs kept). Become chat lessons (`tool_use`, `project_context`, `ask_first`, `too_big`, `compaction`) and `data/v3.5/agent_traces.jsonl` for v3.5's final phase. Run `python make_agent_data.py --version v3.5` before building v3.5's data |
| `muon.py`, `muon_test.py` | 5 | The Muon optimizer (`optimizer="muon"` in config.py; `"muon_cpu"` keeps its memory in RAM so it fits a 12 GB card), and an experiment that measures whether it needs fewer steps than AdamW on our models (~1–2 h on the 4070) |
| `grow.py`, `growth_test.py` | 6 | Grow a trained model into a deeper one, and an experiment that measures how much training compute that saves (run when the GPU is free) |
| `generate.py` | 6 | Generate text or chat with your model. Chat options: `--lookup` (Wikipedia notes), `--web` (web search, online mode), `--memory` (remembers you), `--suggest` (reply suggestions), `--context` (memory meter), `--skill` (skill packs) |
| `make_chat_data.py` | 7 | v1: builds `data/chat.jsonl` fine-tuning examples automatically |
| `make_chat_data_v2.py` | 7 | v2: builds `data/v2/chat.jsonl` (multi-turn conversations) |
| `finetune.py` | 7 | Teach it a chat format using the version's `chat.jsonl`. Ctrl+C pauses; run again to resume. NEFTune (a little noise while training, for better answers) is on from v3 |
| `make_dpo_pairs.py`, `dpo.py` | 7 | Preference training: the chat model answers each question several times, answers are scored by checkable rules (facts from the notes, "I don't know" when right, counts), and it learns to prefer the better one |
| `lora.py`, `skills.py`, `make_skill_data.py`, `train_skill.py`, `skill_test.py` | 7 | Skill packs (Beta): small LoRA add-ons that make the chat model a specialist. First packs: the **Study helper** and the **Teacher assistant** (`classroom.py`: 3rd-grade requests and checks). Includes a Beta router (`generate.py --chat --skill auto`) and an access toggle (everyone / beta testers / off: `python skills.py access`). See [`docs/SKILLS.md`](docs/SKILLS.md) |
| `export_doc.py` | 7 | Saves an answer as a printable PDF or an editable Word file (in chat: `save worksheet.pdf`); worksheets get a Name/Date line and the answer key on its own page |
| `average_ckpts.py` | 6 | Averages the last few snapshots of a run (kept during the fade) for a small free improvement |
| `evaluate.py` + `eval/prompts.jsonl` | 6–7 | 20-question test sheet that scores a chat model |
| `exam.py` | 6 | HellaSwag, a public common-sense test (works on pretrained models; compare versions) |
| `wiki_index.py` | v3 | Searchable copy of Wikipedia for lookups (build + search) |
| `web_search.py` | v3 | Web search for online mode (Wikipedia's free search or Brave Search); results become notes |
| `web_lessons.py` | v3 | Chat lessons for reading web results and honest answers about other AIs (used by make_chat_data_v3.py) |
| `make_teacher_data.py` | v3 | The teacher model (Qwen2.5-7B via llama.cpp, or rented per token from a hosting API) writes practice examples |
| `make_chat_data_v3.py` | 7 | v3 and every later version (`--version`): chat lessons that fix v2's mistakes (lookups, "I don't know", corrections, instructions, topic switches), remembering you, and reply suggestions |
| `chat_memory.py` | 7 | Remembers earlier chats and facts about you, on your computer only (`generate.py --chat --memory`); search by keywords and by meaning |
| `compare.py` | 6 | Side-by-side scoreboard of two versions on the same tests, and whether the new one may replace the old (`--old v3 --new v3.5`) |
| `eval_long.py` | 6 | Long-context tests (needle in a haystack, multi-fact, code recall, loss by position) with pass/fail rules |
| `prepare_long_data.py` | 4 | Long-document data (books, long articles, code by repository, recall practice) for stretching the context |
| `benchmarks.py` | 4–6 | Downloads the public test sets (HellaSwag, GSM8K), used by `exam.py` and to keep them out of training data |
| `export_hf.py` | 8 | Save in standard Llama layout (safetensors + tokenizer.json) |
| `to_gguf.py` | 8 | Convert to GGUF with llama.cpp for phone apps |
| `examples/chat_sample.jsonl` | 7 | Example fine-tuning data format |

Version side-by-side: [`docs/VERSIONS.md`](docs/VERSIONS.md). Where the project is heading: [`docs/ROADMAP.md`](docs/ROADMAP.md).

New to the code? Start with [`docs/HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md). Every function also has a docstring explaining what it does.

## Quick start on your PC (NVIDIA GPU, 8GB+ VRAM)

```bash
git clone https://github.com/dmccottrell/a.i-sml.git
cd a.i-sml

# Phase 0: setup
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # Mac/Linux
pip install torch --index-url https://download.pytorch.org/whl/cu124   # check pytorch.org for your exact command
pip install -r requirements.txt
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"

# Phases 1-3: sanity checks
python bigram.py        # loss drops, prints gibberish (expected!)
python tokenizer.py     # prints "tokenizer OK"
python model.py         # ~29.5M parameters, initial loss ~9.0

# Phase 4: data (~2GB download, 30-70 min total, run once)
python prepare_data.py

# Phase 5: train (5-10 hours on an 8GB card)
python train.py

# Phase 6: try it
python generate.py --prompt "Once upon a time"
```

Checkpoints land in `checkpoints/dev/`.

## Fine-tuning (Phase 7)

```powershell
python make_chat_data.py        # builds data/chat.jsonl (~5,000 examples) from TinyStories
python finetune.py              # ~5-10 min -> checkpoints/dev/chat.pt
python generate.py --ckpt checkpoints/dev/chat.pt --chat
```

`make_chat_data.py` turns stories into requests like *"Tell me a story about Lily."* and adds
greetings and "who are you?" answers (edit `BASICS` in the file to change its personality).
Add your own examples to `data/my_examples.jsonl` (same format as
`examples/chat_sample.jsonl`); they are included 3 times so they count more.

## Putting it on your phone (Phase 8)

**1. Export and convert (once per model version):**
```powershell
python export_hf.py                          # checkpoints/dev/chat.pt -> export/dev/my-ai
git clone https://github.com/ggml-org/llama.cpp ..\llama.cpp
pip install ..\llama.cpp\gguf-py sentencepiece
python to_gguf.py --llama_cpp ..\llama.cpp   # -> export/dev/my-ai-f16.gguf (~60MB)
```

**2. Shrink it (quantize):** download the latest Windows build from
<https://github.com/ggml-org/llama.cpp/releases> (the `llama-...-bin-win-cpu-x64.zip` file),
unzip it, then:
```powershell
<unzipped folder>\llama-quantize.exe export\dev\my-ai-f16.gguf export\dev\my-ai-q8_0.gguf Q8_0
```

**3. Copy `export\dev\my-ai-q8_0.gguf` (~32MB) to your phone:** USB cable, Google Drive,
OneDrive or emailing it to yourself all work.

**4. Load it in a GGUF app** such as PocketPal AI (iPhone and Android): add a model from local
files, pick the `.gguf`, then in its settings:
- **Context size: 512** (the model was trained on 512 tokens; larger values give garbage)
- The chat template is built into the file, so the app should pick up `<|user|>` /
  `<|assistant|>` automatically. If replies look wrong, set it by hand: `<|user|>` before your
  message, `<|assistant|>` before the reply, `<|endoftext|>` as the stop word.
- Temperature around 0.7-0.8.

**5. Test it in airplane mode.** When you're happy with it, copy the `.gguf` to
`checkpoints/production/`.

## Dev → Staging → Production

The project is currently in **development**: training, fine-tuning, generation and export
all use `checkpoints/dev/` and `export/dev/`. When a checkpoint passes your tests, copy it
to `checkpoints/staging/`; when a `.gguf` works well on your phone, copy it to
`checkpoints/production/`. To work from another stage later, change `STAGE` in `stage.py`. `data/`, `checkpoints/` and `export/` are
git-ignored because they're large.

## Troubleshooting

- **`torch.cuda.is_available()` is False**: you installed the CPU-only PyTorch. Uninstall torch and reinstall with the CUDA command.
- **Out of memory**: in `train.py`, halve `batch_size` and double `grad_accum` (e.g. 16 and 8).
- **Loss becomes NaN**: lower `lr_max` to `3e-4`.
- **Train loss far below val loss**: the model is memorizing; stop early or use more data.

## Progress checklist

- [ ] Phase 0: GPU verified in PyTorch
- [ ] Phase 1: `bigram.py` trains and generates
- [ ] Phase 2: `tokenizer.py` self-test passes
- [ ] Phase 3: `model.py` shows ~29.5M params, loss ~9.0
- [ ] Phase 4: `train.bin` and `val.bin` created
- [ ] Phase 5: val loss at or below ~1.5
- [ ] Phase 6: coherent stories from `generate.py`; checkpoint in staging
- [ ] Phase 7: chat mode answers in the right format
- [ ] Phase 8: GGUF runs on your phone offline; copied to production
- [ ] Phase 9: first model trained on your own data
