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

# The lists below define what a valid models.json entry may contain.
# NAMES = the model families a card can belong to; WHERE = runs on the phone ("device") or on the owner's PC ("online");
# STATUS = who may see a model (see the top of this file); REQUIRED = fields every entry must have; MANIFEST_PATH = where the list lives.
NAMES = ("Ember", "Flare", "Equinox", "Solstice", "Apogee")
WHERE = ("device", "online")
STATUS = ("stable", "beta", "planned", "off", "preview")
REQUIRED = ("id", "name", "version", "where", "file", "size_mb", "min_ram_gb", "context", "status")
MANIFEST_PATH = "models.json"
# Default sampling settings (how random the model's word choice is). temperature = randomness, top_k / top_p / min_p = only pick from the
# most likely words, presence_penalty / repeat_penalty = discourage repeating. A models.json entry can override any of these.
# Qwen's recommended settings for Qwen3.5, used by every version 3 model unless its models.json entry says otherwise:
QWEN35_SAMPLING = {"temperature": 0.7, "top_k": 20, "top_p": 0.8, "min_p": 0.0, "presence_penalty": 1.5, "repeat_penalty": 1.0, "repeat_last_n": 64}
QWEN35_SAMPLING_THINK = {"temperature": 1.0, "top_k": 20, "top_p": 0.95, "min_p": 0.0, "presence_penalty": 1.5, "repeat_penalty": 1.0}       # Deep, thinking


def load_manifest(path=MANIFEST_PATH, include_archived=False):
    """Read models.json and return it as a dict, after checking it with check() (raises ValueError listing the problems).
    Also fills in default settings for the newest models. Input: the file path and whether to keep retired models. Output: the manifest dict.

    A model marked "archived" in models.json is retired from the lineup: its files are kept, but the app treats it as off (never listed, never chosen)
    unless include_archived is set (used by the tests, which run the fake backends on the small old models)."""
    # Read the JSON file into a Python dict. utf-8 so non-English characters survive.
    with open(path, encoding="utf-8") as f:
        manifest = json.load(f)
    # Refuse to start with a broken list: better a clear error now than a confusing one when the picker opens.
    problems = check(manifest)
    if problems:
        raise ValueError("models.json: " + "; ".join(problems))
    # setdefault only fills a field when the entry has not set it, so the owner can always override. dict(...) makes a copy so models do not share one dict.
    for m in manifest["models"]:                    # every Emvryx 3 model (Qwen3.5 base) runs as Qwen3.5 is meant to run
        if m.get("open") and str(m.get("base", "")).startswith("Qwen3.5"):
            m.setdefault("think", "empty")          # it was trained with an empty thinking block after every question: the app must add it too
            m.setdefault("sampling", dict(QWEN35_SAMPLING))
            m.setdefault("sampling_think", dict(QWEN35_SAMPLING_THINK))
            m.setdefault("temperature_bounds", [0.2, 1.0])
    # Archived models are not deleted, just treated as "off" so the rest of the code never shows or picks them.
    if not include_archived:
        for m in manifest["models"]:
            if m.get("archived"):
                m["status"] = "off"
    # How many versions of each name to keep on the device before offering to delete older downloads (default 2).
    manifest.setdefault("keep_latest_per_name", 2)
    return manifest


def check(manifest):
    """A list of problems with the manifest (empty means fine)."""
    # problems collects messages; seen remembers ids already met so a duplicate id is caught.
    problems, seen = [], set()
    for m in manifest.get("models", []):
        # Every entry must have all REQUIRED fields; if not, report which are missing and skip the other checks for that entry.
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
    """True if this person may see this model. off/planned are never shown; the owner sees everything else; stable is for everyone;
    beta only for users in beta_users."""
    if model["status"] in ("off", "planned"):
        return False
    return user == owner or model["status"] == "stable" or (model["status"] == "beta" and user in beta_users)


def availability(model, ram_gb=None, downloaded=(), pc_online=True):
    """The badge for a card: (state, text). state is one of ready, download, online, offline, too_big."""
    # A model that runs on the owner's PC needs no download or memory on this device, only that the PC is on.
    if model["where"] == "online":
        return ("online", "Online: your PC") if pc_online else ("offline", "Needs your PC to be on")
    # Only judge memory when we know this device's RAM. Too little memory means the card is shown greyed out with the reason.
    if ram_gb is not None and ram_gb < model["min_ram_gb"]:
        return "too_big", f"Needs {model['min_ram_gb']} GB of memory"
    # Fits in memory: either the file is already here, or it still needs downloading (show its size).
    if model["id"] in downloaded:
        return "ready", "On this device"
    return "download", f"Not downloaded ({model['size_mb']} MB)"


def catalog(manifest, user="owner", beta_users=(), ram_gb=None, downloaded=(), pc_online=True):
    """{"cards": [...], "other": [...], "delete": [ids]} for the picker. Cards are in the order of NAMES."""
    # keep = how many versions per name we are willing to leave on the device.
    keep = manifest.get("keep_latest_per_name", 2)
    # Only models this person is allowed to see take part.
    visible = [m for m in manifest["models"] if may_see(m, user, beta_users)]
    cards, other, delete = [], [], []
    # One card per name. Sort newest first: higher generation wins, then higher version (the minus signs flip the order so bigger comes first).
    for name in NAMES:
        versions = sorted((m for m in visible if m["name"] == name), key=lambda m: (-m.get("generation", 1), -m["version"]))
        # rank 0 is the newest version of this name; it becomes the card. The others go under "Other models".
        for rank, m in enumerate(versions):
            # Work out the badge (ready / download / too_big ...) and copy the model's fields plus state and badge into a new dict.
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
    """Command-line helper: print the model picker as text so the owner can check what the app would show.
    Flags: --manifest (file), --user, --ram (GB), --downloaded (ids already on the device)."""
    p = argparse.ArgumentParser(description="Show the model picker as the app would")
    p.add_argument("--manifest", default=MANIFEST_PATH)
    p.add_argument("--user", default="owner")
    p.add_argument("--ram", type=float, default=None, help="this device's memory in GB (greys out models that need more)")
    p.add_argument("--downloaded", nargs="*", default=[], help="model ids whose files are on this device")
    # Read the flags typed on the command line, then build and print the same lists the app's picker uses.
    a = p.parse_args()
    out = catalog(load_manifest(a.manifest), a.user, ram_gb=a.ram, downloaded=a.downloaded)
    print("Select model")
    for c in out["cards"]:
        # `:g` prints 3.0 as 3 and 2.5 as 2.5.
        print(f"  Emvryx {c['name']} {c['version']:g}   [{c['badge']}]\n      {c['tagline']}")
    if out["other"]:
        print("Other models")
        for c in out["other"]:
            print(f"  Emvryx {c['name']} {c['version']:g} (older)   [{c['badge']}]")
    if out["delete"]:
        print("Can be removed to save space:", ", ".join(out["delete"]))


# Run main() only when this file is started directly (python app/models.py), not when another file imports it.
if __name__ == "__main__":
    main()
