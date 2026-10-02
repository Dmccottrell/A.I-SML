# The app: design (draft, Oct 2026)

One app for the phone and the PC. It runs **your own model, on your own device, offline by default**,
with an optional **online mode** that uses a bigger model on your own PC (later a server).

**App name (working, chosen Oct 2026): Yuvra** (say "YOOV-ruh"), with the website/domain **Yuvra.AI**.
A web search found no exact match, only look-alikes (the Yuva AI companies). Before it is public: search
the US trademark database (tmsearch.uspto.gov), Google Play and the App Store, and check that yuvra.ai
and yuvra.com are free. The models are named Yuvra + a role (Flare, Equinox, Solstice, Apogee) + a generation number, for example Yuvra Equinox 3.5; see docs/ROADMAP.md, "Names".
Backups if Yuvra fails those checks: Brynja, Quenby, Eirvala, Vardrun.

This builds on [ROADMAP.md: One app for phone and PC](ROADMAP.md#one-app-for-phone-and-pc-the-plan-for-the-website-and-app)
(one web codebase, packaged for Android with Capacitor and for the PC with Tauri). This file adds how the
existing Python features plug in, the two modes, the screens, and the build order.

## Principles
1. **Private first.** Offline is the default. A message leaves the device only when the user turns on
   online mode or web search, and the screen always says when that happens.
2. **Same behaviour everywhere.** One chat format (`chat.py`'s `CHAT_TEMPLATE`), one notes format,
   one `.gguf` per model, so a chat acts the same on the phone, the PC and the website.
3. **Swap the brain, keep the app.** v3 → v3.5 → v4 is a new `.gguf` file (and skill packs), not a new app.
4. **Honest.** Shows its sources (lookups, web results), says "I don't know", and says which model
   answered ("on this phone" / "online: v3.5 on your PC").

## How it works

```
                      ┌────────────────────────── the app (one TypeScript codebase) ──────────────────────────┐
  you type ──────────►│ chat screen ─► router (skill pack? online?) ─► notes (memory, lookups, web results)   │
                      │                                       │                                                │
                      │              ┌────────────────────────┴───────────────────────┐                        │
                      │              ▼ offline (default)                                ▼ online mode (a switch)│
                      │   llama.cpp on the phone/PC                       your PC's server (later: a rented one)│
                      │   v3 / v3.5 .gguf (+ skill pack)                  v3.5 full quality, later v5/v6         │
                      └──────────────────────────────────────────────────────────────────────────────────────┘
```

### The two modes
| | On the device (offline) | Online mode |
|---|---|---|
| Model | v3 now; v3.5's Q4 file (~700 MB) when ready | v3.5 at full quality on your PC; v5/v6 later |
| Runs on | The phone (llama.cpp) or the PC | Your PC's `llama-server` + the app server (below) |
| Needs internet | No | Yes, a private connection to your PC (Tailscale or a Cloudflare tunnel) |
| Who sees the messages | Nobody | Only your PC |
| Cost | Nothing | Electricity; a rented server later is ~$200-400/month 24/7, or pay-per-use |

### The app server (PC): reuse the Python that already exists
A small local server (FastAPI) on the PC wraps the tested Python code, so the PC/web version works
within days and becomes online mode for the phone:

| Feature | Python today | On the phone (offline) |
|---|---|---|
| Chat format, notes, memory calls | `chat.py` | Ported to TypeScript (small, shared by every platform) |
| Memory of you | `chat_memory.py` (SQLite) | Ported (SQLite works on phones); export/import to sync |
| Wikipedia lookups | `wiki_index.py` (~10 GB) | A small index (most-read articles, ~1-2 GB), or ask the PC when online |
| Web search | `web_search.py` | Ported (plain web requests); off unless switched on |
| Skill packs + router + access toggle | `skills.py`, `lora.py` | llama.cpp loads LoRA adapters; router and `can_use()` ported |
| Save as PDF / Word | `export_doc.py` | First: ask the PC; later a phone PDF library with the same layout |
| Context meter, reply suggestions | `chat.py` | Ported |

## Screens (first version)
1. **Chat:** messages, a "thinking" indicator, sources under answers, a badge saying where it was
   answered (phone / online), reply suggestions as tappable chips, a Save/Print button on documents.
2. **Chats list:** history, search, delete; private chats that aren't saved.
3. **Memory:** what it remembers about you; edit, delete, "forget everything"; export/import.
4. **Skills:** Study helper and Teacher assistant (Betas) with on/off switches; only packs the account
   may use are shown (`skills.py` access toggle); "Auto" lets the router pick.
5. **Settings:** model picker (see below), online mode on/off and the PC's address, web search on/off,
   lookups on/off, text size, dark mode, privacy summary.
6. **Documents:** saved worksheets and lesson plans (PDF/Word) for the Teacher assistant.

## Model picker (the "Select model" sheet)

A sheet that opens from the chat header (tap the model name), like the model menus in other AI apps. It lets
you choose the model, the effort, and see where each one runs. Works the same on the phone, the PC and the website.

```
 Select model                                   X
 -------------------------------------------------
  Auto   (the router picks)                  [check]
         Best model and effort for each question
  Yuvra Flare 3          [On this phone]
         Fastest for quick answers
  Yuvra Equinox 4        [On this phone]
         For everyday work and homework
  Yuvra Solstice 5       [Online: your PC]
         For harder questions and long writing
  Yuvra Apogee 6         [Online: your PC]
         For your toughest challenges
 -------------------------------------------------
  Effort                              Balanced  >
 -------------------------------------------------
  Skills                              Study helper (Beta), Teacher assistant (Beta)  >
 -------------------------------------------------
  Other models
  Yuvra Equinox 3.5  (older)  [Not downloaded, 700 MB]
  Earlier versions of any name
```

- **One card per model:** name, a one-line description, and a badge that says where it runs: **On this phone**
  (offline), **Online: your PC** (messages go to your own PC; the sheet says so), **Not downloaded (700 MB)**
  (tap to download with a progress bar), or **Beta**. A check mark shows the current choice.
- **Auto** (the default) hands the choice to the router (`skills.py` today; a small trained classifier in v4),
  which picks the size, the effort and the skill pack per question, and the chat says what it picked.
- **Effort:** Quick / Balanced / Deep, the thinking dial from the roadmap. Greyed out for models that can't think yet.
- **Skills:** the same on/off list as the Skills screen, shortcut included.
- **One card per name, newest version first** (each name has its own number, e.g. Flare 3, Equinox 4, Solstice 5, Apogee 6). When a
  model is updated the old one moves to **Other models**, with downloaded files and test builds, so you can compare
  (Equinox 3.5 vs Equinox 4). **Only a limited selection of older models is kept** (for example the previous one or two
  versions of each name, plus anything you pinned); the exact rule is still to be decided, and the manifest gets a `keep` /
  `retire_after` field for it.
- **Honest limits:** a model the device can't run (not enough memory) is greyed out with the reason; the
  badge shows the measured speed on this device once known ("about 200 words a second"); an online model shows
  "needs your PC to be on" when it can't be reached, and the app falls back to the phone model after asking.
- **Access toggle:** which cards appear follows the same rule as the skill packs (`can_use()`, everyone / beta /
  off): a Beta model shows only for the people on the beta list.
- **Switching mid-chat** keeps the conversation and adds a small divider ("Switched to Yuvra Equinox 4"). Each
  answer keeps a tag of which model wrote it.
- **Credits-style badge (later):** if online mode ever runs on a paid server, a card can carry a "Uses online
  credits" badge, like other apps do for their biggest models.

**Where the list comes from:** one `models.json` manifest (the app reads it; the PC server serves the same
file at `/models`). One entry per model: `id`, `name`, `tagline`, `tier` (Lite / Standard / Pro / Max),
`where` (device / online), `file` and `size_mb` (the `.gguf`), `sha256` (to check the download), `min_ram_gb`,
`context` (tokens), `status` (stable / beta / off), `supports_effort`, `skills` (which packs fit this model; a pack only
fits the `chat.pt` it was trained on), and `from_version` (v3, v3.5, ...). Adding a new model is adding a line,
not changing the app.

## Features by version
| | v3 (now) | v3.5 | v4 |
|---|---|---|---|
| Brain on the phone | v3 (~250 MB Q4) | v3.5 Q4 (~700 MB) | v4 (same size as v3.5) |
| Online mode | v3 or v3.5 on the PC | v3.5 full quality | v4; later v5/v6 |
| Memory, lookups, web search, suggestions | yes | better | better |
| Skill packs | Study helper, Teacher assistant (Beta) | retrained on v3.5 | + stories, IT help, fact check, coding |
| Tools | – | – | calculator, clock, files; phone actions (alarms, timers, texts) |
| Voice | – | – | speech in (Whisper) and out (Piper) |
| Phone assistant mode | – | – | default assistant app (side button), "what's on my screen" |

## Accounts and access
- Offline use needs **no account**.
- The access toggle (`data/skills_access.json`: everyone / beta / off, plus the beta tester list) is
  the same rule the app uses per signed-in person, so testers can get Beta packs first.
- First users: you and your wife (Teacher assistant), then a small test group, then public.

## Build order
1. **PC/web version (about a week after v3's chat model is ready):** the app server + a web chat page
   on `llama-server`; chat, memory, web search, skills, PDF export. This is also the online-mode server.
2. **Android app (while v3.5 trains):** the same screens in Capacitor, llama.cpp on the phone, the
   ported chat format and memory; online mode connects to the PC.
3. **v3.5 swap:** new `.gguf` files and retrained skill packs; no app changes.
4. **v4:** tools, voice, phone assistant mode, more skill packs.
5. **iPhone** (needs a Mac and the $99/year developer account) and a public website, if wanted.

## Decisions still open
- **Name** and icon.
- **Android only** at first, or iPhone too?
- **Who first:** family only, a test group, or public (affects accounts and the server).
- **Online mode host:** your PC only (free, works while it's on), or a rented/pay-per-use server.
- **How many older models to keep** under "Other models" (and whether old downloads are deleted automatically).
