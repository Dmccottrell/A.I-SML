# VryxCode: Emvryx's coding assistant (first version built: terminal, Oct 2026)

VryxCode is a separate part of Emvryx made for code: it reads a project, proposes changes, runs the tests and tries again, the way Claude Code does, but running on **your own models, on your own machine**.
It is the coding helper from the roadmap ("Agentic coding") given its own name, its own screen and its own rules. The first version is built as a terminal tool (`vryxcode.py`); the app screen is not. It is tested with scripted and fake models only: **nobody has run it with a real Qwen model yet**, so its real quality is unknown until the first model is trained.

> **First real-model results (Oct 6 2026):** on 10 practice exercises, first try / after a retry: Qwen2.5-Coder-14B (outside model) 8 / 9, Solstice 2 5 / 5, Equinox 2 4 / 5. The agent loop, tool format and permission flow all worked with real models. See [BENCHMARKS.md](BENCHMARKS.md).

## Which models can run it
VryxCode is **only offered on the higher models**:

| Model | VryxCode | What to expect |
|---|---|---|
| Ember 2, Flare 2, Flare 2.5 | **No** | Too small for a reliable coding loop. The app says so and offers a higher model |
| **Equinox 2** (Qwen3-4B) | **Yes, small tasks** | One function, a one-file fix, a test for existing code, explaining code. Expect more mistakes and more retries |
| **Solstice 2** (Qwen3-8B) | **Yes** | The normal choice: small to medium tasks over a few files |
| **Apogee 2** (Qwen3-14B) | **Yes, best** | The strongest local option; still smaller than the big cloud assistants |

In `models.json` the three eligible entries carry `"vryxcode": true`; the picker greys VryxCode out for the others with the reason. Equinox is included but carries a "best for small tasks" note.

## What it is for, and what it is not
- **For:** private and offline coding help (your code never leaves the PC), free once the model is trained, in the same Emvryx family and app.
- **Not:** a match for the largest cloud coding assistants. It handles small and medium tasks. Large refactors and very long unattended sessions are out of reach for a 4B to 14B model. Say so in the app instead of letting it fail quietly.

## Stages (build one at a time, test each)
1. **Read-only:** explain code, find where something happens, answer questions about a repository (needs lookups over files and the 32K context).
2. **Edits with approval:** the model proposes a diff; you accept or reject each change.
3. **Test loop:** edit, run the tests, read the failure, try again, within a step limit.
4. **Multi-file tasks and git:** several files, branches and commits, always **asking before** a commit or anything destructive (the habit is already in `agent_lessons.py`).
First as a terminal tool (`vryxcode` in a project folder), because it is the simplest to build and test. An app screen comes after.

## Using it
```
llama-server -m export/open/solstice-2/my-ai-q4_k_m.gguf -c 32768 --port 8080     # open_models.llama_args("solstice-2") prints the options
cd your-project
python /path/to/vryxcode.py --model solstice-2 "add a function to utils.py that slugifies a title, with tests"
python vryxcode.py --model solstice-2            # no task: interactive
python vryxcode.py --demo                         # a scripted run, no model needed
```
- It works inside the project folder only, asks before it writes, edits or runs anything (showing what; `y`, `n` or `a` for always), and never asks to run the project's tests. `--yes` stops the questions for edits and runs; `git commit` and unknown tools always ask.
- `--allow node,npm` lets it run more programs; the sandbox has no network on Linux, so installs fail there.
- It refuses Ember 2, Flare 2 and Flare 2.5, and tells Equinox 2 users to keep tasks small.
- Qwen's own tool-call format (`<tool_call>`) and our `<|tool_call|>` format both work, and `<think>` blocks are dropped.

## In the chat app: the Code screen

The app has a dedicated **VryxCode** entry in the left menu (like Claude Code or Codex next to their chat). It opens a full screen: a feed of what the model does (each step, each result), a file list with a viewer, a project picker, a model picker and a task box.

- **Projects** are folders on the server, `<data>/code/<person>/<project>/`. Each person only reaches their own; names are letters, digits, dashes and underscores. The model is confined to the project by the same sandbox as the terminal tool.
- **Models:** only the ones flagged `"vryxcode"` (Equinox 2 and above) that are ready on this server. Equinox shows its "small tasks" note.
- **Permissions:** edits and runs show a card with *Allow*, *Always allow this* and *No*; running the unit tests never asks. "Auto-approve edits" skips the questions for the session. **Stop** ends the run at the next step.
- One session per person at a time. The page polls `/api/code/sessions/<id>?after=N`; closing the page does not stop a run, and reopening the screen reattaches to it.
- Server side: `code_sessions.py` (engine thread, events, questions) and the `/api/code/...` routes in `app_server.py`. Tests: `tests/test_code_sessions.py`.
- **Usage:** every model call in a session is counted like a chat message: the same tank, the same weekly allowance and the same model weight (Equinox/Solstice/Apogee cost more than Flare). Before a step the likely cost is held; afterwards the real counts from llama-server replace it (cached prompt tokens count less). The Code screen shows the plan, tank, week and "about N coding steps left", and this run's steps and tokens. When the plan runs out the session stops with "Your usage ran out" and the files so far are kept; the owner is never limited. Coding sessions use many steps with growing prompts, so they use far more than a chat message: expect plans to drain faster.
- **Download zip** gives the whole project (without `.git`, caches, `node_modules`). **Import...** takes a zip or a whole folder (up to 1,000 files, 20 MB, 2 MB each; paths that leave the project are refused and nothing is imported; `.git` and `node_modules` are skipped; same-named files are replaced). Not while a session is running.
- **`<think>` text:** the chat now hides Qwen3's reasoning block as it streams (`app_engine.strip_think`), so it is neither shown nor saved; VryxCode strips it as before. Reasoning tokens are generated, but only the real counts from the server are charged.

