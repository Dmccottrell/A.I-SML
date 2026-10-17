"""
model_publish.py - Publishing a new model version, separately from the app's feature flags.

WHAT THIS FILE DOES
    * A model that is not ready for everyone is marked "status": "preview" in models.json. Only admins see it (in their picker, labelled Preview).
    * Publishing it (now, or at a chosen time) makes it live for everyone. The older versions of that model then simply move to "Other models" (the app lists
      the newest version of a name as its card and the rest as older ones), so nothing is deleted and they stay usable.
    * An update that keeps the version number (a small fix) is recorded as a release without publishing anything.
    * The choices are kept in models_state.json in the data folder (not in models.json, so updating the code never overwrites them). Both kinds of release go
      into the same release history as the feature releases (flags.py), but a model release does not change the app's version.
"""
import json
import os
import threading
import time


def whats_new_note(model, most=3):
    """The first few "what is better" points from models.json "whats_new", for the release note when the person publishing writes none."""
    points = [str(p).strip() for p in ((model.get("whats_new") or {}).get("points") or []) if str(p).strip()]
    return "".join(" " + p for p in points[:most])


class ModelPublisher:
    def __init__(self, path=None, flags=None, clock=time.time, guard=None):
        self.path, self.flags, self.clock, self.lock, self.guard = path, flags, clock, threading.Lock(), guard      # guard(model_id) -> (ok, why): the safety checks
        self.data = {"live": {}, "scheduled": {}, "failed": {}}
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    got = json.load(f)
                for k in ("live", "scheduled", "failed"):
                    if isinstance(got.get(k), dict):
                        self.data[k] = got[k]
            except (OSError, ValueError):
                pass

    def _save(self):
        if not self.path:
            return
        tmp = self.path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, self.path)

    def status_of(self, model):
        """The status the app should use: a model in preview that has been published counts as stable."""
        return "stable" if model["status"] == "preview" and self.live(model["id"]) else model["status"]

    def live(self, model_id):
        return model_id in self.data["live"]

    def scheduled(self, model_id):
        return self.data["scheduled"].get(model_id)

    def _label(self, model):
        return f"{model['name']} {model['version']:g}"

    def _older(self, manifest, model):
        olds = [m for m in manifest["models"] if m["name"] == model["name"] and m["id"] != model["id"] and m["version"] < model["version"] and self.status_of(m) not in ("off", "planned", "preview")]
        return sorted(olds, key=lambda m: -m["version"])

    def publish(self, manifest, model_id, by="", notes="", at=None, skip_checks=False):
        model = next((m for m in manifest["models"] if m["id"] == model_id), None)
        if not model:
            raise ValueError("no such model")
        if model["status"] != "preview":
            raise ValueError("only a model in preview can be published")
        if self.live(model_id):
            raise ValueError("already published")
        if self.guard and not skip_checks:
            ok, why = self.guard(model_id)
            if not ok:
                raise ValueError(why)
        older = self._older(manifest, model)
        move = f" {self._label(older[0])} moves to Other models and stays usable." if older else ""
        with self.lock:
            self.data["live"][model_id] = {"at": at or self.clock(), "by": by, **({"checks_skipped": True} if (self.guard and skip_checks) else {})}
            self.data["scheduled"].pop(model_id, None)
            self.data["failed"].pop(model_id, None)
            self._save()
        if self.flags:
            self.flags.record_model_release(model_id, self._label(model), "model-new", by, (notes or "").strip() or f"{self._label(model)} is here.{whats_new_note(model)}{move}", model.get("tagline", ""))
        return self._label(model)

    def schedule(self, manifest, model_id, at, by=""):
        model = next((m for m in manifest["models"] if m["id"] == model_id), None)
        if not model or model["status"] != "preview" or self.live(model_id):
            raise ValueError("only a model in preview can be scheduled")
        try:
            at = float(at)
        except (TypeError, ValueError):
            raise ValueError("choose a date and time")
        now = self.clock()
        if at <= now:
            raise ValueError("choose a time in the future")
        if at > now + 366 * 86400:
            raise ValueError("choose a time within the next year")
        with self.lock:
            self.data["scheduled"][model_id] = {"at": at, "by": by}
            self._save()

    def cancel_schedule(self, model_id):
        with self.lock:
            if self.data["scheduled"].pop(model_id, None) is not None:
                self._save()

    def run_due(self, manifest):
        """Publish anything whose time has come. Called whenever the picker is built, so nothing needs to run in the background."""
        now = self.clock()
        for mid, due in list(self.data["scheduled"].items()):
            if now >= due["at"]:
                try:
                    self.publish(manifest, mid, by="schedule (set by %s)" % due.get("by", "?"), at=due["at"])
                except ValueError as e:                                  # not ready after all (the safety checks): do not publish, and say why
                    with self.lock:
                        self.data["scheduled"].pop(mid, None)
                        self.data["failed"][mid] = {"at": now, "why": str(e)}
                        self._save()

    def record_update(self, manifest, model_id, notes, by=""):
        model = next((m for m in manifest["models"] if m["id"] == model_id), None)
        if not model or self.status_of(model) in ("off", "planned", "preview"):
            raise ValueError("choose a model that is live")
        if not str(notes or "").strip():
            raise ValueError("say what changed")
        self.flags.record_model_release(model_id, self._label(model), "model-update", by, notes, model.get("tagline", ""))
