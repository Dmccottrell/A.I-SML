"""
flags.py - Feature flags: new things are switched on for the owner and the admins first, then for everyone.

WHAT THIS FILE DOES
    * FLAGS is the list of things that can be switched (a new screen, a new model, a tour). Add one line there when a new feature is built, and ship the feature
      behind it: nobody but you sees it until you widen its audience in Admin > Previews.
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
    {"id": "chat_fixes", "title": "Chat fixes (Oct 21)", "desc": "The overnight chat fixes: answers shown with real formatting (code blocks with a Copy button, tables, lists, links), no more answers cut off as \"looping\" at a table or a line of dashes, more room for long answers on the Emvryx 3 models with their own recommended settings (better facts and code), text that appears as fast as the model writes it, usage counted from what the model really read (an earlier part of the chat costs a tenth), more patience with very long chats, and a closer \"messages left\".", "default": "admins"},
    {"id": "photo_fixes", "title": "Photos, native (Oct 21)", "desc": "Photos go straight to an Emvryx 3 model that can see (no words-only reading first): a photo with no text in it is accepted whenever a model can look at it, it is turned the right way up, WebP, HEIC and other formats are converted to JPEG or PNG (the model's picture loader opens only those), and it is sized for the model (sharper and faster). A model that cannot see pictures hands a message with a photo to one that can, and the answer says which model wrote it.", "default": "admins"},
    {"id": "vryxcode_review", "title": "VryxCode: review like Cursor", "desc": "The VryxCode list grouped into Working, Ready for review and Done, each with the lines added and removed and its last line; reading, searching and thinking shown as quiet grey lines instead of cards; a chip for each changed file (path +52 -3) that opens the change; documents (PDF, Word, text) attached to a task for it to read first; and a short Done line with every file it changed.", "default": "admins"},
    {"id": "vryxcode_projects", "title": "VryxCode: projects organizer", "desc": "A new idea typed on the VryxCode home gets its own project, named from the idea (\"A bill splitter with tip\" becomes bill-splitter), unless you choose to build it in the current one; and the sessions list becomes an organizer like Claude's: every project with its sessions under it, newest first, numbered, a dot on the ones ready for review, and a + to start a new session in that project.", "default": "admins"},
    {"id": "model_bar", "title": "Message box in the model's colour", "desc": "The message box (its edge and glow) takes the colour of the model you picked (Flare orange, Equinox white, Solstice gold, Apogee ice blue), and lights up in that colour as the model is picked, with the colour wash in the same colour; everything else keeps the app's colours. On the website and in the Android app.", "default": "admins"},
    {"id": "vryxcode_fixes", "title": "VryxCode fixes (Oct 21)", "desc": "The overnight VryxCode fixes: pages that save things (a to-do list, a score) work in the preview instead of showing a storage error, a missing favicon or a blocked font is not reported as a problem, retries show as one line, edits that miss get the nearest real lines back, a step that keeps failing the same way is told to change approach, and stop messages that fit the model you are on.", "default": "admins"},
    {"id": "phone_alerts", "title": "Android: notifications", "desc": "The Android app tells you, with the phone's own notifications, when a VryxCode session finishes, needs you or stops, with a live 'working on it' notification while it runs (so it carries on when you switch apps), and when a chat answer is ready while the app is in the background. Tapping one opens that session or chat. The app asks for permission the first time.", "default": "admins"},
    {"id": "vryxcode_preview", "title": "VryxCode: preview follows the work", "desc": "The preview opens the web page VryxCode changed last (not always index.html) and refreshes after every change, the Done line gets a Preview button, and VryxCode is told the preview exists, so asked for a link it points to Preview instead of saying it cannot make links.", "default": "admins"},
    {"id": "vryxcode_guardrails", "title": "VryxCode: guardrails", "desc": "Keeps VryxCode from going in circles or making the code worse: it stops when a change undoes an earlier one (and puts back the last passing files), when the tests stop getting better, or after 5 fixes that did not work; while fixing, each change must get smaller and the existing tests cannot be edited; it asks instead of guessing when unsure. Reviews check the change against the request, grade problems Critical, Major or Nitpick, and end on Approved when nothing serious is wrong; Fix them sends only the serious ones back, each proved with a failing test first.", "default": "admins"},
    {"id": "vryxcode_servers", "title": "VryxCode: run servers", "desc": "VryxCode can start the server it built (Flask, FastAPI, Express...) and you use it in the Preview: it runs sealed in the isolated sandbox with no network, and each request is carried in and out by Docker itself, so nothing else can reach it. Links, forms and logins work inside the Preview; Logs shows what it printed and Stop ends it (it also stops after 30 minutes unused). Needs Docker on the Emvryx computer.", "default": "admins"},
    {"id": "vryxcode_autocheck", "title": "VryxCode: build check after every change", "desc": "Like the red underlines in an editor: after VryxCode changes code, the whole project is built (go vet, tsc, cargo check, dotnet build) and any error, even one in another file the change broke, goes straight back to it to fix; it cannot say it is finished while the project does not build.", "default": "admins"},
    {"id": "vryxcode_open_pc", "title": "VryxCode: nothing blocked on this computer (owner only)", "desc": "In the owner's own VryxCode sessions on This computer, nothing is blocked: any program or language, a real terminal (bash, or cmd on Windows), programs it builds, and installs with the internet. Other people always use the isolated sandbox. The risk: a mistake by the model (deleting the wrong folder) happens on the real computer.", "default": "admins"},
    {"id": "vryxcode_record", "title": "VryxCode: record my sessions for testing (owner only)", "desc": "The owner's own VryxCode sessions are saved whole (their messages and the model's full replies, next to the session history on this computer), so they can be replayed through newer VryxCode code to find bugs: python tools/export_sessions.py makes one zip to send. Other people's sessions are never recorded.", "default": "admins"},
    {"id": "vryxcode_lines", "title": "VryxCode: Claude Code-style feed", "desc": "The VryxCode feed reads like Claude Code: steps that only look or run fold into one quiet grey line (\"Read 3 files, ran 2 commands \u203a\", tap to open it), the model's words in between, file changes as chips with their + and - lines, a plain box for your messages instead of the purple bubble, and a small working line with moving dots and the time.", "default": "admins"},
    {"id": "vryxcode_restore", "title": "VryxCode: Restore on each message", "desc": "Each of your messages in a VryxCode session gets a Restore button: one tap (and a yes) puts the project's files back as they were just before that message, like Rewind but straight from the feed.", "default": "admins"},
    {"id": "vryxcode_secrets", "title": "VryxCode: secrets per project", "desc": "Each project can keep secrets (an API key, a password for a database) in Settings of the project. Programs VryxCode runs get them as environment variables, but the model never sees them: they are never put in its messages, and if a value shows up in a command's output it is replaced with [secret NAME]. Kept encrypted on the Emvryx computer.", "default": "admins"},
    {"id": "vryxcode_github", "title": "VryxCode: save to GitHub", "desc": "When a session is done, Save to GitHub puts the project in a GitHub repository of yours (through the connected GitHub): a new branch, one commit with a description written from the session, and a pull request you can merge. You confirm each step; nothing is pushed by itself.", "default": "admins"},
    {"id": "vryxcode_dbview", "title": "VryxCode: database viewer", "desc": "A SQLite database in the project (.db, .sqlite) opens in the Files panel as tables: every table, its columns and its first 200 rows, with a search box. Read-only: nothing is changed.", "default": "admins"},
    {"id": "vryxcode_publish", "title": "VryxCode: publish to a public link", "desc": "Publish puts a web project (HTML, CSS, JavaScript) on a free public link with GitHub Pages, through the connected GitHub. It says exactly what will be public and asks first; Unpublish takes it down. Servers (Flask, Express) cannot go on Pages: they need the cloud machine.", "default": "admins"},
    {"id": "admin_crashes", "title": "Admin: crashes and errors", "desc": "A Crashes page in Admin lists the errors in server.log (newest first, the same error counted once) with the lines around each one, for the owner only (an error can hold private text). Fix this opens VryxCode on your Emvryx project (imported from GitHub) with the error and the rule to prove it with a failing test first; the fix comes back as a pull request, never straight onto the running app.", "default": "admins"},
    {"id": "apk_link", "title": "Android: one-tap download link", "desc": "Settings shows a Get the Android app button with a fixed link (the android-latest release on GitHub), always the newest app, and a QR code to open it on a phone.", "default": "admins"},
    {"id": "android_vryxcode", "title": "Android: VryxCode like the website", "desc": "The Android app's VryxCode gets the website's newer parts: the Preview button and running apps (logs and stop), the Claude Code-style feed, the review verdict with its Fix button, and Restore on each message. Each part still follows its own VryxCode switch.", "default": "admins"},
    {"id": "cloud_guide", "title": "Cloud machine: step-by-step setup", "desc": "Admin > Cloud machine gets a guide for a free Oracle Cloud machine (the Always Free Arm machine): each step in plain words with a check that it worked, ending with the machine connected so VryxCode's terminal and servers can run there instead of on this PC.", "default": "admins"},
    {"id": "model_code_test", "title": "Models: coding test from real sessions", "desc": "Admin > Models gets a Coding test: the recorded VryxCode sessions (only your own, recorded with the switch for it) are turned into tasks with checks, and each of your models is run on them, sealed, to show which one codes best. Only your own models are tested, and nothing from them is used for training.", "default": "admins"},
]
# Products that are released like a model: every unpublished feature of VryxCode is part of the next VryxCode version. Each feature still has its own switch
# (for testing on the owner and admins); "Push update" in Admin > Models sends all of the waiting ones to everyone at once as, say, VryxCode 1.4.
PRODUCTS = {"vryxcode": {"title": "VryxCode", "desc": "The coding agent. Its new features wait here and go out together as the next VryxCode version."}}
for _f in FLAGS:
    if _f["id"].startswith("vryxcode_"):
        _f.setdefault("model", "vryxcode")
BY_ID = {f["id"]: f for f in FLAGS}
VERSION_RE = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}")
KINDS = ("major", "minor", "patch")


class Flags:
    def __init__(self, path=None, clock=time.time):
        self.path, self.lock, self.clock = path, threading.Lock(), clock
        self.data = {"audiences": {}, "changed": {}, "scheduled": {}, "version": "1.0.0", "releases": [], "products": {}}
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    got = json.load(f)
                self.data.update({k: got[k] for k in ("audiences", "changed", "scheduled", "releases", "products") if isinstance(got.get(k), (dict, list))})
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

    def product_version(self, pid):
        v = (self.data["products"].get(pid) or {}).get("version")
        return v if isinstance(v, str) and re.fullmatch(r"\d{1,3}\.\d{1,3}", v) else "1.0"

    @staticmethod
    def next_product_version(version, kind):
        major, minor = (int(x) for x in version.split("."))
        return f"{major + 1}.0" if kind == "major" else f"{major}.{minor + 1}"

    def products(self):
        """Admin > Models: each product with its version, the features waiting for its next version, the live ones and the ones switched off."""
        out = []
        for pid, p in PRODUCTS.items():
            feats = [f for f in FLAGS if f.get("model") == pid]
            v = self.product_version(pid)
            pick = lambda test: [{"id": f["id"], "title": f["title"], "desc": f["desc"], "audience": self.audience(f["id"])} for f in feats if test(self.audience(f["id"]))]
            out.append({"id": pid, "title": p["title"], "desc": p["desc"], "version": v, "label": f"{p['title']} {v}",
                        "next": {k: self.next_product_version(v, k) for k in ("minor", "major")},
                        "waiting": pick(lambda a: a not in ("everyone", "off")), "live": pick(lambda a: a == "everyone"), "held": pick(lambda a: a == "off")})
        return out

    def push_product(self, pid, by="", kind="minor", notes=""):
        """Every waiting feature of the product goes live for everyone as its next version (a model update in the release history; the app's own version
        does not change). A feature switched Off is on hold and stays out. Returns the new label ("VryxCode 1.4")."""
        if pid not in PRODUCTS:
            raise ValueError("no such model")
        if kind not in ("minor", "major"):
            raise ValueError("choose minor or major")
        title = PRODUCTS[pid]["title"]
        ids = [f["id"] for f in FLAGS if f.get("model") == pid and self.audience(f["id"]) not in ("everyone", "off")]
        if not ids:
            raise ValueError(f"nothing in {title} is waiting: every feature is live or switched off")
        with self.lock:
            v = self.next_product_version(self.product_version(pid), kind)
            now = self.clock()
            for f in ids:
                self.data["scheduled"].pop(f, None)
                self.data["audiences"][f] = "everyone"
                self.data["changed"][f] = {"by": by, "at": now}
            self.data["products"][pid] = {"version": v, "at": now, "by": by}
            label = f"{title} {v}"
            self.data["releases"].append({"seq": self.next_seq(), "version": self.data["version"], "kind": "model-update", "model": label, "product": pid, "at": now, "by": by,
                                          "notes": str(notes)[:500], "items": [{"id": f, "title": BY_ID[f]["title"], "desc": BY_ID[f]["desc"]} for f in ids]})
            del self.data["releases"][:-200]
            self._save()
        return label

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
