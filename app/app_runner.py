"""
app_runner.py - ModelRunner: starts, watches and stops the llama-server that runs a model, plus finding the llama-server program and .gguf files.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import atexit
import json
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from app_errors import AppError
from app_shared import Cancelled, HERE


class ModelRunner:
    """Starts llama-server for the model the person picked and stops it when another one is picked (one at a time, so
    a small PC is not asked to hold two models). `files` is {model id: path to a .gguf}."""

    def __init__(self, llama_bin, files, start_timeout=180, extra_args=(), host="127.0.0.1"):
        self.bin, self.files, self.timeout, self.extra, self.host = llama_bin, dict(files), start_timeout, list(extra_args), host
        self.proc = self.model_id = self.url = self.ctx = None
        self.memo = None                                        # a file that remembers the last model, so a restart can load it ahead of the first message
        self.last_used = time.time()                            # the last time a message needed the model (idle unload looks at this)
        self.loaded_at = None
        self.draft_ahead = set()                                # model ids whose built-in "guess ahead" head (Qwen3.5 MTP) is used: models.json "mtp": true
        self.kv8 = set()                                        # model ids whose chat memory is kept in 8 bits (models.json "cache_bits": 8): half the memory, so 256K fits a 12 GB card
        self.no_draft = set()                                   # ...and those it failed for (an older llama-server, or a file without the head): loaded plainly
        self.lock = threading.Lock()
        self.manifest = None                                    # set by the app: lets a model downloaded while the app runs be found without a restart
        self._looked = 0.0
        atexit.register(self.stop)

    def drop_draft(self, model_id):
        """Stop using guess-ahead for this model (it refused a request with it, e.g. one with a picture) and unload it, so the next load is plain.
        True when that changed anything (so trying again is worth it)."""
        if model_id not in self.draft_ahead or model_id in self.no_draft:
            return False
        self.no_draft.add(model_id)
        print(f"({model_id}: a request was refused with guess-ahead on; loading it without)", flush=True)
        with self.lock:
            if self.model_id == model_id:
                self.stop()
        return True

    def projector(self, model_id):
        """The model's own picture reader (an "mmproj" .gguf) when one sits in the same folder as its .gguf, else None. Emvryx 3 (Qwen3.5) models can look
        at pictures themselves with it; the export step (scripts/export_projector.py) puts it there."""
        path = self.files.get(model_id)
        return projector_for(path) if path else None

    def sees(self, model_id):
        return bool(self.projector(model_id))

    def available(self, model_id):
        if model_id not in self.files and self.manifest and time.time() - self._looked > 10:     # downloaded since the app started (get_model.py): look again
            self._looked = time.time()
            for mid, path in discover_ggufs(self.manifest).items():
                self.files.setdefault(mid, path)
        return model_id in self.files and os.path.exists(self.files[model_id]) and bool(self.bin)

    def ready(self, model_id, ctx):
        """True if this model is already running (so the next message won't wait for it to load)."""
        return bool(self.proc and self.proc.poll() is None and self.model_id == model_id and (self.ctx or 0) >= ctx)

    def _free_port(self):
        with socket.socket() as s:
            s.bind((self.host, 0))
            return s.getsockname()[1]

    def loaded(self):
        """The id of the model that is loaded right now, or None."""
        return self.model_id if (self.proc and self.proc.poll() is None) else None

    def touch(self):
        self.last_used = time.time()

    def unload(self):
        """Free the graphics card and memory: stop llama-server. Not while a model is being loaded (the lock is busy). True if something was stopped."""
        if not self.lock.acquire(blocking=False):
            return False
        try:
            if not self.loaded():
                return False
            self.stop()
            return True
        finally:
            self.lock.release()

    def stop(self):
        proc, self.proc, self.model_id, self.url, self.loaded_at = self.proc, None, None, None, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _prime(self, deadline):
        """One tiny request so the model is truly loaded (weights read from disk, graphics card warmed) before anyone waits on it. Best effort."""
        try:
            req = urllib.request.Request(self.url + "/completion", data=json.dumps({"prompt": "Hi", "n_predict": 1, "temperature": 0}).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=max(5, deadline - time.monotonic())) as r:
                r.read()
        except (urllib.error.URLError, OSError, ValueError):
            pass

    def remember(self, model_id, ctx):
        if self.memo:
            try:
                with open(self.memo, "w", encoding="utf-8") as f:
                    json.dump({"model": model_id, "ctx": ctx}, f)
            except OSError:
                pass

    def warm_last(self):
        """Load, in the background, the model that was in use before the last stop, so the first message after a restart is quick."""
        try:
            with open(self.memo, encoding="utf-8") as f:
                last = json.load(f)
            mid, ctx = str(last["model"]), int(last["ctx"])
        except (OSError, ValueError, KeyError, TypeError):
            return False
        if not self.available(mid):
            return False
        threading.Thread(target=lambda: self._quiet_ensure(mid, ctx), daemon=True).start()
        return True

    def _quiet_ensure(self, mid, ctx):
        try:
            self.ensure(mid, ctx)
        except Exception:                                        # noqa: BLE001 - a failed head start costs nothing but the head start
            pass

    def ensure(self, model_id, ctx, cancel=None):
        """The URL of a llama-server running this model with at least `ctx` tokens of memory. Starts it if needed.
        `cancel()` is asked while it loads: when it says yes the half-loaded server is stopped and Cancelled is raised."""
        with self.lock:
            self.last_used = time.time()
            if self.proc and self.proc.poll() is None and self.model_id == model_id and (self.ctx or 0) >= ctx:
                return self.url
            self.stop()
            if not self.available(model_id):
                raise AppError("This model's file isn't on this computer.",
                               "Put the .gguf next to the others (see docs/V2.md) or start the server with --gguf.")
            port = self._free_port()
            cmd = [self.bin, "-m", self.files[model_id], "--host", self.host, "--port", str(port), "-c", str(ctx)] + self.extra
            proj = self.projector(model_id)
            if proj:
                cmd += ["--mmproj", proj]                       # it can look at pictures itself (no separate picture reader)
            if model_id in self.kv8:
                cmd += ["-ctk", "q8_0", "-ctv", "q8_0"]         # the same setting scripts/long_check.py --kv8 passed with
            drafting = model_id in self.draft_ahead and model_id not in self.no_draft
            if drafting:
                cmd += ["--spec-type", "draft-mtp"]             # the model guesses a few words ahead and checks them in one go: same answers, faster
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            except OSError as e:
                raise AppError("llama-server could not be started.", f"Check the path given with --llama-bin ({e.strerror}).")
            self.model_id, self.ctx, self.url = model_id, ctx, f"http://{self.host}:{port}"
            began = time.monotonic()
            deadline = began + self.timeout
            while time.monotonic() < deadline:
                if cancel and cancel():
                    self.stop()
                    raise Cancelled()
                if self.proc.poll() is not None:
                    self.stop()
                    if drafting:                                 # the speed-up is optional: load the model plainly instead of failing
                        self.no_draft.add(model_id)
                        print(f"({model_id}: guess-ahead decoding did not start, loading it without)", flush=True)
                        self.lock.release()
                        try:
                            return self.ensure(model_id, ctx, cancel)
                        finally:
                            self.lock.acquire()
                    raise AppError("The model stopped while loading.", "Check that the .gguf file is complete and fits in memory.")
                try:
                    with urllib.request.urlopen(self.url + "/health", timeout=2) as r:
                        if json.loads(r.read() or b"{}").get("status", "ok") == "ok":
                            self._prime(deadline)                 # health says "ready" before the weights are really in memory: the first word would then wait for them
                            took = time.monotonic() - began
                            if took > 15:                      # a slow load is worth a line in the log: it is what makes the first answer late
                                print(f"(loading {model_id} took {took:.0f} s; switching models reloads it each time)", flush=True)
                            self.remember(model_id, ctx)
                            self.loaded_at = self.last_used = time.time()
                            return self.url
                except (urllib.error.URLError, OSError, ValueError):
                    pass                                         # still loading (llama-server answers 503 until ready)
                time.sleep(0.25)
            self.stop()
            raise AppError("The model took too long to load.", "Try a smaller model or check the memory it needs.")


def gpu_note(llama_bin, extra_args):
    """One plain line at start-up saying whether the models will use the graphics card, or None when it looks fine."""
    args = [str(a) for a in (extra_args or [])]
    path = str(llama_bin or "")
    gpu = any(a in ("-ngl", "--n-gpu-layers", "--gpu-layers") or a.startswith(("-ngl=", "--n-gpu-layers=")) for a in args)
    low = path.lower()
    if re.search(r"(^|[\\/_.-])cpu([\\/_.-]|$)", low):
        return ("This llama-server looks like a CPU-only build (its path says cpu), so every model runs on the processor and answers can take minutes. "
                "Use the CUDA build instead and add --llama-args \"-ngl 99\".")
    if not gpu:
        return ("No graphics-card option was given. Many llama-server builds then use the processor only, which is slow. "
                "Add --llama-args \"-ngl 99\" to use the graphics card (Apogee 2 may need a smaller number such as -ngl 40 if it does not fit).")
    return None


def find_llama_server():
    """llama-server on the PATH, or None."""
    return shutil.which("llama-server") or shutil.which("llama-server.exe")


def projector_for(gguf_path):
    """The picture reader that goes with a model file: mmproj.gguf (or one other file with "mmproj" in its name) in the same folder. None when there is none,
    or when the folder holds several (they could belong to different models)."""
    folder = os.path.dirname(os.path.abspath(gguf_path))
    exact = os.path.join(folder, "mmproj.gguf")
    if os.path.exists(exact):
        return exact
    try:
        found = [n for n in os.listdir(folder) if "mmproj" in n.lower() and n.lower().endswith(".gguf")]
    except OSError:
        return None
    return os.path.join(folder, found[0]) if len(found) == 1 else None


def discover_ggufs(manifest, root=HERE):
    """{model id: path} for every model whose .gguf already sits where the export scripts put it (see `local_gguf`)."""
    found = {}
    for m in list(manifest["models"]) + list(manifest.get("coders", [])):      # the models, and the outside coding models VryxCode can use
        for rel in m.get("local_gguf", []):
            path = rel if os.path.isabs(rel) else os.path.join(root, rel)
            if os.path.exists(path):
                found[m["id"]] = path
                break
    return found
