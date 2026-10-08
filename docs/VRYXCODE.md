# VryxCode: Emvryx's coding assistant (first version built: terminal, Oct 2026)

VryxCode is a separate part of Emvryx made for code: it reads a project, proposes changes, runs the tests and tries again, the way Claude Code does, but running on **your own models, on your own machine**.
It is the coding helper from the roadmap ("Agentic coding") given its own name, its own screen and its own rules. The first version is built as a terminal tool (`coding/vryxcode.py`); the app screen is not. It is tested with scripted and fake models only: **nobody has run it with a real the open base model yet**, so its real quality is unknown until the first model is trained.

> **First real-model results (Oct 6 2026):** on 10 practice exercises, first try / after a retry: an outside coding model (outside model) 8 / 9, Solstice 2 5 / 5, Equinox 2 4 / 5. The agent loop, tool format and permission flow all worked with real models. See [BENCHMARKS.md](BENCHMARKS.md).

## Sessions, environments and Rewind (the Code home screen)
**Menu > VryxCode** opens a Sessions list, like a to-do list of everything VryxCode has worked on: a card per session with its title, project, where it ran, how long ago, a spinner while it works (or "Needs you" when it is asking permission, or Failed / Interrupted), a short summary, and how many steps and files it changed. Tap a card to open it (a running one carries on live; a finished one reads as it happened, also after the app was restarted). **New session** starts one. The filter shows All, Running, Needs you or Finished.
- **History:** every session is saved as it goes in `.emvryx/code/<you>/.sessions/` (kept out of project lists and downloads; the newest 60 are kept). A session that was working when the app stopped shows as Interrupted. A finished session can't be continued by the model after a restart, so typing in it starts a follow-up session in the same project.
- **Environments:** pick where the code runs when you start a session. **This computer** works in the project folder with the short list of allowed programs. **Isolated sandbox** runs in a locked Docker container (no internet, limited memory and time); it is offered only when Docker is running and the sandbox image is built, and a session never quietly falls back to the computer when you asked for the sandbox. If the owner started the app with the sandbox for everyone, that is what every session uses. **Cloud machine** runs the commands on another computer over SSH (for example a rented Vast.ai box): see "Cloud machine" below.
- **Rewind:** before each of your messages VryxCode saves a snapshot of the project (the last 8 messages of each of your 10 newest sessions, up to 5 MB each). The Rewind tab (in the Files panel, or `/rewind`) lists them ("Before message 2: ...") and puts the files back as they were; files made since are removed and `.git` is left alone. The model's memory of that session is cleared, so it won't act on files that no longer exist.
- **Live preview:** on a wide screen the preview opens beside the chat by itself the first time a web page exists, and reloads after each change; on a phone the Preview button lights up when the page changes.

## Working like a coding teammate: modes, to-do list, commands, @files, VRYX.md, Changes
- **Modes** (the pill next to the environment, or `/plan` `/ask` `/auto`): **Ask before editing** (default), **Edit without asking** (also asks before anything riskier) and **Plan first**. In Plan first the model may only look (list, read, check): writing, editing, running and git are refused. It answers with a short numbered plan and the page shows **Build it** and **Change the plan**. Build it switches back to your earlier mode and tells it to go ahead; the plan stays in the conversation, so it builds what it planned.
- **To-do list:** for a job with more than two steps the model keeps a checklist (its `todo` tool). A card above the chat shows it filling in with a progress bar; tap it to fold it. The tool only records the list; it changes nothing in the project. (Small models sometimes skip it; the work still happens.)
- **Slash commands:** type `/` in the message box: `/plan`, `/ask`, `/auto`, `/init`, `/review`, `/rewind`, `/files`, `/preview`, `/new`, `/help`.
- **@files:** type `@` and pick a file (or write `@notes.txt`): its contents (up to 5 files, 6 KB each) go to the model with that message. Your message still shows as you wrote it. Paths outside the project are ignored.
- **Project instructions:** `/init` creates `VRYX.md` (what the project is, how to run and test it, style rules, things not to touch). VryxCode reads it, up to 3,000 letters, at the start of every session in that project (`EMVRYX.md` and `AGENTS.md` are read too, if there is no VRYX.md).
- **Changes:** the Files panel has Files, **Changes** (each file the session changed with +/- counts and the lines added or removed; long edits show only their first lines, and Open the file shows everything) and Rewind tabs.

