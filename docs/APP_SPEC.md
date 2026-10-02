# Yuvra app: what it needs, what it looks like, how it works

The detailed spec behind [APP.md](APP.md) (the overview and build order). Three parts: **what it needs**
(requirements), **what it looks like** (screens), and **how it works properly** (flows, failure handling,
tests, and what "done" means for the first version).

---

## Part 1: What the app needs

### 1. A model runner (the engine)
| Need | Detail |
|---|---|
| Run a `.gguf` offline | **llama.cpp**: `llama-server` on the PC, and llama.cpp inside the Android app (via a plugin such as llama.rn). Same file format as `to_gguf.py` already makes |
| Our own prompt format | The model was trained with special tokens (`<|user|>`, `<|assistant|>`, `<|notes|>`, `<|tool_call|>`). The chat template stored in the file only knows plain user/assistant text, so **the app builds the prompt itself** (a port of `chat.py`: notes in front of the question, old notes dropped, oldest turns forgotten) and sends it to the raw completion endpoint. Check special-token handling in the first pilot |
| Generation settings | temperature 0.8, top-k 50, repetition penalty 1.15 (the values `generate.py` uses); stop at `<|endoftext|>`; streaming |
| Context management | 2,048 tokens for Flare 3 and Equinox 3.5 (longer later). A **context meter** (exact token counts from the server's tokenizer) and a quiet "older messages forgotten" marker |
| Tool calls | Read `<|tool_call|>{"name": "remember", ...}` out of the reply (`split_memory_calls`) and act on it; v4 adds calculator, clock, files |

### 2. Knowledge and memory
| Need | Detail |
|---|---|
| Memory of you | SQLite on the device: saved facts, earlier chats, search by meaning (a small embedding model, optional) with keyword search as the fallback. A Memory screen to see, edit and delete. Private chats are never saved |
| Wikipedia lookups | PC: the full index (~10 GB). Phone: a small index (most-read articles, ~1-2 GB) or ask the PC when online. Notes show their source |
| Web search | `web_search.py` ported; **off by default**, clearly labelled when on; trusted sites first; failures never stop the chat |
| Sources everywhere | Any answer that used notes shows where they came from (tap to open) |

### 3. Skills and documents
| Need | Detail |
|---|---|
| Skill packs | Study helper, Teacher assistant (Beta). First version ships **merged model files** (`chat_study.gguf`); LoRA adapters next to the main file later (needs a converter from our LoRA format) |
| Router + access | Auto picks the pack per message (`skills.py`); the access toggle (everyone / beta / off, beta list) decides which packs a person sees |
| Save as PDF / Word | The fixed layout from `export_doc.py` (Name/Date line, answer key on its own page). PC first; phone later, with the share sheet |

### 4. Models and where they run
| Need | Detail |
|---|---|
| Model list | One `models.json` manifest (id, name, tagline, tier, where, file, size, sha256, min RAM, context, status, which skill packs fit, `keep` rule). Adding a model = adding a line |
| Download manager | Resume after a dropped connection, check the sha256, show size and storage left, delete old models, keep only a limited selection of older ones |
| Online mode | Your PC's server over a **private connection** (Tailscale or a Cloudflare tunnel) with a secret key; the app says when it's used, and falls back to the phone model (clearly labelled; a Setting can make it ask first) if the PC is off |
| Device check | Not enough memory = the card is greyed out with the reason; measured speed shown once known |

### 5. Safety, privacy and trust
- Offline by default; nothing leaves the device unless online mode or web search is switched on, and the screen always shows it.
- No accounts, no analytics and no crash reports sent anywhere without an explicit opt-in.
- The server refuses requests without the secret key, never listens on the open internet by itself, and never logs message text.
- App lock (device PIN/biometrics) for the chat history; "delete everything" in Settings.
- Honest answers: sources shown, "I don't know" kept, small-model warning where it matters (homework, health, money).

### 6. Quality bars (the app must meet these)
| Area | Bar |
|---|---|
| Speed | first word on screen in under ~1 s once the model is loaded; steady streaming; speed measured and shown per device |
| Memory | never crash on a low-memory phone: check before loading, fall back to a smaller model |
| Battery/heat | generation stops when the screen is off or on request; a "low power" setting (shorter replies) |
| Saving | every message saved as it streams; a crash loses at most the last few words |
| Accessibility | text size, dark/light, screen-reader labels, large touch targets (the Teacher assistant is for classroom use) |

---

## Part 2: What it looks like

Dark by default, calm and plain: lots of space, one accent colour, big readable text. Same layout on the phone,
the PC and the website (the PC adds a chats sidebar).

### Chat (the main screen)
```
+--------------------------------------------------+
|  =   Yuvra Equinox 4  v        [ Auto ]       ...  |   <- tap the model name: the picker
+--------------------------------------------------+
|                                                  |
|   You                                            |
|   Make a 10-question worksheet on                |
|   multiplication facts for 7s                    |
|                                                  |
|   Equinox   (Teacher assistant)                  |
|   # Multiplying by 7                             |
|   Name: ______   Date: ______                    |
|   1. 7 x 3 = ___   ...                           |
|   [ Save PDF ]  [ Save Word ]  [ Copy ]          |
|   Sources: none (made from what I know)          |
|                                                  |
|   [ Quiz me ]  [ Make it easier ]  [ Answer key ]|   <- reply suggestions
+--------------------------------------------------+
|  [+]  Message Yuvra...                  [mic]  ^ |   <- + : attach, skills, web search
|  Memory: 3 facts  *  Context 31%  *  Offline     |   <- small status line
+--------------------------------------------------+
```
- **The tag** above each answer says which model wrote it (just the name, "Equinox"), and where it ran only when that is
  worth knowing (for example "on your PC" when a remote model answered). The model picker sits under the message box.
- **The status line:** memory used, context meter, and **Offline / Online** (tap for details).
- **Reply suggestions** are tappable chips (from the suggest-next-message lesson).

### The other screens
| Screen | What's on it |
|---|---|
| **Model picker** (sheet) | Cards for Flare, Equinox, Solstice, Apogee with badges, an **Auto** card, Effort (Quick / Balanced / Deep), a Skills row, and "Other models" (see APP.md) |
| **Chats** | List and search, pinned chats, private chats marked, delete |
| **Memory** | The facts it remembers, each with edit and delete; "Forget everything"; export / import |
| **Skills** | Study helper and Teacher assistant (Beta) with switches; only packs you may use are shown; a short "what it does" line and a sample |
| **Documents** | Saved worksheets, lesson plans and letters (PDF/Word), re-open, share, print |
| **Settings** | Models and downloads, online mode (PC address, key, test button), web search, lookups, privacy summary (what leaves the device, right now), text size, theme, app lock, delete everything |
| **First run** | Welcome, one question (phone or PC?), download the starter model (with size and Wi-Fi warning), a 3-line privacy promise |

### The Teacher assistant view (your wife's use)
A task picker first (Worksheet, Reading passage, Lesson plan, Spelling list, Parent email, Report comments,
Rubric, Brain breaks), a short form (grade, topic, how many questions), then the result with **Print** and
**Edit in Word**. Student names are never needed; "[Student]" is the placeholder.

---

## Part 3: How it works properly

### The path of one message
```
you type
  -> router: which skill pack? which model and effort? (Auto, or your choice)
  -> notes: memory (earlier chats, saved facts) + Wikipedia + web search (if on)
  -> prompt builder (the port of chat.py): notes, history, context limit, forgotten turns
  -> model (phone or your PC) streams the reply
  -> parse: remember-calls out, sources attached, document layout detected
  -> save the chat; update memory; show the answer with its badge and sources
```
Every step has a fallback: no notes -> answer without; web search fails -> say so and continue; model not loaded ->
load it (with a spinner); PC unreachable -> offer the phone model.

### What can go wrong, and what the app does
| Problem | The app |
|---|---|
| Not enough memory for the model | Greyed out with the reason; suggest the smaller one |
| PC off or unreachable (online mode) | Switches to the on-device model right away and labels the answer ("PC off: answered by Equinox on this device"); a Setting can make it ask first instead. Never the other way: going from device to online is always the person's choice |
| Download interrupted | Resumes; verifies the checksum; never loads a half-file |
| Context full | Drops the oldest turns and old notes (as chat.py does), shows the marker; the meter explains |
| Model answers badly (small model) | The "that's wrong" flow rechecks notes; the "I don't know" lessons; a visible reminder to double-check |
| Reply never ends / loops | Hard cap on length, a Stop button, repetition penalty |
| App closed mid-reply | Draft and partial reply are saved |
| Wrong key / server not found | A clear message and a "Test connection" button, never a blank screen |

**Built and tested (Oct 2026):** every row above is now code with a test that forces the failure (`tests/test_app_robust.py`,
23 tests, against a fake model and real local web servers). `app_errors.py` gives each failure a plain message and one next
step (and buttons where there is a choice); `app_engine.py` has `choose_model` (too big: refused and the next smaller one
offered; PC off: switches to the device model and says so, or asks first if the Setting says so), `Guard` (length cap, loop detector, Stop button that closes the
connection), `ChatStore` (the reply is saved while it streams; a cut-off reply is found again after a restart; private chats
never touch the disk), `run_turn` (uses `chat.py`'s prompt builder, returns how many old messages were forgotten for the
marker), `LlamaServer` (the real client for llama-server) and `test_connection` (the button: unreachable / wrong key /
not our server). `app_download.py` resumes from a `.part` file, starts over if the server can't resume, throws away a file
with a bad checksum, and requires a checksum for every model (fill in `sha256` in `models.json` when a file is built).
Not covered here: the "small model answers badly" row, which only better training fixes (the honesty tests stay the check).

### How we know it works (tests)
1. **Prompt parity tests (the most important):** the app's prompt builder must produce **exactly the same tokens** as
   `chat.py` for the same conversation (golden files generated by the Python code). If these fail, the model gets
   a format it wasn't trained on and answers get worse in ways that are hard to see.
2. **Unit tests** for memory (save, recall, forget, private chats), the router, access rules, export layout.
3. **End-to-end tests** with a tiny model (fast, in CI): send a message, stream a reply, save, reload, find it.
4. **Device checks** on real hardware: your phone and PC: load time, first-word time, tokens/second, memory use,
   battery over 10 minutes of chat.
5. **The honesty set:** `eval/prompts_v3.jsonl` and `eval/web.jsonl` run through the app's path, not just Python,
   and must score the same.

### What "done" means for the first version (phase 1: web app on the PC)
- [ ] `python app_server.py` starts the server; a browser page opens and chats with a model, streaming.
- [ ] The prompt builder matches `chat.py` token for token (golden tests pass).
- [ ] Chats are saved and listed; Stop and Regenerate work; private chat mode works.
- [ ] Memory: it saves "my name is Sam", recalls it in a new chat, and the Memory screen can delete it.
- [ ] The model picker lists the models in `models.json`, shows the right badges, switches mid-chat.
- [ ] Study helper and Teacher assistant switches (access toggle respected); Save as PDF / Word works.
- [ ] Web search switch works and says when it is on; sources are shown under answers.
- [ ] Settings shows what leaves the device; delete-everything works.
- [ ] Installable as an app (PWA) and usable from the phone on the same network.

### What is not in the first version
Voice, tools (calculator, alarms), the phone-assistant mode, accounts, iPhone, the public website and on-device
Android. Each has its place in [APP.md](APP.md) (build order); none is needed to prove the design.

---

## Decisions that shape the build (decided Oct 2026)
1. **Platform: PC/web first.** The local server and browser page come first; they also become the online-mode server. Android follows.
2. **Who first: a small test group** (not family-only). So the beta access list matters from day one: `models.json` status
   `beta` + the same beta-user list as the skill packs (`skills.py`), and each tester is a named user. Public later.
3. **Skill packs: LoRA adapters** next to the main model file (not merged copies). Needs a converter from our LoRA format
   (`lora.py`) to llama.cpp's adapter format, with a test that the adapter gives the same answers as the merged model.
   Until the converter exists, the first build can load merged files (`chat_study.gguf`) behind the same switch.
4. **Memory search: keyword AND meaning from day one**, using the small embedding model (already in `chat_memory.py`);
   keyword search stays as the fallback if the embedding model is missing.
5. **App lock and encryption: a setting, off by default.** Turn on in Settings (device PIN/biometrics); the chat database is
   encrypted when it is on.

What this changes in the first version's checklist: add "adapter converter + same-answers test", "named testers and the
beta list", and "memory finds an earlier chat by meaning, not only by words".

## Built so far
- `models.json` + `models.py` (+ `tests/test_models.py`): the model list and the picker logic (one card per name, newest
  first; older ones under Other models with the retention rule; greyed out when the device is too small; online models
  need the PC; beta models only for the beta list). Try it: `python models.py`.
