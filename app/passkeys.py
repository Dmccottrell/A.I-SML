"""
passkeys.py - Sign in with a passkey (WebAuthn): your fingerprint, face or screen lock instead of a password.

WHAT THIS FILE DOES
    The pure parts of WebAuthn, using the `cryptography` package: reading what the phone or computer sends when a passkey is made
    (registration), and checking the signature when one is used (sign-in). The server (app_server.py) keeps the challenges and the list of passkeys.

    What is checked, every time:
      * the challenge is the one we just issued (so a recording cannot be replayed) and `origin` is our own address;
      * the "relying party id" hash in the authenticator data is the hash of our host name (so a passkey made for another site is useless here);
      * the user was PRESENT and VERIFIED (fingerprint, face or PIN): a passkey sign-in counts as two factors, so it skips the 6-digit code;
      * the signature is valid for the public key we stored (ES256 or RS256), and the use counter never goes backwards.
    Attestation is not requested ("none"): we only need the public key, not proof of what kind of device made it.
"""
# Standard-library tools used below: base64 (text <-> bytes), hashlib (SHA-256 hashes), json (reads the browser's JSON), struct (reads fixed-size numbers out of raw bytes).
import base64
import hashlib
import json
import struct

# The `cryptography` package does the hard maths (checking signatures). It is optional: if it is not installed, AVAILABLE stays False
# and the rest of the app simply skips passkeys instead of crashing.
try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
    AVAILABLE = True
except ImportError:                                             # the app still works without passkeys
    AVAILABLE = False

# Bits inside the one-byte "flags" field of the authenticator data (the blob the device sends back):
#   FLAG_UP = user present (they touched / confirmed it), FLAG_UV = user verified (fingerprint, face or PIN),
#   FLAG_AT = attested credential data is included (only on registration, it carries the new public key).
# A "flag" here is one bit; `flags & FLAG_UP` is non-zero only when that bit is switched on.
FLAG_UP, FLAG_UV, FLAG_AT = 0x01, 0x04, 0x40
# COSE algorithm numbers (COSE is the standard way to label keys): -7 means ECDSA with P-256 + SHA-256 (the common one),
# -257 means RSA with PKCS1v1.5 + SHA-256 (older Windows devices).
ES256, RS256 = -7, -257


class PasskeyError(Exception):
    """Raised for anything wrong with a passkey reply. The message is plain words that are safe to show to the person."""
    pass


