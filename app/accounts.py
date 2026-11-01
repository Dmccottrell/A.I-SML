"""
accounts.py - Passwords, authenticator-app codes (MFA) and recovery codes for Emvryx accounts.

WHAT THIS FILE DOES
    * Passwords are stored as scrypt hashes (Python's own hashlib, a salt per password). The password itself is never kept.
    * MFA is a standard time-based one-time code (RFC 6238: the 6-digit code in Google Authenticator, Microsoft Authenticator, Authy, 1Password, ...).
      The secret is kept encrypted when the server can (see secret_box.py). A code can only be used once (the last used time step is remembered).
    * Recovery codes: 8 one-time codes (xxxx-xxxx) for a lost phone. Only their hashes are kept.
    * Sign-up checks: a name, an email address and a password that is long enough and not one of the usual bad ones.

    Everything here is plain code with a clock you can fake, so it is tested without a server.

    Words used below:
      * A "hash" is a one-way scramble of some text: you can check a guess against it, but you cannot turn it back into the original.
      * A "salt" is random extra data mixed in before hashing, so two people with the same password still get different hashes.
      * MFA means multi-factor authentication: a second proof (a code from your phone) on top of the password.
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

# scrypt is a deliberately slow, memory-hungry hash, which makes password guessing expensive. N = how much work/memory (2**14 = 16384),
# R = block size, P = how many parallel lanes. These are the common "interactive login" settings.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1
# Shortest and longest password we accept. The upper limit stops someone sending a huge password just to make the server work hard.
MIN_PASSWORD = 10
MAX_PASSWORD = 200
# A user name: only letters, digits, "_" and "-", between 3 and 32 characters. (A regex is a text pattern; this one is used with fullmatch below.)
NAME_RE = re.compile(r"[A-Za-z0-9_-]{3,32}")
# Names nobody may sign up with, so nobody can pretend to be the owner or staff.
RESERVED_NAMES = {"owner", "admin", "administrator", "root", "emvryx", "vryxcode", "support", "system", "staff", "moderator", "null", "undefined"}
# A short list of passwords everyone tries first. Anything on it is refused.
COMMON = {"password", "password1", "password12", "password123", "passw0rd", "1234567890", "12345678910", "qwertyuiop", "qwerty12345", "letmein123",
          "iloveyou123", "welcome123", "admin12345", "emvryx1234", "emvryx12345", "abc1234567", "1q2w3e4r5t", "0123456789", "9876543210"}
# How many recovery codes are made at once.
RECOVERY_COUNT = 8
# One-time codes change every STEP seconds and have DIGITS digits (the RFC 6238 / Google Authenticator standard values).
STEP = 30
DIGITS = 6


# ---------------------------------------------------------------- passwords
def hash_password(password, salt=None):
    """Turn a password into a storable text like "scrypt$N$R$P$salt$hash".

    In: the password, and optionally a salt (bytes; a fresh random 16-byte one is made when not given).
    Out: one text holding the settings, the salt and the hash (salt and hash are base64, a way to write raw bytes as plain letters), so
    `verify_password` can later redo the exact same work. The password itself is never stored.
    """
    salt = salt or secrets.token_bytes(16)
    # maxmem raises Python's memory cap for scrypt (64 MB) because N=2**14 with R=8 needs about 16 MB; dklen=32 asks for a 32-byte result.
    raw = hashlib.scrypt(str(password).encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=64 * 1024 * 1024, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (SCRYPT_N, SCRYPT_R, SCRYPT_P, base64.b64encode(salt).decode(), base64.b64encode(raw).decode())


def verify_password(password, stored):
    """True if `password` matches the stored hash. Never raises on a damaged value."""
    try:
        # The stored text has six parts split by "$"; the settings come from the text itself so old hashes keep working if the defaults change.
        kind, n, r, p, salt, want = str(stored).split("$")
        if kind != "scrypt":
            return False
        raw = hashlib.scrypt(str(password).encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), maxmem=64 * 1024 * 1024, dklen=32)
        # compare_digest compares in constant time, so how long the check takes does not leak how many leading bytes were right.
        return hmac.compare_digest(raw, base64.b64decode(want))
    except (ValueError, TypeError):
        # Wrong number of parts, bad base64 or bad numbers: treat a damaged stored value as "no match" instead of crashing the login.
        return False


# Cached hash of a fake password, made the first time it is needed (see burn_time).
_DUMMY = None


def burn_time(password):
    """Do the same work as a real check when the account does not exist, so a missing name takes as long as a wrong password.

    Why: if "no such user" came back instantly, an attacker could time the replies and learn which names exist.
    """
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password("not a real password")
    # The result is thrown away on purpose; only the time spent matters.
    verify_password(password, _DUMMY)


def password_problem(password, name="", email=""):
    """A plain sentence saying what is wrong with the password, or None when it is fine.

    In: the password, plus the person's name and email (to stop passwords built from them).
    """
    pw = str(password or "")
    if len(pw) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters. A few words in a row (a passphrase) is easy to remember and hard to guess."
    if len(pw) > MAX_PASSWORD:
        return f"That is too long (the limit is {MAX_PASSWORD} characters)."
    low = pw.lower()
    # Too easy: on the common list, or fewer than 4 different characters (like "aaaaaaaaaaaa").
    if low in COMMON or len(set(low)) < 4:
        return "That one is too easy to guess. Pick something less common."
    # Refuse a password that contains the user name or the part of the email before the "@" (only when that part is 4+ characters).
    for bit in (str(name or "").lower(), str(email or "").lower().split("@")[0]):
        if len(bit) >= 4 and bit in low:
            return "Don't use your name or email in your password."
    return None


def clean_name(text):
    """A user name (letters, numbers, - and _, 3 to 32; spaces become _), or None."""
    # \s+ means "one or more whitespace characters"; each run becomes a single underscore.
    text = re.sub(r"\s+", "_", str(text or "").strip())                     # "Darryl McCottrell" -> "Darryl_McCottrell"
    # fullmatch means the WHOLE text must fit the pattern, not just a piece of it.
    return text if NAME_RE.fullmatch(text) and text.lower() not in RESERVED_NAMES else None


# ---------------------------------------------------------------- one-time codes from an authenticator app
def new_secret():
    """Make a fresh random MFA secret: 20 random bytes (160 bits) written in base32 (letters A-Z and 2-7), without the "=" padding."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret):
    """Turn the base32 text secret back into raw bytes. Spaces and dashes are ignored and case does not matter, so a typed setup key works."""
    s = re.sub(r"[\s-]", "", str(secret)).upper()
    # base32 text must be a multiple of 8 characters long, so pad with "=" (the -len % 8 trick gives exactly the missing count).
    return base64.b32decode(s + "=" * (-len(s) % 8))


