"""
vision.py - Lets the chat look at pictures: a small vision model describes the picture, and the chosen Emvryx model answers from that description.

WHY
    The Emvryx models read text only. A picture goes to a small "vision helper" (a second llama-server run with an --mmproj file, started on the first picture
    and stopped again when it has been idle for a while, so it does not hold graphics memory for nothing). It writes down what the picture shows and every word on it;
    that goes to the model you picked as notes, the same way Wikipedia notes do. Without the helper files the app still reads the words in a picture (documents.py).

FILES (see docs/VISION.md; `python scripts/get_vision_model.py` fetches them)
    export/open/vision/  a vision model .gguf and its matching "mmproj" .gguf (the picture reader that goes with it)
"""
# base64 turns picture bytes into text so they can travel inside JSON; json/urllib talk to the helper over HTTP;
# subprocess starts the helper program; socket finds a free port; threading/time handle the idle timer.
import base64
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request

# Where the helper's model files live, relative to the project root.
VISION_DIR = os.path.join("export", "open", "vision")
# Stop the helper after this many seconds with no pictures (10 minutes), to free graphics memory.
IDLE_SECONDS = 600
# Longest description kept, in characters, so one picture cannot flood the chat's notes.
MAX_DESCRIPTION_CHARS = 6000

# The instruction sent to the vision model with every picture. {question} is filled in later with what the person asked.
# It tells the helper to DESCRIBE the picture (and copy its text), not to answer, because the chosen Emvryx model answers from the description.
PROMPT = ("Look at this picture carefully. First say what it shows. Then copy out all the text you can read, exactly as written, and say who wrote or said it when that is clear "
          "(a chat, a post, a caption, a sign). Be accurate: if something is unclear or cut off, say so, and never invent details. "
          "The person who sent it asks: \"{question}\". Do not answer that yourself; describe what someone would need to know from the picture to answer it.")


def discover(root):
    """(model path, mmproj path) of a vision helper in export/open/vision, or (None, None)."""
    # Folder that should hold the two .gguf files (.gguf = a model file for llama.cpp).
    folder = os.path.join(root, VISION_DIR)
    # If the folder is missing or unreadable there is no helper.
    try:
        names = sorted(n for n in os.listdir(folder) if n.lower().endswith(".gguf"))
    except OSError:
        return None, None
    # The "mmproj" file is the picture reader; the other .gguf is the language part of the vision model.
    proj = [n for n in names if "mmproj" in n.lower()]
    main = [n for n in names if "mmproj" not in n.lower()]
    # Both are needed; with either missing, report none.
    if not proj or not main:
        return None, None
    # Pick the main file: a name containing q4_k_m (a good size/quality compression) gets 0 and sorts first; ties go by name.
    main.sort(key=lambda n: (0 if "q4_k_m" in n.lower() else 1, n))
    return os.path.join(folder, main[0]), os.path.join(folder, proj[0])


def _clean(text):
    """Tidy the helper's answer: remove any <think>...</think> reasoning block (regex; (?is) = ignore case, and . also matches line breaks), trim, and cut to MAX_DESCRIPTION_CHARS."""
    text = re.sub(r"(?is)<think>.*?</think>", "", text or "")
    return text.strip()[:MAX_DESCRIPTION_CHARS]


