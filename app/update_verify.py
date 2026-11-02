"""
update_verify.py - proves that the code an administrator is about to pull onto the PC really is what the project published, before it is installed.

WHAT THIS FILE DOES
    "Update now" (Admin > PC > Software update, see updater.py) pulls the newest `main` from GitHub onto the PC and restarts the server. That server holds
    everybody's chats and keys, so the update is the most dangerous door into it. Before the update is applied, this file checks three things, all of which
    must hold, and all of which are decided by a small file that lives ONLY on the PC (`.emvryx/update_trust.json`, never in the repository and never changed
    by an update), so whoever controls what is in the repository cannot change the rules:

      1. the connection is safe: the `origin` address is exactly the pinned one (https, the project's own repository), and nothing turns off the checking of
         the certificate (`GIT_SSL_NO_VERIFY`, `http.sslVerify=false`). This is what stops a man in the middle who points git at a copy of their own;
      2. the newest commit carries a valid signature (GPG, the kind GitHub puts on every squash merge it makes, or a person's own key), checked against a
         keyring that holds only the public keys the owner pinned, with git's own `verify-commit`;
      3. the key that made the signature is one of the pinned fingerprints (40 hexadecimal characters, the full fingerprint, not the short id).

    The result is a plain dict the screen can show. Modes (`mode` in the trust file):
      "off"      no trust file: nothing is checked and updates work as before (the default until the owner pins keys);
      "warn"     the check runs and is shown on the screen, but an update is still allowed;
      "enforce"  an update whose newest commit fails any check is refused, and nothing is changed.

    What this does not do, honestly: a signature proves who signed, not that the change is good. If someone with permission to merge into `main` on GitHub
    is tricked or hacked, GitHub will sign their merge too. That risk is handled on GitHub (a protected `main`, required reviews, two-step sign-in), see
    docs/DEVSECOPS.md. This file protects the step between GitHub and the PC.

    Setting it up is one command (scripts/security/pin-update-keys.py), which downloads GitHub's signing key over https, shows its fingerprint to compare with
    GitHub's documentation, and only then writes the trust file.
"""
import json
import os
import re
import subprocess

TRUST_FILE = "update_trust.json"          # inside the PC's data folder (.emvryx), next to the chats, not in the repository
MODES = ("off", "warn", "enforce")
FPR = re.compile(r"[0-9A-Fa-f]{40}")
GIT_TIMEOUT = 60


def trust_path(root):
    """Where the trust file is: the path in EMVRYX_UPDATE_TRUST if set, otherwise <project folder>/.emvryx/update_trust.json."""
    return os.environ.get("EMVRYX_UPDATE_TRUST") or os.path.join(root, ".emvryx", TRUST_FILE)


def load_trust(root):
    """The trust settings as a dict {"mode", "remote", "gnupghome", "fingerprints"}, or None when there is no file (mode off). A file that cannot be read or is
    not valid is treated as mode "enforce" with no allowed keys, so a damaged file can only make updates stricter, never looser."""
    path = trust_path(root)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        mode = raw.get("mode", "enforce")
        fprs = [x.upper() for x in raw.get("fingerprints", []) if isinstance(x, str) and FPR.fullmatch(x)]
        home = raw.get("gnupghome") or os.path.join(".emvryx", "update_gpg")
        if not os.path.isabs(home):
            home = os.path.join(root, home)
        return {"mode": mode if mode in MODES else "enforce", "remote": str(raw.get("remote", "")), "gnupghome": home, "fingerprints": fprs}
    except (OSError, ValueError, AttributeError):
        return {"mode": "enforce", "remote": "", "gnupghome": "", "fingerprints": [], "broken": True}


def normalize_remote(url):
    """A repository address in one form so two spellings compare equal: lower case, no trailing slash, no ".git"."""
    u = (url or "").strip().lower().rstrip("/")
    return u[:-4] if u.endswith(".git") else u


