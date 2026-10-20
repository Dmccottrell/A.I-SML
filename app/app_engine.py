"""
app_engine.py - The parts of the app that make a chat reliable (no web page in here, so every part can be tested).

WHAT THIS FILE DOES
    The path of one message (docs/APP_SPEC.md, Part 3) and what happens when a step fails:

      choose_model   which model answers: refuses one the device is too small for (offers the next smaller), and when
                     the PC is off switches to the on-device model (labelled; or asks first, a Setting)
      Guard          wraps the streaming reply: a hard length cap, a Stop button, and a loop detector, so a reply
                     can't run forever
      ChatStore      SQLite chats; the reply is saved WHILE it streams, so closing the app loses at most a few
                     words, and a cut-off reply is found again when the chat is reopened. Private chats are kept
                     in memory only and never written to disk
      run_turn       builds the prompt with chat.py (old messages dropped when the window is full, and the count of
                     forgotten ones returned for the "older messages forgotten" marker) and streams the answer
      LlamaServer    the real model (llama.cpp's llama-server, over HTTP); FakeBackend is the stand-in for tests
      test_connection  the "Test connection" button: says exactly what is wrong (can't reach, wrong key, not our server)

    All failures are AppError subclasses (app_errors.py): a plain message plus one next step.
"""
import re
import json
import sqlite3
import time
import urllib.error
import urllib.request

from safe_db import SafeDB

import chat
import chat_polish
from app_errors import AppError, BadKey, ModelRefused, ModelTooBig, PcUnreachable, ReplyInterrupted, WrongServer

MAX_REPLY_CHARS = 8000          # ~2,000 tokens: a reply longer than the whole memory is a loop, not an answer


# ------------------------------------------------------------------ which model answers
def smaller_fallback(models, model, ram_gb):
    """The biggest on-device model that fits `ram_gb` and is not the one that didn't fit (or None)."""
    fits = [m for m in models if m["where"] == "device" and m["id"] != model["id"]
            and (ram_gb is None or m["min_ram_gb"] <= ram_gb)]
    return max(fits, key=lambda m: (m["min_ram_gb"], m["version"]), default=None)


def choose_model(models, model_id, ram_gb=None, pc_online=True, ask=None, when_pc_off="switch"):
    """The model to run: `models` is the visible list, `model_id` the person's choice.

    Too big for the device -> ModelTooBig (with the next smaller one offered).
    Online model but the PC is off -> `when_pc_off` decides (a Setting):
      "switch" (default): use the on-device fallback right away. The answer is labelled with the model that really
                          wrote it ("PC off: answered by Equinox on this device"), so it is never hidden. Safe, because
                          the fallback runs on the device and sends nothing anywhere.
      "ask":              asks `ask(fallback_model) -> bool`; without a yes, raises PcUnreachable.
    With no on-device model to fall back to, it always raises PcUnreachable (nothing to switch to).
    The other direction (device -> online) is never automatic: sending messages off the device is always the person's choice."""
    model = next(m for m in models if m["id"] == model_id)
    if model["where"] == "device" and ram_gb is not None and ram_gb < model["min_ram_gb"]:
        raise ModelTooBig(model, ram_gb, smaller_fallback(models, model, ram_gb))
    if model["where"] == "online" and not pc_online:
        fallback = smaller_fallback(models, model, ram_gb)
        if fallback and (when_pc_off == "switch" or (ask and ask(fallback))):
            return fallback
        raise PcUnreachable(fallback)
    return model


# ------------------------------------------------------------------ keeping a reply under control
LOOP_SPAN = 240                  # chat_fixes: a repeat must cover this many characters before it counts as a loop

