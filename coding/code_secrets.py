"""
code_secrets.py - Secrets per VryxCode project (vryxcode_secrets): an API key, a database password.

WHAT THIS FILE DOES
    * The person adds a secret to a project (a NAME and its value). It is kept encrypted (secret_box.py) in <data>/code_secrets/<user>.json, mode 600.
    * Programs VryxCode runs in that project get the secrets as environment variables. The model never sees a value: only the names are
      mentioned to it, and any value that shows up in what a tool returns is replaced with [secret NAME] (harness.Sandbox.mask).
    * The page only ever gets the names back, never a value: a value can be replaced or removed, not read.
"""
# json saves the data as text; os handles files and folders; re = regular expressions (text patterns);
# threading.Lock stops two requests changing the data at the same moment.
import json
import os
import re
import threading

# A secret name: capital letters, digits and underscores, starting with a letter or "_", 1 to 64 characters
# (like OPENWEATHER_KEY). It becomes an environment variable name, so it must look like one.
NAME_RE = re.compile(r"[A-Z_][A-Z0-9_]{0,63}")
# Limits: secrets per project, and characters in one value.
MAX_SECRETS, MAX_VALUE = 30, 4096
# Names a person may not use because they would change how the system itself works (e.g. PATH decides which programs run).
RESERVED = {"PATH", "HOME", "PYTHONPATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "SYSTEMROOT", "PYTHONDONTWRITEBYTECODE", "PYTHONIOENCODING", "PYTHONUNBUFFERED"}


class SecretsError(Exception):
    """A bad secret name or value, with a plain-words message that is safe to show to the person."""
    pass


class ProjectSecrets:
    """Stores each person's per-project secrets, encrypted, and hands out the values only to programs that run."""

    def __init__(self, data_dir, box):
        """data_dir = the server's data folder (None = keep in memory only, for tests); box = the object that
        encrypts and decrypts values (secret_box.py)."""
        self.dir = os.path.join(data_dir, "code_secrets") if data_dir else None
        # lock = guards changes; mem = the in-memory store used when there is no data folder.
        self.box, self.lock, self.mem = box, threading.Lock(), {}

    def _path(self, user):
        """The file for this user. Any character that is not a letter, digit, _ . or - becomes "_", so a user name cannot escape the folder."""
        return os.path.join(self.dir, re.sub(r"[^\w.-]", "_", user) + ".json")

    def _load(self, user):
        """All of this user's secrets as {project: {NAME: encrypted value}}. A missing or damaged file gives {}."""
        if not self.dir:
            return self.mem.setdefault(user, {})
        try:
            with open(self._path(user), encoding="utf-8") as f:
                got = json.load(f)
            return got if isinstance(got, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, user, data):
        """Write the user's secrets. Callers hold the lock."""
        if not self.dir:
            self.mem[user] = data
            return
        os.makedirs(self.dir, exist_ok=True)
        # Write a temporary file first. 0o600 = only the owner may read or write it, set from the moment it is created
        # (os.open lets us pick this; plain open() would create it with default, wider permissions).
        tmp = self._path(user) + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        # Swap it in at once, so a crash never leaves a half-written file.
        os.replace(tmp, self._path(user))

    def names(self, user, project):
        """The secret NAMES of a project, sorted. Never the values."""
        return sorted(self._load(user).get(project, {}))

    def set(self, user, project, name, value):
        """Add a secret, or replace the value of an existing one. Raises SecretsError for a bad name or value."""
        name, value = str(name or "").strip(), str(value or "")
        # fullmatch = the WHOLE name must fit the pattern, not just a part of it.
        if not NAME_RE.fullmatch(name):
            raise SecretsError("Use capital letters, digits and _ for the name, like OPENWEATHER_KEY.")
        # System-owned names are refused.
        if name in RESERVED:
            raise SecretsError(f"{name} is used by the system: choose another name.")
        # An empty or huge value is refused.
        if not value or len(value) > MAX_VALUE:
            raise SecretsError(f"The value must be 1 to {MAX_VALUE} characters.")
        with self.lock:
            data = self._load(user)
            mine = data.setdefault(project, {})
            # Replacing an existing name is always allowed; adding a new one is limited.
            if name not in mine and len(mine) >= MAX_SECRETS:
                raise SecretsError(f"A project can keep at most {MAX_SECRETS} secrets.")
            # Only the encrypted form is stored.
            mine[name] = self.box.encrypt(value)
            self._save(user, data)

    def delete(self, user, project, name):
        """Remove a secret (nothing happens if it does not exist)."""
        with self.lock:
            data = self._load(user)
            # pop returns None when the name was not there; only save when something was really removed.
            if data.get(project, {}).pop(str(name), None) is not None:
                # Drop the project entry too once its last secret is gone.
                if not data[project]:
                    del data[project]
                self._save(user, data)

    def values(self, user, project):
        """NAME -> value, for the programs VryxCode runs (never for the page or the model)."""
        out = {}
        # Decrypt each stored value on the way out.
        for k, v in self._load(user).get(project, {}).items():
            v = self.box.decrypt(v)
            if v:                                       # a value that cannot be read (the key changed) is left out
                out[k] = v
        return out
