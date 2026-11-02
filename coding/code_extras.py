"""
code_extras.py - What VryxCode's full agent keeps between sessions, the way Claude Code does (docs/VRYXCODE.md):

  memory        notes VryxCode keeps about the person and their projects (`remember` tool), in their own folder, read at the start of every session.
  commands      a project's own slash commands: .vryx/commands/<name>.md, the text sent when the person types /<name> (with $ARGUMENTS for what follows).
  rules         a project's saved permission rules {"permissions": {"allow": [...], "deny": [...]}}, kept in the person's own folder, OUTSIDE the project
                (rules_path), so the agent can never give itself permissions by writing a file. A rule is a tool name (write_file) or the start of a
                command (npm test, git push). Deny wins; "Yes, and don't ask again" saves an allow rule.
"""
# json reads/writes the rules file; os.path works with file paths; re = regular expressions (text patterns).
import json
import os
import re

# The memory file name, how many notes are kept (60) and how long one note may be (240 characters).
MEMORY_FILE = "vryx_memory.md"
MEMORY_LINES, MEMORY_CHARS = 60, 240
# Where a project keeps its own slash commands.
COMMANDS_DIR = os.path.join(".vryx", "commands")
# Matches what the person typed for a slash command: "/", a name (letters, digits, _ or -; up to 40 characters,
# starting with a letter or digit), then optionally spaces and the rest (the arguments).
# Group 1 = the name, group 2 = the arguments. re.S lets the arguments span lines; re.I ignores upper/lower case.
COMMAND_NAME = re.compile(r"^/([a-z0-9][a-z0-9_-]{0,39})(?:\s+(.*))?$", re.S | re.I)
# A permission rule may only contain letters, digits, _ space . : / @ = + - and be 1 to 80 characters long.
RULE = re.compile(r"^[\w .:/@=+-]{1,80}$")


# ------------------------------------------------------------------ memory
def memory_path(folder):
    """The full path of the memory file inside the person's folder."""
    return os.path.join(folder, MEMORY_FILE)


def read_memory(folder):
    """The notes kept about this person ([] when none)."""
    # Each note is one line starting with "- ". l[2:] drops that marker; empty notes are skipped.
    try:
        with open(memory_path(folder), encoding="utf-8") as f:
            return [l[2:].strip() for l in f.read().splitlines() if l.startswith("- ") and l[2:].strip()]
    except OSError:
        # No file yet (or unreadable): no notes.
        return []


def write_memory(folder, notes):
    """Save the notes (only the newest 60) to the memory file as a "- note" bullet list."""
    os.makedirs(folder, exist_ok=True)
    # newline="\n" keeps Unix line endings even on Windows, so the file looks the same everywhere.
    with open(memory_path(folder), "w", encoding="utf-8", newline="\n") as f:
        f.write("# What VryxCode remembers about you\n\n" + "".join(f"- {n}\n" for n in notes[-MEMORY_LINES:]))


def remember(folder, note):
    """Add one note (the oldest go first past 60). Returns what the model is told."""
    # Squeeze all whitespace to single spaces and cut to the limit.
    note = " ".join(str(note or "").split())[:MEMORY_CHARS]
    if not note:
        raise ValueError('remember needs a note, like {"note": "Uses Tailwind for styling"}')
    # Drop an older copy of the same note (ignoring case), then add the new one at the end.
    notes = [n for n in read_memory(folder) if n.lower() != note.lower()] + [note]
    write_memory(folder, notes)
    return f"remembered ({len(notes[-MEMORY_LINES:])} notes kept)"


def forget(folder, index=None):
    """Remove one note (by its number, from 0) or, with no number, all of them."""
    notes = read_memory(folder)
    # No number: clear everything. A valid number: remove that one. An out-of-range number changes nothing.
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
    # One sentence that lists all the notes, separated by semicolons.
    return (" WHAT YOU REMEMBER ABOUT THIS PERSON (from earlier sessions; use it, and save anything new and lasting with remember(note)): "
            + "; ".join(notes))


# Added to the agent's instructions so it knows the `remember` tool exists and what not to save.
MEMORY_TOOL_NOTE = (" remember(note) saves one short, lasting fact about the person or how they like to work (\"prefers TypeScript\", \"tests with pytest\") "
                    "for future sessions. Never save passwords, keys or other secrets.")


