# Lessons 4 and the flagship plan (decided October 15, 2026)

**Goal:** lessons as thorough as the big labs' in the ways that matter (careful, checked, consistent answers and learning from comparisons), written
in one Emvryx voice to the [Emvryx Constitution](EMVRYX_CONSTITUTION.md), and a flagship, **Apogee 3**, that is clearly smarter than anything
Emvryx has had and still runs on the owner's RTX 4070 with a long window.

## The hardware rule
- **Chat runs on the RTX 4070 (12 GB) only.** Every published model must fit there with a good window.
- **Training:** Flare 3 and Equinox 3 on the 4070; **Solstice 3 and Apogee 3 on an RTX 5090 (32 GB)** when it is in the PC.
  (llama.cpp and PyTorch need CUDA 12.8 or newer builds for the 5090; a 1000 W power supply is recommended.)

## What is wrong with Lessons 3 (what we use now)
About 110,000 lessons, mostly made by scripts and templates, plus answers copied from open datasets; the NVIDIA general lessons were written by
DeepSeek and Qwen models, so the maths, science and code answers sound like them. Nothing is checked for correctness. The style check flags thousands
of problems (exclamation overload 3,774, too long 3,191, filler openers 1,965, "trained from scratch" 846 of the old from-scratch lessons).

| | Lessons 3 (now) | Lessons 4 |
|---|---|---|
| Answers | templates, scripts, copied | written fresh, judged against the Constitution, rewritten, best of several drafts |
| Correctness | not checked | code run against tests, maths verified exactly, facts checked against Wikipedia and the web notes |
| Voice | mixed (Emvryx, DeepSeek, Qwen, old datasets) | one Emvryx voice everywhere, including maths and code |
| Difficulty | mostly easy and medium | easy to hard, real multi-step problems |
| Reasoning | answers only | plus thinking lessons for hard problems (Deep) |
| Conversations | some, templated | real back-and-forth: follow-ups, corrections, topic changes, long chats |
| Tools | templated lookups | realistic search, calculator, memory and code use |
| Saying no | basic rules | judged by the Constitution's section 7 (helpful by default, decline only real harm, kindly) |
| Preference pairs (DPO) | none | 30,000 to 50,000 chosen/rejected pairs |
| Real use | none | reported and approved answers from the app become new lessons |
| Size | about 60,000 used | about 100,000 checked answers + 30,000 to 50,000 pairs |

## The lesson factory (built October 15, 2026: `data_prep/lesson_factory.py`)

