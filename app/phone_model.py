"""
phone_model.py - android_offline_model: one of your own models runs on the phone itself, so the Android app still answers when the PC is off.

WHAT THIS FILE DOES
    * `pick` chooses the model the phone gets: models.json "phone_model" when set, else the newest small ("Lite") open model whose file is on this
      PC (Flare). The phone runs the same .gguf file the PC runs, with llama.cpp built into the app.
    * `Checksums` works out the file's SHA-256 once (in the background: about 2 GB takes a few seconds) and keeps it with the file's size and time,
      so the phone can check that the download arrived whole before it ever loads it.
    * `kit` is everything the phone needs to answer like the PC does: the chat format (the same ChatML turns as core/chat.py and
      open_tokenizer.py, with the empty thinking block of the Emvryx 3 models), the sampling, the reply length, and this person's own
      instructions (custom instructions, how they like replies to sound, the house rules) and memory, copied to the phone for when the PC is off.
    * `serve_range` sends the file, or the rest of it from a byte offset (HTTP Range), so a download that stopped carries on where it was.
    Only signed-in people with the switch on get any of it; nothing names the model's base to the person.
"""
import hashlib
import json
import os
import re
import threading

import user_memory

EMPTY_THINK = "<think>\n\n</think>\n\n"                 # open_tokenizer.OpenTokenizer.EMPTY_THINK: the answer starts with no thinking
PHONE_CONTEXT = 4096                                     # tokens the phone keeps in view: a phone has far less memory than the PC
PHONE_REPLY = 1024


PHONE_TIERS = ("lite", "standard")                       # Flare (fast) and Equinox (smarter, needs a phone with about 8 GB): never the big ones


def choices(manifest, files):
    """The models a phone may pick: the newest open Lite and Standard model of each name whose file is on this PC, smallest first."""
    have = lambda m: bool(files.get(m["id"])) and os.path.exists(files[m["id"]])     # noqa: E731
    best = {}
    for m in manifest.get("models", []):
        if m.get("archived") or not m.get("open") or str(m.get("tier", "")).lower() not in PHONE_TIERS or not have(m):
            continue
        if m["name"] not in best or float(m.get("version") or 0) > float(best[m["name"]].get("version") or 0):
            best[m["name"]] = m
    return sorted(best.values(), key=lambda m: os.path.getsize(files[m["id"]]))


def pick(manifest, files, want=None, asked=None):
    """The model for phones: {"id", ...} from models.json, or None when this PC has no file for one. `asked`: the phone's own choice,
    only ever one of `choices` (a phone can never fetch the big models)."""
    if asked:
        return next((m for m in choices(manifest, files) if m["id"] == asked), None)
    models = [m for m in manifest.get("models", []) if not m.get("archived")]
    want = want or manifest.get("phone_model")
    have = lambda m: bool(files.get(m["id"])) and os.path.exists(files[m["id"]])     # noqa: E731
    if want:
        return next((m for m in models if m["id"] == want and have(m)), None)
    small = [m for m in models if m.get("open") and str(m.get("tier", "")).lower() == "lite" and have(m)]
    return max(small, key=lambda m: float(m.get("version") or 0), default=None)


class Checksums:
    """The SHA-256 of each model file, worked out once in the background and kept in data_dir/phone_model_sha.json."""

    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "phone_model_sha.json") if data_dir else None
        self.lock = threading.Lock()
        self.busy = set()
        self.known = {}
        if self.path:
            try:
                with open(self.path, encoding="utf-8") as f:
                    got = json.load(f)
                self.known = got if isinstance(got, dict) else {}
            except (OSError, ValueError):
                pass

    @staticmethod
    def _sig(path):
        st = os.stat(path)
        return f"{path}|{st.st_size}|{int(st.st_mtime)}"

    def get(self, path, wait=False):
        """The checksum, or None while it is still being worked out (it starts the first time it is asked for)."""
        sig = self._sig(path)
        with self.lock:
            if sig in self.known:
                return self.known[sig]
            start = sig not in self.busy
            self.busy.add(sig)
        if wait:
            self._work(path, sig)
            return self.known.get(sig)
        if start:
            threading.Thread(target=self._work, args=(path, sig), daemon=True).start()
        return None

    def _work(self, path, sig):
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    h.update(block)
        except OSError:
            with self.lock:
                self.busy.discard(sig)
            return
        with self.lock:
            self.known = {k: v for k, v in self.known.items() if not k.startswith(path + "|")}     # an older file at this path is forgotten
            self.known[sig] = h.hexdigest()
            self.busy.discard(sig)
            if self.path:
                try:
                    with open(self.path + ".tmp", "w", encoding="utf-8") as f:
                        json.dump(self.known, f)
                    os.replace(self.path + ".tmp", self.path)
                except OSError:
                    pass