def b64u(data):
    """Bytes -> URL-safe base64 text with the trailing "=" padding removed (the form WebAuthn uses for ids and challenges)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text):
    """The reverse of b64u: URL-safe base64 text -> bytes. Raises PasskeyError if the text is not valid base64."""
    try:
        # base64 text must have a length that is a multiple of 4; b64u dropped the "=" padding, so put back however many are missing.
        return base64.urlsafe_b64decode(str(text) + "=" * (-len(str(text)) % 4))
    except (ValueError, TypeError):
        raise PasskeyError("That passkey reply was damaged.")


# CBOR is a compact binary format (like JSON, but in bytes). Every item starts with one "head" byte: the top 3 bits are the
# "major type" (what kind of thing: number, bytes, text, list, map...) and the low 5 bits are extra info (a small value, or how many
# more bytes hold the length / number).
# ---------------------------------------------------------------- a small CBOR reader (what a passkey's attestation uses)
def cbor_decode(data, pos=0, depth=0):
    """(value, next position). Maps, arrays, byte and text strings, integers and the simple values; nothing else is needed here."""
    # Safety limits: stop if nested too deep or if we ran off the end of the data (a hostile reply must not make us loop or crash).
    if depth > 8 or pos >= len(data):
        raise PasskeyError("Unreadable passkey data.")
    # Split the head byte: shift right 5 to get the major type, mask with 0x1F (binary 11111) to get the low 5 bits.
    head = data[pos]
    major, info = head >> 5, head & 0x1F
    pos += 1
    # Info 0-23 is the number itself. 24..27 mean "the number follows in the next 1, 2, 4 or 8 bytes" (big-endian).
    if info < 24:
        n = info
    elif info in (24, 25, 26, 27):
        size = {24: 1, 25: 2, 26: 4, 27: 8}[info]
        if pos + size > len(data):
            raise PasskeyError("Unreadable passkey data.")
        n, pos = int.from_bytes(data[pos:pos + size], "big"), pos + size
    else:
        raise PasskeyError("Unreadable passkey data.")
    # Major 0 = unsigned integer. Major 1 = negative integer (stored as -1 - n).
    if major == 0:
        return n, pos
    if major == 1:
        return -1 - n, pos
    # Major 2 = byte string, major 3 = text string; n is the length. Check the data is long enough, then slice it out.
    if major in (2, 3):
        if pos + n > len(data):
            raise PasskeyError("Unreadable passkey data.")
        raw = data[pos:pos + n]
        return (raw if major == 2 else raw.decode("utf-8", "replace")), pos + n
    # Major 4 = array (list) of n items; each item is decoded by calling ourselves again (recursion), one level deeper.
    # Capped at 64 items so a lying length cannot make us work forever.
    if major == 4:
        out = []
        for _ in range(min(n, 64)):
            v, pos = cbor_decode(data, pos, depth + 1)
            out.append(v)
        return out, pos
    # Major 5 = map (dict) of n key/value pairs, also capped at 64.
    if major == 5:
        out = {}
        for _ in range(min(n, 64)):
            k, pos = cbor_decode(data, pos, depth + 1)
            v, pos = cbor_decode(data, pos, depth + 1)
            out[k] = v
        return out, pos
    # Major 7 = simple values: 20 false, 21 true, 22 null. Anything else becomes None.
    if major == 7:
        return {20: False, 21: True, 22: None}.get(info), pos
    raise PasskeyError("Unreadable passkey data.")


# Helpers used by both registration (making a passkey) and sign-in (using one).
# ---------------------------------------------------------------- checks shared by both steps
def rp_hash(rp_id):
    """SHA-256 hash of the "relying party id" (our host name). The device puts this hash in its reply so a passkey made for another site is useless here."""
    return hashlib.sha256(rp_id.encode()).digest()


def check_client_data(client_data_json, kind, challenge, origin):
    """Check the browser's clientDataJSON (base64 text of a JSON note). `kind` is "webauthn.create" or "webauthn.get",
    `challenge` is the random value we issued, `origin` is our web address. Returns the raw JSON bytes (needed later for the signature check)
    or raises PasskeyError if the type, challenge or address is wrong."""
    raw = unb64u(client_data_json)
    try:
        cd = json.loads(raw)
    except ValueError:
        raise PasskeyError("That passkey reply was damaged.")
    # Three must-match checks: right kind of request, the exact challenge we just issued (stops replay), and our own web address (stops phishing sites).
    if cd.get("type") != kind:
        raise PasskeyError("That passkey reply was for something else.")
    if cd.get("challenge") != challenge:
        raise PasskeyError("That passkey request expired or was not ours.")
    if cd.get("origin") != origin:
        raise PasskeyError("That passkey was made for a different web address.")
    return raw


def parse_auth_data(auth_data, rp_id, need_uv=True):
    """(flags, counter, rest) after checking the rp id hash, user presence and verification."""
    # The authenticator data starts with 37 fixed bytes: 32 for the rp id hash, 1 for the flags, 4 for the use counter. Shorter than that is broken.
    if len(auth_data) < 37:
        raise PasskeyError("That passkey reply was damaged.")
    if auth_data[:32] != rp_hash(rp_id):
        raise PasskeyError("That passkey belongs to a different site.")
    # Byte 32 is the flags. Bytes 33-36 are the counter as a big-endian unsigned 32-bit number (">I" in struct's format language).
    flags, counter = auth_data[32], struct.unpack(">I", auth_data[33:37])[0]
    # The person must have been present (and, when need_uv is on, verified) - otherwise someone could have used a stolen, unlocked device silently.
    if not flags & FLAG_UP:
        raise PasskeyError("The passkey was not confirmed on the device.")
    if need_uv and not flags & FLAG_UV:
        raise PasskeyError("The passkey needs your fingerprint, face or screen lock.")
    return flags, counter, auth_data[37:]


def pem_from_cose(cose):
    """Turn the public key the device sent (a COSE map: a dict with numeric keys) into (algorithm number, PEM text).
    PEM is a standard text format for keys that we can store and load later. Only ES256 and RS256 keys are supported."""
    if not AVAILABLE:
        raise PasskeyError("Passkeys need the cryptography package on the server.")
    # COSE key labels: 1 = key type (2 = elliptic curve, 3 = RSA), 3 = algorithm. For an EC key: -1 = curve (1 = P-256), -2 = x and -3 = y coordinates.
    kty, alg = cose.get(1), cose.get(3)
    if kty == 2 and alg == ES256 and cose.get(-1) == 1 and isinstance(cose.get(-2), bytes) and isinstance(cose.get(-3), bytes):
        # Build the elliptic-curve public key from its x and y numbers (bytes read as big-endian integers).
        key = ec.EllipticCurvePublicNumbers(int.from_bytes(cose[-2], "big"), int.from_bytes(cose[-3], "big"), ec.SECP256R1()).public_key()
    elif kty == 3 and alg == RS256 and isinstance(cose.get(-1), bytes) and isinstance(cose.get(-2), bytes):
        # Build the RSA public key from its modulus n (label -1) and exponent e (label -2). The constructor wants (e, n), so the order is swapped here.
        key = rsa.RSAPublicNumbers(int.from_bytes(cose[-2], "big"), int.from_bytes(cose[-1], "big")).public_key()
    else:
        # Any other key type is refused with a clear message.
        raise PasskeyError("This device uses a passkey type Emvryx does not support yet.")
    # Export the key as PEM ("SubjectPublicKeyInfo" is the standard public-key wrapper).
    return alg, key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def verify_registration(credential, challenge, origin, rp_id):
    """The new passkey {"id", "alg", "pem", "counter"} from what the browser's `credentials.create` returned, or a PasskeyError."""
    # Step 1: the browser note must be a "create" request with our challenge and address.
    check_client_data(credential.get("clientDataJSON", ""), "webauthn.create", challenge, origin)
    # Step 2: the attestationObject is CBOR; it should be a map holding the raw "authData" bytes.
    att, _ = cbor_decode(unb64u(credential.get("attestationObject", "")))
    if not isinstance(att, dict) or not isinstance(att.get("authData"), bytes):
        raise PasskeyError("That passkey reply was damaged.")
    # Step 3: check the rp id hash and presence/verification flags. `rest` is whatever follows the 37 fixed bytes.
    flags, counter, rest = parse_auth_data(att["authData"], rp_id)
    if not flags & FLAG_AT or len(rest) < 18:
        raise PasskeyError("That passkey reply had no key in it.")
    # The attested credential data layout: 16 bytes of authenticator id (AAGUID), then a 2-byte length of the credential id, the id itself, then the public key (CBOR).
    cred_len = struct.unpack(">H", rest[16:18])[0]
    cred_id = rest[18:18 + cred_len]
    # The public key sits right after the credential id, as a CBOR map.
    cose, _ = cbor_decode(rest, 18 + cred_len)
    alg, pem = pem_from_cose(cose)
    # The id inside the signed data must match the id the browser reported, otherwise the reply was tampered with or mixed up.
    if not cred_id or b64u(cred_id) != credential.get("id"):
        raise PasskeyError("That passkey reply did not match.")
    return {"id": b64u(cred_id), "alg": alg, "pem": pem, "counter": counter}