## Using an outside coding model (for the best local coding today)
`--coder LABEL` runs VryxCode on any coding model you start in llama-server, such as Qwen2.5-Coder-14B-Instruct or Qwen3.5-9B (both fit a 12 GB card at 4 bits; check the licence on each model's page). It skips the Emvryx model gate and labels the run as an outside model, so its scores are never mistaken for an Emvryx result. `bench_exercises.py` and `vryx_swe.py` take the same flag, so the candidates can be compared on the same exercises.
```
llama-server -m models\coder\qwen2.5-coder-14b-instruct-q4_k_m.gguf -c 12288 -ngl 99 -fa on -ctk q8_0 -ctv q8_0 --port 8080
python vryxcode.py --coder qwen2.5-coder-14b "add a function that slugifies a title, with tests"
python bench_exercises.py --coder qwen2.5-coder-14b --exercises python\exercises\practice --limit 10
```

## Collecting training runs (`collect_runs.py`)
A coding agent is trained on its own checked successes. `collect_runs.py` runs a model through VryxCode on practice tasks (Exercism exercises with `--exercises`, and fresh made-up bug-fix tasks with `--synthetic N`) and keeps a run only if the tests pass when **we** run them, it did not edit the test files, it changed a file and ran the tests, and it did not fall into a spiral of tool errors; rejected runs are counted by reason and not saved. The output is chat examples (`logs/agent_runs.jsonl`) that `finetune_open.py` trains on, with the label of the model that wrote them (open models only). `--samples K` tries each task K times; `--format qwen` writes Qwen's own `<tool_call>` markers (then VryxCode's system prompt would need the same format).
```
python collect_runs.py --coder qwen2.5-coder-14b --exercises python/exercises/practice --limit 20 --synthetic 40 --out logs/agent_runs.jsonl
python finetune_open.py --model solstice-2 --patch --data logs/agent_runs.jsonl      # a short extra pass on the saved adapter
```
Tested with scripted models only. Nothing has been trained on collected runs yet: first look at how many runs are accepted and read a few, and compare the exercise scores before and after.

## What already exists
- `harness.py`: a sandbox that reads a file, edits a file, runs a command and runs tests, all inside a temporary copy.
- `agent_tasks.py`, `agent_lessons.py`, `make_agent_data.py`: tiny practice projects and the lessons for tool use, project notes, asking first, "too big" and carrying on after old steps are folded away.

## What is still needed
- Running it on a real model and measuring it with the coding test sheet (the biggest unknown).
- An app screen (the terminal comes first).
- Tool calling in Qwen's own format (our lessons use our own tool tokens; see `open_tokenizer.py`: the open format has none yet).
- A coding model choice: Qwen's code-specialised models might beat the general ones for this (from memory; check they exist at the sizes we want, and their licences).
- A coding test sheet: small tasks with tests, scored by how many pass, run on every model before it gets VryxCode (like the other sheets, `eval/*.jsonl`).
- A permission model: what it may read, write and run without asking, shown in the terminal.
- Practice data for the open base (tasks run in the sandbox by a stronger open model; no ChatGPT, Claude or Gemini output).

## Benchmarks
The agentic coding benchmarks (SWE-bench Verified, Lite and Pro, Terminal-Bench, the Aider benchmark, LiveCodeBench) and what each needs are in [BENCHMARKS.md](BENCHMARKS.md). Two tools are built (tested with scripted models only): `bench_exercises.py` (Aider-style Exercism exercises, two tries, no Docker) and `vryx_swe.py` (makes SWE-bench-style patches that the official checker scores on a Docker machine). The plan: prove VryxCode on a real model first, then run the exercises, then SWE-bench Lite.

## Name
VryxCode follows the family (Emvryx, Ember, Flare...). **A first quick check (Oct 2026, a Google AI answer, so only a rough sign):** it said "VryxCode" was not registered or pending at the USPTO. That is encouraging but is not a clearance search: before a public launch, search the USPTO trademark database yourself (or ask a trademark attorney) for similar names in software, check for confusingly similar existing brands, and check domains and app-store names, like the other names.