## Cloud machine (another computer over SSH)
The owner sets it up in **Settings > Owner > Cloud machine**: type the host, port and user from the rented machine's Connect button, press **Make a key** (the private half stays on the Emvryx computer, the public half is shown to copy into the machine, on Vast.ai under Account > SSH Keys), then **Test the connection**. After that, **Cloud machine** is an environment you can pick when you start a session. By default only the owner can use it; there is a switch to let other people use it.
- **How it runs:** `coding/cloud_run.py` sits in front of every command, like the Docker sandbox does. It packs the project (without `.git`, caches, `node_modules` and virtual environments), sends it over SSH into a fresh folder `~/emvryx-work/<person>-<project>` on the machine, runs the command there with a time limit, fetches the folder back, and copies **new and changed files** into the project. Output and exit code come back as if it ran here. `git` always stays on the Emvryx computer. The machine needs `python3`, `tar` and `timeout` (any Linux box has them).
- **Safety:** the machine's identity is remembered the first time (trust on first use). What comes back is filtered: absolute paths, `..`, links and device files are dropped, and the total size is capped at 100 MB. The key is never sent anywhere and is not shown in the page. What the model runs there is its code on your machine, which is why others are off by default.
- **Tested** against a stand-in SSH that runs the remote command in a throwaway folder on the same computer (uploading, running, bringing files back, exit codes, an unreachable machine, hostile archives); **not yet against a real remote machine**. The Test button shows the real result.

