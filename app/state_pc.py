"""
state_pc.py - AppState's model-running part: gaming mode, idle unload, safety checks before publishing, and choosing, warming and talking to a model.

WHERE IT FITS
    AppState (the server's big shared object) is built from mixin classes, one per state_*.py file. A mixin's methods are mixed into AppState,
    so `self` here is the whole AppState (self.runner, self.cfg, self.manifest, self.security, self.auth ... come from other parts).
    "The runner" starts and stops llama-server, the separate program that actually loads a model file and answers questions. Loading a model
    takes graphics-card memory, so this file also lets the owner free it for gaming and unloads a model nobody has used for a while.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import json
import queue
import threading
import time
import app_engine as E
import model_guard
import context_window as CW
import models as M
from app_errors import AppError
from tokenizer import BPETokenizer
from open_tokenizer import OpenTokenizer
from app_shared import API_KEY_PREFIX, DemoBackend, TEMPERATURE, demo_tokenizer, error_payload, free_memory_gb
from chat_turn import model_guard_tests, start_turn


class StatePC:
    """The computer and the models on it."""

    # ---- the graphics card: idle unload and Gaming mode
    def gaming_file(self):
        """Path of the flag file gaming.flag in the data folder (or None with no data folder). Its existence means Gaming mode is on."""
        return os.path.join(self.data_dir, "gaming.flag") if self.data_dir else None

    def sync_gaming(self):
        """Gaming mode is on when the switch says so OR the file gaming.flag exists in the data folder (so a shortcut on the desktop can switch it with no key)."""
        # Re-read the file each time, so changes made by a desktop shortcut are noticed. "gaming_mem" is the in-memory switch.
        f = self.gaming_file()
        if f:
            self.cfg["gaming"] = os.path.exists(f) or bool(self.cfg.get("gaming_mem"))
        return bool(self.cfg.get("gaming"))

    def set_gaming(self, on, by=""):
        """Switch Gaming mode. On: nobody can start a reply, and the model is unloaded now (or as soon as the replies running finish)."""
        on = bool(on)
        f = self.gaming_file()
        self.cfg["gaming_mem"] = on
        # Mirror the switch in the flag file: create it when on, delete it when off. A file problem is ignored (the in-memory switch still works).
        if f:
            try:
                if on:
                    with open(f, "w", encoding="utf-8") as h:
                        h.write("Emvryx is paused for gaming. Delete this file (or use Admin > PC) to turn it off.\n")
                elif os.path.exists(f):
                    os.remove(f)
            except OSError:
                pass
        self.cfg["gaming"] = on
        # Turning it on frees the graphics card now; unload_model refuses (False) if a reply is being written right now.
        unloaded = self.unload_model("gaming mode") if on else False
        self.auth.event("gaming_mode", by or "owner", "", "on" if on else "off")
        return {"gaming": on, "unloaded": unloaded, "loaded": self.runner.loaded() if self.runner else None}

    def busy(self):
        """True while a reply or a coding session is using the model."""
        return bool(self.stops or self.code.any_running())

    def unload_model(self, why=""):
        """Stop the loaded model if nothing is using it. True if it was stopped."""
        # Never pull the model out from under a running reply or coding session.
        if not self.runner or self.busy():
            return False
        stopped = self.runner.unload()
        if stopped:
            self.auth.event("model_unloaded", "system", "", why)
            print(f"(model unloaded: {why})", flush=True)
        return stopped

    def idle_tick(self, now=None):
        """Called every few seconds by a background thread: honour Gaming mode, and unload a model nobody has used for `idle_unload_minutes`."""
        if not self.runner:
            return None
        # `now` can be passed in by tests. Returns "gaming" or "idle" when it unloaded the model for that reason, else None.
        now = time.time() if now is None else now
        if self.busy():
            self.runner.touch(now)                                    # used as of this check (not "now" read again: Windows' clock moves in steps)
            return None
        # Gaming mode wins: free the card at once.
        if self.sync_gaming():
            return "gaming" if self.unload_model("gaming mode") else None
        # Idle unload (0 minutes = never): unload when the model is loaded and the time since it was last used is at least that many minutes.
        minutes = int(self.security.get("idle_unload_minutes") or 0)
        if minutes > 0 and self.runner.loaded() and now - self.runner.last_used >= minutes * 60:
            return "idle" if self.unload_model(f"idle for {minutes} minutes") else None
        return None

    def pc_status(self):
        """What the Admin > PC screen shows: gaming on/off, which model is loaded, seconds idle, the idle-unload setting and whether it is busy."""
        r = self.runner
        loaded = r.loaded() if r else None
        model = next((m for m in self.manifest["models"] if m["id"] == loaded), None) if loaded else None
        return {"gaming": bool(self.cfg.get("gaming")), "has_runner": bool(r), "loaded": loaded, "loaded_label": (f"{model['name']} {model['version']:g}" if model else None),
                "idle_seconds": int(time.time() - r.last_used) if (r and loaded) else None, "idle_unload_minutes": int(self.security.get("idle_unload_minutes") or 0),
                "busy": self.busy()}

    def _model_fingerprint(self, model_id):
        """A short text built from the model file's size and last-changed time ("" if there is no file). It changes if the file is replaced."""
        path = (self.runner.files.get(model_id) if self.runner else None) or ""
        try:
            st = os.stat(path)
            return f"{st.st_size}-{int(st.st_mtime)}"
        except OSError:
            return ""

    def model_file_sig(self, model_id):
        """A short id of the model's file on this computer (size and time), so "Record an update" notices a new one. None when there is none."""
        path = (getattr(self.runner, "files", None) or {}).get(model_id) if self.runner else None
        try:
            st = os.stat(path) if path else None
        except OSError:
            return None
        return f"{st.st_size}:{int(st.st_mtime)}" if st else None

    def guard_ok(self, model_id):
        """(True, "") when this model's latest safety checks passed (and the model file has not changed since); otherwise (False, why)."""
        # rec = the saved result of the last safety-check run for this model (None if it was never run).
        rec = self.guards.load(model_id)
        if not rec:
            return False, "Run the safety checks first (Admin > Models > Run safety checks): a new model must pass them before it is published."
        # The results are only trusted for the exact file that was tested: a changed file needs new checks.
        if rec.get("fingerprint") and rec["fingerprint"] != self._model_fingerprint(model_id):
            return False, "The model file changed after the safety checks: run them again."
        if not rec["passed"]:
            return False, "The safety checks did not pass: " + "; ".join(rec["reasons"]) + "."
        return True, ""

    def _guard_who(self):
        """An internal account with no limits that asks the check questions (it sees models in preview, keeps no memory and never searches the web)."""
        # Create the helper account the first time: a hidden "app" user on the top plan, with no limits and every personal feature off,
        # so the check answers are not affected by memory or web search.
        if not self.user_record(self.GUARD_USER):
            self.add_user(self.GUARD_USER, "mega", key_prefix=API_KEY_PREFIX)
            self._set_fields(self.GUARD_USER, app=True, internal=True, app_enabled=True)
            self.set_access(self.GUARD_USER, unlimited=True)
            self.put_settings(self.GUARD_USER, {"memory": False, "live_data": False, "connected_apps": False, "web_search": "none", "custom_instructions": ""})
        return self.who_name(self.GUARD_USER)

    def ask_quietly(self, who, model_id, prompt, effort="balanced", timeout=420):
        """(reply, error) for one question through the whole app, in a private chat that is thrown away."""
        # Use a private chat (it is deleted at the end, in the `finally` below, so nothing is left behind).
        store = self.store(who["user"])
        cid = store.new_chat(private=True)
        # Start the turn like a real chat message. q is a queue of events from the answer as it streams; stop is a flag to cancel it.
        try:
            q, stop, model, win, decision = start_turn(self, who, cid, prompt, model_id, effort, pace=False)
        except Exception as e:                                 # noqa: BLE001
            store.delete_chat(cid)
            return "", str(error_payload(e)[2].get("message", "error"))
        try:
            # monotonic() is a clock that only goes forward (safe for timing, unlike the wall clock). Poll the queue once a second until the
            # deadline; queue.Empty just means "nothing yet".
            deadline = time.monotonic() + timeout
            while True:
                try:
                    kind, val = q.get(timeout=1)
                except queue.Empty:
                    # Too slow: tell the generation to stop, and report it.
                    if time.monotonic() > deadline:
                        stop.set()
                        return "", "took too long"
                    continue
                # "done" carries the finished reply; "error" carries what went wrong. Other event kinds (streamed pieces) are ignored.
                if kind == "done":
                    return (val.get("text") or "").strip(), None
                if kind == "error":
                    return "", str(error_payload(val)[2].get("message", "error"))
        finally:
            store.delete_chat(cid)

    def start_guard(self, model_id, by=""):
        """Run the safety checks on a model in the background (one at a time). Raises ValueError when they cannot start."""
        # Refuse to start unless: the model exists and is real, Gaming mode is off, and its file is on this computer.
        model = next((m for m in self.manifest["models"] if m["id"] == model_id), None)
        if not model or model["status"] in ("off", "planned"):
            raise ValueError("no such model")
        if self.cfg.get("gaming"):
            raise ValueError("Gaming mode is on: turn it off first, the checks need the model loaded")
        if self.runner and not self.runner.available(model_id):
            raise ValueError("That model's file is not on this computer yet.")
        # Under a lock (so two clicks cannot both start a run): only one run at a time; record it in self.guard_run so the screen can show progress.
        with self._guard_lock:
            if self.guard_run and self.guard_run["state"] == "running":
                raise ValueError("The checks are already running for " + self.guard_run["model_id"])
            # The list of check questions; i counts how many are done and n is the total.
            tests = model_guard_tests(self.guard_sheet)
            run = {"model_id": model_id, "state": "running", "i": 0, "n": len(tests), "started": time.time()}
            self.guard_run = run
        who = self._guard_who()
        # Also find the previous version of this model (if any), so the new one's score can be compared with it.
        older_id = None
        olds = self.models_pub._older(self.manifest, model)
        if olds:
            older_id = olds[0]["id"]

        # The job itself, run in a background thread so the request returns at once.
        def work():
            import quality_check
            results = []
            try:
                # Ask each question; quality_check.check decides whether the reply is acceptable. Replies are cut to 600 characters for storage.
                for i, t in enumerate(tests):
                    reply, error = self.ask_quietly(who, model_id, t["prompt"])
                    results.append({"prompt": t["prompt"], "category": t["category"], "ok": bool(not error and quality_check.check(t, reply)), "reply": reply[:600], "error": error})
                    run["i"] = i + 1
                    if i == 2 and all(r["error"] for r in results):          # the first three could not even be asked: do not keep going
                        break
                # Judge the whole set (compared with the older version's saved summary), save the verdict with the file fingerprint, and log it.
                older = self.guards.load(older_id) if older_id else None
                older_label = next((f"{m['name']} {m['version']:g}" for m in self.manifest["models"] if m["id"] == older_id), "")
                passed, reasons, summary = model_guard.judge(results, older["summary"] if older else None, older_label)
                self.guards.save(model_id, {"model_id": model_id, "when": time.time(), "by": by, "passed": passed, "reasons": reasons, "summary": summary, "results": results,
                                           "fingerprint": self._model_fingerprint(model_id)})
                self.auth.event("model_checks", by or "owner", "", f"{model_id}: {'passed' if passed else 'failed'} {summary['percent']:g}%")
                self.record_accuracy(model_id, summary)                       # accuracy_score: every run kept, to see the score over time
            except Exception as e:                                           # noqa: BLE001
                print(f"(safety checks for {model_id} stopped: {e})", flush=True)
            # Whatever happened, mark the run finished so the screen stops showing "running" and a new run can start.
            finally:
                run["state"] = "done"
        threading.Thread(target=work, daemon=True).start()
        return {"started": True, "n": len(tests)}

    def _accuracy_path(self):
        """Where the score history file lives, or None with no data folder."""
        return os.path.join(self.data_dir, "accuracy_history.json") if self.data_dir else None

    def accuracy_history(self):
        """{model id: [{"when", "percent", "passed", "total", "by_category"}, ...]} oldest first, the last 30 runs of each."""
        # Loaded from disk the first time it is needed, then kept in memory (getattr with a default avoids an error before it exists).
        if getattr(self, "_accuracy", None) is None:
            self._accuracy = {}
            path = self._accuracy_path()
            if path and os.path.exists(path):
                try:
                    with open(path, encoding="utf-8") as f:
                        got = json.load(f)
                    self._accuracy = got if isinstance(got, dict) else {}
                except (OSError, ValueError):
                    pass
        return self._accuracy

    def record_accuracy(self, model_id, summary):
        """Add one safety-check score for a model to the history and save it. Only the 30 newest runs per model are kept."""
        hist = self.accuracy_history()
        runs = hist.setdefault(model_id, [])
        runs.append({"when": time.time(), "percent": summary.get("percent"), "passed": summary.get("passed"), "total": summary.get("total"),
                     "by_category": summary.get("by_category", {})})
        # Delete everything except the last 30 entries, then write the file via a temp file and os.replace (so it is never half-written).
        del runs[:-30]
        path = self._accuracy_path()
        if path:
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(hist, f)
            os.replace(path + ".tmp", path)

    def models_admin(self):
        """The Models tab: every model in the family, whether it is in preview or live, what a publish would replace, and the model releases so far."""
        mp, out = self.models_pub, []
        # A scheduled publish that is due goes live first, so the screen shows the current truth.
        mp.run_due(self.manifest)
        # One row per usable model, grouped by name, newest version first. A "preview" is a model not yet published to everyone.
        for name in M.NAMES:
            for m in sorted((x for x in self.manifest["models"] if x["name"] == name and x["status"] not in ("off", "planned")), key=lambda x: -x["version"]):
                preview = m["status"] == "preview" and not mp.live(m["id"])
                olds = mp._older(self.manifest, m)
                out.append({"id": m["id"], "name": m["name"], "version": m["version"], "label": f"{m['name']} {m['version']:g}", "tagline": m.get("tagline", ""), "preview": preview,
                            "scheduled": mp.scheduled(m["id"]), "live": mp.data["live"].get(m["id"]), "replaces": f"{olds[0]['name']} {olds[0]['version']:g}" if (preview and olds) else None,
                            "available": bool(self.runner.available(m["id"])) if self.runner else True,
                            "guard": model_guard.public(self.guards.load(m["id"]), self.guard_run if (self.guard_run and self.guard_run["state"] == "running" and self.guard_run["model_id"] == m["id"]) else None),
                            "schedule_failed": mp.data["failed"].get(m["id"]), "changes": "" if preview else mp.changes(m)})
        return {"models": out, "keep_older": int(self.manifest.get("keep_older_versions", 6)), "checks_running": bool(self.guard_run and self.guard_run["state"] == "running"), "products": self.flags.products(),
                "releases": [r for r in self.flags.releases() if str(r.get("kind", "")).startswith("model")], "accuracy": self.accuracy_history()}

    def preload(self, model_id):
        """Start the model's llama-server now (with the window the owner's chats would ask for), so the first message is not slow.
        Returns a short message for the log. Never raises: a model that cannot load only costs the head start."""
        # Each early return gives a short message for the log explaining why nothing was loaded.
        if not self.runner:
            return "nothing to preload (no local models)"
        if self.sync_gaming():
            return "Gaming mode is on: not loading any model"
        model = next((m for m in list(self.manifest["models"]) + list(self.manifest.get("coders", [])) if m["id"] == model_id), None)
        if not model:
            return f"unknown model {model_id!r}"
        if not self.runner.available(model_id):
            return f"{model_id}: its .gguf file is not on this computer"
        # window = how many tokens of conversation the model can hold; the owner's size is used. ensure() starts llama-server with that size.
        try:
            window = self.window_for({"user": "owner", "tier": "mega", "owner": True}, model)["window"]
            self.runner.ensure(model_id, window)
            return f"{model_id} is loaded and ready"
        except Exception as e:                                   # noqa: BLE001 - a failed head start must not stop the app
            return f"{model_id} could not be preloaded: {getattr(e, 'message', e)}"

    def warm(self, who, model_id):
        """Load this model in the background (the person just picked it or opened a chat), so their next message does not wait for it. Skipped while a reply
        or a coding session is running (it would take that model away). Several quick picks only load the last one. True if a load was started or is under way."""
        if not self.runner:
            return False
        # The model must exist for this person, be ready, and have its file here.
        try:
            model = self.pick_model(who, model_id)
        except KeyError:
            return False
        if model["state"] != "ready" or not self.runner.available(model_id):
            return False
        if self.stops or self.code.any_running() or self.cfg.get("gaming"):
            return False
        # Write down the latest wish (model and window). If a loader thread is already running it will pick this up, so quick repeated picks
        # only load the last one. The lock keeps two requests from starting two threads.
        self._warm_target = (model_id, self.window_for(who, model)["window"])
        with self._warm_lock:
            if self._warm_thread and self._warm_thread.is_alive():
                return True
            self._warm_thread = threading.Thread(target=self._warm_loop, daemon=True)
            self._warm_thread.start()
        return True

    def _warm_loop(self):
        """Background loader for warm(): keeps loading whatever model was most recently asked for, and ends when there is nothing left to load."""
        while True:
            # Take the wish and clear it in one step. If warm() sets a new one while we load, the loop goes round again.
            target, self._warm_target = self._warm_target, None
            if not target:
                return
            try:
                self.runner.ensure(*target)
            except Exception:                                    # noqa: BLE001 - a failed head start costs nothing but the head start
                pass

    def pick_model(self, who, model_id):
        """This person's catalog card for the model id (with its state and badge). Raises KeyError if it is not in their list."""
        cat = self.catalog(who)
        for m in cat["cards"] + cat["other"]:
            if m["id"] == model_id:
                return m
        raise KeyError(model_id)

    def window_for(self, who, model, mode=None):
        """Choose the context window for this person and model: how much conversation fits in at once.

        It depends on the person's window setting (`mode`, or their saved one), their plan's limits (the owner has none), the model, and how
        much memory the computer has free right now. Returns the dict from context_window.pick (it includes "window").
        """
        mode = mode or self.get_settings(who["user"])["window_mode"]
        plan = self.cfg["tiers"][who["tier"]]["windows"]
        # Describe the computer: total memory and the memory free right now (never more than the total).
        device = CW.Device(self.ram_gb, min(self.ram_gb, free_memory_gb(self.ram_gb)))
        return CW.pick(model, device, mode, None if who["owner"] else plan)

    @property
    def demo(self):
        """True when nothing real is attached: every reply is the stand-in."""
        return not (self.llama_url or self.backend_factory or self.runner)

    def tok_for(self, model):
        """The tokenizer this model was trained with: a model's replies are garbage with another version's tokenizer."""
        # A tokenizer turns text into numbers (tokens) the model understands, and back. Loaded ones are cached in self.tokens.
        if model["id"] in self.tokens:
            return self.tokens[model["id"]]
        # Where the tokenizer file is: relative paths count from the project root.
        rel = model.get("tokenizer")
        path = None if not rel else (rel if os.path.isabs(rel) else os.path.join(self.root, rel))
        if not (path and os.path.exists(path)) and model.get("open"):    # a model downloaded from the backup repo has its tokenizer in its export folder
            alt = os.path.join(self.root, "export", "open", model["id"], "my-ai", "tokenizer.json")
            if os.path.exists(alt):
                path = alt
        # Load it: the right class for the model kind. If there is no file, fall back to a default one, or to a fake one for demo/test mode;
        # otherwise raise an error the person can read.
        if path and os.path.exists(path):
            tok = OpenTokenizer.load(path, think=model.get("think")) if model.get("open") else BPETokenizer.load(path)    # "open": a fine-tuned open model (ChatML)
        elif self.default_tok is not None:
            tok = self.default_tok
        elif self.demo or self.backend_factory:
            if self._demo_tok is None:
                self._demo_tok = demo_tokenizer()
            tok = self._demo_tok
        else:
            raise AppError(f"{model['name']} {model['version']:g}: its tokenizer file isn't here.",
                           f"Expected {rel or 'a tokenizer.json'}. Run the app from the project folder, or pass --tokenizer.")
        # Cache it for next time.
        self.tokens[model["id"]] = tok
        return tok

    def sees(self, model):
        """True when this model looks at pictures itself (an Emvryx 3 model with its mmproj file): the picture then goes straight to it, not through the
        separate picture reader that turns it into words first."""
        return model["id"] in self.seeing or bool(self.runner and self.runner.sees(model["id"]))

    def any_eyes(self):
        """True when some model on this computer looks at pictures itself (an Emvryx 3 model with its mmproj file)."""
        return bool(self.seeing) or bool(self.runner and any(self.runner.sees(mid) for mid in list(self.runner.files)))

    def eyes_for(self, who, model):
        """photo_fixes: the model that answers a message with a photo: this one when it can see, else the best ready model this person may use that can
        (an Emvryx 3 model with its picture reader), else None."""
        if self.sees(model):
            return model
        # Otherwise look for another model that can see. ranks orders model names from smallest to biggest, so the best one wins below.
        ranks = {"Flare": 1, "Equinox": 2, "Solstice": 3, "Apogee": 4}
        seeing = []
        for m in self.manifest["models"]:
            try:
                cand = self.pick_model(who, m["id"])
            except Exception:                                    # noqa: BLE001 - not in this person's list
                continue
            # Keep only candidates that are ready and can see.
            if cand.get("state") == "ready" and self.sees(cand):
                seeing.append(cand)
        # Highest name rank first, then highest version; default=None when the list is empty.
        return max(seeing, key=lambda m: (ranks.get(m.get("name"), 0), m.get("version", 0)), default=None)

    def backend_for(self, model, question, ctx=1024, cancel=None):
        """Return the object that actually produces a reply for this model: a test factory's, the local llama-server, a remote one, or the demo.

        `ctx` is the context window size to load the model with; `cancel` lets the caller stop a slow load. `question` is only used by the demo.
        """
        if self.backend_factory:
            return self.backend_factory(model, question)
        # Sampling settings control how adventurous the wording is (temperature: higher = more varied). The ** merges the model's own settings over the default.
        sampling = {"temperature": TEMPERATURE["balanced"], **model.get("sampling", {})}   # a model's own tested settings win
        if self.runner:
            return E.LlamaServer(self.runner.ensure(model["id"], ctx, cancel=cancel), None, timeout=120, **sampling)      # Stop while it loads ends the load
        if self.llama_url:
            return E.LlamaServer(self.llama_url, self.llama_key, **sampling)
        return DemoBackend(question)
