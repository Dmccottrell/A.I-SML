"""
pin_update_keys.py - run ONCE on the PC that runs the chat server. It teaches the software update (Admin > PC > Software update) which signing key to trust, so an
update is installed only when its newest commit was signed by that key, over the project's own https address (app/update_verify.py explains the whole check).

    python scripts/security/pin_update_keys.py                  pin GitHub's signing key (it signs every squash merge made on github.com), in "warn" mode
    python scripts/security/pin_update_keys.py --mode enforce   the same, but an update that fails the check is refused
    python scripts/security/pin_update_keys.py --key-file my_key.asc --accept-fingerprint <40 hex>     pin your own key instead (or as well)

What it does, step by step:
  1. downloads GitHub's public signing key from https://github.com/web-flow.gpg (a certificate-checked https connection);
  2. reads its fingerprint with gpg and REFUSES it unless it ends with GitHub's published key id (4AEE18F83AFDEB23), so a swapped download is caught;
  3. imports it into a keyring that holds only this key (`.emvryx/update_gpg`), never into your personal one;
  4. writes `.emvryx/update_trust.json` with the full fingerprint, the pinned repository address and the mode.
The trust file lives in the data folder, is not in the repository, and an update never changes it. Needs gpg (it comes with Git for Windows).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir))
WEB_FLOW_URL = "https://github.com/web-flow.gpg"
WEB_FLOW_KEY_ID = "4AEE18F83AFDEB23"                     # GitHub's published id of the key that signs commits made through its website
REMOTE = "https://github.com/Dmccottrell/A.I-SML.git"


def fingerprints(gpg, key_text):
    """The fingerprints (primary and sub keys) of an armored public key, read by gpg without importing it anywhere."""
    p = subprocess.run([gpg, "--batch", "--with-colons", "--show-keys", "--fingerprint"], input=key_text, text=True, capture_output=True)
    return [l.split(":")[9].upper() for l in p.stdout.splitlines() if l.startswith("fpr:")] if p.returncode == 0 else []


def main(argv=None, download=None, out=print, root=ROOT):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=("warn", "enforce"), default="warn")
    ap.add_argument("--key-file", help="an armored public key file to pin instead of GitHub's (your own signing key)")
    ap.add_argument("--accept-fingerprint", help="with --key-file: the full 40-character fingerprint you checked yourself")
    ap.add_argument("--remote", default=REMOTE)
    ap.add_argument("--data", default=os.path.join(root, ".emvryx"), help="the server's data folder")
    a = ap.parse_args(argv)
    gpg = shutil.which("gpg")
    if not gpg:
        out("gpg was not found. Install Git for Windows (it includes gpg) or GnuPG, then run this again.")
        return 2
    if a.key_file:
        with open(a.key_file, encoding="utf-8") as f:
            key = f.read()
        found = fingerprints(gpg, key)
        want = (a.accept_fingerprint or "").replace(" ", "").upper()
        if not re.fullmatch(r"[0-9A-F]{40}", want) or want not in found:
            out("The key's fingerprints are: " + ", ".join(found or ["(none read)"]) + "\nRun again with --accept-fingerprint set to the full 40 characters of the one YOU trust.")
            return 2
    else:
        key = (download or (lambda url: urllib.request.urlopen(url, timeout=30).read().decode()))(WEB_FLOW_URL)
        found = fingerprints(gpg, key)
        if not any(f.endswith(WEB_FLOW_KEY_ID) for f in found):
            out(f"GitHub's key was expected to have the id {WEB_FLOW_KEY_ID} but the download has {', '.join(found) or 'no readable key'}. Nothing was pinned.")
            return 1
        want = next(f for f in found if f.endswith(WEB_FLOW_KEY_ID))
    home = os.path.join(a.data, "update_gpg")
    os.makedirs(home, mode=0o700, exist_ok=True)
    subprocess.run([gpg, "--homedir", home, "--batch", "--import"], input=key, text=True, check=True, capture_output=True)
    trust = os.path.join(a.data, "update_trust.json")
    with open(trust, "w", encoding="utf-8") as f:
        json.dump({"mode": a.mode, "remote": a.remote, "gnupghome": home, "fingerprints": [want]}, f, indent=2)
    out(f"Pinned key {want}\nMode: {a.mode}\nRepository: {a.remote}\nWritten: {trust}\nTry it: Admin > PC > Software update > Check for updates shows the result of the check.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
