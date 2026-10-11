"""
thinking.py - Hiding a model's "thinking" from the answer.

The 3.x models (Qwen3.5) can write step-by-step reasoning between <think> and </think> before the answer. The app shows only the answer (and a
"thinking..." line while the reasoning is being written). Two helpers:

    split_thinking(text)  -> (thinking, answer) for a finished reply.
    ThinkFilter()         -> feed() the pieces of a reply as they stream in; it returns only the part to show, and exposes `.thinking` (what was held
                             back so far) and `.in_thinking` (True while the model is inside a thinking block, for the "thinking..." line).
"""
OPEN, CLOSE = "<think>", "</think>"


def split_thinking(text):
    """(thinking, answer). No thinking block: ("", text). A block that never closed counts as all thinking (the answer is empty)."""
    start = text.find(OPEN)
    if start < 0:
        end = text.find(CLOSE)                       # a prompt that already opened the block: only the closing tag shows up in the reply
        return ("", text) if end < 0 else (text[:end].strip(), text[end + len(CLOSE):].strip())
    before, rest = text[:start], text[start + len(OPEN):]
    end = rest.find(CLOSE)
    if end < 0:
        return rest.strip(), before.strip()
    return rest[:end].strip(), (before + rest[end + len(CLOSE):]).strip()


class ThinkFilter:
    """Streaming version. Pieces may cut a tag in half ("<thi" + "nk>"), so a possible tag start is held back until it is clear."""

    def __init__(self, starts_inside=False):
        self.buf, self.thinking, self.in_thinking, self.shown_any = "", "", starts_inside, False

    def feed(self, piece):
        self.buf += piece
        out = ""
        while True:
            tag = CLOSE if self.in_thinking else OPEN
            i = self.buf.find(tag)
            if i >= 0:
                chunk, self.buf = self.buf[:i], self.buf[i + len(tag):]
                if self.in_thinking:
                    self.thinking += chunk
                else:
                    out += chunk
                self.in_thinking = not self.in_thinking
                continue
            keep = 0                                   # hold back the longest ending that could still become the tag
            for n in range(min(len(tag) - 1, len(self.buf)), 0, -1):
                if tag.startswith(self.buf[-n:]):
                    keep = n
                    break
            chunk, self.buf = self.buf[:len(self.buf) - keep], self.buf[len(self.buf) - keep:]
            if self.in_thinking:
                self.thinking += chunk
            else:
                out += chunk
            break
        if not self.shown_any:                         # the blank lines after </think> are not part of the answer
            out = out.lstrip()
        self.shown_any = self.shown_any or bool(out)
        return out

    def finish(self):
        """What is left when the reply ends (a half tag that never completed is shown as text unless we are inside thinking)."""
        rest, self.buf = self.buf, ""
        if self.in_thinking:
            self.thinking += rest
            return ""
        return rest
