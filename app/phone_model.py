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
    * `vision_kit` (android_phone_vision): the PC's picture helper files (vision.py), so the phone can look at a picture itself too.
    Only signed-in people with the switch on get any of it; nothing names the model's base to the person.
"""
# Standard library tools used below: hashlib makes SHA-256 fingerprints, json reads/writes files, os handles paths and file sizes,
# re is regular expressions (text patterns), threading runs work in the background.
import hashlib
import json
import os
import re
import threading

# Project module that holds a person's saved memory facts (we copy them to the phone).
import user_memory

EMPTY_THINK = "<think>\n\n</think>\n\n"                 # open_tokenizer.OpenTokenizer.EMPTY_THINK: the answer starts with no thinking
PHONE_CONTEXT = 4096                                     # tokens the phone keeps in view: a phone has far less memory than the PC
# The longest reply (in tokens, i.e. word pieces) the phone is asked to write.
PHONE_REPLY = 1024


PHONE_TIERS = ("lite", "standard")                       # Flare (fast) and Equinox (smarter, needs a phone with about 8 GB): never the big ones


# Which models may a phone download? Used by `pick` and by the model list sent to the phone.
def choices(manifest, files):
    """The models a phone may pick: the newest open Lite and Standard model of each name whose file is on this PC, smallest first.

    manifest: the parsed models.json (a dict with a "models" list). files: dict of model id -> path of its .gguf file on this PC.
    Returns a list of model dicts (the entries from models.json), sorted by file size so the smallest download comes first.
    """
    # `have(m)` is True when this PC knows a file path for model m and that file really exists on disk.
    have = lambda m: bool(files.get(m["id"])) and os.path.exists(files[m["id"]])     # noqa: E731
    # best maps a model name (e.g. one family name) to its newest version, so old versions of the same model are dropped.
    best = {}
    for m in manifest.get("models", []):
        # Skip models that are retired, not open, too big for a phone (wrong tier) or have no file here.
        if m.get("archived") or not m.get("open") or str(m.get("tier", "")).lower() not in PHONE_TIERS or not have(m):
            continue
        # Keep this one if its name is new, or if its version number is higher than the one kept so far.
        if m["name"] not in best or float(m.get("version") or 0) > float(best[m["name"]].get("version") or 0):
            best[m["name"]] = m
    # Smallest file first, so the phone sees the lightest download at the top.
    return sorted(best.values(), key=lambda m: os.path.getsize(files[m["id"]]))


# Chooses the single model to hand to a phone.
def pick(manifest, files, want=None, asked=None):
    """The model for phones: {"id", ...} from models.json, or None when this PC has no file for one. `asked`: the phone's own choice,
    only ever one of `choices` (a phone can never fetch the big models)."""
    # The phone asked for a model by id: only give it if it is one of the allowed choices (never a big model), else None.
    if asked:
        return next((m for m in choices(manifest, files) if m["id"] == asked), None)
    # No specific request: work from the models that are not retired.
    models = [m for m in manifest.get("models", []) if not m.get("archived")]
    # The owner can name a model for phones in models.json ("phone_model"); an explicit `want` argument wins over it.
    want = want or manifest.get("phone_model")
    have = lambda m: bool(files.get(m["id"])) and os.path.exists(files[m["id"]])     # noqa: E731
    # A model was named: return it if its file is here, otherwise None (no silent swap to another model).
    if want:
        return next((m for m in models if m["id"] == want and have(m)), None)
    # Nothing named: default to the newest small ("Lite") open model whose file is on this PC.
    small = [m for m in models if m.get("open") and str(m.get("tier", "")).lower() == "lite" and have(m)]
    # max() with default=None gives None instead of an error when the list is empty.
    return max(small, key=lambda m: float(m.get("version") or 0), default=None)


class Checksums:
    """The SHA-256 of each model file, worked out once in the background and kept in data_dir/phone_model_sha.json."""

    # data_dir: the folder where the app keeps its data files (may be empty, then nothing is saved to disk).
    # self.lock guards the dicts below because background threads and web requests use them at the same time.
    # self.busy: signatures being hashed right now (so we never start the same job twice).
    # self.known: signature -> finished SHA-256 text.
    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "phone_model_sha.json") if data_dir else None
        self.lock = threading.Lock()
        self.busy = set()
        self.known = {}
        if self.path:
            try:
                with open(self.path, encoding="utf-8") as f:
                    # Load the saved checksums from the last run so a restart does not have to re-hash a 2 GB file.
                    got = json.load(f)
                self.known = got if isinstance(got, dict) else {}
            # A missing/unreadable file (OSError) or broken JSON (ValueError) just means we start with nothing known.
            except (OSError, ValueError):
                pass

    # A static method does not use `self`; it is just a helper that lives inside the class.
    @staticmethod
    def _sig(path):
        """A 'signature' of the file: path, size and last-changed second. If the file is replaced, the signature changes, so an old checksum is never reused."""
        st = os.stat(path)
        return f"{path}|{st.st_size}|{int(st.st_mtime)}"

    def get(self, path, wait=False):
        """The checksum, or None while it is still being worked out (it starts the first time it is asked for)."""
        # Identify this exact version of the file.
        sig = self._sig(path)
        # Hold the lock while reading/changing the shared dicts so two threads cannot collide.
        with self.lock:
            if sig in self.known:
                return self.known[sig]
            # Only the first asker starts the hashing job; later askers just see it is already running.
            start = sig not in self.busy
            self.busy.add(sig)
        # wait=True: hash right here (blocking) and return the answer instead of None.
        if wait:
            self._work(path, sig)
            return self.known.get(sig)
        # Run the slow hashing in a background daemon thread (daemon = it will not keep the program alive on shutdown); the caller gets None now and the phone asks again later.
        if start:
            threading.Thread(target=self._work, args=(path, sig), daemon=True).start()
        return None

    def _work(self, path, sig):
        """Reads the whole file, works out its SHA-256, and stores and saves it. Runs in a background thread. On a read error it gives up quietly."""
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                # Read 1 MB at a time (1 << 20 = 1,048,576 bytes) until the file ends (read returns empty bytes), so a 2 GB file never has to fit in memory.
                for block in iter(lambda: f.read(1 << 20), b""):
                    # Feed each piece into the running hash.
                    h.update(block)
        # The file vanished or could not be read: mark the job as not running any more so a later ask can retry.
        except OSError:
            with self.lock:
                self.busy.discard(sig)
            return
        with self.lock:
            # Drop the checksum of an older version of this same file path.
            self.known = {k: v for k, v in self.known.items() if not k.startswith(path + "|")}     # an older file at this path is forgotten
            # Remember the finished checksum as hex text.
            self.known[sig] = h.hexdigest()
            self.busy.discard(sig)
            if self.path:
                try:
                    # Save safely: write to a .tmp file first, then os.replace swaps it in in one step, so a crash never leaves a half-written file.
                    with open(self.path + ".tmp", "w", encoding="utf-8") as f:
                        json.dump(self.known, f)
                    os.replace(self.path + ".tmp", self.path)
                # Not being able to save is not fatal: the checksum stays in memory.
                except OSError:
                    pass


def chat_format(model):
    """The pieces the phone writes a prompt with (core/chat.py _encode_message_chatml), as text.

    ChatML is the chat layout this model was trained on: each turn is wrapped in <|im_start|>role ... <|im_end|> marker words.
    Returns a dict of the text snippets the phone glues together to build a prompt, plus the `stop` words that tell it to stop writing.
    """
    # Some models expect an empty thinking block at the start of an answer; this says whether this one does.
    think = model.get("think") == "empty"
    # These strings must match the PC's own prompt format exactly, or the phone's answers would be worse than the PC's.
    return {"user_open": "<|im_start|>user\n", "turn_end": "<|im_end|>\n",
            "assistant_open": "<|im_start|>assistant\n" + (EMPTY_THINK if think else ""),
            "stop": ["<|im_end|>", "<|im_start|>", "<|endoftext|>"], "notes_intro": "Notes:\n", "question_intro": "\n\nQuestion: "}


def sampling(model):
    """The model's number settings for picking words (temperature, top_k, ...) as a dict of floats; the model's own "fixes" override its defaults."""
    s = dict(model.get("sampling") or {})
    # Later fixes for this model win over the base settings.
    s.update((model.get("fixes") or {}).get("sampling") or {})
    # Only these settings are sent to the phone.
    keep = ("temperature", "top_k", "top_p", "min_p", "repeat_penalty", "presence_penalty")
    # Keep only real numbers (bool is a kind of int in Python, so True/False are excluded on purpose) and send them as floats.
    return {k: float(s[k]) for k in keep if isinstance(s.get(k), (int, float)) and not isinstance(s.get(k), bool)}


def kit(model, size, sha256, hints, memory_facts, memory_on):
    """What GET /api/phone-model sends: the file to fetch and how to answer with it.

    model: the chosen models.json entry. size / sha256: the file's byte size and checksum (sha256 is None while still being worked out).
    hints: extra instruction text for the phone's system prompt. memory_facts / memory_on: the person's saved memory and whether it is switched on.
    Returns a plain dict that becomes the JSON answer.
    """
    return {
        "available": True, "id": model["id"], "name": model.get("name", ""), "version": model.get("version"),
        # `preparing` tells the phone the checksum is not ready yet, so it should wait and ask again.
        "size": size, "sha256": sha256, "preparing": sha256 is None, "file": "/api/phone-model/file?model=" + model["id"],
        "format": chat_format(model), "sampling": sampling(model),
        # The reply limit is the smaller of the model's own limit and the phone's cap.
        "max_reply_tokens": min(PHONE_REPLY, int(model.get("max_reply_tokens") or PHONE_REPLY)), "context": PHONE_CONTEXT,
        "min_ram_gb": model.get("min_ram_gb") or 4,
        "hints": hints,
        # Send at most the newest 60 memory facts (the [-60:] slice keeps the last 60). `personal` is the text pattern (regex) that spots personal statements in a message.
        "memory": {"on": bool(memory_on), "title": user_memory.TITLE, "facts": [f["text"] for f in memory_facts][-60:],
                   "personal": user_memory.PERSONAL.pattern},
    }


# Matches an HTTP Range header like "bytes=100-" or "bytes=100-199": group 1 is the start, group 2 the optional end. \d+ means one or more digits.
RANGE = re.compile(r"bytes=(\d+)-(\d*)$")


def byte_range(header, size):
    """(start, end) to send for a Range header (end included), None for the whole file, or "bad" when it cannot be met (416).

    A Range header lets a download ask for "the file from byte N on", so an interrupted download can carry on instead of starting over.
    """
    # No header, or one we do not understand: send the whole file.
    m = RANGE.match((header or "").strip())
    if not m:
        return None
    start = int(m.group(1))
    # No end given means 'to the end of the file'; an end past the file is cut back to the last byte.
    end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
    # Starting beyond the file, or ending before the start, cannot be served.
    if start >= size or end < start:
        return "bad"
    return start, end


def serve_range(handler, path, range_header, filename=None):
    """Sends the file (200) or the asked-for part of it (206) on a BaseHTTPRequestHandler, in 1 MB pieces. [filename]: saved under that name
    (a download, not shown in the browser)."""
    # File length in bytes.
    size = os.path.getsize(path)
    r = byte_range(range_header, size)
    # 416 = 'Range Not Satisfiable': tell the client how long the file really is and send no body.
    if r == "bad":
        handler.send_response(416)
        handler.send_header("Content-Range", f"bytes */{size}")
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return
    # Whole file when no range was asked.
    start, end = r if r else (0, size - 1)
    # 206 = 'Partial Content' (a piece); 200 = OK (everything).
    handler.send_response(206 if r else 200)
    # Headers: generic binary type; length of what we send; we accept ranges; do not cache; and stop browsers guessing the type (nosniff).
    handler.send_header("Content-Type", "application/octet-stream")
    handler.send_header("Content-Length", str(end - start + 1))
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    if filename:
        # Make the file name safe for a header: replace any character that is not a letter, digit, dot, underscore, space or dash, and cap the length.
        safe = re.sub(r'[^A-Za-z0-9._ -]', "_", filename)[:120] or "download"
        handler.send_header("Content-Disposition", f'attachment; filename="{safe}"')
    if r:
        handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    handler.end_headers()
    # `left` counts how many bytes still need to be sent.
    left = end - start + 1
    with open(path, "rb") as f:
        # Jump to the first byte asked for.
        f.seek(start)
        while left > 0:
            # Send in pieces of at most 1 MB so a huge file never sits whole in memory.
            block = f.read(min(1 << 20, left))
            # The file ended early (it was shortened while sending): stop.
            if not block:
                break
            try:
                handler.wfile.write(block)
            except (BrokenPipeError, ConnectionResetError):
                return                                                   # the phone stopped (no signal): it carries on from here next time
            left -= len(block)


def for_person(state, who, asked=None):
    """GET /api/phone-model for this person: {"available": False, "message"} when this PC has no model for phones, else the kit (of the model
    the phone `asked` for, when it is one of the choices) with the choices.

    state: the running server's shared objects (models, settings, memory, flags). who: the signed-in person's info dict (has "user").
    """
    # model id -> file path, from the model runner; an empty dict when no runner is loaded.
    files = getattr(state.runner, "files", None) or {} if state.runner else {}
    # Try the phone's own choice first; if that is not allowed or missing, fall back to the default pick.
    model = pick(state.manifest, files, asked=asked) if asked else None
    model = model or pick(state.manifest, files)
    if not model:
        return {"available": False, "message": "This PC has no model for phones yet (a small Flare model file is needed)."}
    # Where the chosen model's file lives.
    path = files[model["id"]]
    settings = state.get_settings(who["user"])
    # Imported here, inside the function, not at the top (probably to avoid a circular import: these modules also import this one).
    import app_skills
    import chat_turn
    memory = state.memory_for(who["user"])
    # Extra text for the phone's system prompt: the person's own custom instructions, and how they like replies to sound (only if memory is on).
    hints = [app_skills.custom_hint(settings.get("custom_instructions")), memory.style_hint() if settings["memory"] else ""]
    # Add the house rules only for this kind of model and only when the feature flag is on for this person.
    if model.get("think") == "empty" and state.flags.on("chat_house_rules", who):
        hints.append(chat_turn.HOUSE_HINT)
    # Build the answer; `state.phone_sha.get` returns None while the checksum is still being computed (and starts it). Empty hints are dropped before joining.
    out = kit(model, os.path.getsize(path), state.phone_sha.get(path), "\n\n".join(h for h in hints if h),
              memory.list() if settings["memory"] else [], settings["memory"])
    # Also list every model this phone could switch to.
    out["choices"] = [{"id": m["id"], "name": m.get("name", ""), "version": m.get("version"), "size": os.path.getsize(files[m["id"]]),
                       "min_ram_gb": m.get("min_ram_gb") or 4, "tagline": m.get("tagline", "")} for m in choices(state.manifest, files)]
    return out


# Reply-length cap for the picture helper, and the two files it needs: the model and the 'mmproj' (the part that turns a picture into numbers the model understands).
PHONE_VISION_REPLY = 600
VISION_PARTS = ("model", "mmproj")


def vision_kit(state):
    """GET /api/phone-model/vision (android_phone_vision): the PC's picture helper (vision.py), its model and its picture reader ("mmproj"),
    for the phone to look at pictures itself with the PC off. The same files and instructions the PC uses; never their names."""
    # None means the PC has no complete picture model.
    paths = vision_paths(state)
    if not paths:
        return {"available": False, "message": "This PC has no picture model yet (see docs/VISION.md), so the phone reads only the words in pictures."}
    # For each file: its size, its checksum (None while pending) and the URL to download it from.
    parts = {k: {"size": os.path.getsize(p), "sha256": state.phone_sha.get(p), "file": "/api/phone-model/vision/file?part=" + k} for k, p in paths.items()}
    # Imported here, only when needed.
    import vision
    return {"available": True, "parts": parts, "size": sum(x["size"] for x in parts.values()), "preparing": any(x["sha256"] is None for x in parts.values()),
            "prompt": vision.PROMPT, "max_reply_tokens": PHONE_VISION_REPLY, "min_ram_gb": 6}


def vision_paths(state):
    """{"model": path, "mmproj": path} for the PC's picture helper, or None unless both files exist."""
    v = getattr(state, "vision", None)
    paths = {"model": getattr(v, "model", None), "mmproj": getattr(v, "mmproj", None)}
    # Both files must exist; half a picture model is useless.
    return paths if all(p and os.path.exists(p) for p in paths.values()) else None


