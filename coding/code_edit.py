"""
code_edit.py - "Edit this selection" and "Explain this" in the VryxCode editor.

The person selects code in the editor, types what to change ("make this handle an empty list"), and VryxCode's model proposes a replacement for just that
selection. Nothing is changed by this: the page shows the before and after as a diff and the person presses Accept or Reject; Accept only puts the text in the
editor (as an ordinary edit, so Undo works) and the file is saved when the person saves it.

This file holds the plain parts: the request sent to the model, and reading its reply (the first fenced code block is the replacement; indentation and the
line ending at the end of the selection are kept the way the selection had them). The model call and the usage counting are in app_server.py.
"""
# re = regular expressions (a regex is a text pattern used to find or cut pieces of text).
import re

# Limits so the request stays small enough for the model: most characters in the selected code, most characters in
# the person's instruction, and how much code before/after the selection is sent as context (lines, and characters).
MAX_SELECTION = 6000
MAX_INSTRUCTION = 500
CONTEXT_LINES = 40
CONTEXT_CHARS = 3000
# Matches a "<think>...</think>" block (the model's private thinking) plus the spaces after it, so it can be removed.
# re.S makes "." also match new lines; ".*?" means "as little as possible", so only one block is matched at a time.
THINK_RX = re.compile(r"<think>.*?</think>\s*", re.S)
# Matches a fenced code block in the model's reply: three backticks, an optional language name (like python or c++),
# a new line, then the code (captured in group 1, as little as possible), an optional new line, and the closing three backticks.
FENCE_RX = re.compile(r"```[\w+#.-]*[ \t]*\n(.*?)(?:\n)?```", re.S)

# The three "system" messages: standing instructions that tell the model its job for each button (edit, insert, explain).
EDIT_SYSTEM = ("You edit code. You are given one file, a selected part of it, and an instruction. Rewrite ONLY the selected part to follow the instruction. "
               "Reply with the new code for the selected part inside ONE fenced code block and nothing else of the code: do not repeat code from before or after the selection, "
               "do not explain inside the block, and keep the file's own style (indentation, quotes, naming). If the instruction cannot be done on this selection, "
               "reply with one plain sentence saying why and no code block.")
INSERT_SYSTEM = ("You write code for an editor. You are given one file, a place in it marked <<<CURSOR>>>, and an instruction. Write ONLY the new code to put at the cursor, "
                 "inside ONE fenced code block, in the file's own style. If the instruction cannot be done, reply with one plain sentence and no code block.")
EXPLAIN_SYSTEM = ("You explain code in plain words for someone who is learning. You are given one file and a selected part of it. Explain what the selected part does in "
                  "a short paragraph or a few bullet points, and mention anything risky or surprising. Do not rewrite the code.")


def _clip_head(text, n):
    """Keep at most the LAST n characters (used for the code before the selection: the nearest code matters most)."""
    return text if len(text) <= n else text[-n:]


def _clip_tail(text, n):
    """Keep at most the FIRST n characters (used for the code after the selection: the nearest code matters most)."""
    return text if len(text) <= n else text[:n]


def context_around(text, start, end, lines=CONTEXT_LINES, chars=CONTEXT_CHARS):
    """(before, selected, after): the lines just around the selection, not the whole file (the model's memory is small)."""
    # Cut the file in three at the selection's start and end positions (counted in characters).
    before, selected, after = text[:start], text[start:end], text[end:]
    # Keep only the last `lines` lines before, and the first `lines` lines after.
    before = "\n".join(before.split("\n")[-lines:])
    after = "\n".join(after.split("\n")[:lines])
    # Then apply the character limit too (very long lines could still make it big).
    return _clip_head(before, chars), selected, _clip_tail(after, chars)


def build_messages(path, lang, text, start, end, instruction, mode="edit"):
    """The chat messages for the model. mode: edit | explain. An empty selection (start == end) in edit mode means "insert at the cursor"."""
    # Positions must be whole numbers, not below 0.
    start, end = max(0, int(start)), max(0, int(end))
    # Reject a backwards selection or one that runs past the end of the file.
    if start > end or end > len(text):
        raise ValueError("The selection is outside the file.")
    # Reject selections that are too large for the model.
    if end - start > MAX_SELECTION:
        raise ValueError(f"Select less code (up to {MAX_SELECTION:,} characters).")
    before, selected, after = context_around(text, start, end)
    # The first lines of every user message: which file, and its language.
    head = f"File: {path} ({lang})\n\n"
    # "Explain" mode: send the code around and the selection, and ask for an explanation. Needs real text selected.
    if mode == "explain":
        if not selected.strip():
            raise ValueError("Select the code you want explained.")
        return [{"role": "system", "content": EXPLAIN_SYSTEM},
                {"role": "user", "content": f"{head}Code before the selection:\n```\n{before}\n```\n\nSELECTED CODE:\n```\n{selected}\n```\n\nCode after the selection:\n```\n{after}\n```\n\nExplain the selected code."}]
    # Tidy the instruction: split() + join squeezes all whitespace to single spaces, then cut to the limit.
    instruction = " ".join(str(instruction or "").split())[:MAX_INSTRUCTION]
    if not instruction:
        raise ValueError("Say what to change.")
    # Nothing selected: the person wants new code at the cursor. <<<CURSOR>>> marks the place in the file text.
    if start == end:
        return [{"role": "system", "content": INSERT_SYSTEM},
                {"role": "user", "content": f"{head}```\n{before}<<<CURSOR>>>{after}\n```\n\nInstruction: {instruction}"}]
    # Otherwise: rewrite the selected part. The model sees the code before, the selection, the code after, and the instruction.
    return [{"role": "system", "content": EDIT_SYSTEM},
            {"role": "user", "content": f"{head}Code before the selection:\n```\n{before}\n```\n\nSELECTED CODE:\n```\n{selected}\n```\n\nCode after the selection:\n```\n{after}\n```\n\nInstruction: {instruction}"}]