def chat_format(model):
    """The pieces the phone writes a prompt with (core/chat.py _encode_message_chatml), as text."""
    think = model.get("think") == "empty"
    return {"user_open": "<|im_start|>user\n", "turn_end": "<|im_end|>\n",
            "assistant_open": "<|im_start|>assistant\n" + (EMPTY_THINK if think else ""),
            "stop": ["<|im_end|>", "<|im_start|>", "<|endoftext|>"], "notes_intro": "Notes:\n", "question_intro": "\n\nQuestion: "}


def sampling(model):
    s = dict(model.get("sampling") or {})
    s.update((model.get("fixes") or {}).get("sampling") or {})
    keep = ("temperature", "top_k", "top_p", "min_p", "repeat_penalty", "presence_penalty")
    return {k: float(s[k]) for k in keep if isinstance(s.get(k), (int, float)) and not isinstance(s.get(k), bool)}


def kit(model, size, sha256, hints, memory_facts, memory_on):
    """What GET /api/phone-model sends: the file to fetch and how to answer with it."""
    return {
        "available": True, "id": model["id"], "name": model.get("name", ""), "version": model.get("version"),
        "size": size, "sha256": sha256, "preparing": sha256 is None, "file": "/api/phone-model/file?model=" + model["id"],
        "format": chat_format(model), "sampling": sampling(model),
        "max_reply_tokens": min(PHONE_REPLY, int(model.get("max_reply_tokens") or PHONE_REPLY)), "context": PHONE_CONTEXT,
        "min_ram_gb": model.get("min_ram_gb") or 4,
        "hints": hints,
        "memory": {"on": bool(memory_on), "title": user_memory.TITLE, "facts": [f["text"] for f in memory_facts][-60:],
                   "personal": user_memory.PERSONAL.pattern},
    }


RANGE = re.compile(r"bytes=(\d+)-(\d*)$")


def byte_range(header, size):
    """(start, end) to send for a Range header (end included), None for the whole file, or "bad" when it cannot be met (416)."""
    m = RANGE.match((header or "").strip())
    if not m:
        return None
    start = int(m.group(1))
    end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
    if start >= size or end < start:
        return "bad"
    return start, end


def serve_range(handler, path, range_header):
    """Sends the file (200) or the asked-for part of it (206) on a BaseHTTPRequestHandler, in 1 MB pieces."""
    size = os.path.getsize(path)
    r = byte_range(range_header, size)
    if r == "bad":
        handler.send_response(416)
        handler.send_header("Content-Range", f"bytes */{size}")
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return
    start, end = r if r else (0, size - 1)
    handler.send_response(206 if r else 200)
    handler.send_header("Content-Type", "application/octet-stream")
    handler.send_header("Content-Length", str(end - start + 1))
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Cache-Control", "no-store")
    if r:
        handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    handler.end_headers()
    left = end - start + 1
    with open(path, "rb") as f:
        f.seek(start)
        while left > 0:
            block = f.read(min(1 << 20, left))
            if not block:
                break
            try:
                handler.wfile.write(block)
            except (BrokenPipeError, ConnectionResetError):
                return                                                   # the phone stopped (no signal): it carries on from here next time
            left -= len(block)


