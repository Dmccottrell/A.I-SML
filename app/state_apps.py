"""
state_apps.py - AppState's connected-apps part: the catalog, apps the owner adds, and their rate limits.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import time
import models as M
from app_shared import API_KEY_PREFIX, APP_PREFIX


class StateApps:
    """Connected apps and the apps the owner adds."""

    # ---- models
    def _card(self, m, who):
        """One model as the picker shows it. state: ready | locked | too_big | missing | soon."""
        plan = self.cfg["tiers"][who["tier"]]["models"]
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
        m["older"] = False
        if m.get("preview") and not who.get("admin"):              # a model's "What's new" goes out only when the owner publishes the model
            m.pop("whats_new", None)
            m.pop("tour", None)
        return m

    def catalog(self, who):
        """The picker: one card per name (Flare, Equinox, Solstice, Apogee) with its newest usable version, and
        "other" with the older versions that can still be chosen (Flare 2.5, ...)."""
        cards, other = [], []
        self.models_pub.run_due(self.manifest)                                  # a scheduled model that is due goes live now
        keep = int(self.manifest.get("keep_older_versions", 6))
        for name in M.NAMES:
            eff = [dict(m, status=self.models_pub.status_of(m), preview=(m["status"] == "preview" and not self.models_pub.live(m["id"]))) for m in self.manifest["models"] if m["name"] == name]
            versions = sorted((m for m in eff if m["status"] != "off" and (not m["preview"] or who.get("admin"))), key=lambda m: -m["version"])
            if not versions:
                continue
            usable = [m for m in versions if m["status"] != "planned"]
            top = (usable or versions)[0]
            cards.append(self._card(top, who))
            for m in usable[1:1 + keep]:
                c = self._card(m, who)
                c["older"] = True
                other.append(c)
        return {"cards": cards, "other": other}

    def add_app(self, slug, display, tier="free", instructions="", rpm=20, model="flare", effort="balanced", lookup="none"):
        """Make an app and return its key (shown once, never stored). The app's name in the logs is app-<slug>."""
        slug = str(slug or "").strip().lower()
        if not self.APP_SLUG.fullmatch(slug):
            raise ValueError("an app's name is lowercase letters, numbers and - (2 to 28 characters), for example finance")
        if lookup not in self.LOOKUP_MODES:
            raise ValueError("lookup is none, wikipedia or auto")
        name = APP_PREFIX + slug
        key = self.add_user(name, tier, key_prefix=API_KEY_PREFIX)
        if key is None:
            raise ValueError("an app with that name already exists")
        self._set_fields(name, app=True, app_name=(str(display or slug).strip() or slug)[:60], app_instructions=" ".join(str(instructions or "").split())[:2000],
                         app_rpm=max(1, min(600, int(rpm))), app_model=str(model or "flare")[:40], app_effort=effort if effort in ("auto", "quick", "balanced", "deep") else "balanced",
                         app_enabled=True, app_created=int(time.time()), app_lookup=lookup)
        self.put_settings(name, {"memory": False, "live_data": False, "connected_apps": False, "web_search": "none", "custom_instructions": ""})
        self.auth.event("app_added", name, "", f"plan {tier}")
        return key

    def app_record(self, name):
        rec = self.user_record(name)
        return rec if rec and rec.get("app") else None

    def update_app(self, name, **ch):
        rec = self.app_record(name)
        if not rec:
            raise ValueError("no such app")
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
        out = []
        for u in self.users.values():
            if not u.get("app") or u.get("internal"):
                continue
            row = self.usage.get_user(u["user"])
            out.append({"name": u["user"], "slug": u["user"][len(APP_PREFIX):], "display": u.get("app_name") or u["user"], "plan": row["tier"], "enabled": u.get("app_enabled", True),
                        "instructions": u.get("app_instructions", ""), "rpm": u.get("app_rpm", 20), "model": u.get("app_model", "flare"), "effort": u.get("app_effort", "balanced"),
                        "lookup": u.get("app_lookup", "none"), "created": u.get("app_created"), "last_used": u.get("app_last_used"), "calls": u.get("app_calls", 0)})
        return sorted(out, key=lambda a: a["slug"])

    def app_rate_ok(self, name, rpm, now=None):
        """A sliding minute per app: True if this call may go ahead (and records it), else the seconds to wait."""
        now = time.time() if now is None else now
        with self.lock:
            hits = [t for t in self._api_hits.get(name, []) if now - t < 60]
            if len(hits) >= rpm:
                self._api_hits[name] = hits
                return False, max(1, int(60 - (now - hits[0])) + 1)
            hits.append(now)
            self._api_hits[name] = hits
        return True, 0

    def note_app_call(self, name):
        rec = self.user_record(name)
        if rec:
            self._set_fields(name, app_last_used=int(time.time()), app_calls=int(rec.get("app_calls", 0)) + 1)
