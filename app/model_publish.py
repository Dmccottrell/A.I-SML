"""
model_publish.py - Publishing a new model version, separately from the app's feature flags.

WHAT THIS FILE DOES
    * A model that is not ready for everyone is marked "status": "preview" in models.json. Only admins see it (in their picker, labelled Preview).
    * Publishing it (now, or at a chosen time) makes it live for everyone. The older versions of that model then simply move to "Other models" (the app lists
      the newest version of a name as its card and the rest as older ones), so nothing is deleted and they stay usable.
    * An update that keeps the version number (a small fix) is recorded as a release without publishing anything.
    * "Record an update" says by itself what changed: the model's entry in models.json (window, settings, skills ...) and its model file are compared with
      how they were when it was published or last updated (`changes`), and that text is the release note unless the owner writes another.
    * The choices are kept in models_state.json in the data folder (not in models.json, so updating the code never overwrites them). Both kinds of release go
      into the same release history as the feature releases (flags.py), but a model release does not change the app's version.
"""
# Standard library: json (save/load the state file), os (files), threading (a lock so two requests cannot write at once), time (the clock).
import json
import os
import threading
import time


def _k(n):
    """Format a token count for people: 131072 -> "128K". Small numbers (or non-numbers) are just turned into text."""
    return f"{n // 1024}K" if isinstance(n, int) and n >= 1024 else str(n)


# TRACKED is the list of model settings that count as a "change". Each row is a tuple of three things:
# (the key in models.json, the plain-words name shown to people, a small function that turns a value into readable text).
# A lambda is a tiny one-line function. `None` for the formatter means "just say it was updated" (used for the big sampling dict).
# what "Record an update" looks at, and how a change is described: (field, name, how a value reads)
TRACKED = (("context_tested", "Memory (context window)", _k), ("cache_bits", "Chat memory", lambda v: f"{v}-bit" if v else "16-bit"),
           ("mtp", "Guess-ahead drafting", lambda v: "on" if v else "off"), ("max_reply_tokens", "Longest reply", lambda v: f"{v} tokens"),
           ("efforts", "Thinking levels", lambda v: ", ".join(v or []) or "none"), ("skills", "Skills", lambda v: ", ".join(v or []) or "none"),
           ("sampling", "Answer settings", None), ("tagline", "Description", lambda v: f"\"{v}\""), ("lookup", "Looking things up", str))


def fingerprint(model, file_sig=None):
    """What a model is right now, for spotting what an update changed.
    Input: one models.json entry and a short id of its model file (file_sig). Output: a small dict with just the TRACKED fields plus "file".
    Two fingerprints taken at different times are compared by describe_changes()."""
    out = {k: model.get(k) for k, _, _ in TRACKED}
    out["file"] = file_sig
    return out


def describe_changes(old, new):
    """The changes between two fingerprints, in words ("Memory (context window): 128K -> 256K. New model file (retrained or re-exported).")."""
    lines = []
    # Walk every tracked setting; skip the ones that are equal, and describe the ones that differ ("name: old -> new").
    for k, name, show in TRACKED:
        a, b = old.get(k), new.get(k)
        if a == b:
            continue
        lines.append(f"{name}: updated" if show is None else f"{name}: {show(a)} \u2192 {show(b)}")
    # Different file ids on both sides means the model file itself was replaced (both must be known, otherwise we cannot tell).
    if old.get("file") and new.get("file") and old["file"] != new["file"]:
        lines.append("New model file (retrained or re-exported)")
    # Join the sentences with ". " and add a final "." only if there was at least one change.
    return ". ".join(lines) + ("." if lines else "")


def whats_new_note(model, most=3):
    """The first few "what is better" points from models.json "whats_new", for the release note when the person publishing writes none."""
    # Collect the non-empty "what is better" bullet points (an empty or missing list gives an empty list).
    points = [str(p).strip() for p in ((model.get("whats_new") or {}).get("points") or []) if str(p).strip()]
    # Glue the first `most` points on, each with a leading space, so the result can follow a sentence.
    return "".join(" " + p for p in points[:most])