def code_at(secret, counter):
    """The 6-digit code for one time step (HOTP, RFC 4226, which TOTP is built on).

    In: the secret text and the step number (seconds since 1970 divided by 30).
    Out: a text like "042913".
    """
    # HMAC-SHA1 = a keyed scramble of the step number (packed as 8 big-endian bytes) using the secret as the key. 20 bytes come out.
    mac = hmac.new(_key(secret), struct.pack(">Q", int(counter)), hashlib.sha1).digest()
    # "Dynamic truncation": the last 4 bits of the hash choose where to read 4 bytes from.
    off = mac[-1] & 0x0F
    # Read those 4 bytes as a number, clear the top bit (0x7FFFFFFF) so it is never negative, then keep the last 6 decimal digits.
    num = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    # Pad with leading zeros so the code is always 6 characters.
    return f"{num:0{DIGITS}d}"


def check_totp(secret, code, last_counter=0, now=None, window=1):
    """The time step the code belongs to (a number > last_counter) if it is right, else None. One step either side is allowed for clock drift."""
    # Strip spaces (phones often show "123 456"), then insist on exactly six digits.
    code = re.sub(r"\s", "", str(code or ""))
    if not re.fullmatch(r"\d{6}", code):
        return None
    # `now` can be given by a test so the clock can be faked; otherwise use the real time.
    now = time.time() if now is None else now
    here = int(now // STEP)
    # Try the current step and `window` steps before and after, in case the phone clock is a little off.
    for c in range(here - window, here + window + 1):
        # `c > last_counter` stops a code being used twice (replay); compare_digest keeps the comparison constant-time.
        if c > int(last_counter or 0) and hmac.compare_digest(code_at(secret, c), code):
            return c
    return None


def otpauth_uri(account, secret, issuer="Emvryx"):
    """The "otpauth://" link that a QR code carries so an authenticator app can add the account in one scan.

    In: the account label (e.g. the user name), the secret text, the app name shown in the authenticator.
    """
    # quote() makes text safe inside a link (spaces, "@", ":" and so on become %XX); safe="" means even "/" is escaped.
    label = urllib.parse.quote(f"{issuer}:{account}", safe="")
    return f"otpauth://totp/{label}?secret={secret}&issuer={urllib.parse.quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}"


def group_secret(secret):
    """The setup key in groups of four so it can be typed: 'ABCD EFGH ...'."""
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))


# ---------------------------------------------------------------- recovery codes
def make_recovery_codes(n=RECOVERY_COUNT):
    """Make `n` one-time recovery codes shaped like "abcd-2345".

    The alphabet leaves out look-alike characters (no i, l, o, 0, 1) so a code read off paper is not mistyped.
    `secrets.choice` is a random pick that is safe for security use (unlike the plain `random` module).
    """
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return ["".join(secrets.choice(alphabet) for _ in range(4)) + "-" + "".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(n)]


def _norm_recovery(code):
    """Boil a typed recovery code down to lowercase letters and digits, so "ABCD-2345", "abcd 2345" and "abcd2345" all count as the same."""
    return re.sub(r"[^a-z0-9]", "", str(code or "").lower())


def hash_recovery(code):
    """The stored form of a recovery code: a digest (one-way hash, see auth.py) of the cleaned-up code with a "recovery:" prefix."""
    return auth.digest("recovery:" + _norm_recovery(code))


def use_recovery(hashes, code):
    """(True, the hashes left) when `code` is one of them (it is then used up), else (False, hashes)."""
    h = hash_recovery(code)
    for x in hashes:
        # auth.same compares two hashes safely (constant time).
        if auth.same(x, h):
            # Match: return the list WITHOUT this hash, so the code cannot be used again.
            return True, [y for y in hashes if y != x]
    # No match: give back a copy of the list unchanged.
    return False, list(hashes)
