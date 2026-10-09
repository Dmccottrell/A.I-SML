"""
accounts.py - Passwords, authenticator-app codes (MFA) and recovery codes for Emvryx accounts.

WHAT THIS FILE DOES
    * Passwords are stored as scrypt hashes (Python's own hashlib, a salt per password). The password itself is never kept.
    * MFA is a standard time-based one-time code (RFC 6238: the 6-digit code in Google Authenticator, Microsoft Authenticator, Authy, 1Password, ...).
      The secret is kept encrypted when the server can (see secret_box.py). A code can only be used once (the last used time step is remembered).
    * Recovery codes: 8 one-time codes (xxxx-xxxx) for a lost phone. Only their hashes are kept.
    * Sign-up checks: a name, an email address and a password that is long enough and not one of the usual bad ones.

    Everything here is plain code with a clock you can fake, so it is tested without a server.
"""
import base64
import hashlib
import hmac
import re
import secrets
import struct
import time
import urllib.parse

import auth

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1
MIN_PASSWORD = 10
MAX_PASSWORD = 200
NAME_RE = re.compile(r"[A-Za-z0-9_-]{3,32}")
RESERVED_NAMES = {"owner", "admin", "administrator", "root", "emvryx", "vryxcode", "support", "system", "staff", "moderator", "null", "undefined"}
COMMON = {"password", "password1", "password12", "password123", "passw0rd", "1234567890", "12345678910", "qwertyuiop", "qwerty12345", "letmein123",
          "iloveyou123", "welcome123", "admin12345", "emvryx1234", "emvryx12345", "abc1234567", "1q2w3e4r5t", "0123456789", "9876543210"}
RECOVERY_COUNT = 8
STEP = 30
DIGITS = 6


# ---------------------------------------------------------------- passwords
def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    raw = hashlib.scrypt(str(password).encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=64 * 1024 * 1024, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (SCRYPT_N, SCRYPT_R, SCRYPT_P, base64.b64encode(salt).decode(), base64.b64encode(raw).decode())


def verify_password(password, stored):
    """True if `password` matches the stored hash. Never raises on a damaged value."""
    try:
        kind, n, r, p, salt, want = str(stored).split("$")
        if kind != "scrypt":
            return False
        raw = hashlib.scrypt(str(password).encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), maxmem=64 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(raw, base64.b64decode(want))
    except (ValueError, TypeError):
        return False


_DUMMY = None


def burn_time(password):
    """Do the same work as a real check when the account does not exist, so a missing name takes as long as a wrong password."""
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password("not a real password")
    verify_password(password, _DUMMY)


def password_problem(password, name="", email=""):
    """A plain sentence saying what is wrong with the password, or None when it is fine."""
    pw = str(password or "")
    if len(pw) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters. A few words in a row (a passphrase) is easy to remember and hard to guess."
    if len(pw) > MAX_PASSWORD:
        return f"That is too long (the limit is {MAX_PASSWORD} characters)."
    low = pw.lower()
    if low in COMMON or len(set(low)) < 4:
        return "That one is too easy to guess. Pick something less common."
    for bit in (str(name or "").lower(), str(email or "").lower().split("@")[0]):
        if len(bit) >= 4 and bit in low:
            return "Don't use your name or email in your password."
    return None


def clean_name(text):
    """A user name (letters, numbers, - and _, 3 to 32; spaces become _), or None."""
    text = re.sub(r"\s+", "_", str(text or "").strip())                     # "Darryl McCottrell" -> "Darryl_McCottrell"
    return text if NAME_RE.fullmatch(text) and text.lower() not in RESERVED_NAMES else None


# ---------------------------------------------------------------- one-time codes from an authenticator app
def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret):
    s = re.sub(r"[\s-]", "", str(secret)).upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def code_at(secret, counter):
    mac = hmac.new(_key(secret), struct.pack(">Q", int(counter)), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    num = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return f"{num:0{DIGITS}d}"


def check_totp(secret, code, last_counter=0, now=None, window=1):
    """The time step the code belongs to (a number > last_counter) if it is right, else None. One step either side is allowed for clock drift."""
    code = re.sub(r"\s", "", str(code or ""))
    if not re.fullmatch(r"\d{6}", code):
        return None
    now = time.time() if now is None else now
    here = int(now // STEP)
    for c in range(here - window, here + window + 1):
        if c > int(last_counter or 0) and hmac.compare_digest(code_at(secret, c), code):
            return c
    return None


def otpauth_uri(account, secret, issuer="Emvryx"):
    label = urllib.parse.quote(f"{issuer}:{account}", safe="")
    return f"otpauth://totp/{label}?secret={secret}&issuer={urllib.parse.quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}"


def group_secret(secret):
    """The setup key in groups of four so it can be typed: 'ABCD EFGH ...'."""
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))


# ---------------------------------------------------------------- recovery codes
def make_recovery_codes(n=RECOVERY_COUNT):
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return ["".join(secrets.choice(alphabet) for _ in range(4)) + "-" + "".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(n)]


def _norm_recovery(code):
    return re.sub(r"[^a-z0-9]", "", str(code or "").lower())


def hash_recovery(code):
    return auth.digest("recovery:" + _norm_recovery(code))


def use_recovery(hashes, code):
    """(True, the hashes left) when `code` is one of them (it is then used up), else (False, hashes)."""
    h = hash_recovery(code)
    for x in hashes:
        if auth.same(x, h):
            return True, [y for y in hashes if y != x]
    return False, list(hashes)
