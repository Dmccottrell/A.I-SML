"""
state_pc.py - AppState's model-running part: gaming mode, idle unload, safety checks before publishing, and choosing, warming and talking to a model.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
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
        return os.path.join(self.data_dir, "gaming.flag") if self.data_dir else None

    def sync_gaming(self):
        """Gaming mode is on when the switch says so OR the file gaming.flag exists in the data folder (so a shortcut on the desktop can switch it with no key)."""
        f = self.gaming_file()
        if f:
            self.cfg["gaming"] = os.path.exists(f) or bool(self.cfg.get("gaming_mem"))
        return bool(self.cfg.get("gaming"))

    def set_gaming(self, on, by=""):
        """Switch Gaming mode. On: nobody can start a reply, and the model is unloaded now (or as soon as the replies running finish)."""
        on = bool(on)
        f = self.gaming_file()
        self.cfg["gaming_mem"] = on
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
        unloaded = self.unload_model("gaming mode") if on else False
        self.auth.event("gaming_mode", by or "owner", "", "on" if on else "off")
        return {"gaming": on, "unloaded": unloaded, "loaded": self.runner.loaded() if self.runner else None}

    def busy(self):
        """True while a reply or a coding session is using the model."""
        return bool(self.stops or self.code.any_running())

    def unload_model(self, why=""):
        """Stop the loaded model if nothing is using it. True if it was stopped."""
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
        now = time.time() if now is None else now
        if self.busy():
            self.runner.touch()
            return None
        if self.sync_gaming():
            return "gaming" if self.unload_model("gaming mode") else None
        minutes = int(self.security.get("idle_unload_minutes") or 0)
        if minutes > 0 and self.runner.loaded() and now - self.runner.last_used >= minutes * 60:
            return "idle" if self.unload_model(f"idle for {minutes} minutes") else None
        return None

    def pc_status(self):
        r = self.runner
        loaded = r.loaded() if r else None
        model = next((m for m in self.manifest["models"] if m["id"] == loaded), None) if loaded else None
        return {"gaming": bool(self.cfg.get("gaming")), "has_runner": bool(r), "loaded": loaded, "loaded_label": (f"{model['name']} {model['version']:g}" if model else None),
                "idle_seconds": int(time.time() - r.last_used) if (r and loaded) else None, "idle_unload_minutes": int(self.security.get("idle_unload_minutes") or 0),
                "busy": self.busy()}

    def _model_fingerprint(self, model_id):
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
        rec = self.guards.load(model_id)
        if not rec:
            return False, "Run the safety checks first (Admin > Models > Run safety checks): a new model must pass them before it is published."
        if rec.get("fingerprint") and rec["fingerprint"] != self._model_fingerprint(model_id):
            return False, "The model file changed after the safety checks: run them again."
        if not rec["passed"]:
            return False, "The safety checks did not pass: " + "; ".join(rec["reasons"]) + "."
        return True, ""

    def _guard_who(self):
        """An internal account with no limits that asks the check questions (it sees models in preview, keeps no memory and never searches the web)."""
        if not self.user_record(self.GUARD_USER):
            self.add_user(self.GUARD_USER, "mega", key_prefix=API_KEY_PREFIX)
            self._set_fields(self.GUARD_USER, app=True, internal=True, app_enabled=True)
            self.set_access(self.GUARD_USER, unlimited=True)
            self.put_settings(self.GUARD_USER, {"memory": False, "live_data": False, "connected_apps": False, "web_search": "none", "custom_instructions": ""})
        return self.who_name(self.GUARD_USER)

    def ask_quietly(self, who, model_id, prompt, effort="balanced", timeout=420):
        """(reply, error) for one question through the whole app, in a private chat that is thrown away."""
        store = self.store(who["user"])
        cid = store.new_chat(private=True)
        try:
            q, stop, model, win, decision = start_turn(self, who, cid, prompt, model_id, effort, pace=False)
        except Exception as e:                                 # noqa: BLE001
            store.delete_chat(cid)
            return "", str(error_payload(e)[2].get("message", "error"))
        try:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    kind, val = q.get(timeout=1)
                except queue.Empty:
                    if time.monotonic() > deadline:
                        stop.set()
                        return "", "took too long"
                    continue
                if kind == "done":
                    return (val.get("text") or "").strip(), None
                if kind == "error":
                    return "", str(error_payload(val)[2].get("message", "error"))
        finally:
            store.delete_chat(cid)

    def start_guard(self, model_id, by=""):
        """Run the safety checks on a model in the background (one at a time). Raises ValueError when they cannot start."""
        model = next((m for m in self.manifest["models"] if m["id"] == model_id), None)
        if not model or model["status"] in ("off", "planned"):
            raise ValueError("no such model")
        if self.cfg.get("gaming"):
            raise ValueError("Gaming mode is on: turn it off first, the checks need the model loaded")
        if self.runner and not self.runner.available(model_id):
            raise ValueError("That model's file is not on this computer yet.")
        with self._guard_lock:
            if self.guard_run and self.guard_run["state"] == "running":
                raise ValueError("The checks are already running for " + self.guard_run["model_id"])
            tests = model_guard_tests(self.guard_sheet)
            run = {"model_id": model_id, "state": "running", "i": 0, "n": len(tests), "started": time.time()}
            self.guard_run = run
        who = self._guard_who()
        older_id = None
        olds = self.models_pub._older(self.manifest, model)
        if olds:
            older_id = olds[0]["id"]

        def work():
            import quality_check
            results = []
            try:
                for i, t in enumerate(tests):
                    reply, error = self.ask_quietly(who, model_id, t["prompt"])
                    results.append({"prompt": t["prompt"], "category": t["category"], "ok": bool(not error and quality_check.check(t, reply)), "reply": reply[:600], "error": error})
                    run["i"] = i + 1
                    if i == 2 and all(r["error"] for r in results):          # the first three could not even be asked: do not keep going
                        break
                older = self.guards.load(older_id) if older_id else None
                older_label = next((f"{m['name']} {m['version']:g}" for m in self.manifest["models"] if m["id"] == older_id), "")
                passed, reasons, summary = model_guard.judge(results, older["summary"] if older else None, older_label)
                self.guards.save(model_id, {"model_id": model_id, "when": time.time(), "by": by, "passed": passed, "reasons": reasons, "summary": summary, "results": results,
                                           "fingerprint": self._model_fingerprint(model_id)})
                self.auth.event("model_checks", by or "owner", "", f"{model_id}: {'passed' if passed else 'failed'} {summary['percent']:g}%")
            except Exception as e:                                           # noqa: BLE001
                print(f"(safety checks for {model_id} stopped: {e})", flush=True)
            finally:
                run["state"] = "done"
        threading.Thread(target=work, daemon=True).start()
        return {"started": True, "n": len(tests)}

    def models_admin(self):
        """The Models tab: every model in the family, whether it is in preview or live, what a publish would replace, and the model releases so far."""
        mp, out = self.models_pub, []
        mp.run_due(self.manifest)
        for name in M.NAMES:
            for m in sorted((x for x in self.manifest["models"] if x["name"] == name and x["status"] not in ("off", "planned")), key=lambda x: -x["version"]):
                preview = m["status"] == "preview" and not mp.live(m["id"])
                olds = mp._older(self.manifest, m)
                out.append({"id": m["id"], "name": m["name"], "version": m["version"], "label": f"{m['name']} {m['version']:g}", "tagline": m.get("tagline", ""), "preview": preview,
                            "scheduled": mp.scheduled(m["id"]), "live": mp.data["live"].get(m["id"]), "replaces": f"{olds[0]['name']} {olds[0]['version']:g}" if (preview and olds) else None,
                            "available": bool(self.runner.available(m["id"])) if self.runner else True,
                            "guard": model_guard.public(self.guards.load(m["id"]), self.guard_run if (self.guard_run and self.guard_run["state"] == "running" and self.guard_run["model_id"] == m["id"]) else None),
                            "schedule_failed": mp.data["failed"].get(m["id"]), "changes": "" if preview else mp.changes(m)})
        return {"models": out, "keep_older": int(self.manifest.get("keep_older_versions", 6)), "checks_running": bool(self.guard_run and self.guard_run["state"] == "running"),
                "releases": [r for r in self.flags.releases() if str(r.get("kind", "")).startswith("model")]}

    def preload(self, model_id):
        """Start the model's llama-server now (with the window the owner's chats would ask for), so the first message is not slow.
        Returns a short message for the log. Never raises: a model that cannot load only costs the head start."""
        if not self.runner:
            return "nothing to preload (no local models)"
        if self.sync_gaming():
            return "Gaming mode is on: not loading any model"
        model = next((m for m in list(self.manifest["models"]) + list(self.manifest.get("coders", [])) if m["id"] == model_id), None)
        if not model:
            return f"unknown model {model_id!r}"
        if not self.runner.available(model_id):
            return f"{model_id}: its .gguf file is not on this computer"
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
        try:
            model = self.pick_model(who, model_id)
        except KeyError:
            return False
        if model["state"] != "ready" or not self.runner.available(model_id):
            return False
        if self.stops or self.code.any_running() or self.cfg.get("gaming"):
            return False
        self._warm_target = (model_id, self.window_for(who, model)["window"])
        with self._warm_lock:
            if self._warm_thread and self._warm_thread.is_alive():
                return True
            self._warm_thread = threading.Thread(target=self._warm_loop, daemon=True)
            self._warm_thread.start()
        return True

    def _warm_loop(self):
        while True:
            target, self._warm_target = self._warm_target, None
            if not target:
                return
            try:
                self.runner.ensure(*target)
            except Exception:                                    # noqa: BLE001 - a failed head start costs nothing but the head start
                pass

    def pick_model(self, who, model_id):
        cat = self.catalog(who)
        for m in cat["cards"] + cat["other"]:
            if m["id"] == model_id:
                return m
        raise KeyError(model_id)

    def window_for(self, who, model, mode=None):
        mode = mode or self.get_settings(who["user"])["window_mode"]
        plan = self.cfg["tiers"][who["tier"]]["windows"]
        device = CW.Device(self.ram_gb, min(self.ram_gb, free_memory_gb(self.ram_gb)))
        return CW.pick(model, device, mode, None if who["owner"] else plan)

    @property
    def demo(self):
        """True when nothing real is attached: every reply is the stand-in."""
        return not (self.llama_url or self.backend_factory or self.runner)

    def tok_for(self, model):
        """The tokenizer this model was trained with: a model's replies are garbage with another version's tokenizer."""
        if model["id"] in self.tokens:
            return self.tokens[model["id"]]
        rel = model.get("tokenizer")
        path = None if not rel else (rel if os.path.isabs(rel) else os.path.join(self.root, rel))
        if not (path and os.path.exists(path)) and model.get("open"):    # a model downloaded from the backup repo has its tokenizer in its export folder
            alt = os.path.join(self.root, "export", "open", model["id"], "my-ai", "tokenizer.json")
            if os.path.exists(alt):
                path = alt
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
        self.tokens[model["id"]] = tok
        return tok

    def sees(self, model):
        """True when this model looks at pictures itself (an Emvryx 3 model with its mmproj file): the picture then goes straight to it, not through the
        separate picture reader that turns it into words first."""
        return model["id"] in self.seeing or bool(self.runner and self.runner.sees(model["id"]))

    def backend_for(self, model, question, ctx=1024):
        if self.backend_factory:
            return self.backend_factory(model, question)
        sampling = {"temperature": TEMPERATURE["balanced"], **model.get("sampling", {})}   # a model's own tested settings win
        if self.runner:
            return E.LlamaServer(self.runner.ensure(model["id"], ctx), None, timeout=120, **sampling)
        if self.llama_url:
            return E.LlamaServer(self.llama_url, self.llama_key, **sampling)
        return DemoBackend(question)
