"""
secret_box.py - Keeps the app's saved secrets (the GitHub token, later other connected accounts) encrypted on disk.

WHAT THIS FILE DOES
    A token in a file is a key to someone's account, so the file should be useless on its own. Every secret is encrypted (Fernet: AES-128-CBC
    with an HMAC, from the `cryptography` package) with a server key that lives in a different file (`<data>/secret.key`, mode 600), or in the
    EMVRYX_SECRET_KEY environment variable (so the key can live outside the data folder, e.g. in a service manager's secrets).
    Someone who copies only the data folder (a backup, a stolen disk image of just that folder) gets nothing readable.

    * A saved secret looks like  enc1:<encrypted text>.  Anything else is treated as an older plain value and is re-saved encrypted the next
      time it is read through `Store`.
    * If the `cryptography` package is not installed, secrets are stored as `plain:` (the file is still mode 600) and `available` is False, so
      the screen can say so. Set "require_encryption": true in .emvryx/security.json to refuse instead of storing plain.
    * Losing secret.key means the saved tokens cannot be read: reconnect the app. Back the key up separately from the data folder.
"""
import os
import stat

PREFIX_ENC, PREFIX_PLAIN = "enc1:", "plain:"

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:                                           # not installed: see the note above
    Fernet = InvalidToken = None


class SecretError(Exception):
    pass


class SecretBox:
    def __init__(self, data_dir=None, env_key=None, require=False):
        self.require = require
        self.available = Fernet is not None
        self.fernet = None
        if not self.available:
            return
        key = env_key if env_key is not None else os.environ.get("EMVRYX_SECRET_KEY")
        if not key and data_dir:
            path = os.path.join(data_dir, "secret.key")
            if os.path.exists(path):
                with open(path, "rb") as f:
                    key = f.read().strip().decode()
            else:
                os.makedirs(data_dir, exist_ok=True)
                key = Fernet.generate_key().decode()
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(key.encode())
                os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        if not key:                                           # in-memory server (tests, demos): a key that lives only as long as the process
            key = Fernet.generate_key().decode()
        try:
            self.fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except (ValueError, TypeError):
            raise SecretError("The secret key is not valid (it must be a Fernet key: 32 url-safe base64 bytes). Delete secret.key to make a new one "
                              "(saved tokens will then need to be connected again).")

    def encrypt(self, text):
        text = str(text)
        if self.fernet is not None:
            return PREFIX_ENC + self.fernet.encrypt(text.encode()).decode()
        if self.require:
            raise SecretError("Encryption is required but the `cryptography` package is not installed (pip install cryptography).")
        return PREFIX_PLAIN + text

    def decrypt(self, stored):
        """The secret, or None if it cannot be read (wrong key, damaged). Plain and unmarked values are returned as they are."""
        stored = str(stored or "")
        if stored.startswith(PREFIX_ENC):
            if self.fernet is None:
                return None
            try:
                return self.fernet.decrypt(stored[len(PREFIX_ENC):].encode()).decode()
            except (InvalidToken, ValueError):
                return None
        return stored[len(PREFIX_PLAIN):] if stored.startswith(PREFIX_PLAIN) else stored

    @staticmethod
    def is_encrypted(stored):
        return str(stored or "").startswith(PREFIX_ENC)
