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

# Every stored secret starts with a tag so we know how to read it back: "enc1:" = encrypted, "plain:" = not encrypted.
PREFIX_ENC, PREFIX_PLAIN = "enc1:", "plain:"

# `cryptography` is an optional outside package; if it is missing we fall back to plain storage instead of crashing.
try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:                                           # not installed: see the note above
    Fernet = InvalidToken = None


class SecretError(Exception):
    """Raised when a secret cannot be protected: a bad key, or encryption is required but the package is missing."""


class SecretBox:
    """Encrypts and decrypts short secret strings (tokens) with one server key."""

    def __init__(self, data_dir=None, env_key=None, require=False):
        """Find or create the key.

        `data_dir`: folder where secret.key is kept. `env_key`: a key given directly (tests); if None, the EMVRYX_SECRET_KEY environment
        variable is used. `require`: True means refuse to store secrets unencrypted.
        """
        self.require = require
        # `available` is True only when real encryption is possible (the package imported fine).
        self.available = Fernet is not None
        self.fernet = None
        if not self.available:
            return
        # Key order of preference: the argument, then the environment variable, then the secret.key file, then a fresh one-off key.
        key = env_key if env_key is not None else os.environ.get("EMVRYX_SECRET_KEY")
        if not key and data_dir:
            path = os.path.join(data_dir, "secret.key")
            if os.path.exists(path):
                # Key file already there: read it back (strip removes the trailing newline).
                with open(path, "rb") as f:
                    key = f.read().strip().decode()
            else:
                # First run: make the folder, generate a new random key, and write it.
                os.makedirs(data_dir, exist_ok=True)
                key = Fernet.generate_key().decode()
                # O_EXCL makes this fail if the file already exists (so two starts cannot overwrite each other's key), and 0o600 means
                # only the owner can read or write it. os.open gives a low-level file number; os.fdopen wraps it as a normal file.
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(key.encode())
                # Set the permissions again in case the system's umask (default permission mask) changed them when creating the file.
                os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        if not key:                                           # in-memory server (tests, demos): a key that lives only as long as the process
            key = Fernet.generate_key().decode()
        # Build the encryptor; a malformed key (wrong length or not base64) makes Fernet raise, which we turn into a clear message.
        try:
            self.fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except (ValueError, TypeError):
            raise SecretError("The secret key is not valid (it must be a Fernet key: 32 url-safe base64 bytes). Delete secret.key to make a new one "
                              "(saved tokens will then need to be connected again).")

    def encrypt(self, text):
        """Return `text` ready to store: "enc1:<encrypted>" normally, or "plain:<text>" when encryption is unavailable and not required."""
        text = str(text)
        if self.fernet is not None:
            return PREFIX_ENC + self.fernet.encrypt(text.encode()).decode()
        # No encryption available: fail loudly if the owner demanded it, otherwise store plain (the file itself is still mode 600).
        if self.require:
            raise SecretError("Encryption is required but the `cryptography` package is not installed (pip install cryptography).")
        return PREFIX_PLAIN + text

    def decrypt(self, stored):
        """The secret, or None if it cannot be read (wrong key, damaged). Plain and unmarked values are returned as they are."""
        stored = str(stored or "")
        if stored.startswith(PREFIX_ENC):
            # Encrypted value but no encryptor (package missing): we cannot read it.
            if self.fernet is None:
                return None
            # Remove the "enc1:" tag, decrypt the rest. InvalidToken means the wrong key or damaged text.
            try:
                return self.fernet.decrypt(stored[len(PREFIX_ENC):].encode()).decode()
            except (InvalidToken, ValueError):
                return None
        # Not encrypted: strip the "plain:" tag if present; an old value with no tag is returned as it is.
        return stored[len(PREFIX_PLAIN):] if stored.startswith(PREFIX_PLAIN) else stored

    @staticmethod
    def is_encrypted(stored):
        """True if this stored value is in the encrypted "enc1:" form (callers use it to decide whether to re-save an older plain value)."""
        return str(stored or "").startswith(PREFIX_ENC)
