"""
code_log.py - VryxCode's session history on disk: what each session did (so the Sessions list survives a restart) and a snapshot of the project before every message (so "Rewind" can undo).

    <person's code folder>/.sessions/<id>.json        the session's summary and its events
    <person's code folder>/.sessions/<id>/cpN.zip      the project as it was before message N

Nothing here runs code. The folder starts with a dot, so it is never listed as a project and never part of a download.
"""
# json saves data as text; os.path works with file paths; re = regular expressions (text patterns); shutil.rmtree
# deletes a whole folder; time formats dates.
import json
import os
import re
import shutil
import time

# Limits: events kept per session, sessions kept, Rewind snapshots kept per session, and the biggest snapshot (bytes).
MAX_EVENTS = 600
MAX_SESSIONS = 60
MAX_CHECKPOINTS = 8
MAX_CHECKPOINT_BYTES = 5_000_000
KEEP_SNAPSHOTS_FOR = 10            # only the newest sessions keep their Rewind snapshots (disk is limited)
# A session id may only be letters, digits, _ or - (1 to 60 characters). This also stops "../" tricks in file names.
ID_OK = re.compile(r"[\w-]{1,60}")


class SessionLog:
    """Reads and writes one person's session history files in their .sessions folder."""

    def __init__(self, base):
        """base = the person's code folder; the history goes in base/.sessions"""
        self.dir = os.path.join(base, ".sessions")

    def _json(self, sid):
        """The path of a session's .json file. Raises ValueError if the id has odd characters."""
        if not ID_OK.fullmatch(str(sid)):
            raise ValueError("bad session id")
        return os.path.join(self.dir, sid + ".json")

    def save(self, meta, events):
        """Store a session: meta = its summary (must have an "id"), events = everything it did, oldest first."""
        os.makedirs(self.dir, exist_ok=True)
        # Only the newest 600 events are kept; "offset" says how many older ones were dropped.
        data = {"meta": meta, "events": events[-MAX_EVENTS:], "offset": max(0, len(events) - MAX_EVENTS)}
        path = self._json(meta["id"])
        # Write to a .tmp file, then os.replace swaps it in at once, so a crash never leaves a half-written file.
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
        # Remove the oldest sessions if there are too many.
        self._trim()

    def load(self, sid):
        """{"meta", "events", "offset"} or None."""
        try:
            with open(self._json(sid), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def set_flag(self, sid, key, value):
        """Change one fact in a saved session's summary (for example "archived") and keep everything else as it was. False if the session is not saved."""
        d = self.load(sid)
        if not d or not d.get("meta"):
            return False
        # Only keep the key when it is on, so an unarchived session looks exactly as it did before archiving existed.
        if value:
            d["meta"][key] = value
        else:
            d["meta"].pop(key, None)
        path = self._json(sid)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, path)
        return True

    def metas(self):
        """The summary (meta) of every stored session, in no particular order."""
        out = []
        try:
            names = os.listdir(self.dir)
        except OSError:
            return out
        for n in names:
            # n[:-5] cuts off ".json" to get the session id.
            if n.endswith(".json"):
                d = self.load(n[:-5])
                if d and d.get("meta"):
                    out.append(d["meta"])
        return out

    def save_replay(self, sid, data):
        """The session's recording (the owner's messages and the model's whole replies), next to its history: <id>.replay"""
        # Same name as the history file but ending ".replay" (the [:-5] removes ".json").
        path = self._json(sid)[:-5] + ".replay"
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(path + ".tmp", path)

    def load_replay(self, sid):
        """The saved recording of a session, or None if there is none or it is unreadable."""
        try:
            with open(self._json(sid)[:-5] + ".replay", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def delete(self, sid):
        """Remove a session completely: its history file, its recording and its snapshot folder."""
        for path in (self._json(sid), self._json(sid)[:-5] + ".replay"):
            try:
                os.remove(path)
            except OSError:
                # Already gone: fine.
                pass
        shutil.rmtree(os.path.join(self.dir, sid), ignore_errors=True)

    def _trim(self):
        """Keep disk use bounded: delete sessions beyond the newest 60, and delete the Rewind snapshots of all but the newest 10."""
        # Newest first, by the "updated" time in each summary.
        metas = sorted(self.metas(), key=lambda m: m.get("updated", 0), reverse=True)
        for m in metas[MAX_SESSIONS:]:
            self.delete(m["id"])
        for m in metas[KEEP_SNAPSHOTS_FOR:MAX_SESSIONS]:
            shutil.rmtree(os.path.join(self.dir, m["id"]), ignore_errors=True)

    # ---- checkpoints
    def save_checkpoint(self, sid, n, data):
        """Store the project snapshot (a zip, as bytes) taken before message number n. Returns False if the data is
        empty or too big and nothing was stored."""
        if not data or len(data) > MAX_CHECKPOINT_BYTES:
            return False
        folder = os.path.join(self.dir, sid)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, f"cp{int(n)}.zip"), "wb") as f:
            f.write(data)
        # Everything except the newest MAX_CHECKPOINTS snapshots is deleted.
        old = sorted(self.checkpoint_numbers(sid))[:-MAX_CHECKPOINTS]
        for k in old:
            try:
                os.remove(os.path.join(folder, f"cp{k}.zip"))
            except OSError:
                pass
        return True

    def checkpoint_numbers(self, sid):
        """The numbers N of the snapshots stored for a session (from files named cpN.zip); [] if none."""
        # The inner generator matches each file name against "cp<digits>.zip"; names that do not match give None and are skipped.
        try:
            return [int(m.group(1)) for m in (re.fullmatch(r"cp(\d+)\.zip", n) for n in os.listdir(os.path.join(self.dir, sid))) if m]
        except OSError:
            return []

    def load_checkpoint(self, sid, n):
        """The snapshot bytes for message n, or None if it is missing."""
        try:
            with open(os.path.join(self.dir, sid, f"cp{int(n)}.zip"), "rb") as f:
                return f.read()
        except (OSError, ValueError):
            return None


def age_words(now, then):
    """'now', '5m', '3h', '2d' or a date: how the Sessions list says when."""
    # Seconds since then (never negative). Then pick the biggest unit that fits.
    secs = max(0, now - then)
    if secs < 60:
        return "now"
    if secs < 3600:
        return f"{int(secs // 60)}m"
    if secs < 86400:
        return f"{int(secs // 3600)}h"
    if secs < 7 * 86400:
        return f"{int(secs // 86400)}d"
    # A week or more ago: a date like "Mar 5" (the replace removes the zero in "Mar 05").
    return time.strftime("%b %d", time.localtime(then)).replace(" 0", " ")