# ------------------------------------------------------------------ the project's own slash commands
def list_commands(workspace):
    """[{"name", "about"}] of the project's own commands (the first line of each file is its description)."""
    folder = os.path.join(workspace, COMMANDS_DIR)
    out = []
    # No commands folder: no commands.
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    for f in names:
        # Only "<name>.md" files with an allowed name count. Group 1 is the name without ".md".
        m = re.fullmatch(r"([a-z0-9][a-z0-9_-]{0,39})\.md", f, re.I)
        if not m:
            continue
        # The description is the first non-empty line, with leading "#" (a Markdown heading mark) removed.
        try:
            with open(os.path.join(folder, f), encoding="utf-8") as fh:
                first = next((l.strip().lstrip("#").strip() for l in fh if l.strip()), "")
        except OSError:
            continue
        out.append({"name": m.group(1).lower(), "about": first[:100]})
    return out


def expand_command(workspace, text):
    """The text of /<name> from the project's commands, with $ARGUMENTS replaced; the text itself when it is not one of them."""
    # Does the text look like "/name something"? If not, it is an ordinary message: return it unchanged.
    m = COMMAND_NAME.match(str(text or "").strip())
    if not m:
        return text
    path = os.path.join(workspace, COMMANDS_DIR, m.group(1).lower() + ".md")
    # Read at most 20000 characters of the command file. No such command: send the text as typed.
    try:
        with open(path, encoding="utf-8") as f:
            body = f.read(20000)
    except OSError:
        return text
    args = (m.group(2) or "").strip()
    # If the file has $ARGUMENTS, put the typed arguments there; otherwise add them at the end.
    return body.replace("$ARGUMENTS", args) if "$ARGUMENTS" in body else body + (f"\n\n{args}" if args else "")


# ------------------------------------------------------------------ saved permission rules
def rules_path(folder, project):
    """Where a project's rules are kept: the person's folder (never inside the project, which the agent can write)."""
    # The project name is made safe for a file name: any character that is not a letter, digit, _ . or - becomes "_".
    return os.path.join(folder, "vryx_rules", re.sub(r"[^\w.-]", "_", str(project)) + ".json")


def load_rules(path):
    """{"allow": [...], "deny": [...]} for the project (empty lists when none)."""
    # A missing, damaged or oddly shaped file means no rules (AttributeError: the JSON was not a dictionary).
    try:
        with open(path, encoding="utf-8") as f:
            perms = (json.load(f) or {}).get("permissions") or {}
    except (OSError, ValueError, AttributeError):
        perms = {}
    # Keep only well-formed text rules; anything else in the file is ignored.
    return {k: [str(r) for r in perms.get(k, []) if isinstance(r, str) and RULE.match(r)] for k in ("allow", "deny")}


def save_rules(path, rules):
    """Write the rules into the file under "permissions" (sorted, no duplicates), keeping any other data already in
    the file. Returns the saved {"allow": [...], "deny": [...]}."""
    # Read the old file first so other keys in it are not lost.
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    # set() removes duplicates; sorted() makes the file stable.
    data["permissions"] = {k: sorted(set(rules.get(k, []))) for k in ("allow", "deny")}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2)
    return data["permissions"]


def add_rule(path, kind, rule):
    """Save a new "allow" or "deny" rule. Raises ValueError for a bad kind or a rule that fails the RULE pattern.
    The same rule is removed from the opposite list so the two lists never disagree."""
    rule = " ".join(str(rule or "").split())
    if kind not in ("allow", "deny") or not RULE.match(rule):
        raise ValueError("A rule is a tool name (write_file) or the start of a command (npm test), up to 80 characters.")
    rules = load_rules(path)
    other = "deny" if kind == "allow" else "allow"
    rules[other] = [r for r in rules[other] if r != rule]
    rules[kind] = rules[kind] + [rule]
    return save_rules(path, rules)


def remove_rule(path, rule):
    """Delete the rule from both lists and save. Returns the saved rules."""
    rules = load_rules(path)
    return save_rules(path, {k: [r for r in v if r != rule] for k, v in rules.items()})


def _matches(rule, key):
    """True if the rule covers the key: they are equal, or the key starts with the rule plus a space
    (so the rule "git push" covers "git push origin" but not "git pushy")."""
    return key == rule or key.startswith(rule + " ")


def decide(path, name, keys):
    """"deny", "allow" or None for a tool call: `keys` are the command's parts (npm test, git push) for run, else []. Deny wins over allow."""
    rules = load_rules(path)
    # For a shell command, every part of it is checked on its own; for any other tool, its name is checked.
    targets = list(keys) if name == "run" and keys else [name]
    # One matching deny rule is enough to refuse.
    if any(_matches(r, k) for r in rules["deny"] for k in targets):
        return "deny"
    # Allowed only when EVERY part is covered by an allow rule. Otherwise None = "no rule: ask the person".
    if targets and all(any(_matches(r, k) for r in rules["allow"]) for k in targets):
        return "allow"
    return None
