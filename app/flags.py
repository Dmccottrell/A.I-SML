"""
flags.py - Feature flags: new things are switched on for the owner and the admins first, then for everyone.

WHAT THIS FILE DOES
    * FLAGS is the list of things that can be switched (a new screen, a new model, a tour). Add one line there when a new feature is built, and ship the feature
      behind it: nobody but you sees it until you widen its audience in Settings > Owner > Features and testing.
    * An audience is one of: off (nobody, a quick way to roll something back), owner (only the PC owner), admins (the owner and every admin) or everyone.
    * The choices are kept in flags.json in the data folder. Nothing here needs a restart.
"""
import json
import re
import os
import threading
import time

AUDIENCES = ("off", "owner", "admins", "everyone")
AUDIENCE_NAMES = {"off": "Off", "owner": "Owner", "admins": "Admins", "everyone": "Everyone"}

# id, what the owner sees, what it does, and where it starts. New features start with the owner and the admins, never with everyone: the owner publishes
# each one when it is ready (tests/test_release_gate.py fails if a flag starts at "everyone"). New models do the same through "status": "preview".
FLAGS = [
    {"id": "welcome_tour", "title": "Welcome tour", "desc": "The animated introduction and walk-through people see the first time they sign in (and can replay in Settings).", "default": "admins"},
    {"id": "violet_theme", "title": "Violet look", "desc": "The whole chat app and the sign-in screen in electric violet instead of amber: buttons, the message box, glows and the Emvryx logo. Each model's logo keeps its own colour.", "default": "admins"},
    {"id": "modern_look", "title": "Modern look", "desc": "A newer look for the main chat: a floating glass sidebar and composer, the model speaking straight on the page, soft glow in the model's own colour, and ideas to try on the empty chat. Switch it off to go back.", "default": "admins"},
    {"id": "context_meter", "title": "Memory meter", "desc": "A ring by the message box (in chats and in VryxCode) that shows how full the model's memory (context window) is, with the details on a tap, and a \"Summarizing earlier messages\" line while a long chat is shortened to make room.", "default": "admins"},
    {"id": "whats_new", "title": "What's new in each model", "desc": "A \"What's new\" page for each new model, from the model picker: what is better than the version before, side by side with the measured numbers. The same points go into the release note when the model is published.", "default": "admins"},
    {"id": "vryxcode_effort", "title": "VryxCode: effort instead of models", "desc": "VryxCode shows no model picker: it uses Apogee 3 by itself (VryxCode 3 once it exists; until Apogee 3 is added, the best coding model that is ready), and the person picks only the effort: Quick, Balanced or Deep (Deep takes more steps and thinks before each one).", "default": "admins"},
    {"id": "vryxcode_full_agent", "title": "VryxCode: works like Claude Code", "desc": "VryxCode's agent the way Claude Code works (always on for VryxCode 3): it keeps going until the task is done (hundreds of steps instead of 12), runs the code and tests after each change and keeps fixing, reads 2,000 lines at a time, finds files and searches the code (glob, grep), replaces every match at once, and runs commands up to 10 minutes. Permissions as in Claude Code: commands that only look run freely, others ask, and \"always allow\" remembers that one command. In the isolated sandbox or on the cloud machine it has a real terminal (pipes, &&); on this PC it keeps the safe list of programs.", "default": "admins"},
    {"id": "vryxcode_update", "title": "VryxCode update", "desc": "The new VryxCode look: electric violet, the \"What should we build?\" home with starter templates and the phone-notification box, glass panels and the floating editor. Switch it off to get the earlier VryxCode look back. (The new tools, like keep or undo per file, search and second opinions, stay available.)", "default": "admins"},
    {"id": "vryxcode_suggest", "title": "VryxCode: suggested reply", "desc": "When VryxCode finishes, its message box shows a greyed-out suggestion for what to say next (as Claude does). Press Tab, or swipe right across the box on a phone, to fill it in; then send it or change it. Typing anything else ignores it.", "default": "admins"},
    {"id": "chat_house_rules", "title": "Emvryx 3: house rules in chat", "desc": "Until the Emvryx 3 models are retrained on Lessons 4, every chat message to them carries a short note on how to answer: answer exactly what was asked, never claim what the person did not say, no flattery, no emoji unless they use them, at most one exclamation mark, bring up remembered facts or other people only when they help, write commands and links out exactly, and say so when unsure. Only the model reads it.", "default": "admins"},
    {"id": "vryxcode_tour", "title": "VryxCode tour", "desc": "A walk-through that plays the first time someone opens VryxCode (WELCOME to VryxCode): describing what to build, effort (or models), Ask / Auto / Plan, how it checks and fixes its own work, permission questions, the preview, editor, keep or undo and rewind, slash commands, and the suggested reply. It shows only the VryxCode features switched on for that person. /tour plays it again.", "default": "admins"},
    {"id": "model_tours", "title": "Model welcome tours", "desc": "A walk-through for each new model that starts with \"WELCOME to Flare 3\" (or whichever model it is) and shows what that model adds compared with the one before it (a checklist, a slide for each, and the measured numbers side by side): its memory, pictures, faster replies, thinking. For the models VryxCode can use it goes on to VryxCode's features. It plays the first time someone picks the model (or opens the app after it arrives), and can be replayed from What's new. A preview model's tour reaches only the owner and the admins until the model is published.", "default": "admins"},
]
BY_ID = {f["id"]: f for f in FLAGS}
VERSION_RE = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}")
KINDS = ("major", "minor", "patch")


