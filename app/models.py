"""
models.py - The model list for the app's "Select model" sheet (models.json).

WHAT THIS FILE DOES
    One file, models.json, lists every model the app knows: name, version, where it runs, file, size, memory needed,
    status. Adding a new model is adding a line. This file reads and checks the list, and turns it into what the
    picker shows (docs/APP_SPEC.md, "Model picker"):

      cards    one per NAME (Flare, Equinox, Solstice, Apogee), the newest the person may use (newest generation first, then the version:
               generation 1 = trained from scratch here, 2 = built on an open base, so Flare 2.5 is newer than Flare 2)
      other    "Other models": older versions of any name, kept only up to `keep_latest_per_name` per name
               (plus anything pinned); the rest are offered for deletion

    A model that can't run on this device is still listed, greyed out, with the reason ("needs 4 GB of memory").
    Status: stable = everyone, beta = the beta list (same access list as the skill packs, skills.py), planned = not
    built yet (never shown), off = hidden, preview = built but only admins see it until it is published (model_publish.py). The owner (you, on your own PC) sees everything that exists.

Usage:  python app/models.py                    (prints the picker for the owner on this PC)
        python app/models.py --ram 3 --user sam
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import argparse
import json
import os

NAMES = ("Ember", "Flare", "Equinox", "Solstice", "Apogee")
WHERE = ("device", "online")
STATUS = ("stable", "beta", "planned", "off", "preview")
REQUIRED = ("id", "name", "version", "where", "file", "size_mb", "min_ram_gb", "context", "status")
MANIFEST_PATH = "models.json"


def load_manifest(path=MANIFEST_PATH, include_archived=False):
    """A model marked "archived" in models.json is retired from the lineup: its files are kept, but the app treats it as off (never listed, never chosen)
    unless include_archived is set (used by the tests, which run the fake backends on the small old models)."""
    with open(path, encoding="utf-8") as f:
        manifest = json.load(f)
    problems = check(manifest)
    if problems:
        raise ValueError("models.json: " + "; ".join(problems))
    if not include_archived:
        for m in manifest["models"]:
            if m.get("archived"):
                m["status"] = "off"
    manifest.setdefault("keep_latest_per_name", 2)
    return manifest


def check(manifest):
    """A list of problems with the manifest (empty means fine)."""
    problems, seen = [], set()
    for m in manifest.get("models", []):
        missing = [k for k in REQUIRED if k not in m]
        if missing:
            problems.append(f"{m.get('id', '?')}: missing {', '.join(missing)}")
            continue
        if m["id"] in seen:
            problems.append(f"{m['id']}: listed twice")
        seen.add(m["id"])
        if m["name"] not in NAMES:
            problems.append(f"{m['id']}: name must be one of {', '.join(NAMES)}")
        if m["where"] not in WHERE:
            problems.append(f"{m['id']}: where must be device or online")
        if m["status"] not in STATUS:
            problems.append(f"{m['id']}: status must be one of {', '.join(STATUS)}")
    return problems


def may_see(model, user, beta_users, owner="owner"):
    if model["status"] in ("off", "planned"):
        return False
    return user == owner or model["status"] == "stable" or (model["status"] == "beta" and user in beta_users)


def availability(model, ram_gb=None, downloaded=(), pc_online=True):
    """The badge for a card: (state, text). state is one of ready, download, online, offline, too_big."""
    if model["where"] == "online":
        return ("online", "Online: your PC") if pc_online else ("offline", "Needs your PC to be on")
    if ram_gb is not None and ram_gb < model["min_ram_gb"]:
        return "too_big", f"Needs {model['min_ram_gb']} GB of memory"
    if model["id"] in downloaded:
        return "ready", "On this device"
    return "download", f"Not downloaded ({model['size_mb']} MB)"


def catalog(manifest, user="owner", beta_users=(), ram_gb=None, downloaded=(), pc_online=True):
    """{"cards": [...], "other": [...], "delete": [ids]} for the picker. Cards are in the order of NAMES."""
    keep = manifest.get("keep_latest_per_name", 2)
    visible = [m for m in manifest["models"] if may_see(m, user, beta_users)]
    cards, other, delete = [], [], []
    for name in NAMES:
        versions = sorted((m for m in visible if m["name"] == name), key=lambda m: (-m.get("generation", 1), -m["version"]))
        for rank, m in enumerate(versions):
            state, text = availability(m, ram_gb, downloaded, pc_online)
            entry = {**m, "state": state, "badge": text}
            if rank == 0:
                cards.append(entry)
            else:
                other.append({**entry, "older": True})
                if rank >= keep and not m.get("pinned") and m["id"] in downloaded:
                    delete.append(m["id"])               # a downloaded file past the retention rule: offer to remove it
    return {"cards": cards, "other": other, "delete": delete}


def main():
    p = argparse.ArgumentParser(description="Show the model picker as the app would")
    p.add_argument("--manifest", default=MANIFEST_PATH)
    p.add_argument("--user", default="owner")
    p.add_argument("--ram", type=float, default=None, help="this device's memory in GB (greys out models that need more)")
    p.add_argument("--downloaded", nargs="*", default=[], help="model ids whose files are on this device")
    a = p.parse_args()
    out = catalog(load_manifest(a.manifest), a.user, ram_gb=a.ram, downloaded=a.downloaded)
    print("Select model")
    for c in out["cards"]:
        print(f"  Emvryx {c['name']} {c['version']:g}   [{c['badge']}]\n      {c['tagline']}")
    if out["other"]:
        print("Other models")
        for c in out["other"]:
            print(f"  Emvryx {c['name']} {c['version']:g} (older)   [{c['badge']}]")
    if out["delete"]:
        print("Can be removed to save space:", ", ".join(out["delete"]))


if __name__ == "__main__":
    main()
