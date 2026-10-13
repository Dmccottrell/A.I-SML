"""
state_settings.py - AppState's per-person data: chats store, documents, notes, memory, settings and usage numbers.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import json
import app_engine as E
import chat_polish
import app_skills
import documents
import lookup_auto
import saved_notes
import user_memory


class StateSettings:
    """What is kept for each person: chats, notes, memory, settings."""

    # ---- chats and settings, per person
    def store(self, user):
        with self.lock:
            if user not in self.stores:
                path = os.path.join(self.data_dir, f"chats-{user}.db") if self.data_dir else ":memory:"
                self.stores[user] = E.ChatStore(path)
            return self.stores[user]

    def docs_for(self, user):
        with self.lock:
            if user not in self.libraries:
                path = os.path.join(self.data_dir, f"docs-{user}.db") if self.data_dir else ":memory:"
                self.libraries[user] = documents.Library(path, clock=self.clock)
            return self.libraries[user]

    def saved_for(self, user):
        with self.lock:
            if user not in self.saved:
                path = os.path.join(self.data_dir, f"saved-{user}.db") if self.data_dir else ":memory:"
                self.saved[user] = saved_notes.SavedNotes(path)
            return self.saved[user]

    def memory_for(self, user):
        with self.lock:
            if user not in self.memories:
                path = os.path.join(self.data_dir, f"memory-{user}.db") if self.data_dir else ":memory:"
                self.memories[user] = user_memory.Memory(path)
            return self.memories[user]

    def remember_lookup(self, user, chat_id, message_id, question, found):
        """Keep what an answer was written from (the last 200), so a thumbs up can save it. Private chats keep nothing."""
        if chat_id < 0 or not found["used"]:
            return
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
            if isinstance(data, dict):
                self.settings = {k: v for k, v in data.items() if isinstance(v, dict)}
        except (OSError, ValueError):
            pass

    def _save_settings(self):
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
        s = {"window_mode": "everyday", "show_tokens": False, "web_search": "auto", "memory": True, "thinking_pause": "short", "live_data": True, "connected_apps": True, "tour_seen": 0, "tour_devices": {}, "whats_new_seq": -1}
        s.update(self.settings.get(user, {}))
        return s

    def put_settings(self, user, new):
        s = self.get_settings(user)
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
        if isinstance(new.get("custom_instructions"), str):
            s["custom_instructions"] = " ".join(new["custom_instructions"].split())[:app_skills.MAX_CUSTOM]
        if isinstance(new.get("connected_apps"), bool):
            s["connected_apps"] = new["connected_apps"]
        if new.get("web_search") in lookup_auto.MODES:
            s["web_search"] = new["web_search"]
        if isinstance(new.get("whats_new_seq"), int) and not isinstance(new.get("whats_new_seq"), bool):
            s["whats_new_seq"] = max(0, min(10 ** 6, new["whats_new_seq"]))
        if isinstance(new.get("tour_seen"), int) and not isinstance(new.get("tour_seen"), bool):
            n = max(0, min(1000, new["tour_seen"]))
            s["tour_seen"] = n
            if new.get("device") in ("desktop", "pwa", "mobile"):          # the tour shows once on each kind of device: a computer, the installed app, a phone's browser
                s["tour_devices"] = dict(s.get("tour_devices") or {}, **{new["device"]: n})
        self.settings[user] = s
        self._save_settings()
        return s

    # ---- the numbers on screen
    def usage_snapshot(self, who, model, effort):
        key = model["name"].lower() if model else "flare"
        snap = self.limiter.snapshot(who["user"], key, effort, self.clock())
        snap["models"] = snap.pop("by_model")
        return snap