def _run(root, args, env, runner):
    """Run `git <args>`; returns (exit code, stdout, stderr). A missing git or a timeout is a failure, never an exception."""
    try:
        p = runner(["git", *args], cwd=root, capture_output=True, text=True, timeout=GIT_TIMEOUT, stdin=subprocess.DEVNULL, env=env)
    except (OSError, subprocess.SubprocessError) as e:
        return 127, "", str(e)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def signer_from_status(stderr):
    """From git's `--raw` GnuPG status lines: (good, fingerprints). `good` is True only when there is a GOODSIG and a VALIDSIG (a bad, expired, revoked or
    unknown-key signature gives ERRSIG, BADSIG, EXPKEYSIG or REVKEYSIG instead). `fingerprints` are the signing key's and its primary key's, in capitals."""
    lines = [l.replace("[GNUPG:] ", "", 1) for l in (stderr or "").splitlines() if l.startswith("[GNUPG:] ")]
    bad = any(l.startswith(("BADSIG", "ERRSIG", "EXPKEYSIG", "EXPSIG", "REVKEYSIG", "NO_PUBKEY")) for l in lines)
    good = any(l.startswith("GOODSIG") for l in lines) and not bad
    fprs = []
    for l in lines:
        if l.startswith("VALIDSIG"):
            parts = l.split()
            fprs += [p.upper() for p in (parts[1:2] + parts[-1:]) if FPR.fullmatch(p)]
    return good and bool(fprs), fprs


def verify(root, sha, runner=subprocess.run):
    """Check commit `sha` (the newest one on GitHub's main) against the trust file. Returns
    {"mode", "ok", "signer", "reason", "checks"}: ok is None when mode is off, otherwise True or False; `checks` lists what passed or failed in plain words."""
    trust = load_trust(root)
    if trust is None:
        return {"mode": "off", "ok": None, "signer": "", "reason": "", "checks": []}
    checks, problems = [], []

    # 1. the connection: the pinned address, and the certificate check left on
    if trust.get("broken"):
        problems.append("the trust file on this computer cannot be read")
    # Two views of the address: what is written in the repository's config, and the address git really connects to (after any `url.<x>.insteadOf` rewriting in
    # a config file or the environment, which could quietly redirect a fetch to somebody else's copy). Both must be the pinned one.
    rc, written, _ = _run(root, ["config", "--get", "remote.origin.url"], None, runner)
    rc, effective, _ = _run(root, ["ls-remote", "--get-url", "origin"], None, runner)
    pinned = normalize_remote(trust["remote"])
    if not pinned.startswith("https://"):
        problems.append("the trust file does not pin an https address")
    elif normalize_remote(written) != pinned:
        problems.append("this computer's origin is " + (written or "unknown") + ", not the pinned " + trust["remote"])
    elif normalize_remote(effective) != pinned:
        problems.append("git is redirected to " + (effective or "another address") + " instead of the pinned " + trust["remote"])
    else:
        checks.append("origin is the pinned https address")
    rc, ssl, _ = _run(root, ["config", "--get", "http.sslVerify"], None, runner)
    if ssl.lower() == "false" or os.environ.get("GIT_SSL_NO_VERIFY"):
        problems.append("the certificate check is switched off for git on this computer")
    else:
        checks.append("the certificate check is on")

    # 2 and 3. the signature, made by a pinned key, read with git's own verify-commit against the pinned keyring only
    signer = ""
    if not trust["fingerprints"]:
        problems.append("no signing key is pinned")
    elif not trust["gnupghome"] or not os.path.isdir(trust["gnupghome"]):
        problems.append("the pinned keyring is missing")
    elif not re.fullmatch(r"[0-9a-f]{40}", str(sha or "")):
        problems.append("the newest change has no full id to check")
    else:
        env = dict(os.environ, GNUPGHOME=trust["gnupghome"])
        rc, _, err = _run(root, ["-c", "gpg.format=openpgp", "-c", "gpg.program=gpg", "verify-commit", "--raw", sha], env, runner)
        good, fprs = signer_from_status(err)
        match = [f for f in fprs if f in trust["fingerprints"]]
        if not good:
            problems.append("the newest change has no valid signature from a pinned key")
        elif not match:
            problems.append("the newest change is signed by a key that is not pinned")
        else:
            signer = match[0]
            checks.append("signed by pinned key " + signer[-16:])
    ok = not problems
    return {"mode": trust["mode"], "ok": ok, "signer": signer, "reason": "; ".join(problems), "checks": checks}