def is_looping(text, min_unit=4, max_unit=120, repeats=4, min_span=0):
    """True if the text ends with the same piece repeated `repeats` times in a row (a stuck model). With `min_span` a short piece must repeat
    until the repeats cover that many characters: a table's "|---|---|---|---|", a line of "====" or four closing "</div>" are formatting, not a loop."""
    for n in range(min_unit, max_unit + 1):
        times = max(repeats, -(-min_span // n)) if min_span else repeats
        if len(text) >= n * times and text[-n * times:] == text[-n:] * times:
            return True
    return False


BLEED_MARKERS = ("<|user|>", "<|assistant|>", "<|system|>", "<|tool_result|>", "<|endoftext|>")


def cut_bleed(text):
    """(text before the first chat marker, True if one was found). A model that keeps going after its answer starts writing
    the next turn ("<|user|>..."); that part must never be shown or saved."""
    cut = min((text.find(m) for m in BLEED_MARKERS if m in text), default=-1)
    return (text, False) if cut < 0 else (text[:cut], True)


MEDIA_MARKER = "<__media__>"          # llama-server's place-holder for one picture in a prompt (multimodal_data fills them in order)


def with_pictures(prompt, asked, n):
    """The prompt text with one picture marker per picture, just before the person's question (the last place it appears). Before the whole prompt's last
    line when the question cannot be found, so the pictures are never lost."""
    marks = (MEDIA_MARKER + "\n") * n
    anchor = (asked or "").strip()[:200]
    at = prompt.rfind(anchor) if anchor else -1
    if at < 0:
        at = prompt.rfind("\n", 0, max(0, len(prompt.rstrip()) - 1)) + 1
    return prompt[:at] + marks + prompt[at:]


def until_stopped(pieces, stop):
    """Pass the model's raw pieces on until `stop` is set (the Stop button). Checked on every raw piece, hidden reasoning included: Guard only sees the
    visible answer, so on its own it could not stop a model that is still thinking."""
    try:
        for piece in pieces:
            if stop is not None and stop.is_set():
                return
            yield piece
    finally:
        close = getattr(pieces, "close", None)
        if close:
            close()


THINK_SHARE, THINK_MAX = 0.4, 1600     # Deep: the hidden thinking may use 40% of the reply's room, never more than 1,600 tokens
THINK_CLOSE = "\n\nThat is enough thinking: time to answer.\n</think>\n\n"


def think_budget(backend, tok, prompt, max_new, chars_per_token=4):
    """Deep on an Emvryx 3 model, with a limit on the hidden thinking. Small models can reason on and on about an easy question (a minute and a
    half on the owner's RTX 4070, Oct 19) and even run out of room before answering. When the thinking passes its budget the stream is stopped,
    the thinking is closed, and the model is asked to go on from there: it answers with what it has worked out (the answer is never lost)."""
    budget = min(THINK_MAX, int(max_new * THINK_SHARE)) * chars_per_token
    gen, said = backend.stream(prompt, max_new), ""
    try:
        for piece in gen:
            said += piece
            yield piece
            if "</think>" in said:                                      # it finished thinking by itself: carry on as usual
                yield from gen
                return
            if len(said) > budget:
                break
        else:
            return
    finally:
        gen.close()                                                     # stops the request to llama-server
    yield THINK_CLOSE
    more = said + THINK_CLOSE
    rest = max(64, max_new - len(said) // chars_per_token)
    if isinstance(prompt, dict):
        follow = dict(prompt, prompt_string=prompt["prompt_string"] + more)
    else:
        follow = list(prompt) + list(tok.encode(more))
    yield from backend.stream(follow, rest)


def strip_think(pieces, open_tag="<think>", close_tag="</think>", inside=False):
    """Drop a model's hidden reasoning (Qwen3 writes <think>...</think> before its answer) from a stream of text pieces, even when a
    tag is split across pieces. The answer never starts with blank space, also when the blank lines after the closing tag arrive in a
    later piece (that showed as an empty gap at the top of Emvryx 3 replies). An unfinished block is dropped."""
    begun = False
    for out in _strip_think(pieces, open_tag, close_tag, inside):
        if not begun:
            out = out.lstrip()
            if not out:
                continue
            begun = True
        yield out


def _strip_think(pieces, open_tag, close_tag, inside=False):
    buf, started = "", False                                       # inside=True: the prompt already opened the thinking block (chat_fixes, Deep)
    for piece in pieces:
        buf += piece
        while True:
            if inside:
                i = buf.find(close_tag)
                if i < 0:
                    buf = buf[-(len(close_tag) - 1):]                  # keep only a possible start of the closing tag
                    break
                buf, inside, started = buf[i + len(close_tag):].lstrip(), False, False
                if not buf:
                    break
                continue
            i = buf.find(open_tag)
            if i >= 0:
                if buf[:i]:
                    yield buf[:i]
                buf, inside = buf[i + len(open_tag):], True
                continue
            keep = 0                                                   # hold back a possible start of "<think>"
            for n in range(min(len(open_tag) - 1, len(buf)), 0, -1):
                if open_tag.startswith(buf[-n:]):
                    keep = n
                    break
            out, buf = buf[:len(buf) - keep], buf[len(buf) - keep:]
            if out:
                yield out
            break
    if buf and not inside:
        yield buf


SOURCE_TAG = re.compile(r"\s*\(source:[^)]*\)", re.I)
SOURCE_START = re.compile(r"\s*(?:\((?:s(?:o(?:u(?:r(?:c(?:e(?::[^)]*)?)?)?)?)?)?)?)?$", re.I)     # blanks and a possible start of the tag, at the end


def strip_source(pieces):
    """Drop a "(Source: ...)" tag from a stream of text pieces. A model trained on lookup notes writes one after its answer; the app shows
    where an answer came from separately, so the tag is only clutter. It works when the tag is split across pieces; the blank before it goes too."""
    buf, removed = "", False
    for piece in pieces:
        buf += piece
        buf, n = SOURCE_TAG.subn("", buf)
        removed = removed or n > 0
        cut = SOURCE_START.search(buf).start()                  # trailing blanks and a half-written tag wait for the next piece
        if cut > 0:
            yield buf[:cut]
        buf = buf[cut:]
    i = buf.lower().find("(source:")
    if i >= 0:                                                  # the reply ended inside a tag
        buf, removed = buf[:i].rstrip(), True
    if buf.strip() or not removed:
        yield buf


class Guard:
    """Wrap a stream of text pieces. Stops it at the length cap, when it loops, when the model starts writing the other
    side of the chat ("bleed"), or when `stop` is set (the Stop button). `reason` is then "length", "loop", "bleed" or
    "stopped"; "done" when the model ended by itself."""

    def __init__(self, pieces, max_chars=MAX_REPLY_CHARS, stop=None, loop_span=0):
        self.pieces, self.max_chars, self.stop, self.reason, self.text = pieces, max_chars, stop, "done", ""
        self.loop_span = loop_span                     # chat_fixes: LOOP_SPAN, so formatting is never taken for a loop

    def __iter__(self):
        try:
            for piece in self.pieces:
                if self.stop is not None and self.stop.is_set():
                    self.reason = "stopped"
                    return
                before = self.text
                self.text += piece
                clean, bled = cut_bleed(self.text)
                if bled:                                       # keep only what came before the marker, then stop
                    keep = clean[len(before):]
                    self.text, self.reason = clean.rstrip() if not keep else clean, "bleed"
                    if keep:
                        yield keep
                    return
                yield piece
                if len(self.text) >= self.max_chars:
                    self.reason = "length"
                    return
                if is_looping(self.text[-self.max_chars:], min_span=self.loop_span):
                    self.reason = "loop"
                    return
        finally:
            close = getattr(self.pieces, "close", None)
            if close:
                close()                      # closes the connection to the model, so it stops generating


# ------------------------------------------------------------------ saving chats as they stream
class ChatStore:
    """Chats and messages in SQLite. A reply is "partial" until finish() is called, and is saved as it streams."""

    def __init__(self, path=":memory:"):
        self.db = SafeDB(path)                                   # shared by the server's threads: every statement takes its lock
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY, title TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, chat_id INTEGER, role TEXT, content TEXT,
                model_id TEXT, status TEXT, created REAL);""")
        for column in ("skill TEXT", "docs TEXT"):                           # chats made before Skills / Documents have none
            try:
                self.db.execute("ALTER TABLE chats ADD COLUMN " + column)
                self.db.commit()
            except sqlite3.OperationalError:
                pass
        for table, column in (("messages", "docs TEXT"),                       # the pictures and files that were sent with a message
                              ("messages", "flags TEXT"),                      # small marks on a message: {"cut": true, "fb": "wrong_fact"}
                              ("chats", "pinned INTEGER"), ("chats", "folder TEXT"),
                              ("chats", "archived INTEGER")):                  # archived: out of the list, still remembered
            try:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
                self.db.commit()
            except sqlite3.OperationalError:
                pass
        self.private_meta = {}                # private chats: {chat_id: {"pinned", "folder"}}
        self.private_docs = {}
        self.private = {}                    # private chats live here only: {chat_id: [messages]}
        self.private_skill = {}
        self._next_private = -1

    def new_chat(self, title="New chat", private=False, skill=None):
        if private:
            cid, self._next_private = self._next_private, self._next_private - 1
            self.private[cid] = []
            if skill:
                self.private_skill[cid] = skill
            return cid
        cur = self.db.execute("INSERT INTO chats (title, created, skill) VALUES (?, ?, ?)", (title, time.time(), skill or None))
        self.db.commit()
        return cur.lastrowid

    def docs(self, chat_id):
        """Ids of the documents attached to this chat."""
        if chat_id < 0:
            return list(self.private_docs.get(chat_id, []))
        r = self.db.execute("SELECT docs FROM chats WHERE id = ?", (chat_id,)).fetchone()
        try:
            return [int(x) for x in json.loads(r[0])] if r and r[0] else []
        except (ValueError, TypeError):
            return []

    def set_docs(self, chat_id, ids):
        ids = [int(i) for i in ids][:10]
        if chat_id < 0:
            self.private_docs[chat_id] = ids
            return
        self.db.execute("UPDATE chats SET docs = ? WHERE id = ?", (json.dumps(ids), chat_id))
        self.db.commit()

    def skill(self, chat_id):
        """The skill switched on for this chat ('' for none)."""
        if chat_id < 0:
            return self.private_skill.get(chat_id, "")
        r = self.db.execute("SELECT skill FROM chats WHERE id = ?", (chat_id,)).fetchone()
        return (r[0] or "") if r else ""

    def add(self, chat_id, role, content, model_id="", status="done", docs=None):
        docs = [int(i) for i in (docs or [])][:10]
        if chat_id < 0:
            self.private[chat_id].append({"id": len(self.private[chat_id]), "role": role, "content": content,
                                          "model_id": model_id, "status": status, "docs": docs, "flags": {}})
            return len(self.private[chat_id]) - 1
        cur = self.db.execute("INSERT INTO messages (chat_id, role, content, model_id, status, created, docs) "
                              "VALUES (?, ?, ?, ?, ?, ?, ?)", (chat_id, role, content, model_id, status, time.time(), json.dumps(docs) if docs else None))
        self.db.commit()
        return cur.lastrowid

    def update(self, chat_id, message_id, content, status):
        if chat_id < 0:
            self.private[chat_id][message_id].update(content=content, status=status)
            return
        self.db.execute("UPDATE messages SET content = ?, status = ? WHERE id = ?", (content, status, message_id))
        self.db.commit()

    def messages(self, chat_id):
        if chat_id < 0:
            return [dict(m) for m in self.private[chat_id]]
        rows = self.db.execute("SELECT id, role, content, model_id, status, docs, flags FROM messages WHERE chat_id = ? ORDER BY id",
                               (chat_id,)).fetchall()
        out = []
        for r in rows:
            m = dict(zip(("id", "role", "content", "model_id", "status", "docs", "flags"), r))
            try:
                m["docs"] = [int(x) for x in json.loads(m["docs"])] if m["docs"] else []
            except (ValueError, TypeError):
                m["docs"] = []
            try:
                m["flags"] = json.loads(m["flags"]) if m["flags"] else {}
            except (ValueError, TypeError):
                m["flags"] = {}
            out.append(m)
        return out

    def set_flag(self, chat_id, message_id, key, value):
        """A small mark on one message (the page reads it back with the message): {"cut": True} after a reply that hit its length limit, {"fb": "wrong_fact"} after feedback."""
        if chat_id < 0:
            if 0 <= message_id < len(self.private.get(chat_id, [])):
                self.private[chat_id][message_id].setdefault("flags", {})[key] = value
            return
        r = self.db.execute("SELECT flags FROM messages WHERE id = ? AND chat_id = ?", (message_id, chat_id)).fetchone()
        if not r:
            return
        try:
            flags = json.loads(r[0]) if r[0] else {}
        except ValueError:
            flags = {}
        flags[key] = value
        self.db.execute("UPDATE messages SET flags = ? WHERE id = ?", (json.dumps(flags), message_id))
        self.db.commit()

    # ---- pin, folders, search, edit and branch
    def meta(self, chat_id):
        if chat_id < 0:
            return dict({"pinned": 0, "folder": ""}, **self.private_meta.get(chat_id, {}))
        r = self.db.execute("SELECT pinned, folder FROM chats WHERE id = ?", (chat_id,)).fetchone()
        return {"pinned": int(r[0] or 0), "folder": r[1] or ""} if r else {"pinned": 0, "folder": ""}

    def set_pinned(self, chat_id, pinned):
        if chat_id < 0:
            self.private_meta.setdefault(chat_id, {})["pinned"] = int(bool(pinned))
            return
        self.db.execute("UPDATE chats SET pinned = ? WHERE id = ?", (int(bool(pinned)), chat_id))
        self.db.commit()

    def set_folder(self, chat_id, folder):
        folder = " ".join(str(folder or "").split())[:30]
        if chat_id < 0:
            self.private_meta.setdefault(chat_id, {})["folder"] = folder
            return
        self.db.execute("UPDATE chats SET folder = ? WHERE id = ?", (folder or None, chat_id))
        self.db.commit()

    def search(self, query, limit=20):
        """Chats whose title or messages contain every word of `query` (any case), newest first: [{"id", "title", "snippet", "message_id", "updated"}]. Private chats are never searched."""
        words = [w for w in re.findall(r"[^\s]+", str(query or "").lower())][:6]
        if not words:
            return []
        like = lambda w: "%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        out, seen = [], set()
        rows = self.db.execute("SELECT c.id, c.title, m.id, m.content, m.created FROM messages m JOIN chats c ON c.id = m.chat_id WHERE m.status != 'compacted' AND m.content != '' "
                               + "".join(" AND lower(m.content || ' ' || c.title) LIKE ? ESCAPE '\\'" for _ in words) + " ORDER BY m.id DESC LIMIT 400", [like(w) for w in words]).fetchall()
        for cid, title, mid, content, created in rows:
            if cid in seen:
                continue
            seen.add(cid)
            low = content.lower()
            at = min((low.find(w) for w in words if low.find(w) >= 0), default=0)
            start = max(0, at - 50)
            out.append({"id": cid, "title": title, "snippet": ("\u2026" if start else "") + " ".join(content[start:start + 160].split()), "message_id": mid, "updated": created})
            if len(out) >= limit:
                break
        for r in self.db.execute("SELECT id, title, created FROM chats WHERE " + " AND ".join("lower(title) LIKE ? ESCAPE '\\'" for _ in words), [like(w) for w in words]).fetchall():
            if r[0] not in seen and len(out) < limit:
                out.append({"id": r[0], "title": r[1], "snippet": "", "message_id": None, "updated": r[2]})
        return out

    def stats(self, since):
        """(questions asked since `since`, {model id: answers given}) in saved chats: counts only, nothing is read back."""
        asked = self.db.execute("SELECT COUNT(*) FROM messages WHERE created >= ? AND role = 'user' AND status != 'compacted' AND status != 'summary'", (since,)).fetchone()[0]
        by = dict(self.db.execute("SELECT model_id, COUNT(*) FROM messages WHERE created >= ? AND role = 'assistant' AND content != '' GROUP BY model_id", (since,)).fetchall())
        return asked, by

    def edit_message(self, chat_id, message_id, text):
        """Change what a user message says and forget everything after it (the page then asks for a new answer). False if it is not a user message."""
        text = str(text or "").strip()
        if not text:
            return False
        if chat_id < 0:
            msgs = self.private.get(chat_id, [])
            if not (0 <= message_id < len(msgs)) or msgs[message_id]["role"] != "user":
                return False
            msgs[message_id]["content"] = text
            del msgs[message_id + 1:]
            return True
        r = self.db.execute("SELECT role FROM messages WHERE id = ? AND chat_id = ?", (message_id, chat_id)).fetchone()
        if not r or r[0] != "user":
            return False
        self.db.execute("UPDATE messages SET content = ? WHERE id = ?", (text, message_id))
        self.db.execute("DELETE FROM messages WHERE chat_id = ? AND id > ?", (chat_id, message_id))
        self.db.commit()
        return True

    def branch(self, chat_id, upto_message_id, private=False):
        """A new chat that starts as a copy of this one up to and including a message: try another direction without losing the first. Returns the new chat id (None if the message is not here)."""
        msgs = [m for m in self.messages(chat_id) if m["status"] != "compacted"]
        keep = []
        for m in msgs:
            keep.append(m)
            if m["id"] == upto_message_id:
                break
        else:
            return None
        title = (self.title(chat_id) or "Chat")[:40] + " (branch)"
        new = self.new_chat(title, private=private or chat_id < 0, skill=self.skill(chat_id) or None)
        for m in keep:
            self.add(new, m["role"], m["content"], m["model_id"], m["status"] if m["status"] in ("done", "summary") else "done", docs=m.get("docs"))
        self.set_docs(new, self.docs(chat_id))
        return new

    def sent_docs(self, chat_id):
        """Ids of the files and pictures already sent with an earlier message of this chat."""
        return {i for m in self.messages(chat_id) for i in (m.get("docs") or [])}

    def list_chats(self, archived=False, everything=False):
        """Saved chats, newest first: [{"id", "title", "updated", "skill", "pinned", "folder", "archived"}]. Private chats are never listed.
        The sidebar gets the ones not archived; `archived=True` gives only the archived ones (Settings > Data controls); `everything` gives both (data export)."""
        where = "" if everything else ("WHERE COALESCE(c.archived, 0) = 1 " if archived else "WHERE COALESCE(c.archived, 0) = 0 ")
        rows = self.db.execute("SELECT c.id, c.title, COALESCE(MAX(m.created), c.created) AS t, c.skill, c.pinned, c.folder, c.archived FROM chats c "
                               "LEFT JOIN messages m ON m.chat_id = c.id " + where + "GROUP BY c.id ORDER BY t DESC, c.id DESC").fetchall()
        return [{"id": r[0], "title": r[1], "updated": r[2], "skill": r[3] or "", "pinned": bool(r[4]), "folder": r[5] or "", "archived": bool(r[6])} for r in rows]

    def set_archived(self, chat_id, archived=True):
        """Archive (out of the chat list, still searchable and still remembered) or bring back one chat."""
        if chat_id < 0:
            return
        self.db.execute("UPDATE chats SET archived = ?, pinned = CASE WHEN ? THEN 0 ELSE pinned END WHERE id = ?", (int(bool(archived)), int(bool(archived)), chat_id))
        self.db.commit()

    def archive_all(self):
        """Archive every chat in the list. Returns how many."""
        n = self.db.execute("UPDATE chats SET archived = 1, pinned = 0 WHERE COALESCE(archived, 0) = 0").rowcount
        self.db.commit()
        return n

    RECALL_CUES = re.compile(r"\b(remember|recall|last time|earlier|before|previous(ly)?|we (talked|spoke|discussed|said)|i (told|asked|said|mentioned)|you (told|said|suggested|helped)|"
                             r"our (chat|conversation)|that (chat|conversation)|again)\b", re.I)
    STOP = set("the a an and or but to of in on at for with is are was were be been it this that what which who how why when where do did does i you me my your we our "
               "can could would should will about from as by so not no yes just like get got have has had please tell remember recall last time earlier before previous "
               "previously talked spoke discussed said told asked mentioned suggested helped chat conversation again".split())

    def recall(self, question, exclude_chat=None, k=2, max_chars=700):
        """Earlier exchanges (in other saved chats, archived ones included) that match a question about the past, as a note for the model, or "".
        Only when the question points back ("last time", "remember when", "what did I tell you about"...), so ordinary questions are not distracted."""
        q = str(question or "")
        if not self.RECALL_CUES.search(q):
            return ""
        words = [w for w in re.findall(r"[a-z0-9']{3,}", q.lower()) if w not in self.STOP][:8]
        if not words:
            return ""
        like = lambda w: "%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = self.db.execute("SELECT m.id, m.chat_id, m.role, m.content, m.created, c.title FROM messages m JOIN chats c ON c.id = m.chat_id "
                               "WHERE m.role = 'user' AND m.content != '' AND m.chat_id != ? AND (" + " OR ".join("lower(m.content) LIKE ? ESCAPE '\\'" for _ in words) + ") "
                               "ORDER BY m.id DESC LIMIT 200", [exclude_chat if exclude_chat is not None else -1] + [like(w) for w in words]).fetchall()
        scored = sorted(((sum(w in r[3].lower() for w in words), r) for r in rows), key=lambda x: (-x[0], -x[1][0]))
        notes, used = [], 0
        for score, (mid, cid, role, content, created, title) in scored:
            if score < max(1, min(2, len(words))) or len(notes) >= k:
                continue
            ans = self.db.execute("SELECT content FROM messages WHERE chat_id = ? AND id > ? AND role = 'assistant' AND content != '' ORDER BY id LIMIT 1", (cid, mid)).fetchone()
            when = time.strftime("%b %d", time.localtime(created)) if created else ""
            line = f"Earlier chat \"{title}\" ({when}): User: {' '.join(content.split())[:220]}" + (f" AI: {' '.join(ans[0].split())[:260]}" if ans else "")
            if used + len(line) > max_chars:
                break
            notes.append(line)
            used += len(line)
        return ("From the user's earlier chats:\n" + "\n".join(notes)) if notes else ""

    def exists(self, chat_id):
        if chat_id < 0:
            return chat_id in self.private
        return self.db.execute("SELECT 1 FROM chats WHERE id = ?", (chat_id,)).fetchone() is not None

    def title(self, chat_id):
        if chat_id < 0:
            return "Private chat"
        r = self.db.execute("SELECT title FROM chats WHERE id = ?", (chat_id,)).fetchone()
        return r[0] if r else ""

    def set_title(self, chat_id, title):
        if chat_id >= 0:
            self.db.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))
            self.db.commit()

    def remove_message(self, chat_id, message_id):
        if chat_id < 0:
            self.private[chat_id][message_id]["status"] = "compacted"   # hidden; ids stay stable
            self.private[chat_id][message_id]["content"] = ""
            return
        self.db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        self.db.commit()

    def delete_chat(self, chat_id):
        if chat_id < 0:
            self.private.pop(chat_id, None)
            return
        self.db.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        self.db.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        self.db.commit()

    def delete_everything(self):
        self.db.execute("DELETE FROM messages")
        self.db.execute("DELETE FROM chats")
        self.db.commit()
        self.private.clear()

    def fold(self, chat_id, ids, summary):
        """Replace `ids` (older messages) by a summary for the model: the first becomes the summary, the rest are marked
        "compacted". Nothing is deleted, so the screen still shows them."""
        first, rest = ids[0], ids[1:]
        if chat_id < 0:
            msgs = self.private[chat_id]
            msgs[first].update(role="user", content=summary, status="summary")
            for i in rest:
                msgs[i]["status"] = "compacted"
            return
        self.db.execute("UPDATE messages SET role = 'user', content = ?, status = 'summary' WHERE id = ?", (summary, first))
        self.db.executemany("UPDATE messages SET status = 'compacted' WHERE id = ?", [(i,) for i in rest])
        self.db.commit()

    def interrupted(self, chat_id):
        """Replies that were cut off (the app closed or the model stopped) and never finished."""
        return [m for m in self.messages(chat_id) if m["status"] == "partial"]

    def history(self, chat_id):
        """The chat as chat.py wants it: [{"role", "content"}], a cut-off reply included (marked by its status)."""
        return [{"role": m["role"], "content": m["content"]} for m in self.messages(chat_id)
                if m["content"] and m["status"] != "compacted"]


# ------------------------------------------------------------------ one message, start to finish
def run_turn(tok, store, chat_id, backend, model, window, max_new, user_text=None, stop=None, save_every=8,
             keep_notes=1, notes=None, limiter=None, user=None, effort="balanced", clock=time.time,
             pacer=None, auto_compact=True, summarize=None, style_hint="", user_docs=None, think=False, pictures=None, on_compact=None, fixes=False):
    """Answer one message. Adds the user's message (if given), streams the reply while saving it, and returns
    {"text", "reason", "forgotten_messages"}. If the model fails mid-reply, what was written is kept (marked
    partial) and the AppError is re-raised, so the screen can offer "Continue".

    With a `limiter` (usage_limits.Limiter) and a `user`, the message is checked against the person's plan first (a
    usage_limits.LimitError is raised before anything is added or run), the estimated cost is held while the reply is
    written, and the real token counts settle it afterwards. A failed reply gives the hold back. A model that runs on
    the device (model["where"] == "device") is never counted.

    `style_hint` is a one-time line added to the end of the last question in the prompt only (Regenerate options).
    `think=True` (Deep, on models that can think) leaves the empty thinking block off the end of the prompt, so the model reasons first; the reasoning is
    hidden from the answer (strip_think below) and counts toward `max_new`.
    `pictures` (base64 strings) go to a model that can look at pictures itself (an Emvryx 3 model run with its mmproj): they are placed just before the question.
    `pacer` (chat_polish.paced, with the time of sending) makes the reply appear after a short pause and write out
    steadily. `auto_compact` shortens a chat that fills the model's memory (chat_polish.compact_chat); `on_compact()` is called as that starts.
    The result's "context" says how full the model's memory is after this reply (the page's memory meter); it is also kept on the reply as its "ctx" mark.
    `fixes` (flag chat_fixes): formatting is never taken for a loop (LOOP_SPAN), and llama-server's own counts are used for the plan, so the part of the
    chat it still had in memory counts at the cached rate instead of all over again.
    """
    user_row = store.add(chat_id, "user", user_text, docs=user_docs) if user_text is not None else None
    folded = 0
    if auto_compact:
        folded = chat_polish.compact_chat(tok, store, chat_id, window, max_new, summarize=summarize, keep_notes=keep_notes, on_start=on_compact)
    history = store.history(chat_id)
    asked = history[-1]["content"] if history and history[-1]["role"] == "user" else ""     # where the pictures go (before any hint is added)
    if style_hint and history and history[-1]["role"] == "user":      # asked for only this once: the saved chat keeps the plain question
        history[-1] = dict(history[-1], content=history[-1]["content"].rstrip() + "\n\n" + style_hint)
    if think and history and history[-1]["role"] == "user":           # Deep: no empty thinking block after this question (chat.build_prompt)
        history[-1] = dict(history[-1], thinking=True)
    if notes and history and history[-1]["role"] == "user":       # also on Regenerate and on the second try with web notes
        history[-1]["notes"] = notes
    limit = window - max_new
    report = chat.context_report(tok, history, window, reserve=max_new, keep_notes=keep_notes)
    ids = chat.build_prompt(tok, history, limit, keep_notes=keep_notes)
    res = None
    if limiter is not None and user is not None:
        key = model["name"].lower()
        est = (len(ids) + max_new) * limiter.weight(key) * limiter.cfg["effort"][effort]
        try:
            res = limiter.reserve(user, key, effort, est, clock(), where="device" if model.get("where") == "device" else "server")
        except Exception:
            if user_row is not None:                           # refused: the question was never asked
                store.remove_message(chat_id, user_row)
            raise
    row = store.add(chat_id, "assistant", "", model["id"], "partial")
    opened = bool(fixes and think and getattr(tok, "think", None) == "empty" and hasattr(tok, "_plain"))
    if opened:                                                  # Deep on an Emvryx 3 model: the thinking block is opened for it, as its own template does, so its reasoning
        ids = list(ids) + list(tok._plain("<think>\n"))           # is always inside the block (when it began without "<think>", the reasoning showed in the answer)
    prompt = {"prompt_string": with_pictures(tok.decode(ids), asked, len(pictures)), "multimodal_data": list(pictures)} if pictures else ids
    if fixes and isinstance(backend, LlamaServer):
        backend.count_cache, backend.usage = True, None              # this reply's own counts (both parts of a Deep reply add up)
    raw = think_budget(backend, tok, prompt, max_new) if think else backend.stream(prompt, max_new)
    stream = strip_source(strip_think(until_stopped(raw, stop), inside=opened))
    guard = Guard(pacer(stream) if pacer else stream, stop=stop, max_chars=max(MAX_REPLY_CHARS, int(max_new * 5)), loop_span=LOOP_SPAN if fixes else 0)   # a long answer is not a loop: room for what the model was allowed
    count = 0
    try:
        for _ in guard:
            count += 1
            if count % save_every == 0:
                store.update(chat_id, row, guard.text, "partial")
    except AppError:
        store.update(chat_id, row, guard.text, "partial")
        _settle(limiter, res, backend, tok, ids, guard.text, effort, clock, failed=not guard.text)
        raise
    except Exception as e:                                     # a broken connection, a crashed server...
        store.update(chat_id, row, guard.text, "partial")
        _settle(limiter, res, backend, tok, ids, guard.text, effort, clock, failed=not guard.text)
        raise ReplyInterrupted() from e
    if stop is not None and stop.is_set() and guard.reason == "done":
        guard.reason = "stopped"                               # stopped while it was still thinking: nothing came out after the press
    store.update(chat_id, row, guard.text, "done")
    _settle(limiter, res, backend, tok, ids, guard.text, effort, clock)
    cut = guard.reason == "length"                             # the reply hit its length limit: the page offers "Continue"
    if not cut and guard.text and guard.reason == "done":
        out_tokens = (getattr(backend, "usage", None) or {}).get("out") or len(tok.encode(guard.text, allow_special=False))
        cut = out_tokens >= max_new - 2
    if cut:
        store.set_flag(chat_id, row, "cut", True)
    ctx = context_meter(len(ids) + len(tok.encode(guard.text, allow_special=False)) if guard.text else len(ids), window, max_new)
    store.set_flag(chat_id, row, "ctx", ctx)
    return {"text": guard.text, "reason": guard.reason, "forgotten_messages": report["forgotten_messages"],
            "message_id": row, "compacted_messages": folded, "cut": cut, "context": ctx}


def context_meter(used, window, max_new):
    """How full the model's memory (context window) is, for the meter by the message box: tokens used, the window, the share used, and when the
    older messages will be summarized (chat_polish.compact_point: 75% of the room left after the reply's share, at most 96K)."""
    used, window = max(0, int(used)), max(1, int(window))
    return {"used": used, "window": window, "pct": round(min(100.0, 100.0 * used / window), 1), "compact_at": chat_polish.compact_point(window, max_new)}


def _settle(limiter, res, backend, tok, ids, text, effort, clock, failed=False):
    """Count what was really used. A reply that produced nothing costs nothing. Backends that report their own counts
    (backend.usage = {"fresh_in", "cached_in", "out"}) are trusted; otherwise the prompt and the reply are counted."""
    if limiter is None or res is None:
        return
    if failed:
        limiter.cancel(res, clock())
        return
    u = getattr(backend, "usage", None) or {}
    fresh = u.get("fresh_in", len(ids))
    out = u.get("out", len(tok.encode(text, allow_special=False)) if text else 0)
    limiter.settle(res, fresh, u.get("cached_in", 0), out, effort, clock())


# ------------------------------------------------------------------ the model
class FakeBackend:
    """A stand-in model for tests: `script` is the reply; mode picks a failure."""

    def __init__(self, script="Hello there, how can I help?", mode="ok", die_after=3, pause=0.0):
        self.script, self.mode, self.die_after, self.prompts = script, mode, die_after, []
        self.limits = []                   # the most tokens each reply was allowed (max_new)
        self.pause = pause                 # seconds between words in "forever" mode: a reply a test can interrupt

    def stream(self, ids, max_new):
        self.prompts.append(dict(ids) if isinstance(ids, dict) else list(ids))       # a dict: the prompt text with pictures (see with_pictures)
        self.limits.append(max_new)
        if self.mode == "dead":
            raise PcUnreachable()
        if self.mode == "loop":
            while True:
                yield "and so on. "
        if self.mode == "forever":
            i = 0
            while True:
                i += 1
                if self.pause:
                    time.sleep(self.pause)
                yield f"word{i} "
        for i, word in enumerate(self.script.split(" ")):
            if self.mode == "die_after" and i >= self.die_after:
                raise ConnectionResetError("the model went away")
            yield word + " "


_MARKERS = {}          # llama-server address -> its picture place-holder (LlamaServer.media_marker)


class LlamaServer:
    """llama.cpp's llama-server over HTTP. The app builds the prompt (token ids) itself and uses the raw
    /completion endpoint, because our chat format isn't the template stored in the .gguf (docs/APP_SPEC.md)."""

    def __init__(self, base_url="http://127.0.0.1:8080", key=None, timeout=60, **sampling):
        self.base, self.key, self.timeout = base_url.rstrip("/"), key, timeout
        self.sampling = {"temperature": 0.8, "top_k": 50, "repeat_penalty": 1.15, **sampling}
        self.count_cache, self.usage = False, None      # count_cache (chat_fixes): usage = llama-server's own {"fresh_in", "cached_in", "out"} for the reply

    def _note_usage(self, data):
        """Add one request's counts from llama-server's last message: prompt_n is what it had to read, cache_n what it still had in memory."""
        t = data.get("timings") or {}
        if not t and "tokens_evaluated" not in data:
            return
        cached = int(t.get("cache_n", data.get("tokens_cached", 0)) or 0)
        fresh = int(t["prompt_n"]) if "prompt_n" in t else max(0, int(data.get("tokens_evaluated", 0) or 0) - cached)
        out = int(t.get("predicted_n", data.get("tokens_predicted", 0)) or 0)
        u = self.usage or {"fresh_in": 0, "cached_in": 0, "out": 0}
        self.usage = {"fresh_in": u["fresh_in"] + fresh, "cached_in": u["cached_in"] + cached, "out": u["out"] + out}

    def _request(self, path, body=None):
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        req = urllib.request.Request(self.base + path, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise BadKey()
            if e.code == 400 and path == "/completion":            # llama-server said no to this request (e.g. a picture it cannot take): say why
                raise ModelRefused(_refusal(e))
            raise WrongServer(f"HTTP {e.code}")
        except (urllib.error.URLError, OSError):
            raise PcUnreachable()

    def media_marker(self):
        """The place-holder this llama-server wants for one picture. Newer builds choose their own (GET /props "media_marker"), so a fixed <__media__>
        no longer matches and the request fails with "Failed to tokenize prompt". Asked once per running server."""
        if self.base not in _MARKERS:
            marker = MEDIA_MARKER
            try:
                with self._request("/props") as r:
                    marker = json.load(r).get("media_marker") or MEDIA_MARKER
            except (AppError, ValueError, OSError):
                pass
            _MARKERS[self.base] = marker
        return _MARKERS[self.base]

    def stream(self, ids, max_new):
        prompt = ids if isinstance(ids, dict) else list(ids)       # token ids, or {"prompt_string", "multimodal_data"} when pictures go with it
        if isinstance(prompt, dict) and prompt.get("multimodal_data"):
            marker = self.media_marker()
            if marker != MEDIA_MARKER:
                prompt = dict(prompt, prompt_string=prompt["prompt_string"].replace(MEDIA_MARKER, marker))
        r = self._request("/completion", {"prompt": prompt, "n_predict": max_new, "stream": True, **self.sampling})
        try:
            for line in r:
                line = line.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = json.loads(line[5:])
                if data.get("content"):
                    yield data["content"]
                if data.get("stop"):
                    if self.count_cache:
                        self._note_usage(data)
                    return
        finally:
            r.close()


def _refusal(err):
    """llama-server's own reason for a refused request ({"error": {"message": ...}}), short; "" when it gave none."""
    try:
        body = json.loads(err.read(4000).decode("utf-8", "replace") or "{}")
        e = body.get("error", body)
        msg = e.get("message", "") if isinstance(e, dict) else str(e)
    except (ValueError, OSError, AttributeError):
        return ""
    return " ".join(str(msg).split())[:200]


def test_connection(base_url, key=None, timeout=5):
    """The "Test connection" button: {"ok": bool, "message": str}, always with a specific reason."""
    try:
        r = LlamaServer(base_url, key, timeout)._request("/health")
        with r:
            body = r.read(2000).decode("utf-8", "replace")
        json.loads(body)
        return {"ok": True, "message": "Connected."}
    except AppError as e:
        return {"ok": False, "message": f"{e.message} {e.action}"}
    except ValueError:
        err = WrongServer("it didn't answer like llama-server")
        return {"ok": False, "message": f"{err.message} {err.action}"}