def _indent_of(line):
    """The spaces/tabs at the start of a line. The regex [ \\t]* matches zero or more spaces or tabs."""
    return re.match(r"[ \t]*", line).group(0)


def _base_indent(text):
    """The indentation of the least-indented non-empty line."""
    # Blank lines are ignored (l.strip() is empty for them). The shortest indent is the block's base level.
    inds = [_indent_of(l) for l in text.split("\n") if l.strip()]
    return min(inds, key=len) if inds else ""


def reindent(replacement, selection):
    """Give the reply the selection's indentation level (a block from inside a function often comes back flush left, or indented too far); relative indentation is kept."""
    sel, rep = _base_indent(selection), _base_indent(replacement)
    # Already the same level: nothing to do.
    if sel == rep:
        return replacement
    # The reply is indented LESS than the selection: add the missing indent to every non-blank line.
    if sel.startswith(rep):
        add = sel[len(rep):]
        return "\n".join((add + l) if l.strip() else l for l in replacement.split("\n"))
    # The reply is indented MORE than the selection: remove the extra indent from every non-blank line.
    if rep.startswith(sel):
        cut = len(rep) - len(sel)
        return "\n".join(l[cut:] if l.strip() else l for l in replacement.split("\n"))
    # Mixed tabs and spaces that do not line up: leave the reply alone rather than guess.
    return replacement


def parse_reply(reply, selection="", mode="edit", prefix=""):
    """{"replacement": str | None, "message": str}. Edit: the first fenced block is the replacement; no block means the model said it could not (message = its words).
    Explain: message = the model's words. `prefix` is the blank space before the selection on its first line (when the selection starts after the indent): it stays in
    the file, so the reply's first line must not repeat it."""
    # Remove the model's private <think> block, then trim the ends.
    text = THINK_RX.sub("", str(reply or "")).strip()
    # Explain mode: the whole reply is the answer (cut to 3000 characters).
    if mode == "explain":
        return {"replacement": None, "message": text[:3000]}
    # Find the first fenced code block. None means the model replied in words only (it said it could not do it).
    m = FENCE_RX.search(text)
    if not m:
        return {"replacement": None, "message": text[:400] or "The model did not answer."}
    code = m.group(1)
    if selection:
        # Match the selection's indentation, then drop the prefix from the first line (it is still in the file).
        code = reindent(code, prefix + selection)
        if prefix and code.startswith(prefix):
            code = code[len(prefix):]
    # Keep the selection's line ending: if it ended with a new line the replacement must too; if it did not, the
    # replacement must not either (otherwise an extra blank line would appear in the file).
    if selection.endswith("\n") and not code.endswith("\n"):
        code += "\n"
    elif selection and not selection.endswith("\n"):
        code = code.rstrip("\n")
    return {"replacement": code, "message": ""}


# ---------------------------------------------------------------- inline autocomplete
# The instruction used for ghost-text autocomplete (it goes through the same insert-at-the-cursor request).
COMPLETE_INSTRUCTION = ("Continue the code at the cursor: write only the next few lines the author most likely wants (at most 6 lines), in the file's own style. "
                        "Do not repeat code that is already there, and do not explain.")
# Longest suggestion we will show: 8 lines and 600 characters.
MAX_COMPLETION_LINES = 8
MAX_COMPLETION_CHARS = 600


def clean_completion(raw, prefix, suffix):
    """The text to show as grey "ghost" text at the cursor, or None. Keeps at most 8 lines (one line when the cursor is in the middle of a line), drops what repeats the code
    right after the cursor (a closing bracket the editor already has), and drops empty or whitespace-only answers."""
    # Remove thinking, and turn Windows line endings (\r\n) into plain \n.
    text = THINK_RX.sub("", str(raw or "")).replace("\r\n", "\n")
    # If the model wrapped the code in a fenced block, use what is inside.
    m = FENCE_RX.search(text)
    if m:
        text = m.group(1)
    text = text.rstrip()
    lines = text.split("\n")
    # The text already on the cursor's line after the cursor.
    rest_of_line = suffix.split("\n", 1)[0]
    if rest_of_line.strip():                                     # the cursor is in the middle of a line: only finish this line
        lines = lines[:1]
    # Apply the size limits.
    text = "\n".join(lines[:MAX_COMPLETION_LINES])[:MAX_COMPLETION_CHARS]
    follow = rest_of_line.lstrip()
    for k in range(min(len(text), len(follow)), 0, -1):          # the completion ends with what already follows the cursor: do not show it twice
        if follow[:k].strip() and text.endswith(follow[:k]):
            text = text[:-k]
            break
    # Nothing useful left: show nothing.
    if not text.strip():
        return None
    return text