def file_for(state, asked=None):
    """The path of the model file to send as a download (the phone's `asked` choice, else the default), or None if there is none."""
    files = getattr(state.runner, "files", None) or {} if state.runner else {}
    # If the phone asked for something not allowed, give nothing (None) rather than a different model; with no request, use the default.
    model = (pick(state.manifest, files, asked=asked) if asked else None) or (None if asked else pick(state.manifest, files))
    return files[model["id"]] if model else None


# Limits on one phone sync: at most this many messages, each cut to this many characters.
MAX_SYNC_MESSAGES = 400
MAX_SYNC_CHARS = 40_000


class Synced:
    """The sync ids already taken in, per person (data_dir/phone_sync.json, the last 500): a sync the phone retries after a lost answer
    is not added twice."""

    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "phone_sync.json") if data_dir else None
        self.lock = threading.Lock()
        # seen: user -> {sync id -> chat id}, so a retried sync is recognised.
        self.seen = {}
        if self.path:
            try:
                with open(self.path, encoding="utf-8") as f:
                    got = json.load(f)
                self.seen = got if isinstance(got, dict) else {}
            except (OSError, ValueError):
                pass

    def get(self, user, sync_id):
        """The chat id this sync id was stored under for this user, or None if it has not been seen."""
        return self.seen.get(user, {}).get(sync_id)

    def put(self, user, sync_id, chat_id):
        """Remember that sync_id ended up in chat_id, keep only the newest 500 per person, and save the file."""
        with self.lock:
            mine = self.seen.setdefault(user, {})
            mine[sync_id] = chat_id
            # Dicts remember insertion order, so the first key is the oldest: drop oldest until 500 remain.
            while len(mine) > 500:
                mine.pop(next(iter(mine)))
            if self.path:
                # Write-then-replace again so the file is never half written.
                with open(self.path + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(self.seen, f)
                os.replace(self.path + ".tmp", self.path)


def sync_chat(store, synced, user, body):
    """POST /api/phone-sync: messages written on the phone while the PC was off, added to an existing chat ("chat": its id) or to a new one.
    {"sync_id", "chat", "title", "model", "messages": [{"role", "content"}]} -> the chat's id. A sync_id seen before changes nothing."""
    # The phone's unique id for this sync (cut to 64 characters).
    sync_id = str(body.get("sync_id") or "")[:64]
    if not sync_id:
        raise ValueError("A sync id is needed.")
    # Already stored? Then return the same chat id and add nothing (the phone is retrying after a lost answer).
    done = synced.get(user, sync_id)
    if done is not None:
        return done
    # Keep only well-formed messages: a dict, role user or assistant, and non-blank text.
    msgs = [m for m in body.get("messages") or [] if isinstance(m, dict) and m.get("role") in ("user", "assistant") and str(m.get("content") or "").strip()]
    if not msgs or len(msgs) > MAX_SYNC_MESSAGES:
        raise ValueError("Nothing to add, or too much at once.")
    # Label for who wrote the replies: "phone:" plus the model name with odd characters removed (regex keeps only letters, digits, underscore, dot, dash).
    model = "phone:" + re.sub(r"[^\w.\-]", "", str(body.get("model") or "phone"))[:40]
    # The chat to add to, if the phone named one.
    cid = body.get("chat")
    # Not a valid existing chat id (bool excluded since True is an int in Python): start a new chat with a tidy one-line title (split/join squeezes extra whitespace).
    if not (isinstance(cid, int) and not isinstance(cid, bool) and cid >= 0 and store.exists(cid)):
        cid = store.new_chat(title=" ".join(str(body.get("title") or "Chat on the phone").split())[:80] or "Chat on the phone")
    # Add each message in order; only assistant messages carry the model label. Long text is cut to the limit.
    for m in msgs:
        store.add(cid, m["role"], str(m["content"])[:MAX_SYNC_CHARS], model_id=model if m["role"] == "assistant" else "")
    synced.put(user, sync_id, cid)
    return cid
