"""
app_runner.py - ModelRunner: starts, watches and stops the llama-server that runs a model, plus finding the llama-server program and .gguf files.

Where it fits: llama-server is a separate program (from the llama.cpp project) that loads a model file (.gguf) and answers over a local web
address. The app server asks ModelRunner.ensure() for that address before each chat message. Vocabulary: a "process" is a running program;
"context" (ctx) is how many tokens (word pieces) of conversation the model can hold at once; a "GGUF" is the model's file format.
"""
# Puts the project folders on Python's import path (the noqa marker is deliberate: this import must come first).
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
# atexit runs a function when Python exits (used to stop llama-server so it is not left running); subprocess starts other programs;
# socket is used to find a free network port; threading gives background threads and locks; urllib.request makes web requests to llama-server.
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
        # Keep the settings: path to the llama-server program, model id -> .gguf file, seconds to wait for a load, extra command-line options, and the address to listen on.
        self.bin, self.files, self.timeout, self.extra, self.host = llama_bin, dict(files), start_timeout, list(extra_args), host
        # State of the running server: the process, which model it holds, its web address, and its context size (how many tokens of conversation it keeps).
        # All None until something is started.
        self.proc = self.model_id = self.url = self.ctx = None
        self.memo = None                                        # a file that remembers the last model, so a restart can load it ahead of the first message
        self.last_used = time.time()                            # the last time a message needed the model (idle unload looks at this)
        self.loaded_at = None
        self.draft_ahead = set()                                # model ids whose built-in "guess ahead" head (Qwen3.5 MTP) is used: models.json "mtp": true
        self.kv8 = set()                                        # model ids whose chat memory is kept in 8 bits (models.json "cache_bits": 8): half the memory, so 256K fits a 12 GB card
        self.no_draft = set()                                   # ...and those it failed for (an older llama-server, or a file without the head): loaded plainly
        # Only one thread may start or stop llama-server at a time; this lock enforces it.
        self.lock = threading.Lock()
        self.manifest = None                                    # set by the app: lets a model downloaded while the app runs be found without a restart
        self.min_ctx = {}                                       # model id -> the window it is always loaded with (its VryxCode window), so moving between chat and VryxCode never reloads it
        self._looked = 0.0
        # Make sure llama-server is stopped when the app quits, so no model stays in memory.
        atexit.register(self.stop)

    def drop_draft(self, model_id):
        """Stop using guess-ahead for this model (it refused a request with it, e.g. one with a picture) and unload it, so the next load is plain.
        True when that changed anything (so trying again is worth it)."""
        # Nothing to do if the model never used guess-ahead, or it was already switched off.
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
        # Look up this model's .gguf file; models with no file have no picture reader.
        path = self.files.get(model_id)
        return projector_for(path) if path else None

    def sees(self, model_id):
        """True if this model can look at pictures (it has a picture-reader file next to it)."""
        return bool(self.projector(model_id))

    def available(self, model_id):
        """True if this model can be started right now: its .gguf file is known and present, and a llama-server program exists."""
        # Not known yet? A model may have been downloaded since the app started, so rescan the disk, but at most once every 10 seconds (so we do not hammer the disk).
        # setdefault only adds ids we do not already have.
        if model_id not in self.files and self.manifest and time.time() - self._looked > 10:     # downloaded since the app started (get_model.py): look again
            self._looked = time.time()
            for mid, path in discover_ggufs(self.manifest).items():
                self.files.setdefault(mid, path)
        # Available means: we know the file, it exists on disk, and we have a llama-server program to run it.
        return model_id in self.files and os.path.exists(self.files[model_id]) and bool(self.bin)

    def ready(self, model_id, ctx):
        """True if this model is already running (so the next message won't wait for it to load)."""
        return bool(self.proc and self.proc.poll() is None and self.model_id == model_id and (self.ctx or 0) >= ctx)

    def _free_port(self):
        """A network port number nobody is using at the moment, for the new llama-server to listen on."""
        # Ask the operating system for any unused network port: binding to port 0 means 'pick one for me'. getsockname()[1] reads which one it chose.
        # The socket is closed on leaving the `with`, freeing the port for llama-server to take (a tiny race is possible but rare).
        with socket.socket() as s:
            s.bind((self.host, 0))
            return s.getsockname()[1]

    def loaded(self):
        """The id of the model that is loaded right now, or None."""
        return self.model_id if (self.proc and self.proc.poll() is None) else None

    def touch(self, now=None):
        """Note that the model was just used, so idle-unload will not free it yet. `now` lets tests give a fake time."""
        # Record 'the model was just used' (now can be passed in by tests). Idle-unload compares against this.
        self.last_used = time.time() if now is None else now

    def unload(self):
        """Free the graphics card and memory: stop llama-server. Not while a model is being loaded (the lock is busy). True if something was stopped."""
        # Try to take the lock without waiting. If it is busy a model is loading right now, so leave it alone.
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
        """Shut down the running llama-server (if any) and forget it. Safe to call when nothing is running."""
        # Forget the running server in our fields first (one tuple assignment), then shut the process down using the saved reference.
        proc, self.proc, self.model_id, self.url, self.loaded_at = self.proc, None, None, None, None
        if proc and proc.poll() is None:
            # Ask the process politely to exit; if it has not within 10 seconds, kill it by force.
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _prime(self, deadline):
        """One tiny request so the model is truly loaded (weights read from disk, graphics card warmed) before anyone waits on it. Best effort."""
        try:
            # Ask llama-server to write one word (n_predict 1) from the prompt 'Hi', temperature 0 = no randomness. The answer is thrown away: this only forces the model to really load.
            req = urllib.request.Request(self.url + "/completion", data=json.dumps({"prompt": "Hi", "n_predict": 1, "temperature": 0}).encode(),
                                         headers={"Content-Type": "application/json"})
            # Wait at most the time left before the deadline, but never less than 5 seconds.
            with urllib.request.urlopen(req, timeout=max(5, deadline - time.monotonic())) as r:
                r.read()
        except (urllib.error.URLError, OSError, ValueError):
            pass

    def remember(self, model_id, ctx):
        """Write the model id and context size to the memo file (if one is set) so warm_last() can reload them after a restart."""
        # Save which model and context size were last used into the memo file (if one is set), so a restart can reload it. Failing to write it is harmless.
        if self.memo:
            try:
                with open(self.memo, "w", encoding="utf-8") as f:
                    json.dump({"model": model_id, "ctx": ctx}, f)
            except OSError:
                pass

    def warm_last(self):
        """Load, in the background, the model that was in use before the last stop, so the first message after a restart is quick."""
        try:
            # Read the memo file written by remember(). Anything missing or damaged just means 'nothing to warm up'.
            with open(self.memo, encoding="utf-8") as f:
                last = json.load(f)
            mid, ctx = str(last["model"]), int(last["ctx"])
        except (OSError, ValueError, KeyError, TypeError):
            return False
        if not self.available(mid):
            return False
        # Load in a background thread so start-up does not wait. daemon=True means the thread will not keep the program alive when it quits.
        threading.Thread(target=lambda: self._quiet_ensure(mid, ctx), daemon=True).start()
        return True

    def _quiet_ensure(self, mid, ctx):
        """ensure() for the background head start: any failure is swallowed, because nobody is waiting for the result."""
        try:
            self.ensure(mid, ctx)
        except Exception:                                        # noqa: BLE001 - a failed head start costs nothing but the head start
            pass

    def ensure(self, model_id, ctx, cancel=None):
        """The URL of a llama-server running this model with at least `ctx` tokens of memory. Starts it if needed.
        `cancel()` is asked while it loads: when it says yes the half-loaded server is stopped and Cancelled is raised."""
        # Never load with less than the model's minimum window, so switching between chat and VryxCode does not force a reload.
        ctx = max(int(ctx), int(self.min_ctx.get(model_id, 0)))
        with self.lock:
            self.last_used = time.time()
            # Already running this model with a big enough window (and the process is still alive): reuse it, no reload.
            if self.proc and self.proc.poll() is None and self.model_id == model_id and (self.ctx or 0) >= ctx:
                return self.url
            # Different model (or a bigger window needed): stop the old server first, so only one model is in memory at a time.
            self.stop()
            # No file for this model (or no llama-server program): fail with a plain message the screen can show.
            if not self.available(model_id):
                raise AppError("This model's file isn't on this computer.",
                               "Put the .gguf next to the others (see docs/V2.md) or start the server with --gguf.")
            # Pick a free port and build the command line: -m model file, --host/--port where to listen, -c context size in tokens.
            port = self._free_port()
            cmd = [self.bin, "-m", self.files[model_id], "--host", self.host, "--port", str(port), "-c", str(ctx)] + self.extra
            # Add optional features: the picture reader, 8-bit chat memory, and guess-ahead decoding (see the notes beside each).
            proj = self.projector(model_id)
            if proj:
                cmd += ["--mmproj", proj]                       # it can look at pictures itself (no separate picture reader)
            if model_id in self.kv8:
                cmd += ["-ctk", "q8_0", "-ctv", "q8_0"]         # the same setting scripts/long_check.py --kv8 passed with
            drafting = model_id in self.draft_ahead and model_id not in self.no_draft
            if drafting:
                cmd += ["--spec-type", "draft-mtp"]             # the model guesses a few words ahead and checks them in one go: same answers, faster
            # On Windows, stop a black console window from popping up (the constant only exists there; elsewhere 0 means no special flags).
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                # Start llama-server as a separate program, throwing away its output. OSError means the program could not be run (wrong path).
                self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            except OSError as e:
                raise AppError("llama-server could not be started.", f"Check the path given with --llama-bin ({e.strerror}).")
            # Record what we started. Then poll (check again and again) until it answers on /health, it dies, we are cancelled, or time runs out.
            self.model_id, self.ctx, self.url = model_id, ctx, f"http://{self.host}:{port}"
            began = time.monotonic()
            deadline = began + self.timeout
            while time.monotonic() < deadline:
                # The caller can ask us to give up (the person pressed Stop).
                if cancel and cancel():
                    self.stop()
                    raise Cancelled()
                # poll() returns None while the process runs; any other value means it already exited, so loading failed.
                if self.proc.poll() is not None:
                    self.stop()
                    if drafting:                                 # the speed-up is optional: load the model plainly instead of failing
                        self.no_draft.add(model_id)
                        print(f"({model_id}: guess-ahead decoding did not start, loading it without)", flush=True)
                        # Retry without guess-ahead. The lock is let go for the recursive call (ensure takes it itself) and taken back afterwards so `with` can release it as usual.
                        self.lock.release()
                        try:
                            return self.ensure(model_id, ctx, cancel)
                        finally:
                            self.lock.acquire()
                    raise AppError("The model stopped while loading.", "Check that the .gguf file is complete and fits in memory.")
                try:
                    # Ask llama-server if it is ready. Its answer is JSON like {"status": "ok"}; an empty body is treated as ok.
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
                # Wait a quarter of a second between checks so we do not spin the processor.
                time.sleep(0.25)
            # The deadline passed without a "ready" answer: clean up the half-started server and give up.
            self.stop()
            raise AppError("The model took too long to load.", "Try a smaller model or check the memory it needs.")


