# Roadmap

Where this project is going, and why. Plans past v2 are a **direction, not a promise**: each
version's test-sheet results decide what the next one focuses on.

> **Update (Oct 2026): Emvryx moves to open bases.** From v3.5 on, models are fine-tuned from an open model instead of trained from scratch
> (cheaper and stronger: about $183 for a forecast ~41-45% from scratch versus a few dollars for roughly 65% on a 1.5B open model).
> They carry the Emvryx name only; the base and its licence are credited in `NOTICE`, and the docs never call a fine-tuned model "from scratch".
> **v1, v2 and v3 (Ember 2, Flare 2) stay from scratch**, and the from-scratch v3.5 run was **stopped** (step recorded in `docs/V3_5.md`).
> **The open-base models are the 2.x series** (generation 2): **Flare 2.5** is the 1.5B open base with a 32K context ([OPEN_MODEL.md](OPEN_MODEL.md)), and a
> "+" refresh takes the next decimal (Flare 2.6). Later rungs (suggestions, not chosen): **Equinox 2** about a 4B base, **Solstice 2** about an 8B base,
> **Apogee 2** about a 14B base on rented GPUs; pick each base when its turn comes, because better open models will exist.
> The version slots map as: v3 -> Flare 2 (from scratch), v3.5 -> Flare 2.5, v4 -> Equinox 2, v5 -> Solstice 2, v6 -> Apogee 2. Text below that uses the old names describes the from-scratch plan.
> The rest of this file was written for the from-scratch plan: where it says a version's brain is trained from scratch or grown from v3.5, read it with this update.