## Live preview
When a project has a web page (an `.html` file, `index.html` first), the **Preview** button in VryxCode's header opens it live inside the app, in a phone, tablet or wide frame, and refreshes it when VryxCode finishes a change.
The page's own problems are collected as it runs: script errors, failed promises, `console.error`, and files that do not load (a missing picture, stylesheet or script). They are listed under the preview with a button,
**Ask VryxCode to fix these**, which sends them to VryxCode as your next message so it can repair them and you can reload. Safety: the preview is served only to the person who owns the project, through a link with a random token
that expires after two hours, and every answer carries `Content-Security-Policy: sandbox`, so what VryxCode wrote runs with an empty identity (no access to the app's cookies, storage or data), also if you open it in its own tab.
Files outside the project folder, `.git` and `.emvryx` are never served. Server programs (Flask, Node and so on) are not previewed, because the sandbox has no network: VryxCode tells you how to run those on your own computer.

## Which language: the chooser, what can run, and the language test
Before the model plans, `coding/languages.py` decides the language with plain rules (not a model), tells the model, and shows you a line when it matters:
- **You named one** ("in Go", "a Rust tool", "do it in C#"): that one wins. Ordinary words are not languages ("give it a go", "go ahead", a lone letter c).
- **The project already has code**: it keeps that language (counted from file endings, ignoring `node_modules`, `.git` and similar) unless you say "new project", "rewrite", "port" or name another.
- **Otherwise it recommends** by what you asked for: websites, browser games, phone apps (a phone-friendly web page first) get HTML, CSS and JavaScript; scripts, data, files, exercises, desktop windows get Python; APIs get Python (Flask or FastAPI) or Node; fast or low-level programs get Go, Rust, C++ or C; SQL gets SQLite. The page shows "Suggested language: X, because ..." and the model is told to say it in one sentence. You can always answer "use Python instead".
- **It checks what can run.** On this computer it looks for the programs that are installed; in the Docker sandbox it uses the image's list (Python, Node, C and C++, SQLite); for a cloud machine it cannot know and tells the model to check with a quick command. If the best fit is not installed it picks the next best that is, and says so; if nothing fits it still picks the best and says "VryxCode will write it and tell you how to run it".
- **Syntax checks before saving** now cover Python, JSON, JavaScript, **Go** (`gofmt`), **PHP** (`php -l`), **Ruby** (`ruby -c`), **C and C++** (`-fsyntax-only`) and **Java** (`javac`), each only when that tool is installed. Only real syntax errors are reported: a missing class, header or import (which usually lives in another file) is never flagged.
- **Measuring it:** `python coding/bench_languages.py --model solstice-2 --llama http://127.0.0.1:8080 --langs python,javascript,go,java,cpp,rust` asks for the same twelve small programs (sum, FizzBuzz, reverse words, primes, word count, palindromes, Fibonacci, gcd, sorting, Roman numerals, anagrams, brackets) in each language, builds and runs them with our own tests, and gives a second try with the error. It reports first-try and after-retry per language and how often a program failed to compile. `--selftest` proves the tests themselves are fair (reference solutions pass in all nine languages here; a wrong answer fails). **No model has been run on it yet**, so how well each model writes each language is still unmeasured: that is the next step on the PC.

## Languages and frameworks
VryxCode follows the language or framework you ask for. If you do not name one it recommends what fits and says why in a sentence (you can ask for something else): a website, landing page, small web app, browser game or tool
with buttons gets plain HTML, CSS and JavaScript (no build step, so it previews at once, with libraries loaded from a CDN if needed); a script, automation or data job gets Python; a command-line tool gets Python (Go or Rust if you want one
fast program); a server or API gets Python (Flask or FastAPI) or Node (Express) with SQLite; a phone app gets a phone-friendly web app first, or React Native or Flutter for a store app; a desktop app gets Python or a web page, or Electron or Tauri to
package it; a game gets canvas JavaScript, or Godot or Unity for a bigger one. What it can **run** depends on the machine: the sandbox image has Python (with Flask, FastAPI, requests, numpy and pytest), Node.js, C and C++ compilers and SQLite
(rebuild the image after updating: `docker build -t emvryx/code-sandbox:1 docker/code-sandbox`; add more languages in `docker/code-sandbox/Dockerfile`); without Docker it uses what is installed on the PC. Allowed programs: python, node, gcc, g++, go, java,
php, ruby, rustc and sqlite3, plus the usual file tools. Package managers (npm, pip, cargo) and `make` are not allowed (they download and run other people's code, and there is no internet in the sandbox): for projects that need them
VryxCode writes the code and tells you the commands to run yourself, such as `npm install` and `npm run dev`. Python, JSON and JavaScript changes are syntax-checked before they are saved (JavaScript when Node is installed).

## Checks before and after a change
VryxCode looks at a Python or JSON change **before** it is made. If the file would not even parse (a syntax error, an invalid JSON file, or, when pyflakes is installed, an undefined name), nothing is saved, you are not asked
to approve it, and the model is told what is wrong so it can fix it and try again. A good change shows "Checked: no problems found" on the approval card and "checked" on the result line. Before it finishes, if code changed
since the tests last passed and the project has tests, it is asked once to run them first. Benchmarks and data collection (`coding/bench_exercises.py`, `coding/vryx_swe.py`, `coding/collect_runs.py`) switch these checks off (`checks=False`),
because they measure the model on its own and must stay comparable with earlier results.

## Talking to VryxCode (a conversation, not just a task)
VryxCode can answer in plain words as well as use its tools. When it replies in words with no tool call, that ends its turn and shows as a message; you answer in the same box and the next
message continues the same conversation (the model sees everything said and done so far, as long as the project and the model stay the same; pick another project or model to start fresh).
It uses this to explain what it changed, to answer questions, to tell you what **you** have to do (for example a command to type in PowerShell, shown in a box with a **Copy** button),
to say what it cannot do from inside the project folder (installing programs, using the internet, anything outside the folder), and to recommend what to do next. When it finishes work it calls
`finish` with a friendly summary and up to three **Suggested next** buttons you can tap. If a model pastes program code into the chat before doing any work, it is told once to save the code
with `write_file` instead; commands to type are fine. Stop works at once, also while it is thinking or the model is loading.

## Which models can run it
VryxCode is **only offered on the higher models**:

| Model | VryxCode | What to expect |
|---|---|---|
| Ember 2, Flare 2, Flare 2.5 | **No** | Too small for a reliable coding loop. The app says so and offers a higher model |
| **Equinox 2** (the 4B open base) | **Yes, small tasks** | One function, a one-file fix, a test for existing code, explaining code. Expect more mistakes and more retries |
| **Solstice 2** (the 8B open base) | **Yes** | The normal choice: small to medium tasks over a few files |
| **Apogee 2** (the 14B open base) | **Yes, best** | The strongest local option; still smaller than the big cloud assistants |

In `models.json` the three eligible entries carry `"vryxcode": true`; the picker greys VryxCode out for the others with the reason. Equinox is included but carries a "best for small tasks" note.

## What it is for, and what it is not
- **For:** private and offline coding help (your code never leaves the PC), free once the model is trained, in the same Emvryx family and app.
- **Not:** a match for the largest cloud coding assistants. It handles small and medium tasks. Large refactors and very long unattended sessions are out of reach for a 4B to 14B model. Say so in the app instead of letting it fail quietly.

## Stages (build one at a time, test each)
1. **Read-only:** explain code, find where something happens, answer questions about a repository (needs lookups over files and the 32K context).
2. **Edits with approval:** the model proposes a diff; you accept or reject each change.
3. **Test loop:** edit, run the tests, read the failure, try again, within a step limit.
4. **Multi-file tasks and git:** several files, branches and commits, always **asking before** a commit or anything destructive (the habit is already in `coding/agent_lessons.py`).
First as a terminal tool (`vryxcode` in a project folder), because it is the simplest to build and test. An app screen comes after.

## Using it
```
llama-server -m export/open/solstice-2/my-ai-q4_k_m.gguf -c 32768 --port 8080     # open_models.llama_args("solstice-2") prints the options
cd your-project
python /path/to/vryxcode.py --model solstice-2 "add a function to utils.py that slugifies a title, with tests"
python coding/vryxcode.py --model solstice-2            # no task: interactive
python coding/vryxcode.py --demo                         # a scripted run, no model needed
```
- It works inside the project folder only, asks before it writes, edits or runs anything (showing what; `y`, `n` or `a` for always), and never asks to run the project's tests. `--yes` stops the questions for edits and runs; `git commit` and unknown tools always ask.
- `--allow node,npm` lets it run more programs; the sandbox has no network on Linux, so installs fail there.
- It refuses Ember 2, Flare 2 and Flare 2.5, and tells Equinox 2 users to keep tasks small.
- the base's own tool-call format (`<tool_call>`) and our `<|tool_call|>` format both work, and `<think>` blocks are dropped.

## In the chat app: the Code screen

The app has a dedicated **VryxCode** entry in the left menu (like Claude Code or Codex next to their chat). It opens a full screen: a feed of what the model does (each step, each result), a file list with a viewer, a project picker, a model picker and a task box.

- **Projects** are folders on the server, `<data>/code/<person>/<project>/`. Each person only reaches their own; names are letters, digits, dashes and underscores. The model is confined to the project by the same sandbox as the terminal tool.
- **Models:** only the ones flagged `"vryxcode"` (Equinox 2 and above) that are ready on this server. Equinox shows its "small tasks" note.
- **Permissions:** edits and runs show a card with *Allow*, *Always allow this* and *No*; running the unit tests never asks. "Auto-approve edits" skips the questions for the session. **Stop** ends the run at the next step.
- One session per person at a time. The page polls `/api/code/sessions/<id>?after=N`; closing the page does not stop a run, and reopening the screen reattaches to it.
- Server side: `coding/code_sessions.py` (engine thread, events, questions) and the `/api/code/...` routes in `app_server.py`. Tests: `tests/test_code_sessions.py`.
- **Usage:** every model call in a session is counted like a chat message: the same tank, the same weekly allowance and the same model weight (Equinox/Solstice/Apogee cost more than Flare). Before a step the likely cost is held; afterwards the real counts from llama-server replace it (cached prompt tokens count less). The Code screen shows the plan, tank, week and "about N coding steps left", and this run's steps and tokens. When the plan runs out the session stops with "Your usage ran out" and the files so far are kept; the owner is never limited. Coding sessions use many steps with growing prompts, so they use far more than a chat message: expect plans to drain faster.
- **Download zip** gives the whole project (without `.git`, caches, `node_modules`). **Import...** takes a zip or a whole folder (up to 1,000 files, 20 MB, 2 MB each; paths that leave the project are refused and nothing is imported; `.git` and `node_modules` are skipped; same-named files are replaced). Not while a session is running.
- **`<think>` text:** the chat now hides the newer open bases's reasoning block as it streams (`app_engine.strip_think`), so it is neither shown nor saved; VryxCode strips it as before. Reasoning tokens are generated, but only the real counts from the server are charged.

## The coding engine choice in the app (outside coder)

The Code screen's model picker lists the Emvryx models that can code (Equinox 2 and above) **and** the outside coding model **an outside coding model**, always labelled "(outside model)" with a note that it is not an Emvryx model and does not carry Emvryx's lessons. It scored 8 / 9 of 10 exercises (first try / after a retry), against 4 / 5 for Equinox 2 and 5 / 5 for Solstice 2, so it is the best coding engine available today.

- It is listed in `models.json` under `coders` (its own entry, not a chat model: it never appears in the chat picker).
- It counts against usage like Solstice (`plan_like`), and is in a plan only if Solstice is. The owner is unlimited.
- On a 12 GB GPU the Q4 file (about 9 GB) fits with a short window (8,192 tokens, `context_tested`), so VryxCode compacts old steps sooner.
- Put the file where the app finds it, or name it yourself: `hf download <coder-model-repo> --include "*q4_k_m*" --local-dir export/open/coders`, then start the app with `--gguf coder-14b=<path to the .gguf>` (for a file split in parts, the first one, `...-00001-of-0000N.gguf`) and `--llama-args "-ngl 99"`.

**Plan (option C):** use the outside coder now; then collect more successful runs (the first 44 are backed up in the Hugging Face repo under `bench-logs-2026-10-06`) and train Solstice and Equinox on them, so an Emvryx model can drive VryxCode as well. That training is not started and needs approval and budget.

## The coding engine choice in the app (outside coder)

The Code screen's model picker lists the Emvryx models that can code (Equinox 2 and above) **and** the outside coding model **an outside coding model**, always labelled "(outside model)" with a note that it is not an Emvryx model and does not carry Emvryx's lessons. It scored 8 / 9 of 10 exercises (first try / after a retry), against 4 / 5 for Equinox 2 and 5 / 5 for Solstice 2, so it is the best coding engine available today.

- It is listed in `models.json` under `coders` (its own entry, not a chat model: it never appears in the chat picker).
- It counts against usage like Solstice (`plan_like`) and is in a plan only if Solstice is. The owner is unlimited.
- On a 12 GB GPU the Q4 file (about 9 GB) fits with a short window (8,192 tokens, `context_tested`), so VryxCode compacts old steps sooner.
- To use it: `hf download <coder-model-repo> --include "*q4_k_m*" --local-dir export/open/coders`, then start the app with `--gguf coder-14b=<path to the .gguf>` (for a file split in parts, the first one, `...-00001-of-0000N.gguf`) and `--llama-args "-ngl 99"`.

**Plan (option C):** use the outside coder now; then collect more successful runs (the first 44 are backed up in the Hugging Face repo under `bench-logs-2026-10-06`) and train Solstice and Equinox on them, so an Emvryx model can drive VryxCode too. That training is not started and needs approval and budget.

## GitHub: create repositories, pull and push (a connected app)

GitHub is the first real **connected app** (Menu > Connected apps > GitHub). Connect it once with a token you make on GitHub, and VryxCode can, per project (project menu > GitHub...):

- **create a new repository** for the project (private by default) and link the project to it, **link** the project to a repository you already have, or **clone** one into an empty project;
- **pull** (fast-forward only: it never rewrites your work) and **push** (never forced; pushing to `main` or `master` needs an extra yes).

The model can do it too: when GitHub is connected and the project is linked, it gets a `github` tool with `status`, `pull` and `push`, after committing with its own `git` tool (which can now also make branches with `switch -c`). Every pull and push shows the usual **Allow / No** card, and "Always allow" and "Auto-approve edits" never cover it: it asks every time. Creating and linking repositories is a button only, never the model.

How it is kept safe (`app/github_link.py`):
- The token lives only on the server, in a private file (mode 600) per person. It is never sent to the page, never in a command line, a log, an event or a model prompt, and it is scrubbed from any git output we show. **Disconnect deletes it at once**; a short activity log (connected, created, pulled, pushed) stays on the Connected apps screen.
- Git is only ever pointed at `https://github.com/<owner>/<repo>.git`, checked from the project's own remote setting before every pull or push, and the token is attached to github.com requests only (git's per-URL header from the environment). The model's file tools cannot edit the `.git` folder (where that setting lives); the model's `git` tool has no `remote`, `config`, `push` or `-c` before the subcommand.
- Use the narrowest token: a fine-grained token limited to the repositories you choose, with Contents read and write, is enough to pull and push. Creating repositories needs a classic token with the `repo` scope (GitHub's rule).
- A project with a running coding session can't be changed by the GitHub buttons until you stop it.
- Honest limit: the command sandbox is not a wall against a deliberately hostile program (see the sandbox notes in `coding/harness.py`); these checks protect against a small model's mistakes and a tampered remote setting, not a determined attacker with a shell.
- Not built: opening pull requests and reading issues (a later step), and sign-in with GitHub's OAuth instead of a pasted token.

## Using an outside coding model (for the best local coding today)
`--coder LABEL` runs VryxCode on any coding model you start in llama-server, such as an outside coding model or a newer 9B open base (both fit a 12 GB card at 4 bits; check the licence on each model's page). It skips the Emvryx model gate and labels the run as an outside model, so its scores are never mistaken for an Emvryx result. `coding/bench_exercises.py` and `coding/vryx_swe.py` take the same flag, so the candidates can be compared on the same exercises.
```
llama-server -m models\coder\coder-14b-q4_k_m.gguf -c 12288 -ngl 99 -fa on -ctk q8_0 -ctv q8_0 --port 8080
python coding/vryxcode.py --coder coder-14b "add a function that slugifies a title, with tests"
python coding/bench_exercises.py --coder coder-14b --exercises python\exercises\practice --limit 10
```

## Collecting training runs (`coding/collect_runs.py`)
A coding agent is trained on its own checked successes. `coding/collect_runs.py` runs a model through VryxCode on practice tasks (Exercism exercises with `--exercises`, and fresh made-up bug-fix tasks with `--synthetic N`) and keeps a run only if the tests pass when **we** run them, it did not edit the test files, it changed a file and ran the tests, and it did not fall into a spiral of tool errors; rejected runs are counted by reason and not saved. The output is chat examples (`logs/agent_runs.jsonl`) that `training/finetune_open.py` trains on, with the label of the model that wrote them (open models only). `--samples K` tries each task K times; `--format open` writes the base's own `<tool_call>` markers (then VryxCode's system prompt would need the same format).
```
python coding/collect_runs.py --coder coder-14b --exercises python/exercises/practice --limit 20 --synthetic 40 --out logs/agent_runs.jsonl
python training/finetune_open.py --model solstice-2 --patch --data logs/agent_runs.jsonl      # a short extra pass on the saved adapter
```
Tested with scripted models only. Nothing has been trained on collected runs yet: first look at how many runs are accepted and read a few, and compare the exercise scores before and after.

## What already exists
- `coding/harness.py`: a sandbox that reads a file, edits a file, runs a command and runs tests, all inside a temporary copy.
- `coding/agent_tasks.py`, `coding/agent_lessons.py`, `coding/make_agent_data.py`: tiny practice projects and the lessons for tool use, project notes, asking first, "too big" and carrying on after old steps are folded away.

## What is still needed
- Running it on a real model and measuring it with the coding test sheet (the biggest unknown).
- An app screen (the terminal comes first).
- Tool calling in the base's own format (our lessons use our own tool tokens; see `core/open_tokenizer.py`: the open format has none yet).
- A coding model choice: the base's code-specialised models might beat the general ones for this (from memory; check they exist at the sizes we want, and their licences).
- A coding test sheet: small tasks with tests, scored by how many pass, run on every model before it gets VryxCode (like the other sheets, `eval/*.jsonl`).
- A permission model: what it may read, write and run without asking, shown in the terminal.
- Practice data for the open base (tasks run in the sandbox by a stronger open model; no ChatGPT, Claude or Gemini output).

## Benchmarks
The agentic coding benchmarks (SWE-bench Verified, Lite and Pro, Terminal-Bench, the Aider benchmark, LiveCodeBench) and what each needs are in [BENCHMARKS.md](BENCHMARKS.md). Two tools are built (tested with scripted models only): `coding/bench_exercises.py` (Aider-style Exercism exercises, two tries, no Docker) and `coding/vryx_swe.py` (makes SWE-bench-style patches that the official checker scores on a Docker machine). The plan: prove VryxCode on a real model first, then run the exercises, then SWE-bench Lite.

## Name
VryxCode follows the family (Emvryx, Ember, Flare...). **A first quick check (Oct 2026, a Google AI answer, so only a rough sign):** it said "VryxCode" was not registered or pending at the USPTO. That is encouraging but is not a clearance search: before a public launch, search the USPTO trademark database yourself (or ask a trademark attorney) for similar names in software, check for confusingly similar existing brands, and check domains and app-store names, like the other names.
