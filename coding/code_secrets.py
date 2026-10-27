"""
code_secrets.py - Secrets per VryxCode project (vryxcode_secrets): an API key, a database password.

WHAT THIS FILE DOES
    * The person adds a secret to a project (a NAME and its value). It is kept encrypted (secret_box.py) in <data>/code_secrets/<user>.json, mode 600.
    * Programs VryxCode runs in that project get the secrets as environment variables. The model never sees a value: only the names are
      mentioned to it, and any value that shows up in what a tool returns is replaced with [secret NAME] (harness.Sandbox.mask).
    * The page only ever gets the names back, never a value: a value can be replaced or removed, not read.
"""
import json
import os
import re
import threading

NAME_RE = re.compile(r"[A-Z_][A-Z0-9_]{0,63}")
MAX_SECRETS, MAX_VALUE = 30, 4096
RESERVED = {"PATH", "HOME", "PYTHONPATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "SYSTEMROOT", "PYTHONDONTWRITEBYTECODE", "PYTHONIOENCODING", "PYTHONUNBUFFERED"}


class SecretsError(Exception):
    pass


class ProjectSecrets:
    def __init__(self, data_dir, box):
        self.dir = os.path.join(data_dir, "code_secrets") if data_dir else None
        self.box, self.lock, self.mem = box, threading.Lock(), {}

    def _path(self, user):
        return os.path.join(self.dir, re.sub(r"[^\w.-]", "_", user) + ".json")

    def _load(self, user):
        if not self.dir:
            return self.mem.setdefault(user, {})
        try:
            with open(self._path(user), encoding="utf-8") as f:
                got = json.load(f)
            return got if isinstance(got, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, user, data):
        if not self.dir:
            self.mem[user] = data
            return
        os.makedirs(self.dir, exist_ok=True)
        tmp = self._path(user) + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self._path(user))

    def names(self, user, project):
        return sorted(self._load(user).get(project, {}))

    def set(self, user, project, name, value):
        name, value = str(name or "").strip(), str(value or "")
        if not NAME_RE.fullmatch(name):
            raise SecretsError("Use capital letters, digits and _ for the name, like OPENWEATHER_KEY.")
        if name in RESERVED:
            raise SecretsError(f"{name} is used by the system: choose another name.")
        if not value or len(value) > MAX_VALUE:
            raise SecretsError(f"The value must be 1 to {MAX_VALUE} characters.")
        with self.lock:
            data = self._load(user)
            mine = data.setdefault(project, {})
            if name not in mine and len(mine) >= MAX_SECRETS:
                raise SecretsError(f"A project can keep at most {MAX_SECRETS} secrets.")
            mine[name] = self.box.encrypt(value)
            self._save(user, data)

    def delete(self, user, project, name):
        with self.lock:
            data = self._load(user)
            if data.get(project, {}).pop(str(name), None) is not None:
                if not data[project]:
                    del data[project]
                self._save(user, data)

    def values(self, user, project):
        """NAME -> value, for the programs VryxCode runs (never for the page or the model)."""
        out = {}
        for k, v in self._load(user).get(project, {}).items():
            v = self.box.decrypt(v)
            if v:                                       # a value that cannot be read (the key changed) is left out
                out[k] = v
        return out
