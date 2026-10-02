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
| Context management | 2,048 tokens for Flare 3 and Flare 3.5 (longer later). A **context meter** (exact token counts from the server's tokenizer) and a quiet "older messages forgotten" marker |
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
| Device check | Not enough memory = the card is greyed out with the reason; measured speed shown once known. It also picks the **context window** for this device (see "Context window and the device check" below) |

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

### Usage and limits: sparks (plan)
Yuvra's own way to show and limit usage. It is counted in **tokens**, shown as **sparks** (1 spark = 1,000 counted tokens), and drawn as a
**brain that fills like a tank** instead of a plain progress bar. Designs: `Usage` (the phone's "Sparks" screen) and `Limits` (owner settings) in
`design/canvas/`.

**Three different numbers (this is the part that is easy to mix up):**

| Number | What it is | Example (private testers) |
|---|---|---|
| **1. The context window** | The most ONE request can hold: the model's working memory for a single message and its history. It is a cap per request, **not an allowance** | Everyday 8,192; Long up to 32,768 |
| **2. The tank** | How much a person can use *right now*. It refills steadily (a "token bucket"), so there is no cliff where everything resets at once | Capacity 200,000 tokens, refills 25,000 per hour (empty to full in 8 hours) |
| **3. The weekly ceiling** | The total of every chat in 7 days. A hard stop for heavy use | 1,000,000 tokens, resets Mon 4:00 AM |

So **32,768 is not "32,000 every few hours"**. It only limits how big a single request may be. What a person may use over time is the tank (short term) and
the weekly ceiling (long term). A message is allowed only if both have room; the smaller one wins.

**What a message costs (token-based counting).** A chat is re-read from the start on every message, so a long chat costs more per message. Counted tokens =
(new text you send x 1) + (earlier chat the server already holds x 0.1) + (what Yuvra writes x 1), then multiplied by the model's weight (Flare 1,
Equinox 2, Solstice 5, Apogee 10). The 0.1 is because a server that keeps the earlier part of the chat in memory does not recompute it ("prefix
caching"); a server without that must count it at x 1. Starting values, to be tuned after measuring real server time.

Worked example (each turn: you write 150 tokens, Yuvra writes 350, so the chat grows by 500):

| | After 10 messages | Why |
|---|---|---|
| A new chat for every message | 5,000 | each message stands alone (500) |
| One growing chat, no caching | 27,500 | every message re-reads everything before it |
| One growing chat, with caching | 7,250 | the earlier part counts at 1/10 |
| A chat whose window is full at 32K, no caching | ~325,000 | ~32,500 per message |
| The same full 32K chat, with caching | ~37,000 | ~3,700 per message |

So under the 1,000,000 weekly ceiling a person gets roughly 2,000 short messages, or about 270 messages in a full 32K chat. **Long chats drain the allowance much faster**;
the app says so, and the tank makes it visible. (Note: the total does NOT flatten at the window size. The window caps one request; the running total keeps
growing with every message.)

| Part | Plan |
|---|---|
| **Where people see it** | Settings, then **Sparks**, and a tap on the chat's status line. The brain tank (how full, "124 of 200 sparks", "refilling 25 an hour, full by 9:40 PM"), **This week** (resets Mon 4:00 AM) as a strip of seven days (not one bar) with a pace note ("you could use about 575 more a day"), and **Tokens this week** by model with a breakdown (you wrote / Yuvra wrote / earlier chat re-read). On-device models: "free, never counted" |
| **Who sets limits** | Only the owner, in the **Limits** screen: the tank (capacity, refill), the weekly ceiling and reset time, the Everyday and Long windows, the counting multipliers, the model weights; per tier (Free, Pro, Mega) and per person (overrides). Alerts at 80% of the week and at the ceiling; a pause-everything switch |
| **What applies** | Only models **served from a shared machine** (your PC, a rented server). Models running on a person's own device are free and never counted |
| **When the tank runs low** | A quiet note at 20%. At empty that model pauses and offers a smaller model, the on-device model (free), or "back to full in about 2 hours". At the weekly ceiling: "resets Mon 4:00 AM" with the same options |
| **Enforced on the server** | By the person's key, never only in the app. The server counts every request, refuses over-limit ones with a clear message, and the Sparks screen reads the same numbers |
| **Stored** | `usage(user, model, fresh_in, cached_in, out, at)` and the limits table in the server's SQLite: numbers only, never message text. Tank level = capacity minus recent use plus refill; week = sum since the reset |
| **Tests** | With a fake clock: counting multipliers and weights add up; the tank refills at the set rate and never exceeds capacity; the weekly total resets on time; a message needs room in both; the 20% note and the empty block fire; a per-person override beats the group limit; on-device use is never counted; no message text is stored |
| **Model list field** | `cost_weight` per model in `models.json` |

**Decided: a fixed weekly reset, Monday 4:00 AM in the person's own time zone.** Monday starts the school and work week, and 4:00 AM is the quietest hour, so almost
nobody is mid-chat when it happens. Each person's time zone is stored with their account; the server keeps the reset as a UTC time per person. The tank is unaffected by
the reset (it refills all week). The setting is `weekly_reset: "mon 04:00"`, and `weekly_window: fixed` (rolling stays an option).

**Tiers (planned): Free, Pro, Mega.** Same app and the same models; the tiers differ in how much of the shared server they may use. Models running on a person's own
device are free and unlimited in every tier, which is the selling point of the free one. These are starting values to be tuned against what the server can really carry
(measured tokens per second, and how many people are on at once). 1 spark = 1,000 counted tokens.

| | **Free** | **Pro** | **Mega** |
|---|---|---|---|
| Tank (capacity / refill per hour) | 40,000 / 5,000 (full in 8 h) | 200,000 / 25,000 (full in 8 h) | 800,000 / 100,000 (full in 8 h) |
| Weekly ceiling | 150,000 (150 sparks) | 1,000,000 (1,000 sparks) | 5,000,000 (5,000 sparks) |
| Roughly, in short messages (~500 counted each) | ~300 a week | ~2,000 a week | ~10,000 a week |
| Models from the server | Flare, Equinox | All four (Flare, Equinox, Solstice, Apogee) | All four |
| Context window (one request) | Everyday 8,192 | Everyday 8,192, Long up to 32,768 | Everyday 8,192, Long up to the longest the model passed (64K and up) |
| Priority when the server is busy | Normal | Normal | First |
| Who | Anyone, once the public version exists | Your private testers now; paying users later | Heavy users; you (the owner) are exempt from all limits |

Free is limited to Flare and Equinox; Pro and Mega can use all four models, so the paid tiers differ in how much they can use, not in which models. Because model weights multiply the counted tokens (Flare 1, Equinox 2, Solstice 5, Apogee 10), the same weekly ceiling buys far fewer Apogee messages than Flare ones:
5,000,000 on Mega is about 500,000 Apogee tokens. The limits live in one config file (`limits.json`: a block per tier, plus per-person overrides), so tiers can be added or
changed without touching code. Pricing is not decided; the tiers only decide access and amounts. The owner screen has a tab for each tier.

**How the server enforces it (details):**
- **Exact counts.** The server counts tokens with the model's own tokenizer (`chat.py` builds the prompt) and takes the figures llama-server reports for each
  reply (tokens read, tokens written, tokens already cached). Never character counts.
- **Check, reserve, settle.** Before a request runs, estimate its cost and check the tank and the week. If there is room, **reserve** the estimate (so two requests
  at once cannot both slip under the limit), then **settle** with the real numbers when the reply ends and give back the difference. A stopped or failed reply is
  settled with what was actually used.
- **Over the limit = HTTP 429** (Too Many Requests) with a `Retry-After` time and a small JSON body (`code`, `message`, `resets_at`, and the choices to offer). The app turns it into the
  friendly message ("tank empty: back to full in about 2 hours"), never a raw error.
- **Weekly window: fixed reset or rolling 7 days?** *Fixed* (resets Sun 2:00 AM) is easy to explain and show. *Rolling* (always the last 168 hours) stops a person emptying the
  week on Saturday night and getting a fresh one on Sunday morning. With the tank, that burst is already capped (a person cannot spend more than the tank's capacity plus
  its refill in one night), so the plan starts with the **fixed** reset plus the tank; rolling stays an option behind one setting (`weekly_window: fixed | rolling`),
  with a test for each.

### Context window and the device check (plan)
The window (the model's working memory, in tokens) costs RAM, not storage: the model's cache grows with every token. The app chooses
the window per device and per model, and never lets it exceed what the model can really use.

| Rule | Detail |
|---|---|
| **Cost per token** | Cache bytes per token = 2 x layers x key/value heads x head size x bytes. Flare 3 (v3): 32 KB at 16-bit, ~16 KB with an 8-bit cache. Flare 3.5 (v3.5): ~24.6 KB at 16-bit. Weights on top: ~240 MB (v3 Q4), ~700 MB (v3.5 Q4) |
| **The window is the smallest of three numbers** | (1) what the model **passed** on the long-context ladder (`stretch_ladder.py`, `eval_long.py`), (2) what the free RAM can hold, (3) the speed limit below. A window the model didn't pass adds nothing |
| **Free RAM, not total RAM** | Checked at load time (Android's available-memory figure, not "12 GB installed"): a usable budget is about half the phone's RAM at most (roughly 2.5 GB on 8 GB phones, 4 GB on 12 GB phones), less when other apps are open. Storage and swap such as Samsung's RAM Plus do not count: too slow for a cache read on every word |
| **Three modes** | **Everyday** (default): about 8K tokens, ~0.3 GB of cache, cool and quick. **Long** (Settings, only if the device and the model allow it): up to the smaller of what the model passed and what fits; a warning says the first reply after pasting a long document can take minutes and warm the phone. **Remote**: the PC or a server, any length the server handles, nothing extra on the phone |
| **8-bit cache** | A setting (default on for Long mode): halves the cache with a small quality cost; the app measures nothing it can't test, so the long-context tests are re-run with it before it is the default |
| **Speed limit** | Reading a long text takes time that grows with its length. The first run measures prefill speed once and the app shows an estimate before reading ("about 3 minutes") and a Stop button |
| **Safety** | Before loading a long window, check free memory again; if it is too low, drop to the next smaller window and say so (never crash or let the system kill the app). While running, if the system warns about memory, shrink the cache or stop generating and keep what was written |
| **What is shown** | The context meter shows used / allowed tokens, and the Settings screen shows why the limit is what it is ("limited by: free memory" / "limited by: what the model passed" / "limited by: speed") |

Examples, worked out from the numbers above (estimates until measured on real phones): an 8 GB phone holds roughly 64K tokens with a 16-bit
cache or 128K with an 8-bit cache; a 12 GB phone roughly 100K or 200K. Whether the model can use that much is decided by the ladder, and
the longest windows (100K and up) are PC and remote only.

Manifest fields this needs (in `models.json`): `context` (trained length), `context_tested` (the longest length that passed the gate, 2,048 until
the ladder has run), `kv_kb_per_token` (16-bit) and `weights_mb`. Tests: with a fake device (RAM, free RAM) the chosen window must never exceed
the smallest of the three limits, must drop and say so when memory falls, and must never be chosen above `context_tested`.

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
