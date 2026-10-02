"""
app_engine.py - The parts of the app that make a chat reliable (no web page in here, so every part can be tested).

WHAT THIS FILE DOES
    The path of one message (docs/APP_SPEC.md, Part 3) and what happens when a step fails:

      choose_model   which model answers: refuses one the device is too small for (offers the next smaller), and when
                     the PC is off asks before switching to the on-device model (never silently)
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
import json
import sqlite3
import threading
import time
import urllib.error
import urllib.request

import chat
from app_errors import AppError, BadKey, ModelTooBig, PcUnreachable, ReplyInterrupted, WrongServer

MAX_REPLY_CHARS = 8000          # ~2,000 tokens: a reply longer than the whole memory is a loop, not an answer


# ------------------------------------------------------------------ which model answers
def smaller_fallback(models, model, ram_gb):
    """The biggest on-device model that fits `ram_gb` and is not the one that didn't fit (or None)."""
    fits = [m for m in models if m["where"] == "device" and m["id"] != model["id"]
            and (ram_gb is None or m["min_ram_gb"] <= ram_gb)]
    return max(fits, key=lambda m: (m["min_ram_gb"], m["version"]), default=None)


def choose_model(models, model_id, ram_gb=None, pc_online=True, ask=None):
    """The model to run: `models` is the visible list, `model_id` the person's choice.

    Too big for the device -> ModelTooBig (with the next smaller one offered).
    Online model but the PC is off -> asks `ask(fallback_model) -> bool`; without a yes, raises PcUnreachable
    (so the app shows the question). Never switches without asking."""
    model = next(m for m in models if m["id"] == model_id)
    if model["where"] == "device" and ram_gb is not None and ram_gb < model["min_ram_gb"]:
        raise ModelTooBig(model, ram_gb, smaller_fallback(models, model, ram_gb))
    if model["where"] == "online" and not pc_online:
        fallback = smaller_fallback(models, model, ram_gb)
        if fallback and ask and ask(fallback):
            return fallback
        raise PcUnreachable(fallback)
    return model


# ------------------------------------------------------------------ keeping a reply under control
def is_looping(text, min_unit=4, max_unit=120, repeats=4):
    """True if the text ends with the same piece repeated `repeats` times in a row (a stuck model)."""
    for n in range(min_unit, max_unit + 1):
        if len(text) >= n * repeats and text[-n * repeats:] == text[-n:] * repeats:
            return True
    return False


