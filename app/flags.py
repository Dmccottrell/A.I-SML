"""
flags.py - Feature flags: new things are switched on for the owner and the admins first, then for named testers, then for everyone.

WHAT THIS FILE DOES
    * FLAGS is the list of things that can be switched (a new screen, a new model, a tour). Add one line there when a new feature is built, and ship the feature
      behind it: nobody but you sees it until you widen its audience in Settings > Owner > Features and testing.
    * An audience is one of: off (nobody, a quick way to roll something back), owner (only the PC owner), admins (the owner and every admin),
      testers (admins plus the named testers) or everyone.
    * The choices are kept in flags.json in the data folder. Nothing here needs a restart.
"""
import json
import os
import threading
import time

AUDIENCES = ("off", "owner", "admins", "testers", "everyone")
AUDIENCE_NAMES = {"off": "Off", "owner": "Owner", "admins": "Admins", "testers": "Testers", "everyone": "Everyone"}

# id, what the owner sees, what it does, and where it starts. New features start with the owner and the admins.
FLAGS = [
    {"id": "welcome_tour", "title": "Welcome tour", "desc": "The animated introduction and walk-through people see the first time they sign in (and can replay in Settings).", "default": "admins"},
]
BY_ID = {f["id"]: f for f in FLAGS}


class Flags:
    def __init__(self, path=None):
        self.path, self.lock = path, threading.Lock()
        self.data = {"audiences": {}, "testers": [], "changed": {}}
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    got = json.load(f)
                self.data.update({k: got[k] for k in ("audiences", "testers", "changed") if isinstance(got.get(k), (dict, list))})
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

    def audience(self, fid):
        if fid not in BY_ID:
            return "off"
        a = self.data["audiences"].get(fid)
        return a if a in AUDIENCES else BY_ID[fid]["default"]

    def testers(self):
        return list(self.data["testers"])

    def on(self, fid, who):
        """True when this person (a dict with user, founder, admin) may see the feature."""
        a = self.audience(fid)
        if a == "everyone":
            return True
        if a == "off" or not who:
            return False
        if a == "owner":
            return bool(who.get("founder"))
        if a == "admins":
            return bool(who.get("admin"))
        return bool(who.get("admin")) or who.get("user") in self.data["testers"]       # testers

    def mapping(self, who):
        return {f["id"]: self.on(f["id"], who) for f in FLAGS}

    def listing(self):
        return [dict(f, audience=self.audience(f["id"]), changed=self.data["changed"].get(f["id"])) for f in FLAGS]

    def set_audience(self, fid, audience, by=""):
        if fid not in BY_ID:
            raise ValueError("no such feature")
        if audience not in AUDIENCES:
            raise ValueError("choose " + ", ".join(AUDIENCES))
        with self.lock:
            self.data["audiences"][fid] = audience
            self.data["changed"][fid] = {"by": by, "at": time.time()}
            self._save()

    def set_testers(self, names):
        clean = []
        for n in names or []:
            n = str(n).strip()
            if n and n not in clean and len(clean) < 50:
                clean.append(n[:64])
        with self.lock:
            self.data["testers"] = clean
            self._save()
        return clean
