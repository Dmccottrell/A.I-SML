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

## The lesson factory (to build)
1. **Questions:** 50,000 to 100,000 across about 20 areas (maths, code in several languages, science, writing, advice, planning, everyday knowledge,
   multi-step tasks, tools, long chats, sensitive topics, "should it ask first?"), tagged easy, medium or hard. Questions may come from open datasets
   (their licences read by the owner); the answers are always made here.
2. **Drafts:** an open teacher model whose licence allows training on its output (Qwen3.5 27B on the 5090, Apache 2.0) writes several drafts,
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

## Later: Apogee 3.5
Grow Apogee 3 again to about **14B** (the most that fits the 4070 with 128K; 64K comfortable), train on **Lessons 4.5** (Lessons 4 plus what the app's
reports and approvals teach) with a second round of DPO and more thinking lessons. Expected about **50 to 52**; before it, write a harder test
sheet, because the current one runs out of room. If a newer open base fits 12 GB better by then, it is tried as well and the better one wins.

## Order of work
1. Now: Flare 3 trains on the 4070 (Lessons 3); Equinox 3 next.
2. The Constitution: the owner reviews and decides the open choices.
3. Build the lesson factory, "grow Qwen" (pass-through layers, fast-layer-only option, train new layers plus major tune) and the 5090 training
   settings; tests for each.
4. With the 5090: Lessons 4, then Solstice 3, then Apogee 3 (pilot first).
5. Flare 3.1 and Equinox 3.1 on Lessons 4 (one night each on the 4070).
6. Collect feedback in the app, then Lessons 4.5 and Apogee 3.5.