class Guard:
    """Wrap a stream of text pieces. Stops it at the length cap, when it loops, or when `stop` is set (the Stop
    button). `reason` is then "length", "loop" or "stopped"; "done" when the model ended by itself."""

    def __init__(self, pieces, max_chars=MAX_REPLY_CHARS, stop=None):
        self.pieces, self.max_chars, self.stop, self.reason, self.text = pieces, max_chars, stop, "done", ""

    def __iter__(self):
        try:
            for piece in self.pieces:
                if self.stop is not None and self.stop.is_set():
                    self.reason = "stopped"
                    return
                self.text += piece
                yield piece
                if len(self.text) >= self.max_chars:
                    self.reason = "length"
                    return
                if is_looping(self.text[-self.max_chars:]):
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
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY, title TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, chat_id INTEGER, role TEXT, content TEXT,
                model_id TEXT, status TEXT, created REAL);""")
        self.private = {}                    # private chats live here only: {chat_id: [messages]}
        self._next_private = -1

    def new_chat(self, title="New chat", private=False):
        if private:
            cid, self._next_private = self._next_private, self._next_private - 1
            self.private[cid] = []
            return cid
        cur = self.db.execute("INSERT INTO chats (title, created) VALUES (?, ?)", (title, time.time()))
        self.db.commit()
        return cur.lastrowid

    def add(self, chat_id, role, content, model_id="", status="done"):
        if chat_id < 0:
            self.private[chat_id].append({"id": len(self.private[chat_id]), "role": role, "content": content,
                                          "model_id": model_id, "status": status})
            return len(self.private[chat_id]) - 1
        cur = self.db.execute("INSERT INTO messages (chat_id, role, content, model_id, status, created) "
                              "VALUES (?, ?, ?, ?, ?, ?)", (chat_id, role, content, model_id, status, time.time()))
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
        rows = self.db.execute("SELECT id, role, content, model_id, status FROM messages WHERE chat_id = ? ORDER BY id",
                               (chat_id,)).fetchall()
        return [dict(zip(("id", "role", "content", "model_id", "status"), r)) for r in rows]

    def interrupted(self, chat_id):
        """Replies that were cut off (the app closed or the model stopped) and never finished."""
        return [m for m in self.messages(chat_id) if m["status"] == "partial"]

    def history(self, chat_id):
        """The chat as chat.py wants it: [{"role", "content"}], a cut-off reply included (marked by its status)."""
        return [{"role": m["role"], "content": m["content"]} for m in self.messages(chat_id) if m["content"]]


# ------------------------------------------------------------------ one message, start to finish
def run_turn(tok, store, chat_id, backend, model, window, max_new, user_text=None, stop=None, save_every=8,
             keep_notes=1, notes=None):
    """Answer one message. Adds the user's message (if given), streams the reply while saving it, and returns
    {"text", "reason", "forgotten_messages"}. If the model fails mid-reply, what was written is kept (marked
    partial) and the AppError is re-raised, so the screen can offer "Continue".
    """
    if user_text is not None:
        store.add(chat_id, "user", user_text)
    history = store.history(chat_id)
    if user_text is not None and notes:
        history[-1]["notes"] = notes
    limit = window - max_new
    report = chat.context_report(tok, history, window, reserve=max_new, keep_notes=keep_notes)
    ids = chat.build_prompt(tok, history, limit, keep_notes=keep_notes)
    row = store.add(chat_id, "assistant", "", model["id"], "partial")
    guard = Guard(backend.stream(ids, max_new), stop=stop)
    count = 0
    try:
        for _ in guard:
            count += 1
            if count % save_every == 0:
                store.update(chat_id, row, guard.text, "partial")
    except AppError:
        store.update(chat_id, row, guard.text, "partial")
        raise
    except Exception as e:                                     # a broken connection, a crashed server...
        store.update(chat_id, row, guard.text, "partial")
        raise ReplyInterrupted() from e
    store.update(chat_id, row, guard.text, "done")
    return {"text": guard.text, "reason": guard.reason, "forgotten_messages": report["forgotten_messages"],
            "message_id": row}


# ------------------------------------------------------------------ the model
class FakeBackend:
    """A stand-in model for tests: `script` is the reply; mode picks a failure."""

    def __init__(self, script="Hello there, how can I help?", mode="ok", die_after=3):
        self.script, self.mode, self.die_after, self.prompts = script, mode, die_after, []

    def stream(self, ids, max_new):
        self.prompts.append(list(ids))
        if self.mode == "dead":
            raise PcUnreachable()
        if self.mode == "loop":
            while True:
                yield "and so on. "
        if self.mode == "forever":
            i = 0
            while True:
                i += 1
                yield f"word{i} "
        for i, word in enumerate(self.script.split(" ")):
            if self.mode == "die_after" and i >= self.die_after:
                raise ConnectionResetError("the model went away")
            yield word + " "


class LlamaServer:
    """llama.cpp's llama-server over HTTP. The app builds the prompt (token ids) itself and uses the raw
    /completion endpoint, because our chat format isn't the template stored in the .gguf (docs/APP_SPEC.md)."""

    def __init__(self, base_url="http://127.0.0.1:8080", key=None, timeout=60, **sampling):
        self.base, self.key, self.timeout = base_url.rstrip("/"), key, timeout
        self.sampling = {"temperature": 0.8, "top_k": 50, "repeat_penalty": 1.15, **sampling}

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
            raise WrongServer(f"HTTP {e.code}")
        except (urllib.error.URLError, OSError):
            raise PcUnreachable()

    def stream(self, ids, max_new):
        r = self._request("/completion", {"prompt": list(ids), "n_predict": max_new, "stream": True, **self.sampling})
        try:
            for line in r:
                line = line.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = json.loads(line[5:])
                if data.get("content"):
                    yield data["content"]
                if data.get("stop"):
                    return
        finally:
            r.close()


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
