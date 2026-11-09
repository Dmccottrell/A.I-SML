"""
state_settings.py - AppState's per-person data: chats store, documents, notes, memory, settings and usage numbers.

WHERE IT FITS
    AppState (the server's big shared object) is built from mixin classes, one per state_*.py file. A mixin's methods are mixed into AppState,
    so `self` here is the whole AppState (self.lock, self.data_dir, self.stores, self.settings ... come from other parts).
    Each person gets their own small SQLite database files (chats, documents, saved notes, memory) in the data folder, opened the first
    time they are needed and then kept in a dict. With no data folder, ":memory:" databases are used (they vanish when the server stops).
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import json
import app_engine as E
import chat_polish
import app_skills
import documents
import lookup_auto
import saved_notes
import study_cards
import user_memory


class StateSettings:
    """What is kept for each person: chats, notes, memory, settings."""

    # ---- chats and settings, per person
    def store(self, user):
        """This person's chat database (created on first use). Same pattern for docs_for, saved_for and memory_for below."""
        # The lock makes sure two threads asking at the same moment do not both create (and overwrite) the database object.
        with self.lock:
            if user not in self.stores:
                path = os.path.join(self.data_dir, f"chats-{user}.db") if self.data_dir else ":memory:"
                self.stores[user] = E.ChatStore(path)
            return self.stores[user]

    def docs_for(self, user):
        """This person's document library (uploaded files they can ask questions about)."""
        with self.lock:
            if user not in self.libraries:
                path = os.path.join(self.data_dir, f"docs-{user}.db") if self.data_dir else ":memory:"
                self.libraries[user] = documents.Library(path, clock=self.clock)
            return self.libraries[user]

    def saved_for(self, user):
        """This person's saved notes (answers they approved with a thumbs up, see saved_notes.py)."""
        with self.lock:
            if user not in self.saved:
                path = os.path.join(self.data_dir, f"saved-{user}.db") if self.data_dir else ":memory:"
                self.saved[user] = saved_notes.SavedNotes(path)
            return self.saved[user]

    def decks_for(self, user):
        """This person's flashcard decks (study_cards.py)."""
        with self.lock:
            if user not in self.decks:
                path = os.path.join(self.data_dir, f"study-{user}.db") if self.data_dir else ":memory:"
                self.decks[user] = study_cards.Decks(path)
            return self.decks[user]

    def memory_for(self, user):
        """This person's memory: facts the assistant remembers about them between chats."""
        with self.lock:
            if user not in self.memories:
                path = os.path.join(self.data_dir, f"memory-{user}.db") if self.data_dir else ":memory:"
                self.memories[user] = user_memory.Memory(path)
            return self.memories[user]

    def remember_lookup(self, user, chat_id, message_id, question, found):
        """Keep what an answer was written from (the last 200), so a thumbs up can save it. Private chats keep nothing."""
        # Private chats have negative ids and save nothing; also skip answers that used no notes.
        if chat_id < 0 or not found["used"]:
            return
        # Keyed by (person, chat, message) so the thumbs-up can find it later. The dict remembers insert order, so popping the first key drops the oldest.
        with self.lock:
            self.lookups[(user, chat_id, message_id)] = {"question": question, "notes": found["used"], "recent": found.get("recent", False)}
            while len(self.lookups) > 200:
                self.lookups.pop(next(iter(self.lookups)))

    def _load_settings(self):
        """Each person's settings are kept in settings.json, so a restart does not put them back to the defaults."""
        if not self.data_dir:
            return
        try:
            with open(os.path.join(self.data_dir, "settings.json"), encoding="utf-8") as f:
                data = json.load(f)
            # Expect {person: {setting: value}}; keep only entries whose value is a dict, so a damaged file cannot break startup.
            if isinstance(data, dict):
                self.settings = {k: v for k, v in data.items() if isinstance(v, dict)}
        except (OSError, ValueError):
            pass

    def _save_settings(self):
        """Write everyone's settings to settings.json. A temp file is written first and then swapped in, so a crash cannot leave half a file."""
        if not self.data_dir:
            return
        path = os.path.join(self.data_dir, "settings.json")
        try:
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(self.settings, f)
            os.replace(path + ".tmp", path)
        except OSError:
            pass

    def get_settings(self, user):
        """This person's settings: the defaults below, with anything they saved laid on top (so new settings get a sensible value for old users)."""
        s = {"window_mode": "everyday", "show_tokens": False, "web_search": "auto", "memory": True, "thinking_pause": "short", "live_data": True, "connected_apps": True, "tour_seen": 0, "tour_devices": {}, "whats_new_seq": -1, "model_tours_seen": [], "vryx_tour_seen": 0}
        s.update(self.settings.get(user, {}))
        return s

    def put_settings(self, user, new):
        """Change some of a person's settings from `new` (a dict that came from the browser) and save. Returns the full settings.

        Each setting is checked first (right type, allowed value, within limits), and anything invalid is silently ignored, so the browser
        can never store nonsense. Settings missing from `new` stay as they were.
        """
        s = self.get_settings(user)
        # Simple on/off and pick-from-a-list settings: accept only allowed values.
        if new.get("window_mode") in ("everyday", "long"):
            s["window_mode"] = new["window_mode"]
        if isinstance(new.get("show_tokens"), bool):
            s["show_tokens"] = new["show_tokens"]
        if new.get("thinking_pause") in chat_polish.PAUSE_SCALE:
            s["thinking_pause"] = new["thinking_pause"]
        if isinstance(new.get("memory"), bool):
            s["memory"] = new["memory"]
        if isinstance(new.get("live_data"), bool):
            s["live_data"] = new["live_data"]
        # Free text: squeeze extra whitespace into single spaces and cut to the allowed length.
        if isinstance(new.get("custom_instructions"), str):
            s["custom_instructions"] = " ".join(new["custom_instructions"].split())[:app_skills.MAX_CUSTOM]
        if isinstance(new.get("connected_apps"), bool):
            s["connected_apps"] = new["connected_apps"]
        if new.get("web_search") in lookup_auto.MODES:
            s["web_search"] = new["web_search"]
        # "What's new" and tour counters: only whole numbers (True/False count as ints in Python, so bool is excluded), clamped to a sane range.
        if isinstance(new.get("whats_new_seq"), int) and not isinstance(new.get("whats_new_seq"), bool):
            s["whats_new_seq"] = max(0, min(10 ** 6, new["whats_new_seq"]))
        if isinstance(new.get("tour_seen"), int) and not isinstance(new.get("tour_seen"), bool):
            n = max(0, min(1000, new["tour_seen"]))
            s["tour_seen"] = n
            if new.get("device") in ("desktop", "pwa", "mobile"):          # the tour shows once on each kind of device: a computer, the installed app, a phone's browser
                s["tour_devices"] = dict(s.get("tour_devices") or {}, **{new["device"]: n})
        if isinstance(new.get("vryx_tour_seen"), int) and not isinstance(new.get("vryx_tour_seen"), bool):     # the VryxCode tour: the version last seen
            s["vryx_tour_seen"] = max(0, min(1000, new["vryx_tour_seen"]))
        # Remember the last 50 model tours seen: drop the id if it is already there, add it at the end, keep the final 50.
        mid = new.get("model_tour_seen")
        if isinstance(mid, str) and mid in {m["id"] for m in self.manifest["models"]}:   # a model's welcome tour, seen once (only real model ids are kept)
            seen = [x for x in (s.get("model_tours_seen") or []) if x != mid]
            s["model_tours_seen"] = (seen + [mid])[-50:]
        # Store the complete settings for this person and write the file.
        self.settings[user] = s
        self._save_settings()
        return s

    # ---- the numbers on screen
    def usage_snapshot(self, who, model, effort):
        """The usage numbers for the bar on screen (how much of the allowance is used) for this person, model and effort level."""
        # Usage is counted per model name in lower case ("flare" is the default when no model is given).
        key = model["name"].lower() if model else "flare"
        snap = self.limiter.snapshot(who["user"], key, effort, self.clock(), real=self.flags.on("chat_fixes", who))
        # Rename the "by_model" entry to "models", which is the name the screen expects.
        snap["models"] = snap.pop("by_model")
        return snap