def for_person(state, who, asked=None):
    """GET /api/phone-model for this person: {"available": False, "message"} when this PC has no model for phones, else the kit (of the model
    the phone `asked` for, when it is one of the choices) with the choices."""
    files = getattr(state.runner, "files", None) or {} if state.runner else {}
    model = pick(state.manifest, files, asked=asked) if asked else None
    model = model or pick(state.manifest, files)
    if not model:
        return {"available": False, "message": "This PC has no model for phones yet (a small Flare model file is needed)."}
    path = files[model["id"]]
    settings = state.get_settings(who["user"])
    import app_skills
    import chat_turn
    memory = state.memory_for(who["user"])
    hints = [app_skills.custom_hint(settings.get("custom_instructions")), memory.style_hint() if settings["memory"] else ""]
    if model.get("think") == "empty" and state.flags.on("chat_house_rules", who):
        hints.append(chat_turn.HOUSE_HINT)
    out = kit(model, os.path.getsize(path), state.phone_sha.get(path), "\n\n".join(h for h in hints if h),
              memory.list() if settings["memory"] else [], settings["memory"])
    out["choices"] = [{"id": m["id"], "name": m.get("name", ""), "version": m.get("version"), "size": os.path.getsize(files[m["id"]]),
                       "min_ram_gb": m.get("min_ram_gb") or 4, "tagline": m.get("tagline", "")} for m in choices(state.manifest, files)]
    return out


def file_for(state, asked=None):
    files = getattr(state.runner, "files", None) or {} if state.runner else {}
    model = (pick(state.manifest, files, asked=asked) if asked else None) or (None if asked else pick(state.manifest, files))
    return files[model["id"]] if model else None


MAX_SYNC_MESSAGES = 400
MAX_SYNC_CHARS = 40_000


class Synced:
    """The sync ids already taken in, per person (data_dir/phone_sync.json, the last 500): a sync the phone retries after a lost answer
    is not added twice."""

    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "phone_sync.json") if data_dir else None
        self.lock = threading.Lock()
        self.seen = {}
        if self.path:
            try:
                with open(self.path, encoding="utf-8") as f:
                    got = json.load(f)
                self.seen = got if isinstance(got, dict) else {}
            except (OSError, ValueError):
                pass

    def get(self, user, sync_id):
        return self.seen.get(user, {}).get(sync_id)

    def put(self, user, sync_id, chat_id):
        with self.lock:
            mine = self.seen.setdefault(user, {})
            mine[sync_id] = chat_id
            while len(mine) > 500:
                mine.pop(next(iter(mine)))
            if self.path:
                with open(self.path + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(self.seen, f)
                os.replace(self.path + ".tmp", self.path)


def sync_chat(store, synced, user, body):
    """POST /api/phone-sync: messages written on the phone while the PC was off, added to an existing chat ("chat": its id) or to a new one.
    {"sync_id", "chat", "title", "model", "messages": [{"role", "content"}]} -> the chat's id. A sync_id seen before changes nothing."""
    sync_id = str(body.get("sync_id") or "")[:64]
    if not sync_id:
        raise ValueError("A sync id is needed.")
    done = synced.get(user, sync_id)
    if done is not None:
        return done
    msgs = [m for m in body.get("messages") or [] if isinstance(m, dict) and m.get("role") in ("user", "assistant") and str(m.get("content") or "").strip()]
    if not msgs or len(msgs) > MAX_SYNC_MESSAGES:
        raise ValueError("Nothing to add, or too much at once.")
    model = "phone:" + re.sub(r"[^\w.\-]", "", str(body.get("model") or "phone"))[:40]
    cid = body.get("chat")
    if not (isinstance(cid, int) and not isinstance(cid, bool) and cid >= 0 and store.exists(cid)):
        cid = store.new_chat(title=" ".join(str(body.get("title") or "Chat on the phone").split())[:80] or "Chat on the phone")
    for m in msgs:
        store.add(cid, m["role"], str(m["content"])[:MAX_SYNC_CHARS], model_id=model if m["role"] == "assistant" else "")
    synced.put(user, sync_id, cid)
    return cid