```
llama-server -m Qwen3.6-27B-Q4_K_M.gguf -ngl 99 -c 32768 --parallel 8 --jinja --port 8099   # the teacher (on the 5090)
python data_prep/lesson_factory.py questions --per 40          # the teacher writes 40 questions per area and level (20 areas x 3 levels)
python data_prep/lesson_factory.py maths --n 3000              # exact maths with known answers
python data_prep/lesson_factory.py import FILE.jsonl --source NAME --area AREA   # questions from an open dataset (licence read first)
python data_prep/lesson_factory.py run --workers 8              # drafts, checks, judging, rewriting, pairs, thinking (resumes by itself)
python data_prep/lesson_factory.py review --n 30                # data\v4\review.md: a random sample for the owner to read
python data_prep/lesson_factory.py stats
```
Files in `data\v4\`: questions, lessons, pairs (DPO), thinking, rejected (with the reason) and review.md. The parts: `factory_questions.py` (the
20 areas, importers for GSM8K-, MBPP-, Alpaca- and chat-shaped files, de-duplication), `factory_checks.py` (the voice rules, known answers,
code that must parse and pass its tests, run in an isolated Python process with a time limit), `lesson_factory.py` (the steps below).
A lesson is kept only when every check passes and every Constitution score is at least 7 of 10 (average at least 8); a weaker draft that is
clearly worse becomes the "rejected" side of a pair. Tested with a scripted teacher (`tests/test_lesson_factory.py`).

### The steps
1. **Questions:** 50,000 to 100,000 across about 20 areas (maths, code in several languages, science, writing, advice, planning, everyday knowledge,
   multi-step tasks, tools, long chats, sensitive topics, "should it ask first?"), tagged easy, medium or hard. Questions may come from open datasets
   (their licences read by the owner); the answers are always made here.
2. **Drafts:** an open teacher model whose licence allows training on its output (**Qwen3.6 27B** on the 5090, Apache 2.0; decided Oct 16, newer and better at code than Qwen3.5 27B) writes several drafts,
   given the Constitution.
3. **Checks:** code is run against tests in the sandbox; numbers are recomputed exactly; facts are checked against Wikipedia and the web notes;
   anything that fails is fixed or dropped.
4. **Critique and rewrite:** each draft is judged against the Constitution (honesty, helpfulness, voice, safety) and rewritten until it passes.
5. **Pairs:** the best answer is "chosen", a weaker draft "rejected", for preference training (DPO).
6. **Thinking lessons:** for hard problems, the step-by-step reasoning is kept as a thinking lesson (only when the final answer checked out).
7. **Owner review:** a random sample each round, by hand; the factory's rules are fixed when the owner disagrees.
8. **From the app:** answers people reported (with a corrected answer) and approved become lessons and pairs.

**Never used:** answers from Claude or ChatGPT (both companies' terms forbid training another AI on their output), personal data, secrets.

**Time:** about 2 to 4 days of the 5090 to build the first set; reused for every later model.

## The flagship: Apogee 3, grown from Qwen3.5 9B
- **Grow:** add 10 to 12 new layers to the 9B (32 to about 44 layers, about **12B**). The new layers start as pass-throughs (the grown model starts
  exactly as good as the 9B, no dip), and only Qwen3.5's "fast" (linear-attention) kind is added, so the chat memory does not grow and **128K still
  fits the 4070** (about 10.5 GB with the chat memory in 8-bit).
- **Train (on the 5090):** the new layers fully, a major tune (high-rank LoRA) on the rest, on Lessons 4, then preference training (DPO).
- **Built (Oct 16): `training/grow_qwen.py`.** Each new layer is a copy of the fast layer before it with its two output weights set to zero, so the grown
  model answers exactly like the 9B before training (tested: difference 0.0). The new layers sit after fast layers spread over the middle, and llama.cpp
  reads the new layer pattern from config.json when converting. Training (`finetune_open.py --model apogee-3`) tunes every language layer, the fast
  layers' own projections included, at rank 64, and the new layers at rank 256 (fits a 24 GB card), or fully with `--grow_full` on a 40 GB+ card.
  ```
  python training/grow_qwen.py --base Qwen/Qwen3.5-9B --add 12 --out checkpoints/grown/apogee-3-base     # about 10 minutes, no graphics card needed
  python training/finetune_open.py --model apogee-3 --data data/v3/chat_3x.jsonl --pilot                  # memory and speed first
  python training/finetune_open.py --model apogee-3 --data data/v3/chat_3x.jsonl                          # then the real run (resumes by itself)
  python training/finetune_open.py --model apogee-3 --merge                                               # then convert with llama.cpp as usual
  ```
- **Checks before publishing:** the hard sheet, the everyday sheet, identity, honesty and safety, the long-memory check (32K, 64K, 128K) and the
  picture check. Published only if it beats Apogee 2.
- **Expected (hard sheet, out of 52):** Apogee 2 today 43; Apogee 3 **47 to 50**; about 50 tokens/sec on the 4070.
- **Risk:** growing with only the fast kind of layer is newer and less proven; the pilot and the long-memory check decide. Fallback: the normal layer
  rhythm at about 12B with a 64K window on the 4070.

## The family on Lessons 4
| Model | Base | Trained on | Tune | Expected hard sheet | Runs on the 4070 |
|---|---|---|---|---|---|
| Flare 3 | Qwen3.5 2B | 4070 (now, Lessons 3) | light | 30 to 33 | 128K |
| Equinox 3 | Qwen3.5 4B | 4070 (Lessons 3) | light | 40 to 43 | 128K |
| Solstice 3 | Qwen3.5 9B | 5090 | major, 16-bit | 43 to 46 | 128K |
| **Apogee 3 (flagship)** | **Qwen3.5 9B, grown to about 12B** | 5090 | new layers + major + DPO | **47 to 50** | 128K (8-bit chat memory) |
| Flare 3.1 / Equinox 3.1 | same bases | 4070 | light, on Lessons 4 | +1 to +2, one Emvryx voice | 128K |
| **VryxCode 3 (the one coding model)** | Apogee 3 | 5090 | coding tune on the teacher's checked builds + DPO | projects start to finish: 60 to 70% (v1: about 10 to 20%) | 128K |

**VryxCode 3** (decided Oct 16, 2026): one dedicated coding model instead of VryxCode on several chat models. Its lessons are whole projects the teacher (Qwen3.6 27B) builds in VryxCode's own long-build loop, kept only when hidden tests pass, plus bug hunts and preference pairs (`coding/project_factory.py`). Measured with the 15-project test (`coding/bench_projects.py`). Details: [VRYXCODE.md](VRYXCODE.md).

## The whole family: Lessons 4 for every model, then growing every model (decided Oct 16, 2026)
Every model gets Lessons 4 first (a **.1** version, same size), and later grows (a **.5** version, bigger). The four stay clearly spaced from fastest
to smartest, and every one still runs on the RTX 4070 with 128K (only "fast" layers are added, so the chat memory does not grow). All numbers are
estimates until each model's exam; a version is published only if it beats the one before it (hard sheet, everyday sheet, identity, safety).

### What Lessons 4 does for each model (no growth)
| Model | Today | With Lessons 4 (.1) | What gets better | Hard sheet |
|---|---|---|---|---|
| Flare 3.1 (2B) | Lessons 3 | 25,000 to 50,000 checked lessons, short answers weighted | one Emvryx voice; follows instructions and formats exactly; honest "I don't know"; fewer wrong numbers (maths checked) | 30-33 -> 31-35 |
| Equinox 3.1 (4B) | Lessons 3 | the same, plus the code and maths lessons | code that runs, maths with checked answers, longer chats without losing track, kinder refusals | 40-43 -> 41-45 |
| Solstice 3.1 (9B) | Lessons 3 (training now) | the same, plus thinking lessons and the first preference pairs | step-by-step reasoning on hard problems, documents and pictures explained better, calibrated confidence | 43-46 -> 45-47 |
| Apogee 3 (grown 12B) | - | trained on Lessons 4 from the start, then preference training | everything above, plus the hardest problems and Deep mode thinking | 46-48 |
| Apogee 3.1 | Apogee 3 | 50,000 lessons aimed at what Apogee 3 still misses, a second preference round | weak areas found by its exam, long conversations, tool use | 48-49 |

Small models gain most in voice, instruction-following and honesty (the parts that are about habits); big models gain most in reasoning and code
(the parts that need capacity). The checked answers help every model: a wrong number or code that does not run is never taught.

### Growing every model (.5)
| Model | Now -> grown | Speed on the 4070 (words/sec, rough) | What gets better | Hard sheet |
|---|---|---|---|---|
| Flare 3.5 | 2B -> about 3B | about 120 -> 100 | multi-step questions, planning, fewer slips; stays the fast Free-plan default, so the smallest growth | 33-36 |
| Equinox 3.5 | 4B -> about 6B | about 80 -> 65 | the biggest everyday upgrade: maths, code, long chats; close to today's Solstice | 43-46 |
| Solstice 3.5 | 9B -> about 11B | about 55 -> 45 | deep explanations, long documents, pictures; about where Apogee 3 starts, but faster | 46-49 |
| Apogee 3.5 | 12B -> about 14B | about 45 -> 38 | the hardest reasoning, Deep mode, expert questions; the most that fits the 4070 with 128K | 50-52 |
| VryxCode 3.5 | on Apogee 3.5 | - | bigger projects (10 to 20 files), fewer stuck loops, better at fixing its own failed tests | whole projects 70-80% |

### The rounds
| Round | Lessons 4 total | Trained | Where | Time, cost (rented 3090 at about $0.23/hr) |
|---|---|---|---|---|
| 1 | 25,000 | Apogee 3 (grow to 12B), Solstice 3.1 | rented | about 1 to 1.5 weeks, about $45 |
| VryxCode | + the teacher's builds | VryxCode 3 on Apogee 3 | rented | about 1 week, about $35 |
| 2 | 50,000 | Flare 3.1 and 3.5, Equinox 3.1 and 3.5, Apogee 3.1 | Flare on the 4070 (free), the rest rented | about 1.5 weeks, about $40 |
| 3 | 100,000 (Lessons 4.5, with the app's approved reports) | Solstice 3.5 (11B), Apogee 3.5 (14B), VryxCode 3.5 | rented (a 48 GB card or a 5090 for Apogee) | about 2 weeks, about $90 |

About 5 to 6 weeks and about $210 for the whole family. Why this order: the flagship first (it proves growing works before the rest), the small models
next (cheap; Flare trains at home), the biggest growths last (when the lessons are at their best). Risk: growing with only fast layers is newer; every
grown model has a pilot and the long-memory check (32K, 64K, 128K), and falls back to the normal layer rhythm with a 64K window if it fails.

## Using what Qwen3.5 does natively (decided Oct 16, 2026)
| Native feature | Status |
|---|---|
| Seeing pictures | built: the "eyes" step and the picture check |
| Long memory | built: 128K on the 4070, the long-memory check at 32K, 64K and 128K |
| Thinking mode | built: Deep mode uses it, the thinking check guards it |
| **Guess-ahead decoding (MTP)** | **built Oct 16:** a merged model now keeps the mtp.* head (transformers drops it; `finetune_open.restore_mtp` copies it back from the base, and the grown Apogee keeps it too). In the app a model with `"mtp": true` in models.json starts llama-server with `--spec-type draft-mtp`: the same answers, expected about 1.5 to 2 times faster on the 4070. If llama-server refuses the option or the file has no head, it loads the model without it. **To test** with Flare 3: words per second with and without, in the app |
| **Native tool calls** | **planned for the 3.1 lessons:** chat tools (search, calculator, memory, pictures) taught in Qwen's own `<tool_call>` format instead of ours, so tool use is as reliable as Qwen trained it; VryxCode already reads both |
| 201 languages | works already; the Emvryx voice in other languages would need lessons in them (not planned yet) |

## Picture conversations (decided Oct 17, 2026)
Goal: replies to a picture that feel like Claude's or ChatGPT's (the style, not their words: their outputs are never used as lessons).
**Now (in the app):** a model that sees pictures gets a short playbook with each picture (`app/documents.py` `PICTURE_PLAYBOOK`): open by showing it got
the picture, in the person's tone; add something they did not say (meaning, context, an honest take) in 2 to 4 sentences; fit the kind of picture (news or
a post, an error or code, homework or a form, a chart, a photo, a meme, a product); one short question only when natural; never read out the text or
cite file names. Later messages keep the picture and answer what was just said first.
**Lessons 4 (so the habit is learned, not told):** about 1,500 picture conversations, each 1 to 3 turns:
| Kind | Share | What a good reply does |
|---|---|---|
| Screenshots of posts and news | 25% | reacts, adds context, gives a take |
| Errors, code, settings screens | 20% | names the problem, gives the fix |
| Homework, forms, bills, receipts | 15% | helps with the actual task |
| Charts and tables | 10% | the main takeaway, then a detail |
| Photos (food, places, things, people's stuff) | 15% | comments on what stands out, useful tips |
| Memes and jokes | 5% | gets the joke, plays along |
| Follow-ups ("I'm excited", "what should I do?") | 10% | answers the person first, uses the picture only if it helps |
Pictures come from the owner's own screenshots (with permission) and openly licensed sets (licence checked per set, like the general lessons). The
teacher must be able to see pictures: Qwen3.6 27B if its vision works in llama.cpp (check first), otherwise a Qwen3.5 model with its picture reader.
The judge step scores each reply on the playbook above; replies that list or transcribe the picture are rejected. A new check, the **picture chat
check** (20 pictures, judged), guards it before publishing.

## Casual typing (decided Oct 18, 2026)
People write the way they text: "Sometimes I overtime ya know", "ngl", "idk", misspellings, voice-to-text mistakes, half-finished thoughts.
**Lessons 4:** a new factory area, **casual** (about 1,000 lessons): messages like these, often a feeling or opinion rather than a question; a good
reply works out the meaning, answers it naturally as "you", never corrects spelling and never says it did not understand when the meaning can be
guessed. The messy-typing copies (`data_prep/typo_lessons.py`) now also use slang ("gonna", "ngl", "idk", "rn") and casual endings ("ya know",
"lol", "fr"). **Now (in the app):** a message that reads as slang gets a short hint to go by what is meant (`chat_turn.CASUAL_HINT`).

## Making Lessons 4 much better than Lessons 3 (decided Oct 19, 2026; `data_prep/factory_plus.py`)
Lessons 3 taught mostly what the models already knew, in mixed voices, with nothing checked. On top of the factory above:

| | What it does | Command |
|---|---|---|
| 1 Teach what they miss | each model (a "student" on its own llama-server) answers the questions; proved right or wrong where possible, judged otherwise. `run --focus` answers the missed ones first and only 15% of the ones every model gets right | `probe --student URL --name flare-3`, then `run --focus` |
| 2 Their own mistakes as pairs | a model's wrong answer paired with the checked lesson for the same question (preference training on its real habits) | `student-pairs` |
| 3 The model checks itself | 6 tries on questions with a provable answer; the shortest one proved right becomes a lesson in its own voice, plus a pass/fail pair | `selfcheck --student URL --name flare-3` |
| 4 Thinking sized to the question | short reasoning (under 1,200 characters) for medium questions, up to 4,000 for hard ones; longer reasoning is condensed by the teacher; easy questions answer straight away (Solstice 3 thought too long) | automatic in `run` |
| 5 Real use | the app's reports (Admin > Feedback > export) become questions: only the person's question, never the old answer or who sent it | `feedback feedback_export.jsonl` |
| 6 Tests kept out | questions sharing 8 words in a row with a test question (the eval sheets, the thinking check, HellaSwag) are dropped, so scores stay honest | `clean` |
| 7 Near-duplicates | the same question in other words is dropped (MinHash), not just exact copies | `clean` |
| 8 Tools and pictures | questions that come with what the app looked up (weather, a web page, a calculation, a memory) and replies to a picture from its description, so the lessons show using them; the notes go with the message the way the app sends them | `tools --per 20` |
| 9 Quality report | pass rate, judge scores, proved right, style problems, lengths, thinking length, coverage by area: quality.md for every batch | `quality` |
| 10 The owner reads a sample | 30 random lessons to read (`review.md`) | `review --n 30` |
| Training files | train.jsonl (checked lessons + self-checked + thinking) and pairs_all.jsonl (every kind of pair) | `export` |

Order on a rental (teacher on port 8099; a model to probe on 8100, e.g. `llama-server -m export/open/flare-3/my-ai-q4_k_m.gguf -ngl 99 -c 8192 --parallel 4 --port 8100`):
`questions` and `maths` and `tools`, `feedback` (if there are reports), `clean`, `probe` for each model, `selfcheck` for each model, `run --focus`,
`student-pairs`, `quality`, `review`, `export`. The teacher (about 17 GB) and one model at a time (2 to 7 GB) fit the 5090 together.

## Later: Apogee 3.5
Grow Apogee 3 again to about **14B** (the most that fits the 4070 with 128K; 64K comfortable), train on **Lessons 4.5** (Lessons 4 plus what the app's
reports and approvals teach) with a second round of DPO and more thinking lessons. Expected about **50 to 52**; before it, write a harder test
sheet, because the current one runs out of room. If a newer open base fits 12 GB better by then, it is tried as well and the better one wins.

## Order of work
1. Now: Flare 3 trains on the 4070 (Lessons 3); Equinox 3 next.
2. The Constitution: the owner reviews and decides the open choices.
3. ~~Build the lesson factory~~ (built Oct 15). ~~Build "grow Qwen"~~ (built Oct 16: (pass-through layers, fast-layer-only option, train new layers plus major tune) and the 5090 training
   settings; tests for each).
4. With the 5090: Lessons 4 and VryxCode 3's builds (the same teacher), then Solstice 3, then Apogee 3 (pilot first), then VryxCode 3 on top of Apogee 3.
5. Flare 3.1 and Equinox 3.1 on Lessons 4 (one night each on the 4070).
6. Collect feedback in the app, then Lessons 4.5 and Apogee 3.5.
