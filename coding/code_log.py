"""
code_log.py - VryxCode's session history on disk: what each session did (so the Sessions list survives a restart) and a snapshot of the project before every message (so "Rewind" can undo).

    <person's code folder>/.sessions/<id>.json        the session's summary and its events
    <person's code folder>/.sessions/<id>/cpN.zip      the project as it was before message N

Nothing here runs code. The folder starts with a dot, so it is never listed as a project and never part of a download.
"""
import json
import os
import re
import shutil
import time

MAX_EVENTS = 600
MAX_SESSIONS = 60
MAX_CHECKPOINTS = 8
MAX_CHECKPOINT_BYTES = 5_000_000
KEEP_SNAPSHOTS_FOR = 10            # only the newest sessions keep their Rewind snapshots (disk is limited)
ID_OK = re.compile(r"[\w-]{1,60}")


class SessionLog:
    def __init__(self, base):
        self.dir = os.path.join(base, ".sessions")

    def _json(self, sid):
        if not ID_OK.fullmatch(str(sid)):
            raise ValueError("bad session id")
        return os.path.join(self.dir, sid + ".json")

    def save(self, meta, events):
        os.makedirs(self.dir, exist_ok=True)
        data = {"meta": meta, "events": events[-MAX_EVENTS:], "offset": max(0, len(events) - MAX_EVENTS)}
        path = self._json(meta["id"])
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
        self._trim()

    def load(self, sid):
        """{"meta", "events", "offset"} or None."""
        try:
            with open(self._json(sid), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def metas(self):
        out = []
        try:
            names = os.listdir(self.dir)
        except OSError:
            return out
        for n in names:
            if n.endswith(".json"):
                d = self.load(n[:-5])
                if d and d.get("meta"):
                    out.append(d["meta"])
        return out

    def delete(self, sid):
        try:
            os.remove(self._json(sid))
        except OSError:
            pass
        shutil.rmtree(os.path.join(self.dir, sid), ignore_errors=True)

    def _trim(self):
        metas = sorted(self.metas(), key=lambda m: m.get("updated", 0), reverse=True)
        for m in metas[MAX_SESSIONS:]:
            self.delete(m["id"])
        for m in metas[KEEP_SNAPSHOTS_FOR:MAX_SESSIONS]:
            shutil.rmtree(os.path.join(self.dir, m["id"]), ignore_errors=True)

    # ---- checkpoints
    def save_checkpoint(self, sid, n, data):
        if not data or len(data) > MAX_CHECKPOINT_BYTES:
            return False
        folder = os.path.join(self.dir, sid)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, f"cp{int(n)}.zip"), "wb") as f:
            f.write(data)
        old = sorted(self.checkpoint_numbers(sid))[:-MAX_CHECKPOINTS]
        for k in old:
            try:
                os.remove(os.path.join(folder, f"cp{k}.zip"))
            except OSError:
                pass
        return True

    def checkpoint_numbers(self, sid):
        try:
            return [int(m.group(1)) for m in (re.fullmatch(r"cp(\d+)\.zip", n) for n in os.listdir(os.path.join(self.dir, sid))) if m]
        except OSError:
            return []

    def load_checkpoint(self, sid, n):
        try:
            with open(os.path.join(self.dir, sid, f"cp{int(n)}.zip"), "rb") as f:
                return f.read()
        except (OSError, ValueError):
            return None


def age_words(now, then):
    """'now', '5m', '3h', '2d' or a date: how the Sessions list says when."""
    secs = max(0, now - then)
    if secs < 60:
        return "now"
    if secs < 3600:
        return f"{int(secs // 60)}m"
    if secs < 86400:
        return f"{int(secs // 3600)}h"
    if secs < 7 * 86400:
        return f"{int(secs // 86400)}d"
    return time.strftime("%b %d", time.localtime(then)).replace(" 0", " ")