def gpu_note(llama_bin, extra_args):
    """One plain line at start-up saying whether the models will use the graphics card, or None when it looks fine."""
    # Turn the extra options into plain strings. `gpu` is True if any of them asks for graphics-card use (-ngl = number of layers to put on the GPU).
    args = [str(a) for a in (extra_args or [])]
    path = str(llama_bin or "")
    gpu = any(a in ("-ngl", "--n-gpu-layers", "--gpu-layers") or a.startswith(("-ngl=", "--n-gpu-layers=")) for a in args)
    # Lower-case copy of the path for case-insensitive checks.
    low = path.lower()
    # A regular expression (text pattern): the word 'cpu' on its own, with the start of the text or one of \ / _ . - before it and the end or one of those after it,
    # so 'llama-cpu-build' matches but 'cpuinfo' does not.
    if re.search(r"(^|[\\/_.-])cpu([\\/_.-]|$)", low):
        return ("This llama-server looks like a CPU-only build (its path says cpu), so every model runs on the processor and answers can take minutes. "
                "Use the CUDA build instead and add --llama-args \"-ngl 99\".")
    # No GPU option was given.
    if not gpu:
        return ("No graphics-card option was given. Many llama-server builds then use the processor only, which is slow. "
                "Add --llama-args \"-ngl 99\" to use the graphics card (Apogee 2 may need a smaller number such as -ngl 40 if it does not fit).")
    # Looks fine (a GPU option was given and the path does not say cpu): nothing to warn about.
    return None


