"""
state_apps.py - AppState's connected-apps part: the catalog, apps the owner adds, and their rate limits.

WHERE IT FITS
    AppState (the server's big shared object) is built from mixin classes, one per state_*.py file. A mixin's methods are mixed into AppState,
    so `self` here is the whole AppState (self.cfg, self.manifest, self.users, self.usage ... come from other parts).
    "Apps" here are outside programs that call Emvryx with their own key; each is stored as a special user whose name starts with "app-".
    This file also builds the model picker ("catalog") that each person sees.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import time
import models as M
from app_shared import API_KEY_PREFIX, APP_PREFIX


class StateApps:
    """Connected apps and the apps the owner adds."""

    # ---- models
    def _card(self, m, who):
        """One model as the picker shows it. state: ready | locked | too_big | missing | soon.

        `m` is a model entry from the manifest (the list of models); `who` is the signed-in person. Returns a copy with "state" and "badge"
        (the label on the card) added, so the screen can grey out models this person cannot use right now.
        """
        # Which models this person's plan allows: the string "all", or a list of lower-case names.
        plan = self.cfg["tiers"][who["tier"]]["models"]
        # Work on a copy so the shared manifest is never changed. Then pick the FIRST reason the model cannot be used, in this order:
        # not released yet, not in the plan, too little memory, not installed, otherwise it is ready.
        m = dict(m)
        if m["status"] == "planned":
            m["state"], m["badge"] = "soon", "Coming soon"
        elif not who["owner"] and plan != "all" and m["name"].lower() not in plan:
            m["state"], m["badge"] = "locked", "Not in your plan"
        elif self.ram_gb < m["min_ram_gb"]:
            m["state"], m["badge"] = "too_big", f"Needs {m['min_ram_gb']} GB of memory"
        elif self.runner and not self.runner.available(m["id"]):
            m["state"], m["badge"] = "missing", "Not on this computer" if self.runner.bin else "llama-server not found"
        else:
            m["state"], m["badge"] = "ready", "Preview" if m.get("preview") else "Beta" if m["status"] == "beta" else "Ready"
        # "older" is set True later for old versions listed under "other".
        m["older"] = False
        if m.get("preview") and not who.get("admin"):              # a model's "What's new" goes out only when the owner publishes the model
            m.pop("whats_new", None)
            m.pop("tour", None)
        return m

    def catalog(self, who):
        """The picker: one card per name (Flare, Equinox, Solstice, Apogee) with its newest usable version, and
        "other" with the older versions that can still be chosen (Flare 2.5, ...).

        `who` decides what is shown (admins also see unreleased "preview" models). Returns {"cards": [...], "other": [...]}.
        """
        cards, other = [], []
        self.models_pub.run_due(self.manifest)                                  # a scheduled model that is due goes live now
        # How many older versions of each model to keep in the "other" list.
        keep = int(self.manifest.get("keep_older_versions", 6))
        for name in M.NAMES:
            # All versions of this model name, with their status as it is NOW (a scheduled release may have just gone live) and whether
            # they are still an unreleased preview.
            eff = [dict(m, status=self.models_pub.status_of(m), preview=(m["status"] == "preview" and not self.models_pub.live(m["id"]))) for m in self.manifest["models"] if m["name"] == name]
            # Hide switched-off models (and previews, unless an admin is looking); newest version first (the minus sign reverses the sort).
            versions = sorted((m for m in eff if m["status"] != "off" and (not m["preview"] or who.get("admin"))), key=lambda m: -m["version"])
            if not versions:
                continue
            # The card shows the newest version that can actually be used (a "planned" one is only a teaser, used if nothing else exists).
            usable = [m for m in versions if m["status"] != "planned"]
            top = (usable or versions)[0]
            cards.append(self._card(top, who))
            # The next `keep` usable versions go in the "older" list.
            for m in usable[1:1 + keep]:
                c = self._card(m, who)
                c["older"] = True
                other.append(c)
        return {"cards": cards, "other": other}

    def add_app(self, slug, display, tier="free", instructions="", rpm=20, model="flare", effort="balanced", lookup="none"):
        """Make an app and return its key (shown once, never stored). The app's name in the logs is app-<slug>.

        Arguments: `slug` short name, `display` friendly name, `tier` plan, `instructions` text always given to the model, `rpm` allowed
        requests per minute, `model`/`effort` defaults, `lookup` web-lookup mode. Raises ValueError with a sentence if something is invalid.
        """
        slug = str(slug or "").strip().lower()
        # APP_SLUG is a regex (text pattern) defined on AppState; fullmatch means the whole slug must fit it.
        if not self.APP_SLUG.fullmatch(slug):
            raise ValueError("an app's name is lowercase letters, numbers and - (2 to 28 characters), for example finance")
        if lookup not in self.LOOKUP_MODES:
            raise ValueError("lookup is none, wikipedia or auto")
        # An app is stored as an ordinary user named "app-<slug>", with a key that starts with API_KEY_PREFIX. add_user gives None if it exists.
        name = APP_PREFIX + slug
        key = self.add_user(name, tier, key_prefix=API_KEY_PREFIX)
        if key is None:
            raise ValueError("an app with that name already exists")
        # Save the app's settings on its user record. Every text is trimmed (extra whitespace squeezed to single spaces) and cut to a maximum
        # length; rpm is forced into 1..600; an unknown effort falls back to "balanced".
        self._set_fields(name, app=True, app_name=(str(display or slug).strip() or slug)[:60], app_instructions=" ".join(str(instructions or "").split())[:2000],
                         app_rpm=max(1, min(600, int(rpm))), app_model=str(model or "flare")[:40], app_effort=effort if effort in ("auto", "quick", "balanced", "deep") else "balanced",
                         app_enabled=True, app_created=int(time.time()), app_lookup=lookup)
        # Apps start with the personal features off: no memory, live data, connected apps, web search or custom instructions.
        self.put_settings(name, {"memory": False, "live_data": False, "connected_apps": False, "web_search": "none", "custom_instructions": ""})
        self.auth.event("app_added", name, "", f"plan {tier}")
        return key

    def app_record(self, name):
        """The stored record of the app with this user name, or None if that name is missing or is a normal person rather than an app."""
        rec = self.user_record(name)
        return rec if rec and rec.get("app") else None

    def update_app(self, name, **ch):
        """Change an app's settings. Only the keys present in `ch` (display, instructions, rpm, model, effort, enabled, lookup, plan) are changed.

        Uses the same trimming and limits as add_app. Raises ValueError for an unknown app or a bad lookup mode.
        """
        rec = self.app_record(name)
        if not rec:
            raise ValueError("no such app")
        # Gather the changes first, then save them all together at the end.
        fields = {}
        if "display" in ch:
            fields["app_name"] = (str(ch["display"]).strip() or name)[:60]
        if "instructions" in ch:
            fields["app_instructions"] = " ".join(str(ch["instructions"]).split())[:2000]
        if "rpm" in ch:
            fields["app_rpm"] = max(1, min(600, int(ch["rpm"])))
        if "model" in ch:
            fields["app_model"] = str(ch["model"])[:40]
        if "effort" in ch and ch["effort"] in ("auto", "quick", "balanced", "deep"):
            fields["app_effort"] = ch["effort"]
        if "enabled" in ch:
            fields["app_enabled"] = bool(ch["enabled"])
        if "lookup" in ch:
            if ch["lookup"] not in self.LOOKUP_MODES:
                raise ValueError("lookup is none, wikipedia or auto")
            fields["app_lookup"] = ch["lookup"]
            self.put_settings(name, {"web_search": self.LOOKUP_MODES[ch["lookup"]]})
        if "plan" in ch:
            self.set_plan(name, ch["plan"])
        if fields:
            self._set_fields(name, **fields)

    def apps(self):
        """The list of apps for the admin screen (sorted by slug), each a dict of its settings plus usage: last time used and call count."""
        out = []
        for u in self.users.values():
            # Skip normal people and the server's own internal apps.
            if not u.get("app") or u.get("internal"):
                continue
            row = self.usage.get_user(u["user"])
            out.append({"name": u["user"], "slug": u["user"][len(APP_PREFIX):], "display": u.get("app_name") or u["user"], "plan": row["tier"], "enabled": u.get("app_enabled", True),
                        "instructions": u.get("app_instructions", ""), "rpm": u.get("app_rpm", 20), "model": u.get("app_model", "flare"), "effort": u.get("app_effort", "balanced"),
                        "lookup": u.get("app_lookup", "none"), "created": u.get("app_created"), "last_used": u.get("app_last_used"), "calls": u.get("app_calls", 0)})
        return sorted(out, key=lambda a: a["slug"])

    def app_rate_ok(self, name, rpm, now=None):
        """A sliding minute per app: (True, 0) if this call may go ahead (and records it), else (False, seconds to wait).

        "Sliding window": we remember the time of each call in the last 60 seconds and allow at most `rpm` (requests per minute) of them.
        `now` can be passed in by tests.
        """
        now = time.time() if now is None else now
        with self.lock:
            # Keep only the calls from the last 60 seconds.
            hits = [t for t in self._api_hits.get(name, []) if now - t < 60]
            # Over the limit: say how long until the oldest call leaves the window (+1 to round up, never less than 1 second).
            if len(hits) >= rpm:
                self._api_hits[name] = hits
                return False, max(1, int(60 - (now - hits[0])) + 1)
            hits.append(now)
            self._api_hits[name] = hits
        return True, 0

    def note_app_call(self, name):
        """Record that the app was just used: set its last-used time and add one to its call counter."""
        rec = self.user_record(name)
        if rec:
            self._set_fields(name, app_last_used=int(time.time()), app_calls=int(rec.get("app_calls", 0)) + 1)