> **Later generations (planned):** 3.x on a newer open generation (2B, 4B, 9B, 27B) and 4.x on newer open bases or the newest base; each needs a short pilot first. See [OPEN_MODEL.md](OPEN_MODEL.md).
>
> **Public access (later):** staying on keys for now; the plan to open it to anyone, with the security work it needs, is the "Going public" checklist in [DEPLOY.md](DEPLOY.md).
>
> **VryxCode** (a coding assistant, first version built: terminal and the app's Code screen; only on Equinox 2, Solstice 2 and Apogee 2): [VRYXCODE.md](VRYXCODE.md).
>
> **Order of work (decided Oct 2026):** build all the 2.0 models first (Flare 2.5, Equinox 2, Solstice 2, Apogee 2), then the improved **Equinox 2.5, Solstice 2.5 and Apogee 2.5** releases (new lessons, DPO, skill packs, tools, thinking dial). Details: [OPEN_MODEL.md](OPEN_MODEL.md#order-of-work-all-the-20-builds-first-then-the-improved-25-releases-decided-oct-2026).

<!-- next:start -->
## Decided on Oct 11, 2026: four models are the standard

The owner's decisions:

- **Four models:** Flare, Equinox, Solstice and Apogee. Ember is gone from the app.
- **Ember and Flare 2 (the from-scratch models) are archived, not deleted.** Their entries stay in `models.json` marked `"archived"`, and their checkpoints, exports and training code stay in the repository. The app treats them as off: not in the picker, not in any plan, refused if asked for. Setting `"archived"` back off in `models.json` brings one back. The Flare card is Flare 2.5 (on the open Qwen base).
- **Free plan:** Flare and Equinox. Pro and Mega: all four.
- **Feature flags:** the audiences are Off, Owner, Admins and Everyone. There is no tester list; new features start with the owner and admins.
- **Still to decide:** the first app to connect to the Emvryx API (household finance? what it is built with and where it is hosted). Planned for later: the API, a What's new panel with draft / testing / published status, and the 2.5 retrain.
- **Website:** the home, models, plans, usage and about pages now show four models (done Oct 11, 2026).

## Decided and built (Oct 11, 2026): model versions and publishing a model update

The owner's idea: an update to a model can raise its version (Flare 2.5 to 2.6 or 2.7), the old version moves to "Other models" and stays usable, and a small fix does not change the version. Publishing works for models the way it does for features, but with its own switch.

**Proposal, to be confirmed:**

- **Two kinds of change.** A *patch* (small fix, same lessons mostly: tuned wording, a better prompt, a bug in the model's start-up settings) keeps the version, for example Flare 2.5 stays 2.5 and the release history notes "2.5, update 3". A *new version* (several changes together: new lessons, a retrain, a new base) makes Flare 2.6. The rule of thumb: if the files or lessons the model was trained on changed, it is a new version.
- **Model releases are separate from feature releases.** Admin gets a **Models** tab next to Previews. A finished model build is added as *In preview*: visible to you only (it appears in your picker with a "Preview" label). Publish moves it to everyone and, in the same step, moves the previous version of that model to **Other models** (still usable, never deleted). Scheduling and the release history work the same way, and the "What's new" sheet shows "Flare 2.6 is here" with what changed.
- **Checks before publishing:** the regression guard (idea 15) must pass, so a new version cannot replace a good one by accident. Plans follow the model name (Free gets Flare and Equinox, so Flare 2.6 is Free-eligible the moment it is published).
- **Publish all** would cover features and models together (one release, one version number for the app) or each tab on its own; to decide.

**The owner's answers:** (1) yes, a new version when the training lessons change, otherwise an update that keeps the version; (2) yes, the app's version and the model versions stay separate; (3) keep 5 to 6 older versions in Other models (set to 6, `keep_older_versions` in `models.json`). Built: Admin > **Models** tab, `app/model_publish.py`, see [FEATURE_FLAGS.md](FEATURE_FLAGS.md). The regression check before a publish (idea 15) is built too: Admin > Models > Run safety checks.

## Emvryx 3: the plan so far (Oct 11, 2026)

**The owner's rule: every model must run on the owner's RTX 4070 (12 GB), by itself, with nothing split into system RAM.** That rules out the 27B, the 26B and 35B mixture models and anything else that needs more than the card holds, and it keeps gaming possible alongside a small model. Training can still be done on a rented GPU (with the owner's approval first); only running has to fit at home.

**What 3 means:** the first build on a newer open-model generation, instead of retraining the 2.x models as 2.5. The 2.5 improvements (new lessons from reported mistakes, DPO, tool calling, thinking dial, long-document lessons) go into the 3.0 builds so training money is spent once. Flare 2.5 can still get its free refresh at home.

**Decision (Oct 11, 2026): Apogee stays on its current base (Qwen3-14B, runs on the 4070 at about 9 GB) and gets the improved 2.5 release. Flare, Equinox and Solstice move to the new generation as Flare 3, Equinox 3 and Solstice 3.** Each model has its own version number, so Apogee can be 2.5 while the others are 3. Apogee 3 waits for a newer model of about 12B to 14B that clearly beats Qwen3-14B on our own tests (Gemma 4 12B and the Qwen3.5 9B in thinking mode are the ones to try in the pilot); nothing is forced. Details of the pilot: [EMVRYX3_PILOT.md](EMVRYX3_PILOT.md).

**Version 3 plan (decided Oct 12, 2026; the owner asked for the approach most likely to work best, and the bake-off results confirm or change each pick):**

| Slot | Base | Trained on | Thinking | Notes |
|---|---|---|---|---|
| Flare 3 | Qwen3.5 2B (the plain model already beat Flare 2.5 on the everyday sheet, 39 vs 35 of 41, first bake-off line) | Emvryx lessons (`--keep 0.4`) + 30% general lessons | Quick and Balanced only | Cheapest, so it is the A/B test: train once with and once without the general lessons, keep the winner |
| Equinox 3 | Qwen3.5 4B | same recipe as the Flare winner | Deep | Gemma 4 E4B is the challenger |
| Solstice 3 | Qwen3.5 9B | same recipe | Deep | DeepSeek-R1-0528-Qwen3-8B is the challenger |
| Apogee 3 | the bake-off winner of Qwen3.5 9B (thinking) and DeepSeek-R1-Distill-Qwen-14B | same recipe if it fits training in 12 GB | always or Deep | Decided by `logs/bakeoff.md`, not by reputation |
| Apogee 3.5 | Qwen3.8-27B at 2-bit (about 9 GB) | **not trained** (a 2-bit file cannot be trained; the 27B does not fit training in 12 GB) | Deep | Runs on the 4070 with Emvryx instructions in the prompt; only kept if it clearly beats Apogee 2/3 on the bake-off and passes identity checks; Gaming mode must unload it |

- **The lessons:** all Emvryx lessons stay, identity, honesty and corrections always kept; general lessons from Nemotron-Post-Training-Dataset-v2 (cc-by-4.0, the "reasoning off" rows only, replies capped at 2,500 characters) are added as 30% of the final set (`data_prep/general_lessons.py`, `format_lessons_3x.py --general`).
- **Thinking:** built in Oct 12, 2026: Deep effort on a model with `"think": "empty"` leaves the empty thinking block off the prompt so the model reasons first; the reasoning is hidden and the saved chat never holds it. After each training run, `evaluation/thinking_check.py` compares the tuned model with its plain base; only if tuning wore the thinking down do we make thinking lessons and retrain.
- **From the 2.5 plan, built into 3.0 so training is paid for once:** preference training (DPO) from reported answers, tool calling in the base's own format, long-document lessons. **App-side, no retrain, for all models:** receipts on every answer, second opinion, careful mode, never-guess-a-number.
- **Newer models make possible:** native pictures (keep the vision part and its extra llama.cpp file; Qwen3.5 is an image-and-text model), faster big models with a tiny same-family draft model (idea 14), long-document questions on 12 GB (the new design needs far less memory per token).
- **Not decided by me:** nothing is rented or bought; every dataset's licence is read by the owner before it is used.

**Apogee 2.5 (same base):** new lessons built from mistakes people reported, preference training (DPO), tool calling in the base's own format, the thinking dial, long-document lessons; about $12 to train by the earlier estimate. On top of that, the app-side features that make the top model feel smarter without a bigger base: careful mode (draft, critique, fix), receipts and checked quotes, second opinion, and tools the model asks for itself.

**Candidates (all from web searches on Oct 11, 2026: secondhand, to be checked on the official model cards)**

| Slot | Size on the 4070 | Leading candidate | Also test | Notes |
|---|---|---|---|---|
| Flare 3 | about 1.5 to 2 GB | Qwen3.5 2B (or 0.8B) | | Apache 2.0, natively multimodal (reported) |
| Equinox 3 | about 3 GB | Qwen3.5 4B | Gemma 4 E4B | |
| Solstice 3 | about 6 GB | Qwen3.5 9B | DeepSeek-R1-0528-Qwen3-8B (a thinking comparison) | |
| Apogee (stays 2.5 for now) | about 9 GB | Qwen3-14B (current) | Gemma 4 12B (about 7.8 GB reported), Qwen3.5 9B in thinking mode, DeepSeek-R1-Distill-Qwen-14B | Only replaced if one clearly wins the pilot; a 12B is reported by several sources but not yet confirmed on Google's own page |

Left out because they do not fit the rule: Qwen3.6-35B-A3B, Gemma 4 26B-A4B, the 27B-class models, DeepSeek V4 (hundreds of billions of parameters).

**Preparation code is written and tested (Oct 11, 2026), to be run at the end of the month:** the presets, the thinking format (`think="empty"`), a pre-flight check, the pilot runner and report, the lesson style check and balanced subset builder, optional verified thinking lessons, a thinking regression check, and a resumable home training chain. Step by step: [EMVRYX3_RUNBOOK.md](EMVRYX3_RUNBOOK.md). The voice the lessons should follow is in [EMVRYX_STYLE.md](EMVRYX_STYLE.md) (the owner still decides the open choices there).

**Open points before choosing**
- Gemma uses its own chat format, not the ChatML our lessons and `core/open_tokenizer.py` assume: it needs a conversion and a check of the trainer.
- Quantization-aware (QAT) 4-bit files are for running as released; we fine-tune from full-precision weights and compress ourselves, so that advantage may not carry over.
- Every base says who made it: each needs our identity lessons (see IDENTITY.md).
- New open models can write long "thinking" by default: decide keep, hide, or tie to Deep.
- Memory for conversations: a 12B at about 7.8 GB leaves about 4 GB on the card, so keep windows at 16K to 32K.

**Next steps (nothing is spent without the owner's approval):**
1. Short pilots on a rented GPU (cents each): does the trainer load it, does the chat template work, does it fit and how fast does it run on the 4070 (`training/finetune_open.py --pilot`).
2. Head-to-head on our own tests (`evaluation/exam_open.py`, the quality check, the language benchmark) against the 2.x model in the same slot, before anything is trained for real.
3. Build the app-side protection for gaming: unload an idle model and a Gaming mode switch (planned).

## What's next: the 2.5 plan and 25 ideas

This is a **direction, not a promise**. Nothing below is built unless it says so, and the order can change once the quality check and language benchmark show what the models actually get wrong. Costs are estimates from the figures elsewhere in this roadmap.

### The 2.5 plan, in order

| Step | What we do | Why |
|---|---|---|
| 1. Measure | Run the quality check (`evaluation/quality_check.py`) and the language benchmark (`coding/bench_languages.py`) on every model, one at a time, never during training. | The 2.5 lessons should fix what really fails, not what we guess fails. |
| 2. Preference training (DPO) | Teach the models which of two answers is better, using answers people reported, "Ask Solstice" comparisons and cut-off or could-not-read cases. | The cheapest big gain. The app already collects the raw material. |
| 3. Tools the model asks for itself | The model says "look this up" or "run this" and our code does it, instead of our code guessing when. | Moves Equinox, Solstice and Apogee from chatbot toward assistant. Helps VryxCode most. |
| 4. Thinking dial and reasoning lessons | A "think first" mode, trained on worked step-by-step solutions from a larger teacher model. | Small models are weakest at multi-step reasoning. Expect gains on math and logic, not miracles. |
| 5. Pictures natively | A base that sees pictures directly, instead of a helper that describes them first. | The helper loses detail in screenshots, charts and handwriting. |
| 6. Long-document test | Check that the models really use their long context (answer from page 40 of a PDF). | Small models often claim more context than they use well. |
| 7. Voice | Speech in (Whisper) and out (Piper), both free and offline. | Independent of the brain, so it can ship any time. |
| 8. Identity wording | Put "built on an open foundation model" into the lessons so it is baked in. | Avoids patching it later. Owner's choice pending. |
| 9. Newer bases | Pick each base when its turn comes, after a short pilot run. | Better open models will exist by then. |

**Suggested order of models:** Solstice 2.5 first (best mix of quality and cost to retrain, about $5 per fine-tune), then Equinox 2.5 (about $3), then Apogee 2.5 (about $12). Flare 2.5 can be refreshed on the home GPU for free.

### 25 ideas to push Emvryx further

Effort is a guess: **S** is days, **M** is a couple of weeks, **L** is a big project. "New model" means it needs a retrain; the others are app or tool work.

| # | Idea | What it would do | Effort | New model? |
|---|---|---|---|---|
| 1 | **Receipts on every answer** | Tap a reply to see what it used: the notes it read, the live source, memory or lookup, and when it is guessing. | M | No |
| 2 | **Visible confidence** | A small "sure / not sure" marker, trained on whether past answers turned out right. | L | Yes |
| 3 | **Checked quotes** | After answering, compare each claim with the source text and flag lines the source does not support. | M | No |
| 4 | **Never guesses a number** | For any number the model writes a few lines of code, runs them and shows the working. | M | No |
| 5 | **Second opinion** | A "Check this" button asks another model and shows where the two agree and differ. | S | No |
| 6 | **What left this computer** | A list of every outside request the app made, with time and source. Chats and files stay local. | S | No |
| 7 | **Projects** | A folder per topic (Homework, My business) with its own files, instructions, memory and chats. | M | No |
| 8 | **Memory you can see** | One page showing what Emvryx remembers about you, with edit and forget buttons. | S | No |
| 9 | **Search my files** | Index a folder of PDFs and notes on your PC and answer from them with sources. Stays private on the PC. | M | No |
| 10 | **Scheduled tasks** | "Every Monday, read my calendar and mail and send me a summary." Builds on the weekly summary and connected apps. | M | No |
| 11 | **Data analyst mode** | Upload a spreadsheet, ask questions, get tables and charts made by code you can read. | M | No |
| 12 | **Smarter Auto** | Start on the smallest model that can answer, move up only when unsure. Saves your usage. | M | Some |
| 13 | **Careful mode** | The model drafts, critiques its own draft and fixes it, for answers that matter. Slower, optional. | S | No |
| 14 | **Faster big models** | A small model drafts and the big one checks (speculative decoding), so Apogee feels quicker on the RTX 4070. | M | No |
| 15 | **Regression guard** | Every retrain must pass a frozen set of everyday questions and past reports before it replaces the current model. | S | No |
| 16 | **Many languages** | Test and train for languages other than English, starting with the ones people ask for. | L | Yes |
| 17 | **Native vision** | See photos, charts and handwriting directly. | L | Yes |
| 18 | **Voice** | Dictate and read aloud, then a hands-free mode. | M | No |
| 19 | **Ask about this page** | Share a web page or photo from your phone straight into Emvryx. | S | No |
| 20 | **Explain mode in VryxCode** | "Explain each step in plain English" and "teach me what you just built" for people who are not programmers. | S | No |
| 21 | **"Done" means tests pass** | VryxCode keeps going until the checks you named pass, and builds a map of a big project first. | M | No |
| 22 | **Code review mode** | Read a change (a GitHub pull request, read-only) and list the problems worst first. | M | No |
| 23 | **Family accounts and learning loop** | A parent view with budgets, a kid-safe mode with reading level, and flashcards and quizzes made from your own documents. | L | No |
| 24 | **Emvryx API** | A simple address so your own apps (household finance, charting practice) can ask your models questions, with their own key, plan limits and instructions. Also lets an app check first whether Emvryx is on. | M | No |
| 25 | **Shareable skill packs** | Export a specialist mode (Study helper, Lawyer's checklist) as a file and import one someone sent you. | S | No |

**Also worth doing, smaller:** screen-reader and large-text checks across the app, a dyslexia-friendly font option, a "where it fails" note on each model's scorecard entry, and keeping the website's numbers in step with `limits.json`.

**What we will not do:** train on people's chats without a clear opt-in, or let an answer claim a source it did not read.
<!-- next:end -->

## Emvryx API and connecting my own apps (the API is built, Oct 12, 2026)

> **Built Oct 12, 2026:** `POST /api/v1/ask` with one key per app, managed in Admin > Apps (instructions, plan, speed limit, on/off, new key, remove), nothing saved, no lookups by default, errors an app can show kindly, a tiny client (`examples/emvryx_client.py`) and a guide for non-experts: [API.md](API.md). **First app chosen: household finance (PennyOtter), kept in its own repository.** Emvryx stays generic (the API, keys, Admin > Apps); everything about money lives in the app. The first feature (the otter coach answering through Emvryx, behind a feature preview, no Claude) is built on the branch `claude/emvryx-coach` of the `household-finance` repository, not merged; its plan is `docs/emvryx-coach.md` there. Still to do: switch it on, try it, then pick the next job. Generic abilities the apps will want from Emvryx: structured answers (a fixed set of allowed values) and batch calls.

The owner's request: use Emvryx inside the other apps already built (household finance, charting practice). The text below is the original plan. The repos seen on the GitHub account: `household-finance` and `Personal-Finance-app`; the charting practice app is not identified yet.

**What to decide on Sunday**
1. Which app goes first, what it is built with, and where it is hosted (Vercel, only on the PC, or a phone app).
2. Which jobs it should do first (see the list below).
3. Whether the key sits in a small server-side piece (a Vercel function) or the app only runs on the owner's own devices.

**What gets built in Emvryx (idea 24)**
- `POST /api/v1/ask`: one question in, one answer out (plus an optional streaming form). Needs a key; counts against that key's plan; each app can send its own instructions ("you are a budgeting helper").
- A key per app (made with `--add-user`-style names such as `app-finance`), so one app can be switched off or rotated without touching the others.
- A way for an app to ask "is Emvryx on?" first (the public `/api/status` already exists) and show "assistant offline" kindly when the PC is off.
- Safe by default: read-only, no tools that change anything, rate limits, and the key never goes in browser code.
- A tiny example client and a page in `docs/` (`API.md`) written for a non-expert.

**The rule for money and numbers:** the app's own code adds up the totals and the model only explains them in plain words. A model never does the arithmetic. This is idea 4 ("Never guesses a number").

**Possible first jobs**
- Household finance: sort transactions into categories, a plain-English monthly summary, answers to "can we afford this?" from the app's own totals, odd charges explained. Data stays on the owner's PC.
- Charting practice: explain a pattern and quiz on it, review practice notes and point out mistakes, a short coaching note after a session. No predictions and no trading advice.

**Limits to say out loud:** the PC must be on; the answers can be wrong, so anything important is checked; nothing here is financial advice.

**Steps**
1. Read the app (its code, its data shape) and write a one-page plan the owner approves.
2. Build the endpoint and per-app keys in Emvryx, with tests.
3. Add one small feature to one app behind a switch, try it, then decide on the next.

## At a glance

| Version | Theme | Brain | Main new abilities | Where it trains | Cost |
|---|---|---|---|---|---|
| **v1** ✅ | Learn the pipeline | 30M | Tells children's stories; runs offline on the phone | RTX 4070, 4 hours | $0 |
| **v2** ✅ | Knowledge | 88M | General Q&A, explanations, multi-turn chat | RTX 4070, ~18 hours | $0 |
| **v3** 🛠️ | Accuracy | ~400M | Looks things up (RAG), says "I don't know", handles corrections, exact instructions, preference training (DPO), remembers you, reply suggestions, basic code; v3-long stretches it to 8K–32K | RTX 4070 afternoons + a rented RTX 3090 overnight (25.8 / 17.5 s/step) | ~$30–40 cloud + electricity |
| **Flare 2.5** (was v3.5) | Scale | **1.5B open base (the 1.5B base), 32K context** | Same lessons as v3 (lookups, "I don't know", corrections, instructions) on a stronger base. *(The from-scratch ~1.12B / 40B-token plan below was stopped.)* | RTX 4070 (LoRA, free) or one rented RTX 5090 | $0 or a few dollars |
| **Equinox 2** (was v4) | Abilities | **the 4B open base** open base (suggested), 32K context, up to 128K | Specialist skill packs + router, tools, voice, own app | One rented RTX 5090, about 5 hours per fine-tune | about $3 per fine-tune |
| **Solstice 2** (was v5) | Scale | **the 8B open base** open base (suggested), 32K context, up to 128K | Genuinely capable assistant | One rented RTX 5090, about 10 hours per fine-tune; runs on the 4070 at Q4 | about $5 per fine-tune |
| **Apogee 2** (was v6) | Bigger small | **the 14B open base** open base (suggested), 32K context, up to 128K | Stronger reasoning, coding and knowledge; powers online mode | One rented RTX 5090 with 4-bit weights (QLoRA), about 24 hours per fine-tune | about $12 per fine-tune |
| **Apogee 2.5 or later** (was v6.5) | Borderline medium | A bigger open base, chosen when it is time (about 30B class) | The best model for PC and server; the app's online brain | Rented 48–80 GB GPU | to be measured |

Guiding rules:
- **Cheapest over fastest.** Time isn't a constraint, so everything that fits on the RTX 4070
  trains there (electricity is far cheaper than cloud rental). Only 3B needs the cloud.
- **Grow about 3× per step, with pilot runs.** Before each long run, train 5–10% of the steps
  first to catch problems cheaply.
- **Better data beats a bigger model.** Most quality gains come from what the model reads.
- **Measure everything.** Every version is scored on `eval/prompts.jsonl` (`evaluation/evaluate.py`) and
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
| **lm-evaluation-harness** | Standard AI exams (HellaSwag, ARC, MMLU, GSM8K...) | **v3** | Works with `tools/export_hf.py`'s output. Scores v2 and v3 on the same public tests |
| **TensorBoard** | Live graphs of loss and speed while training | **v3** | Local and free. Handy for an 18-day run |
| **bitsandbytes** (8-bit optimizer) | Cuts optimizer memory ~75% | v3 (optional) → **v3.5** (needed) | In v3 it could replace gradient checkpointing if the pilot runs out of memory, and it's a rehearsal for 1B |
| **TRL-style DPO** | "Which answer is better" training | **v3** | Small enough to write ourselves, like the rest of the training code |
| **PEFT / LoRA** | Small add-on skill packs | Try on v3 → **v4** | A first skill pack can be tested cheaply on v2/v3 |
| **Web search** (`app/web_search.py`: Wikipedia's free search, or Brave Search with a key) | Online mode: our code searches the web and hands the results to the model as notes | **v3** (off by default) → better every version | See [Web search, version by version](#web-search-version-by-version) |
| **Coding harness extras** (`coding/harness.py`) | A safe git subset, syntax diagnostics, project notes, hooks with a finish gate, permissions, compaction, tool registry | ✅ built (Oct 2026) | See [Agentic coding](#agentic-coding-a-coding-helper-that-works-in-a-loop); the MCP client itself is not built |
| **App reliability layer** (`app/app_engine.py`, `app/app_download.py`) | Plain errors, model choice, reply guard, chats saved as they stream, resumable checksum-checked downloads | ✅ built (Oct 2026) | See [APP_SPEC.md](APP_SPEC.md) |
| **Tool calling (MCP-style)** | The model asks for a tool, our code runs it | v3 (lookups) → **v4** | v3's "look it up" is the first tool; v4 adds calculator, clock, files, and lets the model call web search itself |
| **Whisper** (OpenAI, open source) | Speech-to-text | **v4** (can try any time) | Independent of the brain, so it can be tested early |
| **Text-to-speech** (e.g. Piper) | Speaks the answers | **v4** | Small, offline, open source |
| **FSDP** (inside PyTorch) | Splits training across many GPUs | Written during v3.5 → **v5** | Needed for 3B in the cloud, and for v6/v6.5 |
| **vLLM / llama.cpp server** | Serves a big model to many users at once | **v6** | The online mode's server |

---

## Every version builds on the last
The rule for every new version: **keep everything the last one could do, then do it better.** In
practice that means three things.

**1. Nothing is left behind.** Every feature, lesson and test is written once and reused by every
later version (the scripts take `--version`):

| Built once | Used by every later version |
|---|---|
| Chat lessons (`data_prep/make_chat_data_v3.py --version ...`): lookups, "I don't know", corrections, instructions, memory, reply suggestions | v3.5, v3-long, v4, v5 ... reuse them in their own folder, with longer conversations when their context is longer; v3's teacher examples are reused, and each version adds its own |
| Lookups (`data_prep/wiki_index.py`), memory (`app/chat_memory.py`), the context meter, notes dropped from old turns | the same code for every model |
| Long-context stretch (`v3-long-*` settings, `data_prep/prepare_long_data.py`, `evaluation/eval_long.py`) | rehearsed on v3, then the same recipe for v3.5 and later |
| Tests: HellaSwag (`evaluation/exam.py`), the test sheet (`evaluation/evaluate.py`), the long-context tests, the unit tests | every version runs all of them |

**2. Each version grows every ability.**

| Ability | v3 | v3.5 | v4 | v5 | v6 / v6.5 |
|---|---|---|---|---|---|
| Context | 2K, stretched to 8K–32K | 32K, goal 75K–100K | same as v3.5 | 128K goal, a model designed for long text (local + global attention, smaller memory per token) | 256K → 500K goals |
| Memory of you | saves facts itself, finds past chats by meaning | better judgement about what to save | memory screen, model-driven saving through tools | summarizes old chats into memories | the same, larger |
| Reply suggestions | simple, from real follow-ups | sharper (bigger model) | greyed-out in the app; teacher-written follow-ups if plain | better | best |
| Facts | Wikipedia lookups + web search (our code searches) | reads web results better (2× the lessons) | the model decides when to search (tool call) | combines several sources | long documents, research mode |
| Thinking | trial on math | short thinking | adaptive + effort levels | longer | extended |
| Tools / coding | – | – | calculator, files, coding loop | more reliable | strongest |

**3. It has to prove it's better before it replaces the last one.** Before a new version becomes
the default, it runs the same tests as the version before and must:
- score higher on HellaSwag and the test sheet (more right answers, fewer made-up ones),
- pass the long-context tests at every length it claims,
- keep every older skill (memory, suggestions, "I don't know", corrections): no row of the
  comparison may get worse by more than a small margin.
If it doesn't, it isn't released yet: we find out why (data, training length, settings) and fix
that first. `python evaluation/compare.py --old v3 --new v3.5` runs all of this on both versions and prints
one side-by-side scoreboard with the verdict (HellaSwag, the test sheet by category, skill checks for
notes / "I don't know" / memory / secrets / suggestions, and `--long` for the long-context check).
Scores are saved next to each checkpoint, so the old version isn't re-tested every time.

## Fine-tuning ladder (from simple to advanced)
| Technique | What it does | Status |
|---|---|---|
| Chat fine-tuning (`training/finetune.py`) | learns from the AI's answers only (and the user's follow-ups at 30%, for suggestions) | ✅ built |
| NEFTune | a little noise on the word vectors while fine-tuning: better chat answers for free | ✅ built, on from v3 |
| Checkpoint averaging (`training/average_ckpts.py`) | averages the last snapshots of the fade (v3: every 900 steps) | ✅ built, used when v3 finishes |
| DPO (`data_prep/make_dpo_pairs.py`, `training/dpo.py`) | prefers the better of two answers; pairs scored by checkable rules (facts from the notes, "I don't know" when right, counts), no grader to trust | ✅ built, first used on v3 |
| Teacher-judged pairs | the teacher picks the better answer where no rule can check (style, helpfulness) | planned (v3.5) |
| Verified self-training | several tries per math/code question; only checked-correct ones become lessons (teaches thinking) | v3.5 |
| LoRA skill packs (`core/lora.py`, `core/skills.py`, `training/train_skill.py`) | small swappable add-ons per skill, a Beta router and an access toggle | ✅ built: **Study helper** and **Teacher assistant** (Betas), trained and tested on v3 once it's chat-tuned; real at v4 ([SKILLS.md](SKILLS.md)) |
| RL with verifiable rewards (GRPO) | rewards from passing tests / correct math | v4/v5 |
| Logit distillation | learning a bigger model's full probabilities | v4/v5 (needs the shared tokenizer decision) |

## Speed and safety experiments
| Idea | What it could give | Status |
|---|---|---|
| **Muon optimizer** (`core/muon.py`, `training/muon_test.py`) | the same quality in fewer steps | ✅ **tested and chosen for v3.5** (Oct 2): on a 39M test model it reached AdamW's final loss in ~33% fewer steps and ended 0.124 lower (3.809 vs 3.933). Its memory is on the GPU, so v3.5 trains on rented GPUs |
| **Off-machine backup** (`training/hub_backup.py`) | a rented machine dying costs at most ~30 min of training | built and running for v3 |
| **Reliable hosts** | Vast.ai hosts vary; ours dropped from 98% to 73% reliability in a night | rent 99%+ reliability (or Secure Cloud) from now on |
| **8-bit training on the 4070** | ~1.3-1.5x faster matrix math (the 3090 can't) | idea; needs a pilot |
| **Better data mix** (some DCLM-style general web next to FineWeb-Edu) | better everyday common sense (HellaSwag) at the same cost | idea for v3.5's data build |
| **More reading** | every doubling of tokens helps; 1B keeps improving past 30B | chosen: v3.5 reads 40B; **v4's brain is v3.5 continued** (+15–30B tokens, ~49–62 per parameter) |

**Tokens per parameter (how much each version reads for its size):** v2 ~30, v3 ~30 (11.8B tokens /
394M), v3.5 ~29. "Compute-optimal" is ~20; modern small models read far more (SmolLM2-360M: ~11,000,
a 0.5B open model: ~36,000), which is the main reason they score higher. Reading 1T tokens would take v3
~2 years on one RTX 3090 or ~70 days on one H100 (~$3,700 either way; preparing the data is fast:
~4-5 days). Better data, Muon and distillation get part of that gain for much less.

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
                                             chat.jsonl ─► training/finetune.py ─► student
```

- **Teacher size:** a ~7B open model as a Q4 GGUF fits in 12 GB and writes roughly 40–60 words a
  second. With several answers in parallel, ~50,000 answers takes about a day or two, and costs a
  few dollars of electricity.
- **Pick a teacher whose license allows training on its outputs.** Good candidates use permissive
  licenses such as Apache 2.0 (for example OLMo, Mistral 7B, a 7B open model, or OpenAI's gpt-oss).
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
| Test sheet (`evaluation/evaluate.py`) | **18/20** (identity 2/2, facts 7/8, explain 5/5, advice 2/2, writing 1/1, stories 1/2) |
| HellaSwag (`evaluation/exam.py`) | **28.4%** (random 25%, GPT-2 124M ~29–31%) |
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

**Status (Oct 2):** pretraining is running on a rented RTX 5090 (since step 6,054; 6.9 s/step), done ~Oct 3.
Latest: step 18,000, mini-exam 39.4%, best val loss 2.636 (step 17,500); full test 31.7% at step 15,000.
Earlier (PC in the afternoon, a rented RTX 3090 overnight): step 2,000:
val loss 3.426 and **HellaSwag 33.4%** (500-question mini-exam), already above v2's final 28.4% at 4% of
the training. Step 4,000: val 2.900 and **HellaSwag 35.6%**, ahead of the forecast: v3's final forecast
rises from 37–42% to ~40–45%, v3.5's from 45–52% to ~49–55%, and v4 (v3.5 trained longer) ~51–58%.
**Correction (step 15,000):** those mini-exam scores use the FIRST 500 questions, which are ~5 points
easier than the whole test. The full test (all 10,042) gave **31.7%** at step 15,000 (37% on the first
500), against v2's full-test 28.4%. Forecasts on the full test: **v3 ~34–38%, v3.5 ~44–51%** (1.12B, 40B
tokens with everyday web), **v4 ~46–54%**. From now on versions are compared on the full test only.
Two more exams (steps 6,000 and 8,000) confirm or undo this. Built while it trains and waiting for the finished model: chat lessons with memory and
reply suggestions, NEFTune, checkpoint averaging, DPO with rule-checked pairs (`data_prep/make_dpo_pairs.py`,
`training/dpo.py`), `evaluation/compare.py` (the release gate against v2), the context meter, long-context tools for v3-long,
and an off-machine checkpoint backup (`training/hub_backup.py`). Next after pretraining: average → chat-tune →
DPO → compare.

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
| **Web search (online mode, optional)** | `tools/generate.py --web`: our code searches the web for each message; the model answers from the results, naming the site and date. ~1,500 chat lessons (`data_prep/web_lessons.py`) plus honest answers about other AIs | v2 made up "metrics for Claude" and claimed "ChatGPT is better than Claude". See [Web search, version by version](#web-search-version-by-version) |

**Tools starting in v3:** keyword search for lookups (FAISS as an upgrade), a local teacher model
that writes the lookup and "I don't know" examples (DPO pairs are scored by checkable rules instead of
the teacher, so no grader has to be trusted), standard AI exams
(lm-evaluation-harness), TensorBoard graphs, and optionally the 8-bit optimizer. See
[Tools by version](#tools-by-version).

**Built into v3's pretraining (ready):**
- **Reserved special tokens** for lookups, tools, system prompts and 20 spares, so the tokenizer never changes later
- **Decontamination:** training documents containing HellaSwag or GSM8K test questions are skipped
- **"Study the best material last":** a steady learning rate, then a fade over the last 10% of steps
  while reading a higher-quality anneal set (top-rated web pages, Wikipedia, math)
- **Longer-memory ready:** RoPE setting 500,000, so stretching to 8k tokens later is easier
- **Mini-exam** (HellaSwag, 500 questions) every 2,000 steps, plus `evaluation/exam.py` for the full test
- **metrics.csv + TensorBoard graphs**, **torch.compile** speed-up (automatic fallback),
  **`--backup_dir`** copies of `latest.pt`, and **`--hub_backup`**: a copy OFF the machine (a private
  Hugging Face repo) every 30 min-2 h, after a rented host went offline mid-run
- **Phone alerts** (`--notify`), **snapshots during the fade** for checkpoint averaging, and PC/cloud
  handoff (`training/handoff.py`)
- A `--pilot` option (speed, memory and finish-time report) and optional gradient checkpointing

**Ready for later features without retraining:** the 20 spare special tokens are planned for thinking
(start and end) and the three effort levels, so v3 can learn to think in a fine-tune. See
[Thinking, effort levels and analytical steps](#thinking-effort-levels-and-analytical-steps).

Details and commands: [V3.md](V3.md).

### Web search, version by version

No AI goes online by itself, not even ChatGPT or Claude: the app searches, the model reads what comes
back. v3 starts simple, and every version gets better at it. Off by default (private and offline); when
it's on, only the question is sent to the search service.

| Version | Who decides to search | What the model learns | Lessons | Test |
|---|---|---|---|---|
| **v3** | Our code, for every message (`--web`) | Answer from the results, name the site and date; newest result wins; say when sources disagree or don't answer it; honest about other AIs | ~1,500 web + 400 other-AI (`data_prep/web_lessons.py`) | `eval/web.jsonl` |
| **v3.5** | Our code | The same, with twice the practice; reads longer, messier pages (its 32K memory fits whole pages) | ~3,000 (`WEB_LESSONS`) | same sheet, should score higher |
| **v4** | **The model**: it writes a `search` tool call only when a question needs fresh facts, and can search again with better words | When to search, rewriting a query, a second round when the first results are thin | + tool-call lessons | + "should it have searched?" checks |
| **v5** | The model | Combines several sources into one answer, notices a site that contradicts the others, prefers trusted sites | + multi-source lessons | + harder disagreement cases |
| **v6+** | The model | Research mode: several rounds, reading many pages, a short report with sources | | |

Sources: Wikipedia's free search (no key), or Brave Search's API for the whole web (free tier, a key in
`BRAVE_API_KEY`). Trusted sites (encyclopedias, .gov/.edu, science, big news agencies) go first, and
blocked sites are skipped, because a small model believes whatever it reads.

---

## v3.5: ~1.12B, 40B tokens (2× RTX 5090, or started at home)

Goal: the biggest brain that runs well on a phone, reading as much as a few weeks of rented GPUs allow.
**Final plan (Oct 2026):** 24 layers (1.12B, up from 1.04B), 40B tokens (up from 30B) with everyday web
pages added on top of the educational ones, more code and math, no TinyStories. Step by step: [V3_5.md](V3_5.md).

| | |
|---|---|
| Size | **1.124B** parameters: 2048 wide × 24 layers, feed-forward 5,632, grouped-query attention (4 key/value heads), 32k vocabulary. All sizes are multiples of 256, so the phone's Q4 format works |
| Reading | **40B tokens** (~36 per parameter) + a 4.1B-token final-phase set; ~88 GB on disk (~170 GB free while building) |
| Steps | **75,000** at 262,144 tokens each (~19.7B tokens, 8K context; trimmed from the 152,600 / 40B plan, Oct 2026); the fade starts at step 67,500 |
| Time / cost | **2× RTX 5090: ~18–19 days at the full 152,600 steps, ~$385–420** (about 10–11 s/step; the pilot gives the real number). Muon's saving can be spent on speed instead: trimmed to ~115,000 steps (~30B tokens) it is ~14 days and ~$300, at the quality of a longer AdamW run. Choose ~250 GB of disk when renting |
| Optimizer | **Muon**, in two forms with interchangeable saved state: `muon_cpu` at home (memory in RAM, fits the 4070's 12 GB) and `muon` in the cloud (memory on the GPU). A run can start at home and finish on rented GPUs; mixing Muon with AdamW is refused |
| Phone file | ~700 MB (Q4) or ~1.2 GB (Q8) |
| Features | Everything from v3 (lookups, web search, "I don't know", corrections, memory, preference training) |
| **Code** | **Several languages** instead of Python only (see below) |

**Why 40B tokens and everyday web:** v3's full-test HellaSwag (31.7% at step 15,000, 37% on the first 500
questions only) showed the educational-only mix is strong on knowledge but weaker on everyday "what
happens next" sense. Everyday pages (DCLM) are **added** rather than swapped in, so the ~19B educational
tokens stay. A cheap A/B (v3plus vs v3plus-edu, ~$9 each) checks the idea before the big run.

**Why 1.12B and not 1.2B+:** 24 layers still fits the 4070 (the backup if the rental ends) and leaves
room in a 29-day rental; 1.2B+ might not fit at home. Deeper rather than wider (research on small
models favours depth), so phone speed drops only ~8%.

### v3.5's data (~44B tokens to prepare)

**Main reading: 40B tokens**

| Share | Tokens | Source | Notes |
|---|---|---|---|
| 47.5% | 19.0B | Educational web pages (FineWeb-Edu `sample-100BT`) | The same amount as the 30B plan; no page read twice |
| 17.5% | 7.0B | **Everyday web (DCLM-baseline)** | How-tos, forums, reviews, news, filtered for quality |
| 11.25% | 4.5B | Wikipedia | About one full read of English Wikipedia |
| 12.5% | 5.0B | Code, 9 languages (The Stack) | Python first, then JavaScript/HTML/CSS, SQL, Java, C#, shell, PowerShell |
| 7.5% | 3.0B | Math (FineMath 4+) | Step-by-step math |
| 3.75% | 1.5B | Textbook-style text (Cosmopedia v2) | Written by the open Mixtral model, not ChatGPT/Claude/Gemini |

**Final phase: 4.1B tokens** (read during the last 10% of steps): 35% top-rated FineWeb-Edu pages,
10% DCLM, 20% Wikipedia, 12% math, 13% code, 5% Cosmopedia, **5% human-written Q&A (Stack Exchange,
best answer)**, so the model reaches chat training already used to "question → helpful answer".

**No TinyStories from v3.5 on:** they were written by GPT-3.5/4, and this project never trains on
ChatGPT/Claude/Gemini output. Stories in the chat lessons now come from Cosmopedia.

**Preparing it:** ~44B tokens, about **5–8 hours** at v3's measured speed. Test questions are removed
as in v3. Keep one tokenizer for every machine (home and cloud) so the data matches.

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
- `v3.5` entry in `core/config.py` (1.124B parameters, 152,600 steps, `python training/train.py --version v3.5 --cloud --pilot`)
- `core/offload_optim.py`: optimizer in system RAM (`optimizer="adamw_cpu"`); gives the same numbers as normal AdamW and resumes correctly
- **Cloud mode** (`training/train.py --cloud`, `cloud_train` in `core/config.py`): on rented 32 GB cards (planned: **2x RTX 5090, ~2-2.5
  weeks, ~$280-360**) the 12 GB workarounds come off (optimizer on the GPU, no gradient checkpointing, micro-batch 2 x 64,
  saves every 150 steps). Same steps and results, so one run moves between home and cloud at any step. See [V3_5.md](V3_5.md)
- `checkpoint_every` setting: protect every block (1) or every 2nd block (2) with gradient checkpointing
- `optimizer="adamw8bit"` (bitsandbytes) as a fallback (untested here)

- **Data prep for v3.5** (`python data_prep/prepare_web_data.py --version v3.5`): the bigger FineWeb-Edu slice
  (`sample-100BT`, main and score 4-5 anneal versions) and `code_multi`: Python 49%, JavaScript 14%,
  HTML 5%, CSS 4%, Java 7%, C# 6%, SQL 8%, shell 5%, PowerShell 2% from The Stack, mixed by character
  share so the tokenizer sees every language, and skipping minified/generated files. Tested end to end
  with fake sources (Hugging Face isn't reachable from where I build); **not** tested against the real
  datasets. The Stack needs a free Hugging Face account: accept its terms once and run
  `hf auth login` (older versions: `huggingface-cli login`).

**Still to build:** the pilot runs on your PC, and checking the real dataset names and speeds on the first
`--test` run (`python data_prep/prepare_web_data.py --version v3.5 --test`, 20M tokens, minutes).

**Code needed** (added when we get there):
- **CPU offload for the optimizer** (and the 8-bit optimizer, bitsandbytes, as a fallback), **plus gradient checkpointing** (all layers, or every other layer for about half the time cost): together they bring GPU memory to ~10–11 GB
- **Gradient checkpointing**: saves working memory for ~30% more time
- **Micro-batches of 1–2 sequences** with more gradient accumulation (same results)
- **Bigger data prep**: the same resumable streaming with the bigger FineWeb-Edu slice and the
  multi-language code source
- **Step-by-step math in the chat data**: the teacher model writes worked word problems (GSM8K
  style) for fine-tuning. Keep the real GSM8K questions for testing only, so the test stays fair.
- **Mandatory pilot runs**: at 1.12B, to confirm memory, speed and falling loss

**While it trains:** the GPU is busy, so this is the time to *write* v4's code (the coding
harness, router, website) and test it on small models (and on v3). **Keep `pre_decay.pt`** (saved at
step 103,500, before the fade): v4's brain continues from it.

**Checkpoints:** keep `latest.pt` backed up (`--backup_dir`). A five-month run is worth protecting.
---

## v4: Abilities

Goal: turn the model into a **personal assistant** with specialist skills, on a **better-read brain**.

### v4's brain: v3.5 trained longer

> **Starting settings (steps, learning rate, exam, snapshots, chat tuning, sampling)** for this version: see [VERSIONS.md, Settings carried forward](VERSIONS.md#settings-carried-forward-by-version). What changed after v3 and why: [LESSONS.md](LESSONS.md).

v4 doesn't start a new brain. It **continues v3.5** from `pre_decay.pt` (the copy saved just before
v3.5's fade), reads more at the steady learning rate, then fades again on a new anneal set. Same trick
as "v3+" would be for v3.

| | v3.5 | v4 |
|---|---|---|
| Size, phone speed, download | 1.12B, ~700 MB (Q4) | **the same** |
| Reading | 40B tokens (~36 per parameter) | **+15B or +30B more** (~49–62 per parameter) |
| HellaSwag forecast (full test) | ~44–51% | **~46–54%** (+1–2 points for +15B, +2–3 for +30B) |
| Where / how long | 2× RTX 5090 with Muon, ~18–19 days | Rented GPUs with Muon (it continues with v3.5's optimizer, `muon` or `muon_cpu`): roughly **+40–75% of v3.5's time** for +15–30B |
| Cost | ~$110–270 electricity | ~$55–270 electricity |

**Why this way:** v4's abilities are mostly *code* (app, router, tools, voice), and the GPU would sit idle
while that's written. Instead, the PC trains v4's brain in the background:

```
v3.5 run ── pre_decay.pt ── fade ── ships as v3.5 (the app and skill packs are built and tested on it)
               │
               └── v4 brain: continue +15–30B tokens ── new fade ── skill packs, thinking and tools
                                                                    retrained on it (days) ── v4 ships
```

- **Mini-exam: the full HellaSwag test** (all 10,042 questions, `exam_questions=0`), so every check is
  as accurate as the final one (about ±0.5 points; v3 used 500 questions, v3.5 uses 5,000). Set it in
  v4's config entry when the continuation run is added.
- **Data:** new pages, never repeated: more of FineWeb-Edu's `sample-100BT` than v3.5 read, more code
  and math, plus a few percent of **skill-aware text** (tool calls, thinking steps, code with tests), so
  the skill packs start from a base that already knows those formats. A second pass over v3.5's data is
  the fallback. `data_prep/prepare_web_data.py` will need a way to skip what v3.5 already read (to build).
- **How much:** +15B or +30B is decided once v3.5's scores are in.
- **Gate:** v4's brain must beat v3.5 in `evaluation/compare.py` before the skill packs move to it.
- **Code needed** (small): a `v4` entry in `core/config.py` with `init_from` = v3.5's `pre_decay.pt`, the new
  step total and fade point, and the new data folder.
- **Not chosen (for now):** growing v3.5 deeper (`core/grow.py`, 22 → 32 layers, ~1.5B) would add ~4–6 points
  but doesn't fit in the 4070's 12 GB (cloud only, ~$400–600) and is ~1.45× slower on phones. It stays
  an option for a later PC/online model; `training/growth_test.py` measures what growth saves first.

### Specialists (skill packs + router)

```
                        ┌─► Study helper    (explains school topics)          Beta on v3
                        ├─► Teacher assistant (worksheets, lesson plans, PDFs)  Beta on v3
                        ├─► Story writer    (the v1 skill)
You ─► Router ─► Base ──┼─► IT helper       (printers, networks, troubleshooting)
      (picks)   model   ├─► Fact checker    (looks things up, cites sources)
                        ├─► Document helper (summarizes, rewrites, drafts, makes to-do lists)
                        └─► Coding helper   (works in a loop, small tasks)
```

- **More skill ideas (planned, to look at later):** writing coach, planner (with reminders), recipe and
  meal helper, budget helper, language tutor, resume and job helper, kids' mode. Which come first follows
  what Beta testers ask for. See [SKILLS.md](SKILLS.md).
- **Save as PDF or Word (built, `app/export_doc.py`):** any answer, and above all the Teacher assistant's
  worksheets, saves as a printable PDF (answer key on its own page) or an editable Word file; the app
  gets a Download / Print button.
- **One base model** (v4's brain: v3.5 trained longer; v3.5 or v3 until it's ready) holds general language and knowledge.
- **Skill packs (LoRA adapters):** small add-ons (~19-25 MB each), trained in under an hour
  each. Adding one never breaks the others. llama.cpp supports them. **Built as a Beta:** the Study
  helper, a keyword router (`tools/generate.py --skill auto`) and an access toggle (everyone / beta testers / off),
  tested on v3 first; see [SKILLS.md](SKILLS.md).
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
- **Personal memory:** saved notes about you that it looks up in later chats. **Prototype built
  early (`app/chat_memory.py`, `tools/generate.py --chat --memory`):** past chats and facts you save
  (`remember: ...`) are kept on your computer and searched like the Wikipedia lookup; the best
  matches reach the model as notes ("Earlier chat (Sep 29)", "Saved memory"), a format v3 is already
  trained on. `memories` / `forget <n>` / `forget everything` / `--private`.
  **Saving on its own (in v3's chat lessons):** when you say something worth keeping ("my name is
  Sam"), the model writes a `remember` tool call before its reply; the chat saves it and shows
  "(saved to memory: ...)". It is taught not to save passwords, card numbers, moods or other people's
  business, and to answer "what's my name?" from saved memories or say it doesn't know yet.
  **Search by meaning:** a small embedding model (all-MiniLM-L6-v2, Apache-2.0, CPU) finds "my cat"
  when you ask about "my pet"; combined with keyword search. `pip install sentence-transformers`
  to turn it on. Still to do: the app's memory screen (v4).

### Agentic coding (a coding helper that works in a loop)

> **VryxCode (planned):** this coding helper becomes its own part of Emvryx, **VryxCode**, offered only on **Equinox 2 (small tasks), Solstice 2 and Apogee 2**, not on Ember or Flare. Plan, stages and what exists: [VRYXCODE.md](VRYXCODE.md).

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
| 1 | ✅ **Built and tested (`coding/harness.py`):** read file, edit file, run command, run tests, all inside a **sandbox** (a temporary folder, no internet, time and memory limits, nothing outside it can be touched) | While v3.5 trains (CPU work) |
| 1b | ✅ **Built and tested (Oct 2026): the "Claude Code"-style extras around the loop** (all plain code in `coding/harness.py`): `git` (safe subset: status, diff, log, add, commit, branch, worktrees; no push, no config flags), `diagnostics` (syntax errors; more with pyflakes: our stand-in for LSP), **project notes** (EMVRYX.md / AGENTS.md shown at the start), **hooks** (`.emvryx/hooks.json`: after an edit, before a command, and a **finish gate**: the tests must pass before it may stop), **permissions** (allow / ask / deny; `git commit` asks first), **compaction** (old steps folded into an "Earlier steps" list when the 2,048-token memory fills) and a **tool registry** (`register_tool`: where MCP tools plug in; the MCP client itself is not built) | Done |
| 1c | ✅ **Practice data made by our own code (`coding/agent_tasks.py`, `coding/agent_lessons.py`, `coding/make_agent_data.py`):** tiny projects with a bug, solved by a scripted solver through the REAL harness; only runs whose tests pass are kept. Chat lessons: `tool_use` (incl. diagnostics-first and retry after a wrong fix), `project_context`, `ask_first` (and "refused: say so, don't retry"), `too_big` ("that's too big; start with one file") and `compaction`. v3.5 gets 2,500 of them (`AGENT_LESSONS`); its final-phase reading also has real commit data (`commits`, CommitPackFT Python, permissive licenses) and the practice runs as text (`agent_traces`, 0.2%) | Done; v3.5 trains on them |
| 2 | **Training data (v4):** a coding-focused open teacher (e.g. an outside coding model, license to be checked) works through small coding tasks in the harness. Keep only runs where the **tests really pass** (checked by running them) | After v3.5 |
| 3 | **Fine-tune** a "coding" skill pack (LoRA) on those runs | v4 |
| 4 | **Measure** on a small test set of real tasks (fix this bug, add this function) | v4 |

**What to expect at each size:**

| Model | What it can do |
|---|---|
| v3 (394M) | Autocomplete only, no agent work |
| v3.5 / v4 (~1.12B) | Small, simple tasks: fix an obvious bug in one short file, write a small function, run a command and read the result |
| v5 (3B) | Small multi-step jobs: a few files, a couple of retries |
| v6.5 (7B) | Real everyday scripting help |

v3.5 only gets a taste of this (a few thousand lessons on templated one-bug tasks), enough to learn the format, to ask before
committing and to say "too big". Real multi-file work waits for v4's teacher-made runs and longer memory.

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
fine-tune where the teacher (the open base) solves math problems that come with known answers, keeping only
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
One app and one website that work offline and online. The design and decisions are in [APP.md](APP.md) and
[APP_SPEC.md](APP_SPEC.md); the model list, failure handling and downloads are built and tested. See
[Offline and online](#offline-and-online-the-goal-for-the-app-and-website) and
[Using your AI](#using-your-ai-apps) below.

**Reply suggestions (already in v3's chat lessons):** after each answer, the model guesses what you
might ask next and the app shows it greyed out in the message box (Tab or Enter to use it; never sent
on its own). v3 learns it from the user's follow-ups in everyday chats (weight 0.3), and
`tools/generate.py --chat --suggest` shows it in the terminal. If v3's suggestions are too plain, v3.5/v4
can add teacher-written follow-up questions.

**Skill pack access (built):** each pack has a switch (everyone / beta testers / off) in
`data/skills_access.json`, and `skills.can_use()` decides per user. The app will show a toggle only for the
packs an account may use, so Beta packs go to chosen testers first. See [SKILLS.md](SKILLS.md#who-can-use-a-pack-the-access-toggle).

---

## v5: Scale (3B)

> **Starting settings (steps, learning rate, exam, snapshots, chat tuning, sampling)** for this version: see [VERSIONS.md, Settings carried forward](VERSIONS.md#settings-carried-forward-by-version). What changed after v3 and why: [LESSONS.md](LESSONS.md).

Three routes:

| Route | How | Time | Cost |
|---|---|---|---|
| **From scratch** | Rent cloud GPUs. The cheapest route: Vast.ai (or similar) interruptible GPUs, since `training/train.py` already resumes after interruptions. v3.5's 1B run at home is the rehearsal | ~4–7 days on 8 rented GPUs (longer on fewer) | ~$800–2,500 depending on GPU and pricing |
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
resume later (`training/train.py` already does this). The catch: a 3B checkpoint is ~35–40 GB with the
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

> **Starting settings (steps, learning rate, exam, snapshots, chat tuning, sampling)** for this version: see [VERSIONS.md, Settings carried forward](VERSIONS.md#settings-carried-forward-by-version). What changed after v3 and why: [LESSONS.md](LESSONS.md).

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
  `training/growth_test.py` measures how much this really saves (v2's 12 layers grown to 24, against a 24-layer model
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
better without training the small ones from scratch. The open teacher stays until Max replaces it.

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

| Tier class | Model name | Size | Versions |
|---|---|---|---|
| Lite (fast and light) | **Emvryx Flare 2** (from scratch), then **Emvryx Flare 2.5** (open base) | ~400M, then ~1.5B | v3, then v3.5 |
| Everyday | **Emvryx Equinox 2** | ~4B (the 4B open base, suggested) | with skill packs, the router, tools, thinking, effort levels and the app |
| Balanced | **Emvryx Solstice 2** | ~8B (the 8B open base, suggested) | one rented RTX 5090 to fine-tune |
| Most capable | **Emvryx Apogee 2** | ~14B (the 14B open base, suggested) | 4-bit fine-tune on a rented RTX 5090 |
| Top | A bigger Apogee | 30B class | chosen when it is time (see [Beyond v6.5](#beyond-v65-v7-v8-and-max)) |

(The text from here to the end of this section describes the old from-scratch plan, where v4 (Equinox 2) was Flare 2.5's brain **trained longer**
(15–30B more tokens, including some "skill-aware" text with tool calls, thinking steps and code with tests,
so the skill packs start from a base that already knows those formats), plus the abilities.)
See [v4's brain](#v4s-brain-v35-trained-longer).

**Names (working names):** the umbrella is **Emvryx** (the app, Emvryx.AI, and the whole model family). Each model adds one of
**five role names**, taken from the sky's calendar, and a generation number.

**How the names work:** five names make up the lineup, the way other AI families have a small, a middle and
a big model. **Emvryx Ember** is the lowest (the small first assistant: v2, 88M, runs on almost any device), then **Emvryx Flare** (fast and light), **Emvryx Equinox** (balanced everyday), **Emvryx Solstice**
(stronger, for a PC or online mode) and **Emvryx Apogee** (most capable). **Each name has its own version number**, and a
number only goes up when *that* model is updated, so the numbers differ from name to name (for example Flare 2.5, Equinox 2,
Solstice 2 and Apogee 2 at the same time). When a model is updated, the new one takes the main spot in the app's picker and
the old one moves to "Other models" (still downloadable). The numbers follow the project's version numbers (v3, v3.5, v4, ...):
a model is numbered by the project version it was built in, and a model can also get a refresh between versions
(Flare 2.5 -> Flare 2.6). **Generations (Oct 2026):** generation 1 models were trained from scratch (Ember 2, Flare 2); generation 2, the 2.x series, is built on open bases (Flare 2.5, Equinox 2, Solstice 2, Apogee 2). A newer generation takes the main spot in the picker. A number *before* the name ("Emvryx 2 Flare") is kept for a full reset
of the whole family (a new tokenizer or design, so old files and skill packs don't carry over), if that ever happens.

| Lineup in the picker | Emvryx Ember | Emvryx Flare | Emvryx Equinox | Emvryx Solstice | Emvryx Apogee |
|---|---|---|---|---|---|
| Now (Oct 2026) | 2 (beta) | 3 (3.5 about to train) | – | – | – |
| After v3.5 | 2 | 3.5 (3 moves to Other models) | – | – | – |
| After v4 | 2 | 3.5 | 4 | – | – |
| After v5 | 2 | 3.5 | 4 | 5 | – |
| After v6.5 | 2 | 3.5 | 4 | 5 | 6.5 (6 moves to Other models) |
| After v7 (13B) | 2 | 3.5 | 4 | 5 | 7 |
| A later new small model | 7 (3.5 moves to Other models) | 4 | 5 | 7 |

**Numbers for "+" and grown models.** Between the big steps a name can have variants, and the decimal says what happened:

| Number | Meaning | Example (Flare) |
|---|---|---|
| **A whole number** | A big step: trained from scratch, or a new size or new abilities | Flare 2, then Flare 5 (a fresh retrain at a new size) |
| **.1, .2, ...** | A **"+" model**: the same weights read more (like v3+, continuing from `pre_decay.pt`), same size | Flare 3.1 (v3 + more reading) |
| **.5** | The half-step slot: Flare 2.5 is the v3.5 slot built on an open base. A "+" refresh of an open-base model takes the next decimal (more lessons, DPO, skill packs) | Flare 2.5, then Flare 2.6 |
| **Next whole number + .1** | A **grown model** (`core/grow.py` adds layers, so the size changes), started from the earlier weights | Flare 4.1 (Flare 2 grown deeper); its own "+" steps are 4.2, 4.5, ... |

**On an open base (Oct 2026):** a "+" model is the same open base with better or more lessons, DPO or skill packs (a few dollars, hours; see [OPEN_MODEL.md](OPEN_MODEL.md#upgrades--and-growth-on-an-open-base)). A grown model copies layers of the open base and needs real continued training, so it is expensive and only worth it when no open model of the size you want exists.

Growth only adds layers (same width and tokenizer), so a grown Flare is a deeper Flare, never an Equinox. Every new number
is a new set of weights, so its skill packs are retrained (a pack only fits the exact model it was trained on). The app's picker
shows the newest of each name and keeps the rest under "Other models".

They are placeholders: **no trademark check has been done beyond web searches (Oct 2026)**, so search each name (and its domain)
before a public launch, and rename if there is a conflict. A first set (Nova, Pulsar, Quasar, Supernova) was dropped because each
is already the name of a known AI model (Amazon Nova, Ambient.ai's Pulsar, Quasar Alpha and Quasar 438B, Arcee SuperNova); the
words kept are only used by niche AI tools. Earlier Norse working names: Rune = Flare, Skald = Equinox, Saga = Solstice,
Edda = Apogee. In this document, the tier names map as: Lite = Flare, Standard = Equinox, Pro = Solstice and Apogee,
Max = the largest Apogee.

## To discuss tomorrow: moving the model names up a size (Oct 7, 2026, the owner's idea, not decided)
Today: Flare 2.5 = the 1.5B open base, Equinox 2 = the 4B open base, Solstice 2 = the 8B open base, Apogee 2 = the 14B open base (training).
The idea, as the owner put it: "make 2.5 for Flare what Equinox is, make Equinox 2 what Solstice is, and make Solstice 3.5 4B." Clarified Oct 7: "Solstice 3.5" = a model on the new **a newer 4B open base** base, to be tried (a pilot first: it must really beat the 8B, or the top-tier name would mislead;
check that our trainer and llama.cpp support the a newer open generation design). The relabelling of Flare and Equinox does not depend on it and can be done first. Notes so far:
* Why it makes sense: the 1.5B Flare is weak at facts (it cannot name a famous person without a note); the 4B Equinox answered the same question well; the 8B and 14B are better again.
* Cheapest way: relabel the models that already exist (no retraining): current Equinox 2 weights become the new Flare, current Solstice 2 weights the new Equinox. The 1.5B would be retired or kept as a small "other model".
* Things to do if we go ahead: new model ids and versions (do not reuse "Flare 2.5" for different weights; saved chats store the model id), `models.json` sizes, `min_ram_gb`, `cost_weight` and plan tiers (free would then get a 4B/8B: check the server cost),
  tagline texts, About/Models pages, benchmark tables (numbers belong to the weights, not the name), the family guide, and the `lookup` policy flags.
* Where Apogee (14B, training now) and a a newer open generation model fit in the new ladder is still open.

## To discuss: lessons made for the open base, not for Flare 2 (Oct 7, 2026, the owner's decision to pursue)
Flare 2.5, Equinox 2, Solstice 2 and Apogee 2 were all trained on `data/v3/chat.jsonl`, which `data_prep/make_chat_data_v3.py` built to fix the mistakes of the tiny from-scratch v2 model (answer from notes, "I don't know" when the notes are
silent, doubt when corrected, "unknowable" questions). the open base already knows far more and answers well, so those lessons made it over-trust a wrong note and hedge. The owner wants Apogee (and the next models) trained on their own,
open-base lessons instead. Notes so far:
* Apogee 2 has already been trained (1,266 steps, about 16 h, about $8) on the v3 lessons; a retrain on new lessons is a new run. Keep that run as the baseline and compare.
* A open-base set can be much smaller: the adapter only has to teach Emvryx's identity and manners, not knowledge. About 300 steps on the 14B would be about 4 h (about $2), against 16 h.
* Candidate contents: identity (what Emvryx is, who made it, the base credit), everyday chat and instruction following (open data, licences checked), exact formats and counts, using a note only when it matches the question
  and ignoring one that does not, saying "I'm not sure" only for things that really cannot be known (live, personal, made-up) and answering famous facts plainly, plus agent runs for VryxCode (collected from the coder model).
* Drop the from-scratch lessons: `dont_know` for things the model does know, `memory_doubt`, and the "answer only from the notes" lesson. The app already looks things up only for recent questions or when the model is unsure.

## Model tiers (Lite, Standard, Pro, Max)

Like the big labs' model families, tiers are **the same family at different sizes**: the same
reading mix, chat lessons, personality and features, but different sizes, so you can pick
speed or smarts.

| Tier | Size | Runs on | Good for | Arrives |
|---|---|---|---|---|
| **Lite = Emvryx Flare** (Flare 2, Flare 2.5) | ~400M (Flare 2), ~1.5B (Flare 2.5) | Any phone, offline, fast | Quick questions, small talk, simple lookups | v3, v3.5 |
| **Standard = Emvryx Equinox** (4) | ~1.12B (v4) | Phones and PCs | Everyday use: lookups, explanations, advice, skills and tools | v4 |
| **Pro = Emvryx Solstice, Emvryx Apogee** (Solstice 2, Apogee 2) | ~8B and ~14B | PC or a server (the app's online mode) | Harder questions, coding, long writing | 2.x |
| **Max = a bigger Emvryx Apogee** (later) | 13B, later ~30B ("upper small", then "medium"; see [Beyond v6.5](#beyond-v65-v7-v8-and-max)) | A server, or a PC with a 24 GB GPU for 13B; online mode | The hardest questions: deep reasoning, real coding help, long documents. Also the teacher for every smaller tier | After v6.5, if funded |

The names are working names (see above).

**How they're made:**
- **Same recipe for every tier:** same tokenizer, data mix and chat lessons, so they behave alike
  and differ mainly in how much they know and how well they reason.
- **The big tier teaches the small ones:** once v3.5's 1B exists, it becomes the teacher for Lite
  (instead of the open base). Small models trained this way get noticeably smarter for their size, and there
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

Every model is exported as a **GGUF** file (`tools/to_gguf.py`). That one format already works with
**llama.cpp, Ollama, LM Studio, llamafile** (one double-clickable file) and, in a browser, **wllama**
(llama.cpp compiled to WebAssembly). So nothing extra needs building per platform. We are *not*
planning an ONNX/WebLLM version: it would mean a second conversion path for little gain.

| Size | Realistic targets | Not realistic |
|---|---|---|
| v1-v2 (30-88M) | Phones, PCs, browsers | Microcontrollers (an ESP32 has ~0.5 MB of RAM, the file alone is 20+ MB) and smartwatches |
| v3-v4 (0.4-1.12B) | Phones, PCs, browsers, Raspberry Pi 5 (a few words per second), old laptops | Pi Zero / Pico |
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
The detailed design (modes, screens, how the Python features plug in, build order): [APP.md](APP.md).

**The trick: build the app once.** Write the chat screen and the "brain around the model" (chat
format, lookups, notes, tools, effort levels) in **one web codebase (TypeScript/JavaScript)**, then
package it several ways:

| Where | How it's packaged | Model runs with |
|---|---|---|
| Website (any browser) | The site itself. Also **installable as an app** (a "PWA": works offline once the model file is cached) | wllama (llama.cpp in the browser) for small models; a server for bigger ones |
| Android | Wrapped with **Capacitor** (same web code in an app shell) | llama.cpp through a native plugin |
| Windows / Mac PC | Wrapped with **Tauri** (small) or Electron | llama.cpp (`llama-server`) or wllama |
| iPhone | Same Capacitor wrapper; needs a Mac + Xcode ($99/year to keep installed) | llama.cpp |

**Same files everywhere:** one `.gguf` per model size, exactly what `tools/to_gguf.py` already makes. The
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

### Hosting the online server (to revisit)

"Online" in the app means **where the model runs** (a computer that is not the phone), not "searches the web". Web search is a
separate switch. A domain (emvryx.ai) is only a name that points at a server; something still has to run the model. A Cloudflare
tunnel gives a home PC a stable name (for example `chat.emvryx.ai`) without opening ports.

Decided for now: **the home PC through a tunnel**, for you and a small test group. When it should keep working while the PC is
off, rent a machine by the month. Prices below are listed prices found in a web search (Oct 2026), not verified on the
providers' own pages; check them before paying. A 1B model in Q4 (~700 MB) needs far less than any of these GPUs.

| Option | Example | Roughly | Notes |
|---|---|---|---|
| CPU VPS | Contabo (4 vCPU, 8 GB), Hetzner CPX31 | ~$7 / ~$16 a month | Cheapest always-on; about 10-20 words a second, fine for testers |
| Small GPU, monthly | CloudClusters RTX 3060 Ti | ~$129 a month | Fast, always on |
| Mid GPU, monthly | GPUCloudHQ RTX 4090 / 5090; CloudClusters 4090 | ~$189 / ~$279 / ~$359 a month | GPUCloudHQ is far below others (DatabaseMart lists the 5090 at ~$479): read the terms |
| Dedicated, Europe | Hetzner GEX44 (RTX 4000, 20 GB); LeaderGPU | ~EUR 184-234 (+ setup fee); from EUR 249 | Billed until cancelled; no stop button |
| Pay per use | serverless GPU platforms | only when used | Cheapest while few use it; a slow first reply |

Things that differ from training on Vast: it must stay up (use on-demand, not interruptible machines), the IP can change (use the
tunnel), and disk is billed even when the machine is off. Move to a bigger GPU only when many people chat at once. The app code
does not change: it only points at a different address.

**The plan is both, not either/or.** Every model should be runnable at home *and* in the cloud, and reachable *privately*
(you and named testers) or *publicly* (anyone, with accounts and limits). Home first for private use, then a rented server
for always-on private access, then a public hosted version. Same files, same app; only the address and who may connect
change.

**Revisit when:** the test group needs it to work while the PC is off, or before any public launch. Then also: write the
server install steps (llama-server + tunnel), re-check prices, and decide CPU vs small GPU from measured speed.

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