class VisionHelper:
    """Describes pictures with a llama-server that has a vision model. `url` skips starting one (a server that is already running).

    llama-server is the program that runs the model and answers over HTTP. This class starts it on demand, sends it a picture,
    returns the description, and stops it again when idle. One request at a time (a lock), and recent answers are cached.
    """

    def __init__(self, llama_bin=None, model=None, mmproj=None, extra_args=(), host="127.0.0.1", start_timeout=240, idle_s=IDLE_SECONDS, url=None):
        """`llama_bin`: the llama-server program; `model`/`mmproj`: the two files; `extra_args`: extra command-line options; `host`: the address to bind (this PC only); `start_timeout`: seconds to wait for it to load; `idle_s`: idle seconds before stopping; `url`: use an already-running server instead of starting one."""
        self.bin, self.model, self.mmproj, self.extra, self.host = llama_bin, model, mmproj, list(extra_args), host
        self.timeout, self.idle_s, self.fixed_url = start_timeout, idle_s, url
        self.proc = self.url = None
        self.last_used = 0.0
        self.lock = threading.Lock()
        self.cache = {}                                   # (picture id, question) -> description

    def available(self):
        """True if a picture can be described: either a ready server was given, or the program and both model files exist."""
        if self.fixed_url:
            return True
        return bool(self.bin and self.model and self.mmproj and os.path.exists(self.model) and os.path.exists(self.mmproj))

    # ---- the server
    def _free_port(self):
        # Ask the operating system for a free network port: binding to port 0 makes it pick one, then we read which one it chose.
        with socket.socket() as s:
            s.bind((self.host, 0))
            return s.getsockname()[1]

    def stop(self):
        """Shut the helper down (if running) and forget its address. Safe to call when nothing is running."""
        # Swap the stored values out first, so a second caller does not try to stop the same process; poll() is None while the process is still running.
        proc, self.proc, self.url = self.proc, None, None
        if proc and proc.poll() is None:
            # Ask it to exit politely, wait up to 10 seconds, and kill it if it will not.
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _ensure(self):
        """Make sure a helper is running and answering; return its address. Starts it if needed. Raises RuntimeError if it dies or loads too slowly."""
        # A server we were given needs no starting.
        if self.fixed_url:
            return self.fixed_url
        # Already running and healthy-looking: reuse it.
        if self.proc and self.proc.poll() is None and self.url:
            return self.url
        # Clear any dead leftover, then pick a free port.
        self.stop()
        port = self._free_port()
        # The command line: model file, picture reader, local-only address, port, and a context size of 8192 tokens (how much it can read at once).
        cmd = [self.bin, "-m", self.model, "--mmproj", self.mmproj, "--host", self.host, "--port", str(port), "-c", "8192"] + self.extra
        # On Windows, CREATE_NO_WINDOW stops a black console window popping up; on other systems the attribute does not exist, so 0 (no flag).
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # Start it in the background and throw away its output.
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        self.url = f"http://{self.host}:{port}"
        # monotonic() is a clock that only goes forward, good for timeouts.
        deadline = time.monotonic() + self.timeout
        # Poll until it is ready or the time is up.
        while time.monotonic() < deadline:
            # The process exited already (for example a bad model file).
            if self.proc.poll() is not None:
                self.stop()
                raise RuntimeError("the vision helper stopped while loading")
            # Ask the server's /health page whether it has finished loading; it answers {"status": "ok"} when ready.
            try:
                with urllib.request.urlopen(self.url + "/health", timeout=2) as r:
                    if json.loads(r.read() or b"{}").get("status", "ok") == "ok":
                        return self.url
            # Not up yet (connection refused, bad reply): wait and try again.
            except (urllib.error.URLError, OSError, ValueError):
                pass
            time.sleep(0.3)
        # Timed out: clean up so no half-started process is left.
        self.stop()
        raise RuntimeError("the vision helper took too long to load")

    def _post(self, url, body):
        """Send a chat request (JSON) to the helper at `url` and return its JSON answer. Waits up to 5 minutes, since pictures can be slow."""
        req = urllib.request.Request(url + "/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())

    def _idle_check(self):
        """Called by a timer: stop the helper if it has really been idle for the whole idle period."""
        with self.lock:
            # The -1 gives a little slack so a timer firing just before the limit still counts.
            if self.proc and time.monotonic() - self.last_used >= self.idle_s - 1:
                self.stop()

    # ---- the one thing it does
    def describe(self, picture_id, data, mime, question=""):
        """Words for one picture (what it shows and the text on it). Raises RuntimeError when the helper can't be used."""
        # One-line question, at most 300 characters; a default question if empty.
        question = " ".join(str(question or "").split())[:300] or "What is in this picture?"
        # The cache key is the picture plus the question, because the description depends on both.
        key = (picture_id, question)
        if key in self.cache:
            return self.cache[key]
        # One picture at a time: the lock stops two requests starting two helpers.
        with self.lock:
            url = self._ensure()
            # temperature 0.2 = steady, not creative answers; max_tokens 900 = longest reply.
            body = {"model": "local", "temperature": 0.2, "max_tokens": 900,
                    # The message holds the picture (as a data: web address with the bytes in base64) and the instruction text.
                    "messages": [{"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}},
                        {"type": "text", "text": PROMPT.format(question=question)}]}]}
            # Any network trouble or odd reply shape: stop the helper (it may be stuck) and report a clear error.
            try:
                out = self._post(url, body)
                text = _clean(out["choices"][0]["message"]["content"])
            except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError) as e:
                self.stop()
                raise RuntimeError("the vision helper could not read the picture") from e
            # Remember when it was last used, for the idle timer.
            self.last_used = time.monotonic()
        # An empty description is as good as a failure.
        if not text:
            raise RuntimeError("the vision helper gave no description")
        # Keep the cache small: drop the oldest entry (dicts remember insertion order) once there are over 50.
        if len(self.cache) > 50:
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = text
        # Schedule an idle check (a background timer; daemon=True so it never blocks the program from exiting).
        if not self.fixed_url and self.idle_s:
            t = threading.Timer(self.idle_s, self._idle_check)
            t.daemon = True
            t.start()
        return text
