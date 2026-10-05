# VryxCode: Emvryx's coding assistant (planned)

VryxCode is a separate part of Emvryx made for code: it reads a project, proposes changes, runs the tests and tries again, the way Claude Code does, but running on **your own models, on your own machine**.
It is the coding helper from the roadmap ("Agentic coding") given its own name, its own screen and its own rules. Nothing here is built as a product yet; the engine underneath is (see "What already exists").

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

## What already exists
- `harness.py`: a sandbox that reads a file, edits a file, runs a command and runs tests, all inside a temporary copy.
- `agent_tasks.py`, `agent_lessons.py`, `make_agent_data.py`: tiny practice projects and the lessons for tool use, project notes, asking first, "too big" and carrying on after old steps are folded away.

## What is still needed
- Tool calling in Qwen's own format (our lessons use our own tool tokens; see `open_tokenizer.py`: the open format has none yet).
- A coding model choice: Qwen's code-specialised models might beat the general ones for this (from memory; check they exist at the sizes we want, and their licences).
- A coding test sheet: small tasks with tests, scored by how many pass, run on every model before it gets VryxCode (like the other sheets, `eval/*.jsonl`).
- A permission model: what it may read, write and run without asking, shown in the terminal.
- Practice data for the open base (tasks run in the sandbox by a stronger open model; no ChatGPT, Claude or Gemini output).

## Name
VryxCode follows the family (Emvryx, Ember, Flare...). **A first quick check (Oct 2026, a Google AI answer, so only a rough sign):** it said "VryxCode" was not registered or pending at the USPTO. That is encouraging but is not a clearance search: before a public launch, search the USPTO trademark database yourself (or ask a trademark attorney) for similar names in software, check for confusingly similar existing brands, and check domains and app-store names, like the other names.