def find_llama_server():
    """llama-server on the PATH, or None."""
    # shutil.which looks for a program the way the shell does, by searching the folders in PATH.
    return shutil.which("llama-server") or shutil.which("llama-server.exe")


def projector_for(gguf_path):
    """The picture reader that goes with a model file: mmproj.gguf (or one other file with "mmproj" in its name) in the same folder. None when there is none,
    or when the folder holds several (they could belong to different models)."""
    # The model's own folder. The picture reader is expected beside it: first the exact name mmproj.gguf, otherwise a single other file with 'mmproj' in its name.
    folder = os.path.dirname(os.path.abspath(gguf_path))
    exact = os.path.join(folder, "mmproj.gguf")
    if os.path.exists(exact):
        return exact
    try:
        # List the folder; keep names that contain 'mmproj' and end in .gguf (case ignored).
        found = [n for n in os.listdir(folder) if "mmproj" in n.lower() and n.lower().endswith(".gguf")]
    except OSError:
        return None
    # Exactly one candidate: use it. Zero or several: answer None, because with several we cannot tell which belongs to this model.
    return os.path.join(folder, found[0]) if len(found) == 1 else None


def discover_ggufs(manifest, root=HERE):
    """{model id: path} for every model whose .gguf already sits where the export scripts put it (see `local_gguf`)."""
    # Build {model id: file path}. The 'models' list and the optional 'coders' list are both searched; `local_gguf` lists places the file may be (relative to the project folder or absolute).
    found = {}
    for m in list(manifest["models"]) + list(manifest.get("coders", [])):      # the models, and the outside coding models VryxCode can use
        for rel in m.get("local_gguf", []):
            path = rel if os.path.isabs(rel) else os.path.join(root, rel)
            # First path that really exists wins; `break` skips the other candidates for this model.
            if os.path.exists(path):
                found[m["id"]] = path
                break
    return found
