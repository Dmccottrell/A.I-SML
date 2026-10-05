# VryxCode: Emvryx's coding assistant (first version built: terminal, Oct 2026)

VryxCode is a separate part of Emvryx made for code: it reads a project, proposes changes, runs the tests and tries again, the way Claude Code does, but running on **your own models, on your own machine**.
It is the coding helper from the roadmap ("Agentic coding") given its own name, its own screen and its own rules. The first version is built as a terminal tool (`vryxcode.py`); the app screen is not. It is tested with scripted and fake models only: **nobody has run it with a real Qwen model yet**, so its real quality is unknown until the first model is trained.

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

## Name
VryxCode follows the family (Emvryx, Ember, Flare...). **A first quick check (Oct 2026, a Google AI answer, so only a rough sign):** it said "VryxCode" was not registered or pending at the USPTO. That is encouraging but is not a clearance search: before a public launch, search the USPTO trademark database yourself (or ask a trademark attorney) for similar names in software, check for confusingly similar existing brands, and check domains and app-store names, like the other names.
