"""
vision.py - Lets the chat look at pictures: a small vision model describes the picture, and the chosen Emvryx model answers from that description.

WHY
    The Emvryx models read text only. A picture goes to a small "vision helper" (a second llama-server run with an --mmproj file, started on the first picture
    and stopped again when it has been idle for a while, so it does not hold graphics memory for nothing). It writes down what the picture shows and every word on it;
    that goes to the model you picked as notes, the same way Wikipedia notes do. Without the helper files the app still reads the words in a picture (documents.py).

FILES (see docs/VISION.md; `python scripts/get_vision_model.py` fetches them)
    export/open/vision/  a vision model .gguf and its matching "mmproj" .gguf (the picture reader that goes with it)
"""
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

VISION_DIR = os.path.join("export", "open", "vision")
IDLE_SECONDS = 600
MAX_DESCRIPTION_CHARS = 6000

PROMPT = ("Look at this picture carefully. First say what it shows. Then copy out all the text you can read, exactly as written, and say who wrote or said it when that is clear "
          "(a chat, a post, a caption, a sign). Be accurate: if something is unclear or cut off, say so, and never invent details. "
          "The person who sent it asks: \"{question}\". Do not answer that yourself; describe what someone would need to know from the picture to answer it.")


def discover(root):
    """(model path, mmproj path) of a vision helper in export/open/vision, or (None, None)."""
    folder = os.path.join(root, VISION_DIR)
    try:
        names = sorted(n for n in os.listdir(folder) if n.lower().endswith(".gguf"))
    except OSError:
        return None, None
    proj = [n for n in names if "mmproj" in n.lower()]
    main = [n for n in names if "mmproj" not in n.lower()]
    if not proj or not main:
        return None, None
    main.sort(key=lambda n: (0 if "q4_k_m" in n.lower() else 1, n))
    return os.path.join(folder, main[0]), os.path.join(folder, proj[0])


def _clean(text):
    text = re.sub(r"(?is)<think>.*?</think>", "", text or "")
    return text.strip()[:MAX_DESCRIPTION_CHARS]


class VisionHelper:
    """Describes pictures with a llama-server that has a vision model. `url` skips starting one (a server that is already running)."""

    def __init__(self, llama_bin=None, model=None, mmproj=None, extra_args=(), host="127.0.0.1", start_timeout=240, idle_s=IDLE_SECONDS, url=None):
        self.bin, self.model, self.mmproj, self.extra, self.host = llama_bin, model, mmproj, list(extra_args), host
        self.timeout, self.idle_s, self.fixed_url = start_timeout, idle_s, url
        self.proc = self.url = None
        self.last_used = 0.0
        self.lock = threading.Lock()
        self.cache = {}                                   # (picture id, question) -> description

    def available(self):
        if self.fixed_url:
            return True
        return bool(self.bin and self.model and self.mmproj and os.path.exists(self.model) and os.path.exists(self.mmproj))

    # ---- the server
    def _free_port(self):
        with socket.socket() as s:
            s.bind((self.host, 0))
            return s.getsockname()[1]

    def stop(self):
        proc, self.proc, self.url = self.proc, None, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _ensure(self):
        if self.fixed_url:
            return self.fixed_url
        if self.proc and self.proc.poll() is None and self.url:
            return self.url
        self.stop()
        port = self._free_port()
        cmd = [self.bin, "-m", self.model, "--mmproj", self.mmproj, "--host", self.host, "--port", str(port), "-c", "8192"] + self.extra
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        self.url = f"http://{self.host}:{port}"
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                self.stop()
                raise RuntimeError("the vision helper stopped while loading")
            try:
                with urllib.request.urlopen(self.url + "/health", timeout=2) as r:
                    if json.loads(r.read() or b"{}").get("status", "ok") == "ok":
                        return self.url
            except (urllib.error.URLError, OSError, ValueError):
                pass
            time.sleep(0.3)
        self.stop()
        raise RuntimeError("the vision helper took too long to load")

    def _post(self, url, body):
        req = urllib.request.Request(url + "/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())

    def _idle_check(self):
        with self.lock:
            if self.proc and time.monotonic() - self.last_used >= self.idle_s - 1:
                self.stop()

    # ---- the one thing it does
    def describe(self, picture_id, data, mime, question=""):
        """Words for one picture (what it shows and the text on it). Raises RuntimeError when the helper can't be used."""
        question = " ".join(str(question or "").split())[:300] or "What is in this picture?"
        key = (picture_id, question)
        if key in self.cache:
            return self.cache[key]
        with self.lock:
            url = self._ensure()
            body = {"model": "local", "temperature": 0.2, "max_tokens": 900,
                    "messages": [{"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}},
                        {"type": "text", "text": PROMPT.format(question=question)}]}]}
            try:
                out = self._post(url, body)
                text = _clean(out["choices"][0]["message"]["content"])
            except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError) as e:
                self.stop()
                raise RuntimeError("the vision helper could not read the picture") from e
            self.last_used = time.monotonic()
        if not text:
            raise RuntimeError("the vision helper gave no description")
        if len(self.cache) > 50:
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = text
        if not self.fixed_url and self.idle_s:
            t = threading.Timer(self.idle_s, self._idle_check)
            t.daemon = True
            t.start()
        return text
