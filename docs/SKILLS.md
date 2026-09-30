# Skill packs (Beta)

A **skill pack** is a small add-on that makes the chat model a specialist, without changing the model
itself. v4 plans six packs and a router that picks one per message. The first one, the **Study helper**,
is a **Beta**: it's built and tested on v3 so the recipe is proven before v4, and only you (and people you
add as testers) can use it.

## How it works

The chat model stays frozen. Next to each attention and feed-forward layer sits a tiny pair of matrices
(LoRA, `lora.py`), and only those are trained:

| | v3 | v3.5 / v4 |
|---|---|---|
| Add-on size (rank 16) | 9.3M numbers, 2.4% of the model | 12.6M, 1.2% |
| Pack file | ~19 MB | ~25 MB |
| Training time (a few thousand lessons, RTX 4070) | minutes to under an hour | under an hour |

- A fresh pack changes nothing; it only learns the skill.
- Packs can't damage each other or the chat model: each is a separate file, switched on and off per message.
- A pack only fits the model it was trained on. v4's brain gets its own packs, retrained from the same lessons
  (`load_pack` refuses a pack from a different `chat.pt`; `--any_base` overrides for experiments).
- For the phone, `--merge` folds the pack into the weights (`chat_study.pt`), which `to_gguf.py` converts
  as usual.

## The Study helper (Beta)

Explains school topics (math, science, history, geography, English, computer science, economics) at the
student's level, gives a worked example or numbered steps, and ends with **"Quick check: ...?"**. When the
student answers, it says whether that's right and explains the mistake if not.

```
You: I don't understand how to add fractions with different denominators.
AI:  To add fractions, the bottom numbers (denominators) must match first...
     For example, 1/2 + 1/3: ...
     Quick check: What is 1/4 + 1/2?
You: 2/6
AI:  Not quite: 2/6 adds the tops and bottoms. Change 1/2 to 2/4 first, so 1/4 + 2/4 = 3/4.
```

## Build, train and test it (after v3 is chat-tuned)

```
python make_teacher_data.py --task study --n 3000        # the teacher writes lessons (~2,000+ kept)
python make_skill_data.py --version v3 --skill study     # -> data/v3/skills/study/train.jsonl, val.jsonl
python train_skill.py --version v3 --skill study         # -> checkpoints/.../v3/skills/study.pt
python skill_test.py --version v3 --skill study          # with vs without the pack, and the router
python evaluate.py --version v3 --skill study            # everyday answers must not get worse
python generate.py --version v3 --chat --skill study     # chat with it (or --skill auto)
```

- **Lessons** (`make_teacher_data.py --task study`): 68 topics × 3 levels × 7 question styles; half the
  student answers are right, half are a typical mistake. Lessons that break the format (no quick check, no
  example, too long, feedback that doesn't match) are thrown away automatically. Local teacher or a hosted
  one, as for the other teacher tasks (see `make_teacher_data.py`).
- **Training file** (`make_skill_data.py`): every lesson becomes a chat; about half include the student's
  answer and the feedback. 20% general chat lessons are mixed in ("replay") so the pack keeps everyday
  manners. 5% of the lessons are held back for validation.
- **Training** (`train_skill.py`): 2 epochs, learning rate 2e-4, rank 16. It prints the validation loss
  of the plain chat model and of the pack; lower with the pack = it learned the skill. Ctrl+C pauses,
  the same command resumes. `--merge` also writes `chat_study.pt` for the phone.
- **Test** (`skill_test.py`): the questions in `eval/skills/study.jsonl`, each with and without the pack,
  scored on: ends with a quick check, gives an example or steps, 40–300 words, finishes properly. PASS when
  the pack is clearly better. Every answer is saved side by side in `skills/study_test.md`.

## The Beta router

`python generate.py --version v3 --chat --skill auto` picks a pack for each message (or none) and says
which: `(skill: Study helper (Beta))` or `(skill: none, plain chat)`. It scores school words and question
shapes; small talk ("hi", "what is your name?"), printer questions and poems stay with the plain model.
It gets all 20 messages in `eval/skills/study.jsonl` right. v4 replaces it with a small trained classifier
that also picks the effort level and the model size.

## Who can use a pack (the access toggle)

Each pack has a switch: **everyone**, **beta** (only people on the beta list) or **off**. Beta packs start
at `beta`, planned ones at `off`. You (the `owner`) can always use every trained pack.

```
python skills.py access                         # show the switches and the beta testers
python skills.py access study beta              # testers only (the default for a Beta)
python skills.py access study everyone          # release it
python skills.py access study off               # switch it off for everyone but you
python skills.py beta add sam                   # add a tester (remove: beta remove sam)
python generate.py --version v3 --chat --skill auto --user sam    # chat as sam: only packs sam may use
```

The settings live in `data/skills_access.json`. The app will use the same file and the same `can_use()`
rule with each signed-in account, so giving testers early access, releasing a pack, or pulling it is one
switch, and the app's settings screen can show only the packs a user is allowed to turn on.

## For v4 (expanding it)

- **Study helper:** retrain on v4's brain from the same lessons; add lessons with Wikipedia notes (cite the
  source), more subjects and levels, multi-step math checked by the calculator tool, and "quiz me" sessions.
- **More packs:** each one needs a data builder in `make_skill_data.py`, a teacher task, a test in
  `skill_test.py` and its entry in `skills.py` (already listed: stories, IT helper, fact checker,
  documents, coding).
- **Router:** a small trained classifier instead of keywords; also picks Lite/Standard and the effort level.
- **Phone:** llama.cpp can load LoRA adapters next to the main file; the Beta ships merged files first.
