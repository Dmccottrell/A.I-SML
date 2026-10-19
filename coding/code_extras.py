"""
code_extras.py - What VryxCode's full agent keeps between sessions, the way Claude Code does (docs/VRYXCODE.md):

  memory        notes VryxCode keeps about the person and their projects (`remember` tool), in their own folder, read at the start of every session.
  commands      a project's own slash commands: .vryx/commands/<name>.md, the text sent when the person types /<name> (with $ARGUMENTS for what follows).
  rules         a project's saved permission rules {"permissions": {"allow": [...], "deny": [...]}}, kept in the person's own folder, OUTSIDE the project
                (rules_path), so the agent can never give itself permissions by writing a file. A rule is a tool name (write_file) or the start of a
                command (npm test, git push). Deny wins; "Yes, and don't ask again" saves an allow rule.
"""
import json
import os
import re

MEMORY_FILE = "vryx_memory.md"
MEMORY_LINES, MEMORY_CHARS = 60, 240
COMMANDS_DIR = os.path.join(".vryx", "commands")
COMMAND_NAME = re.compile(r"^/([a-z0-9][a-z0-9_-]{0,39})(?:\s+(.*))?$", re.S | re.I)
RULE = re.compile(r"^[\w .:/@=+-]{1,80}$")


# ------------------------------------------------------------------ memory
def memory_path(folder):
    return os.path.join(folder, MEMORY_FILE)


def read_memory(folder):
    """The notes kept about this person ([] when none)."""
    try:
        with open(memory_path(folder), encoding="utf-8") as f:
            return [l[2:].strip() for l in f.read().splitlines() if l.startswith("- ") and l[2:].strip()]
    except OSError:
        return []


def write_memory(folder, notes):
    os.makedirs(folder, exist_ok=True)
    with open(memory_path(folder), "w", encoding="utf-8", newline="\n") as f:
        f.write("# What VryxCode remembers about you\n\n" + "".join(f"- {n}\n" for n in notes[-MEMORY_LINES:]))


def remember(folder, note):
    """Add one note (the oldest go first past 60). Returns what the model is told."""
    note = " ".join(str(note or "").split())[:MEMORY_CHARS]
    if not note:
        raise ValueError('remember needs a note, like {"note": "Uses Tailwind for styling"}')
    notes = [n for n in read_memory(folder) if n.lower() != note.lower()] + [note]
    write_memory(folder, notes)
    return f"remembered ({len(notes[-MEMORY_LINES:])} notes kept)"


def forget(folder, index=None):
    """Remove one note (by its number, from 0) or, with no number, all of them."""
    notes = read_memory(folder)
    if index is None:
        notes = []
    elif 0 <= int(index) < len(notes):
        notes.pop(int(index))
    write_memory(folder, notes)
    return notes


def memory_note(folder):
    """The text added to the agent's instructions, or ""."""
    notes = read_memory(folder)
    if not notes:
        return ""
    return (" WHAT YOU REMEMBER ABOUT THIS PERSON (from earlier sessions; use it, and save anything new and lasting with remember(note)): "
            + "; ".join(notes))


MEMORY_TOOL_NOTE = (" remember(note) saves one short, lasting fact about the person or how they like to work (\"prefers TypeScript\", \"tests with pytest\") "
                    "for future sessions. Never save passwords, keys or other secrets.")


# ------------------------------------------------------------------ the project's own slash commands
def list_commands(workspace):
    """[{"name", "about"}] of the project's own commands (the first line of each file is its description)."""
    folder = os.path.join(workspace, COMMANDS_DIR)
    out = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    for f in names:
        m = re.fullmatch(r"([a-z0-9][a-z0-9_-]{0,39})\.md", f, re.I)
        if not m:
            continue
        try:
            with open(os.path.join(folder, f), encoding="utf-8") as fh:
                first = next((l.strip().lstrip("#").strip() for l in fh if l.strip()), "")
        except OSError:
            continue
        out.append({"name": m.group(1).lower(), "about": first[:100]})
    return out


def expand_command(workspace, text):
    """The text of /<name> from the project's commands, with $ARGUMENTS replaced; the text itself when it is not one of them."""
    m = COMMAND_NAME.match(str(text or "").strip())
    if not m:
        return text
    path = os.path.join(workspace, COMMANDS_DIR, m.group(1).lower() + ".md")
    try:
        with open(path, encoding="utf-8") as f:
            body = f.read(20000)
    except OSError:
        return text
    args = (m.group(2) or "").strip()
    return body.replace("$ARGUMENTS", args) if "$ARGUMENTS" in body else body + (f"\n\n{args}" if args else "")


# ------------------------------------------------------------------ saved permission rules
def rules_path(folder, project):
    """Where a project's rules are kept: the person's folder (never inside the project, which the agent can write)."""
    return os.path.join(folder, "vryx_rules", re.sub(r"[^\w.-]", "_", str(project)) + ".json")


def load_rules(path):
    """{"allow": [...], "deny": [...]} for the project (empty lists when none)."""
    try:
        with open(path, encoding="utf-8") as f:
            perms = (json.load(f) or {}).get("permissions") or {}
    except (OSError, ValueError, AttributeError):
        perms = {}
    return {k: [str(r) for r in perms.get(k, []) if isinstance(r, str) and RULE.match(r)] for k in ("allow", "deny")}


def save_rules(path, rules):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    data["permissions"] = {k: sorted(set(rules.get(k, []))) for k in ("allow", "deny")}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2)
    return data["permissions"]


def add_rule(path, kind, rule):
    rule = " ".join(str(rule or "").split())
    if kind not in ("allow", "deny") or not RULE.match(rule):
        raise ValueError("A rule is a tool name (write_file) or the start of a command (npm test), up to 80 characters.")
    rules = load_rules(path)
    other = "deny" if kind == "allow" else "allow"
    rules[other] = [r for r in rules[other] if r != rule]
    rules[kind] = rules[kind] + [rule]
    return save_rules(path, rules)


def remove_rule(path, rule):
    rules = load_rules(path)
    return save_rules(path, {k: [r for r in v if r != rule] for k, v in rules.items()})


def _matches(rule, key):
    return key == rule or key.startswith(rule + " ")


def decide(path, name, keys):
    """"deny", "allow" or None for a tool call: `keys` are the command's parts (npm test, git push) for run, else []. Deny wins over allow."""
    rules = load_rules(path)
    targets = list(keys) if name == "run" and keys else [name]
    if any(_matches(r, k) for r in rules["deny"] for k in targets):
        return "deny"
    if targets and all(any(_matches(r, k) for r in rules["allow"]) for k in targets):
        return "allow"
    return None
