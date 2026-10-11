"""
flags.py - Feature flags: new things are switched on for the owner and the admins first, then for everyone.

WHAT THIS FILE DOES
    * FLAGS is the list of things that can be switched (a new screen, a new model, a tour). Add one line there when a new feature is built, and ship the feature
      behind it: nobody but you sees it until you widen its audience in Settings > Owner > Features and testing.
    * An audience is one of: off (nobody, a quick way to roll something back), owner (only the PC owner), admins (the owner and every admin) or everyone.
    * The choices are kept in flags.json in the data folder. Nothing here needs a restart.
"""
import json
import os
import threading
import time

AUDIENCES = ("off", "owner", "admins", "everyone")
AUDIENCE_NAMES = {"off": "Off", "owner": "Owner", "admins": "Admins", "everyone": "Everyone"}

# id, what the owner sees, what it does, and where it starts. New features start with the owner and the admins.
FLAGS = [
    {"id": "welcome_tour", "title": "Welcome tour", "desc": "The animated introduction and walk-through people see the first time they sign in (and can replay in Settings).", "default": "admins"},
]
BY_ID = {f["id"]: f for f in FLAGS}


class Flags:
    def __init__(self, path=None, clock=time.time):
        self.path, self.lock, self.clock = path, threading.Lock(), clock
        self.data = {"audiences": {}, "changed": {}, "scheduled": {}}
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    got = json.load(f)
                self.data.update({k: got[k] for k in ("audiences", "changed", "scheduled") if isinstance(got.get(k), (dict, list))})
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
        self._run_schedule(fid)
        a = self.data["audiences"].get(fid)
        return a if a in AUDIENCES else BY_ID[fid]["default"]

    def on(self, fid, who):
        """True when this person (a dict with user, founder, admin) may see the feature."""
        a = self.audience(fid)
        if a == "everyone":
            return True
        if a == "off" or not who:
            return False
        if a == "owner":
            return bool(who.get("founder"))
        return bool(who.get("admin"))

    def mapping(self, who):
        return {f["id"]: self.on(f["id"], who) for f in FLAGS}

    def listing(self):
        return [dict(f, audience=self.audience(f["id"]), changed=self.data["changed"].get(f["id"]), scheduled=self.data["scheduled"].get(f["id"])) for f in FLAGS]

    def set_audience(self, fid, audience, by=""):
        if fid not in BY_ID:
            raise ValueError("no such feature")
        if audience not in AUDIENCES:
            raise ValueError("choose " + ", ".join(AUDIENCES))
        with self.lock:
            self.data["audiences"][fid] = audience
            self.data["changed"][fid] = {"by": by, "at": self.clock()}
            self.data["scheduled"].pop(fid, None)                 # a change by hand replaces a pending schedule
            self._save()

    # Scheduled publishing: at a chosen time a feature moves to a wider audience (normally Everyone) by itself. Nothing needs to run in the
    # background: the time is checked whenever the feature is asked about, so it goes live on the first look after the time has passed.
    def _run_schedule(self, fid):
        due = self.data["scheduled"].get(fid)
        if due and self.clock() >= due["at"]:
            with self.lock:
                self.data["audiences"][fid] = due["audience"]
                self.data["changed"][fid] = {"by": "schedule (set by %s)" % due.get("by", "?"), "at": due["at"]}
                del self.data["scheduled"][fid]
                self._save()
            return due
        return None

    def publish_now(self, fid, by=""):
        self.cancel_schedule(fid)
        self.set_audience(fid, "everyone", by)

    def schedule(self, fid, at, audience="everyone", by=""):
        if fid not in BY_ID:
            raise ValueError("no such feature")
        if audience not in AUDIENCES:
            raise ValueError("choose " + ", ".join(AUDIENCES))
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
            self.data["scheduled"][fid] = {"at": at, "audience": audience, "by": by}
            self._save()

    def cancel_schedule(self, fid):
        with self.lock:
            if self.data["scheduled"].pop(fid, None) is not None:
                self._save()
