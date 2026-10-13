"""
code_edit.py - "Edit this selection" and "Explain this" in the VryxCode editor.

The person selects code in the editor, types what to change ("make this handle an empty list"), and VryxCode's model proposes a replacement for just that
selection. Nothing is changed by this: the page shows the before and after as a diff and the person presses Accept or Reject; Accept only puts the text in the
editor (as an ordinary edit, so Undo works) and the file is saved when the person saves it.

This file holds the plain parts: the request sent to the model, and reading its reply (the first fenced code block is the replacement; indentation and the
line ending at the end of the selection are kept the way the selection had them). The model call and the usage counting are in app_server.py.
"""
import re

MAX_SELECTION = 6000
MAX_INSTRUCTION = 500
CONTEXT_LINES = 40
CONTEXT_CHARS = 3000
THINK_RX = re.compile(r"<think>.*?</think>\s*", re.S)
FENCE_RX = re.compile(r"```[\w+#.-]*[ \t]*\n(.*?)(?:\n)?```", re.S)

EDIT_SYSTEM = ("You edit code. You are given one file, a selected part of it, and an instruction. Rewrite ONLY the selected part to follow the instruction. "
               "Reply with the new code for the selected part inside ONE fenced code block and nothing else of the code: do not repeat code from before or after the selection, "
               "do not explain inside the block, and keep the file's own style (indentation, quotes, naming). If the instruction cannot be done on this selection, "
               "reply with one plain sentence saying why and no code block.")
INSERT_SYSTEM = ("You write code for an editor. You are given one file, a place in it marked <<<CURSOR>>>, and an instruction. Write ONLY the new code to put at the cursor, "
                 "inside ONE fenced code block, in the file's own style. If the instruction cannot be done, reply with one plain sentence and no code block.")
EXPLAIN_SYSTEM = ("You explain code in plain words for someone who is learning. You are given one file and a selected part of it. Explain what the selected part does in "
                  "a short paragraph or a few bullet points, and mention anything risky or surprising. Do not rewrite the code.")


def _clip_head(text, n):
    return text if len(text) <= n else text[-n:]


def _clip_tail(text, n):
    return text if len(text) <= n else text[:n]


def context_around(text, start, end, lines=CONTEXT_LINES, chars=CONTEXT_CHARS):
    """(before, selected, after): the lines just around the selection, not the whole file (the model's memory is small)."""
    before, selected, after = text[:start], text[start:end], text[end:]
    before = "\n".join(before.split("\n")[-lines:])
    after = "\n".join(after.split("\n")[:lines])
    return _clip_head(before, chars), selected, _clip_tail(after, chars)


def build_messages(path, lang, text, start, end, instruction, mode="edit"):
    """The chat messages for the model. mode: edit | explain. An empty selection (start == end) in edit mode means "insert at the cursor"."""
    start, end = max(0, int(start)), max(0, int(end))
    if start > end or end > len(text):
        raise ValueError("The selection is outside the file.")
    if end - start > MAX_SELECTION:
        raise ValueError(f"Select less code (up to {MAX_SELECTION:,} characters).")
    before, selected, after = context_around(text, start, end)
    head = f"File: {path} ({lang})\n\n"
    if mode == "explain":
        if not selected.strip():
            raise ValueError("Select the code you want explained.")
        return [{"role": "system", "content": EXPLAIN_SYSTEM},
                {"role": "user", "content": f"{head}Code before the selection:\n```\n{before}\n```\n\nSELECTED CODE:\n```\n{selected}\n```\n\nCode after the selection:\n```\n{after}\n```\n\nExplain the selected code."}]
    instruction = " ".join(str(instruction or "").split())[:MAX_INSTRUCTION]
    if not instruction:
        raise ValueError("Say what to change.")
    if start == end:
        return [{"role": "system", "content": INSERT_SYSTEM},
                {"role": "user", "content": f"{head}```\n{before}<<<CURSOR>>>{after}\n```\n\nInstruction: {instruction}"}]
    return [{"role": "system", "content": EDIT_SYSTEM},
            {"role": "user", "content": f"{head}Code before the selection:\n```\n{before}\n```\n\nSELECTED CODE:\n```\n{selected}\n```\n\nCode after the selection:\n```\n{after}\n```\n\nInstruction: {instruction}"}]


def _indent_of(line):
    return re.match(r"[ \t]*", line).group(0)


def _base_indent(text):
    """The indentation of the least-indented non-empty line."""
    inds = [_indent_of(l) for l in text.split("\n") if l.strip()]
    return min(inds, key=len) if inds else ""


def reindent(replacement, selection):
    """Give the reply the selection's indentation level (a block from inside a function often comes back flush left, or indented too far); relative indentation is kept."""
    sel, rep = _base_indent(selection), _base_indent(replacement)
    if sel == rep:
        return replacement
    if sel.startswith(rep):
        add = sel[len(rep):]
        return "\n".join((add + l) if l.strip() else l for l in replacement.split("\n"))
    if rep.startswith(sel):
        cut = len(rep) - len(sel)
        return "\n".join(l[cut:] if l.strip() else l for l in replacement.split("\n"))
    return replacement


def parse_reply(reply, selection="", mode="edit", prefix=""):
    """{"replacement": str | None, "message": str}. Edit: the first fenced block is the replacement; no block means the model said it could not (message = its words).
    Explain: message = the model's words. `prefix` is the blank space before the selection on its first line (when the selection starts after the indent): it stays in
    the file, so the reply's first line must not repeat it."""
    text = THINK_RX.sub("", str(reply or "")).strip()
    if mode == "explain":
        return {"replacement": None, "message": text[:3000]}
    m = FENCE_RX.search(text)
    if not m:
        return {"replacement": None, "message": text[:400] or "The model did not answer."}
    code = m.group(1)
    if selection:
        code = reindent(code, prefix + selection)
        if prefix and code.startswith(prefix):
            code = code[len(prefix):]
    if selection.endswith("\n") and not code.endswith("\n"):
        code += "\n"
    elif selection and not selection.endswith("\n"):
        code = code.rstrip("\n")
    return {"replacement": code, "message": ""}