class ModelPublisher:
    """Keeps track of which preview models are live, which are scheduled, and which failed to go live, and writes release notes.
    The state lives in `data` (four dicts keyed by model id) and is saved to a JSON file so it survives restarts."""

    def __init__(self, path=None, flags=None, clock=time.time, guard=None, file_sig=None):
        # path: state file (None = keep in memory only). flags: the release-history keeper (flags.py). clock: returns "now" (tests pass a fake one).
        self.path, self.flags, self.clock, self.lock, self.guard = path, flags, clock, threading.Lock(), guard      # guard(model_id) -> (ok, why): the safety checks
        self.file_sig = file_sig or (lambda model_id: None)                  # file_sig(model_id) -> a short id of the model file (size and time), to notice a new one
        # live = published models, scheduled = models waiting for a time, failed = scheduled ones that could not go live, seen = last fingerprint of each model.
        self.data = {"live": {}, "scheduled": {}, "failed": {}, "seen": {}}
        # Load the saved state if there is a file. A missing or damaged file just means we start empty (the except below ignores it).
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    got = json.load(f)
                # Only accept the four known keys, and only when they are dicts, so a bad file cannot break later code.
                for k in ("live", "scheduled", "failed", "seen"):
                    if isinstance(got.get(k), dict):
                        self.data[k] = got[k]
            except (OSError, ValueError):
                pass

    def _save(self):
        """Write the state file safely: write a temporary file first, then swap it in, so a crash never leaves a half-written file."""
        if not self.path:
            return
        tmp = self.path + ".tmp"
        # 0o600 = only the owner of the file may read or write it.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        # os.replace swaps the new file in as one step.
        os.replace(tmp, self.path)

    def status_of(self, model):
        """The status the app should use: a model in preview that has been published counts as stable."""
        return "stable" if model["status"] == "preview" and self.live(model["id"]) else model["status"]

    def live(self, model_id):
        """True if this model has been published."""
        return model_id in self.data["live"]

    def scheduled(self, model_id):
        """The {"at", "by"} record of a pending scheduled publish, or None."""
        return self.data["scheduled"].get(model_id)

    def _label(self, model):
        """Short name for messages, e.g. "Flare 2.5" (`:g` drops a useless ".0")."""
        return f"{model['name']} {model['version']:g}"

    def _older(self, manifest, model):
        """Older versions of the same name that are currently shown to people, newest first (these move to "Other models" on publish)."""
        olds = [m for m in manifest["models"] if m["name"] == model["name"] and m["id"] != model["id"] and m["version"] < model["version"] and self.status_of(m) not in ("off", "planned", "preview")]
        return sorted(olds, key=lambda m: -m["version"])

    def publish(self, manifest, model_id, by="", notes="", at=None, skip_checks=False):
        """Make a preview model live for everyone. Raises ValueError (with a plain reason) if it cannot be published.
        `by` = who did it, `notes` = release note (blank = a default one), `at` = time it counts as published, skip_checks = ignore the safety checks.
        Returns the model's label."""
        # Find the model entry by id (next() gives the first match, or None when there is none).
        model = next((m for m in manifest["models"] if m["id"] == model_id), None)
        if not model:
            raise ValueError("no such model")
        if model["status"] != "preview":
            raise ValueError("only a model in preview can be published")
        if self.live(model_id):
            raise ValueError("already published")
        # Run the safety checks (if any were given) and refuse to publish when they fail.
        if self.guard and not skip_checks:
            ok, why = self.guard(model_id)
            if not ok:
                raise ValueError(why)
        # Work out the sentence about the previous version moving to "Other models".
        older = self._older(manifest, model)
        move = f" {self._label(older[0])} moves to Other models and stays usable." if older else ""
        # Hold the lock while changing shared data, so two threads cannot corrupt it.
        with self.lock:
            self.data["live"][model_id] = {"at": at or self.clock(), "by": by, **({"checks_skipped": True} if (self.guard and skip_checks) else {})}
            self.data["seen"][model_id] = fingerprint(model, self.file_sig(model_id))      # what it was when it went live: later updates are compared with this
            self.data["scheduled"].pop(model_id, None)
            self.data["failed"].pop(model_id, None)
            self._save()
        # Add an entry to the release history (shown under What's new). The model release does not change the app's version number.
        if self.flags:
            self.flags.record_model_release(model_id, self._label(model), "model-new", by, (notes or "").strip() or f"{self._label(model)} is here.{whats_new_note(model)}{move}", model.get("tagline", ""))
        return self._label(model)

    def schedule(self, manifest, model_id, at, by=""):
        """Ask for a preview model to be published later. `at` is a Unix time (seconds since 1970). Must be in the future and within a year."""
        model = next((m for m in manifest["models"] if m["id"] == model_id), None)
        if not model or model["status"] != "preview" or self.live(model_id):
            raise ValueError("only a model in preview can be scheduled")
        try:
            at = float(at)
        except (TypeError, ValueError):
            raise ValueError("choose a date and time")
        now = self.clock()
        # Reject times in the past, and times more than a year ahead (366 days * 86400 seconds per day).
        if at <= now:
            raise ValueError("choose a time in the future")
        if at > now + 366 * 86400:
            raise ValueError("choose a time within the next year")
        with self.lock:
            self.data["scheduled"][model_id] = {"at": at, "by": by}
            self._save()

    def cancel_schedule(self, model_id):
        """Remove a pending scheduled publish (does nothing if there is none)."""
        with self.lock:
            if self.data["scheduled"].pop(model_id, None) is not None:
                self._save()

    def run_due(self, manifest):
        """Publish anything whose time has come. Called whenever the picker is built, so nothing needs to run in the background."""
        now = self.clock()
        # list(...) makes a copy, because publish() removes entries from the dict while we loop over it.
        for mid, due in list(self.data["scheduled"].items()):
            if now >= due["at"]:
                try:
                    self.publish(manifest, mid, by="schedule (set by %s)" % due.get("by", "?"), at=due["at"])
                except ValueError as e:                                  # not ready after all (the safety checks): do not publish, and say why
                    with self.lock:
                        self.data["scheduled"].pop(mid, None)
                        self.data["failed"][mid] = {"at": now, "why": str(e)}
                        self._save()

    def changes(self, model):
        """What changed in a live model since it was published or last updated, in words ("" when nothing did). The first look at a model that went live
        before this was kept only remembers how it is now."""
        # `now` is how the model looks today; `before` is how it looked when last recorded.
        now = fingerprint(model, self.file_sig(model["id"]))
        before = self.data["seen"].get(model["id"])
        # First time we look at this model: just remember it, and report no change (we have nothing to compare with).
        if before is None:
            with self.lock:
                self.data["seen"][model["id"]] = now
                self._save()
            return ""
        return describe_changes(before, now)

    def record_update(self, manifest, model_id, notes, by=""):
        """Record an update that keeps the version. With no notes, the note is what changed (see `changes`)."""
        model = next((m for m in manifest["models"] if m["id"] == model_id), None)
        if not model or self.status_of(model) in ("off", "planned", "preview"):
            raise ValueError("choose a model that is live")
        # Use the written note if there is one, otherwise the automatic "what changed" text. If both are empty, ask the person to say what changed.
        notes = str(notes or "").strip() or self.changes(model)
        if not notes:
            raise ValueError("nothing has changed since the last update: say what changed")
        # Add to the release history, then remember the new fingerprint so the next update compares against this one.
        self.flags.record_model_release(model_id, self._label(model), "model-update", by, notes, model.get("tagline", ""))
        with self.lock:
            self.data["seen"][model_id] = fingerprint(model, self.file_sig(model_id))
            self._save()
