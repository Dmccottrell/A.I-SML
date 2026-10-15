# A.I-SML — Build Your Own Small Language Model

Llama-style language models, with the first versions built completely from scratch: your own tokenizer, your own
transformer, your own training run. No pretrained weights. Any finished model can run wherever you
want it: fully offline on your phone or PC, at home on your own machine, or in the cloud (private for
you and your testers, or public). Where it runs is a choice per chat, not a property of the model.

| Version | What it is | Status |
|---|---|---|
| **v1** | 30M story-teller trained on TinyStories (~32MB on the phone) | ✅ Done: runs offline on the phone |
| **v2** | 88M mini assistant: web text + Wikipedia + multi-turn chat (89MB on the phone) | ✅ Done: 18/20 test sheet, HellaSwag 28.4%, runs offline on the phone. See **[docs/V2.md](docs/V2.md)** |
| **v3** | 394M accuracy-focused assistant: + code and math, 2,048-token memory (~240MB on the phone as Q4), lookups, remembers you, reply suggestions | ✅ Pretraining finished (45,000 steps; HellaSwag 37.1% on a 2,000-question sample, v2: 28.4%; validation loss ≈2.68), 🛠️ chat tuning next: the teacher lessons are being generated. ~30 tokens read per parameter. See **[docs/V3.md](docs/V3.md)** and **[docs/LESSONS.md](docs/LESSONS.md)** |
| **v3-long** | v3 stretched to 8K → 16K → 32K tokens after it finishes (the rehearsal for v3.5's 75K–100K) | Code ready, tested on small models: see **[docs/LONG_CONTEXT.md](docs/LONG_CONTEXT.md)** |
| **v3.5** | ~1.12B (24 layers), ~20B tokens (75,000 steps, 8K context), Muon optimizer; then stretched to 32K+ (goal 75K–100K) | Code ready, data build in progress: see **[docs/V3_5.md](docs/V3_5.md)** |

## Where the project is now (Oct 2026)
- **Live:** the Emvryx app (`python app_server.py`, served at chat.emvryx.app from the home PC) with four models: **Flare 2.5, Equinox 2, Solstice 2, Apogee 2** (the 2.x series on open bases). Plans and usage limits, accounts with passwords, two-step sign-in and passkeys, Skills, Teacher mode, documents, 21 connected apps, live facts, and **VryxCode** (the coding assistant with its editor, output panel, live preview, review, queue and "+" new projects). The owner can update the PC from the phone (Admin > PC > Software update). New things ship behind feature flags (Admin > Previews; see [docs/FEATURE_FLAGS.md](docs/FEATURE_FLAGS.md)).
- **Website:** emvryx.app, built from `design/` by `python tools/build_site.py` into `site/` (Vercel). Violet look; chat is still amber behind the "Violet look" flag.
- **Next models (3.x):** Flare 3 (Qwen3.5 2B, training now) and Equinox 3 (4B) on the RTX 4070; Solstice 3 (9B, major tune) and the flagship **Apogee 3** (Qwen3.5 9B grown to about 12B, new layers + major tune + preference training) on an RTX 5090. Every model still chats on the 4070 with a 128K window. Runbook: [docs/EMVRYX3_RUNBOOK.md](docs/EMVRYX3_RUNBOOK.md).
- **Lessons 4 and the Emvryx Constitution:** the next lessons are written to Emvryx's own written character ([docs/EMVRYX_CONSTITUTION.md](docs/EMVRYX_CONSTITUTION.md)): every answer judged and rewritten, code run, maths verified, facts checked, plus preference pairs (DPO), in one Emvryx voice. Plan, flagship and Apogee 3.5: [docs/LESSONS_4.md](docs/LESSONS_4.md).
- **Native apps:** Android (Kotlin) first, then iPhone (Swift); planned, not started: [docs/NATIVE.md](docs/NATIVE.md).
- The v1 to v3.5 rows in the table above are the from-scratch line; the v3.5 run was stopped.

**After v3's pretraining:** average the last snapshots → chat fine-tune (with NEFTune) → DPO → `evaluation/compare.py --old v2 --new v3`. Steps in [docs/V3.md](docs/V3.md).

**Every version builds on the last:** each new one keeps everything the previous could do (the
lessons, memory, suggestions, lookups and tests are shared code) and must score better on the same
tests before it replaces it. See [Every version builds on the last](docs/ROADMAP.md#every-version-builds-on-the-last).

Every script takes `--version` (`v1` is the default; `v2`, `v3`, `v3.5`, `v3-long-8k` ...). Settings for each version
live in `core/config.py`.

> **Current stage: DEVELOPMENT.** Every script reads and writes only `checkpoints/dev/`
> and `export/dev/` (set in `training/stage.py`). Nothing touches staging or production until you
> promote it by hand.

## Model family names (working names)

The app and the whole family are called **Emvryx** (Emvryx.AI). Each model is Emvryx + one of five names + its own version
number: **Emvryx Ember** (small and quick), **Emvryx Flare** (fast and light), **Emvryx Equinox** (balanced everyday),
**Emvryx Solstice** (stronger) and **Emvryx Apogee** (most capable). There are two generations:

| Generation | Models | How they are made |
|---|---|---|
| **1: trained from scratch here** (the original line) | Ember 2 (88M), Flare 2 (394M) | Our own tokenizer, transformer and training run |
| **2: the 2.x series, built on open bases** | **Flare 2.5** (the 1.5B open base), **Equinox 2** (about 4B), **Solstice 2** (about 8B), **Apogee 2** (about 14B) | Fine-tuned here on Emvryx's own lessons, with the base credited in `NOTICE` |

Planned: a 3.x series on a newer open generation and a 4.x series on newer open bases or the newest base (`docs/OPEN_MODEL.md`). A newer generation takes the main spot in the app's picker. Each name has
its own number that goes up only when that model is updated ("+" refreshes take the next decimal: Flare 2.5 to Flare 2.6). The from-scratch v3.5 run was
stopped (see `docs/V3_5.md`). They are placeholders: no trademark check has been done yet. See `docs/ROADMAP.md`, `docs/OPEN_MODEL.md` and `docs/APP.md`. For non-technical readers, see the plain-language **[Family guide](docs/FAMILY_GUIDE.md)**. Measured so far (HellaSwag, tuned vs plain base): Flare 2.5 65.3% vs 65.6%, Equinox 2 69.1%, Solstice 2 73.6% vs 71.9%; identity 16/16 on Equinox, Solstice and Apogee (trained, 8.4 GB 4-bit file). What changed lately is in **[docs/CHANGELOG.md](docs/CHANGELOG.md)**. The app also has Skills, Teacher mode, Documents, live facts and a 6-hour usage window ([SKILLS](docs/SKILLS.md), [TEACHER_MODE](docs/TEACHER_MODE.md), [DOCUMENTS](docs/DOCUMENTS.md), [LIVE_DATA](docs/LIVE_DATA.md)). A coding assistant, **VryxCode** (built: terminal tool and a Code screen in the chat app, usage-metered; only on Equinox 2 and above), is described in `docs/VRYXCODE.md`.

## Pretrained weights policy (updated Oct 2026)

Two kinds of models, each described honestly:

| Models | How they are made |
|---|---|
| **v1, v2, v3** (Ember 2, Flare 2) | Trained **from scratch** here: random numbers at the start, learning only from the text we give them. No one else's weights are used |
| **The 2.x series, built on an open base** (the first: Flare 2.5 on the 1.5B open base, 32K context; see `docs/OPEN_MODEL.md`) | Start from an open model's weights and are fine-tuned here on our lessons. They carry the Emvryx name; the base model and its licence are credited in `NOTICE` |

Rules:
- Only open models whose licence allows this. Keep each licence's notice (`NOTICE`) and check it before sharing a model.
- Never describe a model as "trained from scratch" unless it was. The from-scratch line (v1 to v3) stays what it is.
- Never use the ChatGPT, Claude or Gemini APIs to write training data; their terms restrict using outputs to build competing models.
- Other open models may also be used as **helpers beside a model** (a teacher that writes practice examples and grades answers, an optional search model, Whisper and Piper for voice). Only their text or audio output is used.
- Some training data (for example the smol-smoltalk conversations) was written by other AIs. It shapes the chat *style*.

## Where things are

The code lives in folders by job. Run everything from the project folder, for example `python training/finetune_open.py ...` or `bash scripts/chain_open.sh`.

| Folder | What is in it |
|---|---|
| `app_server.py`, `web/` | The Emvryx app: the server (`python app_server.py`, which holds the start-up, the request handler's plumbing and the page and file routes) and the chat page. Kept in the project folder because the Windows start-up task runs it from there. The page's code is split by part into `web/js/` (`core`, `chat`, `settings`, `admin`, `code`, `ide`, `auth`...; loaded in that order by `web/index.html`; there is no inline script) |
| `app/` | The server's other parts, split out of `app_server.py` by job: `state_*.py` (what `AppState` does: accounts, settings, apps, the PC and models, VryxCode, operations), `routes_*.py` (the web routes: chat, account and sign-in, admin, VryxCode), `chat_turn.py` (one chat turn), `app_runner.py` (starting llama-server), `app_shared.py` (limits and small helpers). Also everything behind the chat page: reliability and errors, sign-in and plans, usage limits, memory, look-ups (Wikipedia, web search), **live facts**, **Skills**, **Teacher mode**, **Documents**, saving answers as PDF or Word, connected apps |
| `coding/` | **VryxCode**: the coding assistant, its tools and loop, the safe sandbox, live preview, and the coding benchmarks |
| `core/` | The model itself: the transformer, tokenizer, chat format, settings for each version, LoRA, and the open-base model list |
| `training/` | Pretraining, fine-tuning (from scratch and on open bases), preference training, run supervision, backups and cloud hand-off |
| `data_prep/` | Building the training data and the chat lessons (including the open-base lessons) |
| `evaluation/` | The exams, test sheets, public benchmarks and the side-by-side comparison |
| `tools/` | Export and convert (Hugging Face layout, GGUF), generate text, build the website, back up server data |
| `scripts/` | The shell scripts for cloud runs (`chain_open.sh`, `wrap_open.sh`, `bench_all.sh`, `cloud_setup.sh`) |
| `tests/` | The automatic tests. Fast way: `python scripts/run_tests.py` (runs the files side by side, about 2 minutes, lists the slowest); reference: `python -m unittest discover -s tests -t .`. `python tools/lint.py` checks for unused imports and undefined names. GitHub runs both on every push (`.github/workflows/tests.yml`) |
| `docs/` | The guides: [Family guide](docs/FAMILY_GUIDE.md), versions, roadmap, benchmarks, how each feature works |
| `site/`, `design/` | The website (built pages and design sources) and the brand |
| `eval/`, `examples/`, `docker/`, `windows/` | Test sheets, sample data, the VryxCode sandbox image, the Windows start-up installer |

Each script starts with `import emvryx_paths`, which makes all the code folders importable by plain name (`import chat`), so the files did not have to change how they find each other.

## Files

| File | Phase | What it does |
|---|---|---|
| `training/stage.py` | all | Sets the working stage (`dev`) and its folders |
| `core/config.py` | all | Settings for each version (model size, folders, training) |
| `core/chat.py` | 6–8 | The chat format, shared by fine-tuning, chat and export |
| `core/bigram.py` | 1 | Warm-up: tiny character model that learns from `examples/input.txt` |
| `core/tokenizer.py` | 2 | Byte-level BPE tokenizer written from scratch |
| `core/model.py` | 3 | The transformer (RMSNorm, RoPE, attention, SwiGLU) |
| `data_prep/prepare_data.py` | 4 | v1 data: downloads TinyStories, trains the tokenizer, writes `data/train.bin` / `val.bin` |
| `data_prep/prepare_web_data.py` | 4 | v2+ data: streams FineWeb-Edu + Wikipedia (+ code for v3) + TinyStories into `data/<version>/` (resumable) |
| `data_prep/prepare_data_v2.py` | 4 | Shortcut for `data_prep/prepare_web_data.py --version v2` |
| `training/train.py` | 5 | Pretraining loop. Ctrl+C pauses; run again to resume. Also trains on several GPUs of one machine (DDP, via torchrun or `training/run_training.py --gpus N`) |
| `training/run_training.py` | 5 | Runs `training/train.py` and restarts it automatically after a crash (for long runs) |
| `core/offload_optim.py` | 5 | AdamW that keeps its memory in system RAM, so a 1B model fits on a 12 GB GPU (v3.5) |
| `docs/CLOUD.md` | - | How to rent a GPU and train there when your PC is off (or for big runs) |
| `training/handoff.py` | 5 | Moves a training run between your PC and a rented cloud GPU (one command each way) |
| `training/hub_backup.py` | 5 | Off-machine backup of the checkpoint to a private Hugging Face repo (`--hub_backup`), so a rented machine going offline doesn't take the run with it |
| `training/notify.py` | 5 | Push messages to your phone about training progress, crashes and finish (free, via ntfy.sh); see `docs/PHONE.md` |
| `app/app_errors.py`, `app/app_engine.py`, `app/app_download.py` | app | The app's reliability layer: plain-language errors, model choice (too big / PC off), reply guard (length cap, loop detector, Stop), chats saved while they stream, the llama-server client, "Test connection", and resumable checksum-verified downloads |
| `design/` | app | The Emvryx website, app and logo concept: logo SVGs, brand colours per model, and the design canvas sources (see `design/README.md`) |
| `models.json`, `app/models.py` | app | The app's model list (Ember, Flare, Equinox, Solstice, Apogee, each with its own version) and the "Select model" picker logic; see `docs/APP_SPEC.md` |
| `coding/harness.py` | 6 | The coding helper's tools and loop (no model needed; tests in `tests/`): safe file/command tools, a safe git subset, syntax diagnostics, project notes (EMVRYX.md / AGENTS.md), hooks with a finish gate, permissions (ask before commits), compaction of long runs, and a tool registry (where MCP tools plug in) |
| `coding/agent_tasks.py`, `coding/agent_lessons.py`, `coding/make_agent_data.py` | 6 | Coding practice made by our own code: tiny bug-fix projects solved by a scripted solver through the real harness (only passing runs kept). Become chat lessons (`tool_use`, `project_context`, `ask_first`, `too_big`, `compaction`) and `data/v3.5/agent_traces.jsonl` for v3.5's final phase. Run `python coding/make_agent_data.py --version v3.5` before building v3.5's data |
| `training/stretch_ladder.py` | 6 | Stretches v3's memory step by step (8K, 16K, 32K, 64K, 128K, 256K) and stops at the first step that fails its long-context tests, so you find how far it can go without wasted training (see `docs/LONG_CONTEXT.md`) |
| `app/usage_limits.py`, `limits.json` | 6 | Plans (Free, Pro, Mega), token counting, the tank and the fixed weekly reset, plain numbers for the Usage screen (see `docs/APP_SPEC.md`) |
| `app/context_window.py` | 6 | The device check: picks the context window from what the model passed, free memory, speed and the plan |
| `app_server.py`, `web/` | 6 | The Emvryx app: a web server and chat page (`python app_server.py`), with plans and usage, model picker, thinking animation, private chats and a Usage screen. Demo mode until a model is attached |
| `app/effort_router.py` | 6 | "Auto" effort: picks Quick, Balanced or Deep from the message (plain rules, with a reason), and sizes the thinking pause to it |
| `app/regen_modes.py` | 6 | The Regenerate menu: try again, a different answer, explain it differently, simpler, more detail, shorter, or three choices |
| `app/connected_apps.py` | 6 | The "Connected apps" list and rules (Calendar, Gmail, Drive, Notion, Slack, GitHub, Vercel, Supabase; all coming soon) |
| `tools/build_site.py`, `site/`, `docs/DEPLOY.md` | 6 | Builds the website designs into static pages for Vercel; DEPLOY.md says what goes where (Vercel, Supabase, the app server) |
| `core/muon.py`, `training/muon_test.py` | 5 | The Muon optimizer (`optimizer="muon"` in core/config.py; `"muon_cpu"` keeps its memory in RAM so it fits a 12 GB card), and an experiment that measures whether it needs fewer steps than AdamW on our models (~1–2 h on the 4070) |
| `core/grow.py`, `training/growth_test.py` | 6 | Grow a trained model into a deeper one, and an experiment that measures how much training compute that saves (run when the GPU is free) |
| `tools/generate.py` | 6 | Generate text or chat with your model. Chat options: `--lookup` (Wikipedia notes), `--web` (web search, online mode), `--memory` (remembers you), `--suggest` (reply suggestions), `--context` (memory meter), `--skill` (skill packs) |
| `data_prep/make_chat_data.py` | 7 | v1: builds `data/chat.jsonl` fine-tuning examples automatically |
| `data_prep/make_chat_data_v2.py` | 7 | v2: builds `data/v2/chat.jsonl` (multi-turn conversations) |
| `training/finetune.py` | 7 | Teach it a chat format using the version's `chat.jsonl`. Ctrl+C pauses; run again to resume. NEFTune (a little noise while training, for better answers) is on from v3 |
| `data_prep/make_dpo_pairs.py`, `training/dpo.py` | 7 | Preference training: the chat model answers each question several times, answers are scored by checkable rules (facts from the notes, "I don't know" when right, counts), and it learns to prefer the better one |
| `evaluation/bench_open.py` | 7 | Runs public benchmarks (ARC, WinoGrande, MMLU, GSM8K, TruthfulQA, MMLU-Pro, GPQA, IFEval, MATH, MuSR, BBH, HumanEval, MBPP) on an open model, plain base versus our tuned one. See [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md), which also plans the agentic ones (SWE-bench, Terminal-Bench, Aider, LiveCodeBench) |
| `coding/collect_runs.py` | 7 | Collects training runs for VryxCode: a model works on practice tasks and only the runs that really pass (tests run by us, no test-file edits) are kept as training examples. See [`docs/VRYXCODE.md`](docs/VRYXCODE.md) |
| `coding/bench_exercises.py`, `coding/vryx_swe.py` | 7 | Agentic coding benchmarks for VryxCode: Aider-style Exercism exercises (two tries, no Docker) and SWE-bench-style patch predictions (scored on a Docker machine). See [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md) |
| `app/app_links.py`, `app/connected_apps.py` | 7 | The connected apps: 21 free, read-only services (calendar, email, Notion, Slack, Todoist, Linear...) connected with a pasted token, link or app password. See [`docs/CONNECTED_APPS.md`](docs/CONNECTED_APPS.md) |
| `app/accounts.py`, `app/auth.py`, `app/mailer.py`, `app/secret_box.py`, `coding/code_sandbox.py`, `app/data_tools.py`, `tools/backup_data.py` | 7 | Security and data rights for opening Emvryx to more people: sessions, pairing links and email-code sign-in, passwords, authenticator-app two-step sign-in, invite codes, rate limits and bans, encrypted tokens, a Docker sandbox for VryxCode, quotas, data export and deletion, backups. See [`docs/SECURITY.md`](docs/SECURITY.md) and [`docs/ACCOUNTS.md`](docs/ACCOUNTS.md) |
| `app/github_link.py` | 7 | GitHub as a connected app: connect with a token, create or link a repository for a VryxCode project, pull and push, with the token kept private on the server. See [`docs/VRYXCODE.md`](docs/VRYXCODE.md) |
| `coding/code_sessions.py` | 7 | VryxCode inside the chat app: the Code screen's server side (projects, sessions, permission questions). See [`docs/VRYXCODE.md`](docs/VRYXCODE.md) |
| `coding/vryxcode.py`, `coding/harness.py` | 7 | VryxCode, the coding assistant for Equinox 2 and above: a terminal tool that reads, edits and tests your project in a sandbox, asking before it changes anything. See [`docs/VRYXCODE.md`](docs/VRYXCODE.md) |
| `training/finetune_open.py`, `core/open_models.py`, `core/open_tokenizer.py`, `evaluation/exam_open.py`, `evaluation/evaluate_open.py`, `data_prep/identity_lessons.py`, `NOTICE` | 7 | Emvryx models built on an open base (the 1.5B open base, 32K context): LoRA fine-tune on our lessons, model presets, ChatML tokenizer adapter, the HellaSwag exam for open models, and the base's licence notice. See [`docs/OPEN_MODEL.md`](docs/OPEN_MODEL.md) |
| `core/lora.py`, `core/skills.py`, `data_prep/make_skill_data.py`, `training/train_skill.py`, `evaluation/skill_test.py` | 7 | Skill packs (Beta): small LoRA add-ons that make the chat model a specialist. First packs: the **Study helper** and the **Teacher assistant** (`evaluation/classroom.py`: 3rd-grade requests and checks). Includes a Beta router (`tools/generate.py --chat --skill auto`) and an access toggle (everyone / beta testers / off: `python core/skills.py access`). See [`docs/SKILLS.md`](docs/SKILLS.md) |
| `app/export_doc.py` | 7 | Saves an answer as a printable PDF or an editable Word file (in chat: `save worksheet.pdf`); worksheets get a Name/Date line and the answer key on its own page |
| `training/average_ckpts.py` | 6 | Averages the last few snapshots of a run (kept during the fade) for a small free improvement |
| `evaluation/evaluate.py` + `eval/prompts.jsonl` | 6–7 | 20-question test sheet that scores a chat model |
| `evaluation/exam.py` | 6 | HellaSwag, a public common-sense test (works on pretrained models; compare versions) |
| `data_prep/wiki_index.py` | v3 | Searchable copy of Wikipedia for lookups (build + search) |
| `app/web_search.py` | v3 | Web search for online mode (Wikipedia's free search or Brave Search); results become notes |
| `data_prep/typo_lessons.py` | v3 | Chat lessons for messy typing: copies of ordinary lessons with the user's message typed carelessly (slips, no apostrophes, text-speak) and the clean answer; on by default in `data_prep/make_chat_data_v3.py` (`--typos`) |
| `data_prep/web_lessons.py` | v3 | Chat lessons for reading web results and honest answers about other AIs (used by data_prep/make_chat_data_v3.py) |
| `data_prep/make_teacher_data.py` | v3 | The teacher model (a 7B open model via llama.cpp, or rented per token from a hosting API) writes practice examples |
| `data_prep/make_chat_data_v3.py` | 7 | v3 and every later version (`--version`): chat lessons that fix v2's mistakes (lookups, "I don't know", corrections, instructions, topic switches), remembering you, and reply suggestions |
| `app/chat_memory.py` | 7 | Remembers earlier chats and facts about you, on your computer only (`tools/generate.py --chat --memory`); search by keywords and by meaning |
| `evaluation/compare.py` | 6 | Side-by-side scoreboard of two versions on the same tests, and whether the new one may replace the old (`--old v3 --new v3.5`) |
| `evaluation/eval_long.py` | 6 | Long-context tests (needle in a haystack, multi-fact, code recall, loss by position) with pass/fail rules |
| `data_prep/prepare_long_data.py` | 4 | Long-document data (books, long articles, code by repository, recall practice) for stretching the context |
| `evaluation/benchmarks.py` | 4–6 | Downloads the public test sets (HellaSwag, GSM8K), used by `evaluation/exam.py` and to keep them out of training data |
| `tools/export_hf.py` | 8 | Save in standard Llama layout (safetensors + tokenizer.json) |
| `tools/to_gguf.py` | 8 | Convert to GGUF with llama.cpp for phone apps |
| `examples/chat_sample.jsonl` | 7 | Example fine-tuning data format |

Version side-by-side: [`docs/VERSIONS.md`](docs/VERSIONS.md) (with the settings each version trains with). What we learned along the way: [`docs/LESSONS.md`](docs/LESSONS.md). Where the project is heading: [`docs/ROADMAP.md`](docs/ROADMAP.md).

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
python core/bigram.py        # loss drops, prints gibberish (expected!)
python core/tokenizer.py     # prints "tokenizer OK"
python core/model.py         # ~29.5M parameters, initial loss ~9.0

# Phase 4: data (~2GB download, 30-70 min total, run once)
python data_prep/prepare_data.py

# Phase 5: train (5-10 hours on an 8GB card)
python training/train.py

# Phase 6: try it
python tools/generate.py --prompt "Once upon a time"
```

Checkpoints land in `checkpoints/dev/`.

## Fine-tuning (Phase 7)

```powershell
python data_prep/make_chat_data.py        # builds data/chat.jsonl (~5,000 examples) from TinyStories
python training/finetune.py              # ~5-10 min -> checkpoints/dev/chat.pt
python tools/generate.py --ckpt checkpoints/dev/chat.pt --chat
```

`data_prep/make_chat_data.py` turns stories into requests like *"Tell me a story about Lily."* and adds
greetings and "who are you?" answers (edit `BASICS` in the file to change its personality).
Add your own examples to `data/my_examples.jsonl` (same format as
`examples/chat_sample.jsonl`); they are included 3 times so they count more.

## Putting it on your phone (Phase 8)

**1. Export and convert (once per model version):**
```powershell
python tools/export_hf.py                          # checkpoints/dev/chat.pt -> export/dev/my-ai
git clone https://github.com/ggml-org/llama.cpp ..\llama.cpp
pip install ..\llama.cpp\gguf-py sentencepiece
python tools/to_gguf.py --llama_cpp ..\llama.cpp   # -> export/dev/my-ai-f16.gguf (~60MB)
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
`checkpoints/production/`. To work from another stage later, change `STAGE` in `training/stage.py`. `data/`, `checkpoints/` and `export/` are
git-ignored because they're large.

## Troubleshooting

- **`torch.cuda.is_available()` is False**: you installed the CPU-only PyTorch. Uninstall torch and reinstall with the CUDA command.
- **Out of memory**: in `training/train.py`, halve `batch_size` and double `grad_accum` (e.g. 16 and 8).
- **Loss becomes NaN**: lower `lr_max` to `3e-4`.
- **Train loss far below val loss**: the model is memorizing; stop early or use more data.

## Progress checklist

- [ ] Phase 0: GPU verified in PyTorch
- [ ] Phase 1: `core/bigram.py` trains and generates
- [ ] Phase 2: `core/tokenizer.py` self-test passes
- [ ] Phase 3: `core/model.py` shows ~29.5M params, loss ~9.0
- [ ] Phase 4: `train.bin` and `val.bin` created
- [ ] Phase 5: val loss at or below ~1.5
- [ ] Phase 6: coherent stories from `tools/generate.py`; checkpoint in staging
- [ ] Phase 7: chat mode answers in the right format
- [ ] Phase 8: GGUF runs on your phone offline; copied to production
- [ ] Phase 9: first model trained on your own data