class Flags:
    def __init__(self, path=None, clock=time.time):
        self.path, self.lock, self.clock = path, threading.Lock(), clock
        self.data = {"audiences": {}, "changed": {}, "scheduled": {}, "version": "1.0.0", "releases": []}
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    got = json.load(f)
                self.data.update({k: got[k] for k in ("audiences", "changed", "scheduled", "releases") if isinstance(got.get(k), (dict, list))})
                if isinstance(got.get("version"), str) and VERSION_RE.fullmatch(got["version"]):
                    self.data["version"] = got["version"]
                for i, r in enumerate(self.data["releases"], 1):         # releases saved before they were numbered
                    r.setdefault("seq", i)
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
            return bool(who.get("founder") or who.get("granter"))
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
            self.data["scheduled"].pop(fid, None)                 # a change by hand replaces a pending schedule
            self._apply(fid, audience, by, self.clock())
            self._save()

    def _apply(self, fid, audience, by, at, kind="minor", notes=""):
        """Set one feature's audience (caller holds the lock). Going live for everyone is a release: the version goes up and the release history gets a line."""
        was = self.audience_raw(fid)
        self.data["audiences"][fid] = audience
        self.data["changed"][fid] = {"by": by, "at": at}
        if audience == "everyone" and was != "everyone":
            self._release([fid], by, at, kind, notes)

    def audience_raw(self, fid):
        a = self.data["audiences"].get(fid)
        return a if a in AUDIENCES else BY_ID[fid]["default"]

    def _release(self, fids, by, at, kind="minor", notes=""):
        major, minor, patch = (int(x) for x in self.data["version"].split("."))
        major, minor, patch = (major + 1, 0, 0) if kind == "major" else (major, minor + 1, 0) if kind == "minor" else (major, minor, patch + 1)
        self.data["version"] = f"{major}.{minor}.{patch}"
        items = [{"id": f, "title": BY_ID[f]["title"], "desc": BY_ID[f]["desc"]} for f in fids]
        self.data["releases"].append({"seq": self.next_seq(), "version": self.data["version"], "kind": kind, "at": at, "by": by, "notes": notes, "items": items})
        del self.data["releases"][:-200]

    def next_seq(self):
        return max((r.get("seq", 0) for r in self.data["releases"]), default=0) + 1

    def last_seq(self):
        return max((r.get("seq", 0) for r in self.data["releases"]), default=0)

    def record_model_release(self, model_id, label, kind, by, notes="", desc=""):
        """A model going live ("model-new") or getting an update that keeps its version ("model-update"). It is listed with the releases but does not change the app's own version."""
        if kind not in ("model-new", "model-update"):
            raise ValueError("choose model-new or model-update")
        with self.lock:
            self.data["releases"].append({"seq": self.next_seq(), "version": self.data["version"], "kind": kind, "model": label, "at": self.clock(), "by": by, "notes": str(notes)[:500],
                                          "items": [{"id": model_id, "title": label, "desc": desc}]})
            del self.data["releases"][:-200]
            self._save()

    @staticmethod
    def next_version(version, kind):
        """What publishing would make the version: 1.4.2 -> patch 1.4.3, minor 1.5.0, major 2.0.0."""
        major, minor, patch = (int(x) for x in str(version).split("."))
        return {"major": f"{major + 1}.0.0", "minor": f"{major}.{minor + 1}.0", "patch": f"{major}.{minor}.{patch + 1}"}[kind]

    def version(self):
        return self.data["version"]

    def releases(self):
        return list(reversed(self.data["releases"]))

    def preview_ids(self):
        return [f["id"] for f in FLAGS if self.audience(f["id"]) != "everyone"]

    def publish_all(self, by="", kind="minor", notes=""):
        """Everything still in preview goes live for everyone as ONE release. Returns the ids that went live."""
        if kind not in KINDS:
            raise ValueError("choose " + ", ".join(KINDS))
        ids = [f for f in self.preview_ids() if self.audience(f) != "off"]       # a feature switched Off is on hold, not ready
        if not ids:
            raise ValueError("nothing is waiting to be published")
        with self.lock:
            for f in ids:
                self.data["scheduled"].pop(f, None)
                self.data["audiences"][f] = "everyone"
                self.data["changed"][f] = {"by": by, "at": self.clock()}
            self._release(ids, by, self.clock(), kind, str(notes)[:500])
            self._save()
        return ids

    # Scheduled publishing: at a chosen time a feature moves to a wider audience (normally Everyone) by itself. Nothing needs to run in the
    # background: the time is checked whenever the feature is asked about, so it goes live on the first look after the time has passed.
    def _run_schedule(self, fid):
        due = self.data["scheduled"].get(fid)
        if due and self.clock() >= due["at"]:
            with self.lock:
                del self.data["scheduled"][fid]
                self._apply(fid, due["audience"], "schedule (set by %s)" % due.get("by", "?"), due["at"], due.get("kind", "minor"), due.get("notes", ""))
                self._save()
            return due
        return None

    def publish_now(self, fid, by="", kind="minor", notes=""):
        if fid not in BY_ID:
            raise ValueError("no such feature")
        if kind not in KINDS:
            raise ValueError("choose " + ", ".join(KINDS))
        with self.lock:
            self.data["scheduled"].pop(fid, None)
            if self.audience_raw(fid) != "everyone":
                self.data["audiences"][fid] = "everyone"
                self.data["changed"][fid] = {"by": by, "at": self.clock()}
                self._release([fid], by, self.clock(), kind, str(notes)[:500])
            self._save()

    def schedule(self, fid, at, audience="everyone", by="", kind="minor", notes=""):
        if fid not in BY_ID:
            raise ValueError("no such feature")
        if kind not in KINDS:
            raise ValueError("choose " + ", ".join(KINDS))
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
            self.data["scheduled"][fid] = {"at": at, "audience": audience, "by": by, "kind": kind, "notes": str(notes)[:500]}
            self._save()

    def cancel_schedule(self, fid):
        with self.lock:
            if self.data["scheduled"].pop(fid, None) is not None:
                self._save()
