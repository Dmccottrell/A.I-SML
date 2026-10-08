# Changelog

What changed, newest first. Measured numbers live in [BENCHMARKS.md](BENCHMARKS.md); each model's details are in [VERSIONS.md](VERSIONS.md).

## October 2026 (late)

### Latest
- **Chat tools:** a **Report** button under every answer (kind + note; the owner sees counts by kind and model in Settings > Owner > Answer reports, and can download them as a lessons file); **Continue** when an answer stopped at its length limit; **search** over your chats; **edit and ask again** on your own messages; **Branch** a chat from any answer; **pin** chats and put them in **folders** (the ... menu). The privacy page now says what a report sends.
- **VryxCode and languages:** a language chooser (what you asked for, the project's own language, or a recommendation by task) that also checks what can run on this computer, in the sandbox or on a cloud machine; "Suggested language: X, because..." shows in the session; syntax checks for Go, PHP, Ruby, C, C++ and Java (when installed); and `coding/bench_languages.py`, a twelve-program test in nine languages with its own self-test. See [VRYXCODE.md](VRYXCODE.md). The models have not been run on the language test yet.
- **Everything left on the accounts list is built:** **passkeys** (fingerprint, face or screen lock; also checked against a real Chromium virtual authenticator), **Continue with Google** (needs a Google client id from the owner), **custom instructions** (Settings > Memory), mail settings in `keys.env` plus a **Send a test email** button, and VryxCode's **Cloud machine** (run code on another computer over SSH, with a built-in key maker and connection test). See [ACCOUNTS.md](ACCOUNTS.md) and [VRYXCODE.md](VRYXCODE.md). Not run against the real services: Google, a real phone's passkey, a real remote machine, the real models with custom instructions.
- **21 connected apps, all free and read-only:** Calendar (a private iCal link: Google, Apple, Outlook), Email (IMAP with an app password: Gmail, Outlook, iCloud, Yahoo), News feeds, Todoist, Raindrop, Readwise, Home Assistant, Notion, Slack, Linear, Asana, ClickUp, Trello, Jira, Dropbox, GitLab, Hugging Face, Vercel, Netlify, Cloudflare, Supabase. Ask in a chat ("what is on my calendar tomorrow?") and the matching items are read; private chats never use them. See [CONNECTED_APPS.md](CONNECTED_APPS.md).
- **Invite codes from the website:** the home page has a "Try Emvryx" box; the code goes to Create account in the app, prefilled. Owners can copy an invite link. The two-step setup now shows a **QR code** (drawn in the page, no outside library; checked to decode at every size). The website also has a **VryxCode** section.
- **Accounts, sign-in and Settings rebuilt.** A new sign-in / create-account screen (name or email + password, email code, access key); passwords; **two-step sign-in** with any authenticator app plus recovery codes; sign-up rules (closed / invite only / open) with invite codes; and a full **Settings** page with search: General, Chat and lookups, Memory, Data controls, Connected apps, Security (password, two-step, devices, recent activity), Account, About. The **owner** gets extra pages: Overview (safe-to-share checklist, last-hour numbers, pause), People (reset someone's two-step), Sign-ups and invites, Security log. Settings now survive a restart. See [ACCOUNTS.md](ACCOUNTS.md).
- API keys can live in `.emvryx\keys.env` (read at start, never committed). A "time-sensitive" answer that only used Wikipedia now says so under the reply, and answers like "there is no specific information about..." later in the text now trigger the second try.
- No more "Loading model (first message only)" message: the picked model is loaded in the background when you choose it, open the app or start a new chat, and the normal thinking words carry on if it is still starting. Settings can list which live sources are on.
- **VryxCode workflow:** modes (Ask / Auto-edit / Plan first, with Build it), a to-do list the model keeps, `/` commands, `@file` mentions, `VRYX.md` project instructions (`/init`), and a Files / Changes / Rewind panel.
- **VryxCode home:** a Sessions list with cards (title, project, where it ran, time, spinner, summary), saved on disk; per-session **environments** (this computer, isolated sandbox, cloud placeholder); **Rewind** to before any of the last 8 messages; the preview opens beside the chat on wide screens. See [VRYXCODE.md](VRYXCODE.md).
- Phone fit fixes for VryxCode's menus and top bar; pictures: preview, sent with the message, optional vision helper ([VISION.md](VISION.md)).
- **Wording and names:** the website and docs now present Emvryx as one family of five models and no longer name the open foundation models (credits stay in `NOTICE`, as the licence requires). The lesson files were renamed to match: `data_prep/make_chat_data_open.py`, `data_prep/open_lessons.py`, `scripts/wrap_open.sh`, `docs/OPEN_LESSONS.md`, `data/open/`. The outside coding model's id is now `coder-14b`.
- Apogee 2 is a beta in the app (its 4-bit file is on the PC).
- **Attach menu:** the + button is now a small menu (files, photos or screenshots, a folder, your documents) instead of a full-screen box. Pictures have their words read; photos can't be described yet.
- **Teacher mode is its own chat:** type anything, or tap a tool chip; a Tools button stays in the chat.

### Models
- **All four open-base models were retrained with the open-base lessons** (`data/open/chat.jsonl`, 10,419 chats plus 1,000 corrected identity lessons; see [OPEN_LESSONS.md](OPEN_LESSONS.md)). Cloud runs on rented GPUs, each backed up to the private Hugging Face repo.
- **Apogee 2 (the 14B open base) is trained.** Identity 16/16. Its 4-bit file (Q4_K_M) is 8.4 GB instead of 28.2 GB; it is in the app as "planned" until the file is on the PC.
- **Measured (full HellaSwag):** Flare 2.5 **65.3%** (plain base 65.6%), Equinox 2 **69.1%**. Solstice 2 73.6% (base 71.9%). Identity 16/16 on Equinox 2, Solstice 2 and Apogee 2.
- Rules sheet: Flare 22/30 (base 23), Equinox 24/30 (base 7), Solstice 26/30 (base 9). MBPP: Equinox 62%, Solstice 66%. VryxCode exercises (10): Equinox 4 first try / 5 after a retry, Solstice 5 / 5.
- Picker taglines: Flare "Fastest", Equinox "Everyday" (the one to leave loaded), Solstice "Stronger", Apogee "Strongest".

### App
- **Skills**: seven reply styles per chat (study, teacher, writing, story, IT, recipe, planner). [SKILLS.md](SKILLS.md)
- **Teacher mode**: lesson plans, quizzes, rubrics, parent emails and more; calculators for class stats, weighted grade, needed-on-final, curve, points plan and reading level; save as PDF, Word or Google Docs. [TEACHER_MODE.md](TEACHER_MODE.md)
- **Documents**: upload PDF, Word or text files (10 MB each, 40 per person) and attach them to a chat; answers use them first. [DOCUMENTS.md](DOCUMENTS.md)
- **Live facts**: about 50 free sources (exact maths, dates, time zones, currency, crypto, stocks, sports, weather history, holidays, news, books, recipes, nutrition, earthquakes, filings, papers and more), always labelled with their source and skipped in private chats. [LIVE_DATA.md](LIVE_DATA.md)
- **Usage tank is a 6-hour window**: your first message starts it; everything refills together six hours later. Pulling updates or restarting no longer refills it.
- The app reopens the chat you were last in; the sidebar is tidier; the lookup falls back correctly for "look up online"; cloud commands were added to the docs.

### Repository
- Code moved into folders: `app/`, `coding/`, `core/`, `training/`, `data_prep/`, `evaluation/`, `tools/`, `scripts/`. `app_server.py` stays at the top (the Windows autostart runs it from there). Commands now read `python training/finetune_open.py ...` and `bash scripts/wrap_open.sh ...`. The README has a "Where things are" map.
- 931 tests pass.

### Website
- Models page: a test-scores table (HellaSwag, identity, rules, MBPP, VryxCode) with base comparisons, updated statuses (Equinox and Solstice beta, Apogee trained and testing).
- Home page: new cards for looked-up facts, exact numbers, Skills and Teacher mode, documents and VryxCode. Usage and plans pages describe the 6-hour window.

### Lessons learned
- Hugging Face private storage counts about 15 minutes late after deletes: upload small adapters and the 4-bit file, not the 29 GB merged model.
- Conversion needs free disk; `llama-quantize` must be built on a fresh cloud machine.
- Plain the newer open bases bases score near zero on some of our sheets because of the hidden `<think>` block, so those gaps are not quoted as gains.