def verify_assertion(credential, passkey, challenge, origin, rp_id):
    """The new use counter when the signature is right, or a PasskeyError."""
    # Sign-in: first the same browser-note checks, but for a "get" request.
    raw = check_client_data(credential.get("clientDataJSON", ""), "webauthn.get", challenge, origin)
    auth_data = unb64u(credential.get("authenticatorData", ""))
    # Same rp id / presence / verification checks; we only keep the use counter (flags and the rest are not needed).
    _, counter, _ = parse_auth_data(auth_data, rp_id)
    # What the device signed is the authenticator data followed by the SHA-256 hash of the browser note.
    signed = auth_data + hashlib.sha256(raw).digest()
    # Load the public key we stored at registration.
    key = serialization.load_pem_public_key(passkey["pem"].encode())
    try:
        # verify() returns quietly when the signature matches and raises InvalidSignature when it does not. ES256 uses ECDSA; the other (RS256) uses RSA PKCS1v1.5.
        if passkey["alg"] == ES256:
            key.verify(unb64u(credential.get("signature", "")), signed, ec.ECDSA(hashes.SHA256()))
        else:
            key.verify(unb64u(credential.get("signature", "")), signed, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        raise PasskeyError("That passkey's signature was not valid.")
    # Clone check: each real use bumps the device's counter. If it did not go up, a copy of the key may be in use. (Some devices always send 0, so zero-vs-zero is allowed.)
    old = int(passkey.get("counter", 0))
    if (counter or old) and counter <= old:
        raise PasskeyError("That passkey looks cloned (its use counter went backwards).")
    return counter
