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
import base64
import hashlib
import json
import struct

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
    AVAILABLE = True
except ImportError:                                             # the app still works without passkeys
    AVAILABLE = False

FLAG_UP, FLAG_UV, FLAG_AT = 0x01, 0x04, 0x40
ES256, RS256 = -7, -257


class PasskeyError(Exception):
    pass


def b64u(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text):
    try:
        return base64.urlsafe_b64decode(str(text) + "=" * (-len(str(text)) % 4))
    except (ValueError, TypeError):
        raise PasskeyError("That passkey reply was damaged.")


# ---------------------------------------------------------------- a small CBOR reader (what a passkey's attestation uses)
def cbor_decode(data, pos=0, depth=0):
    """(value, next position). Maps, arrays, byte and text strings, integers and the simple values; nothing else is needed here."""
    if depth > 8 or pos >= len(data):
        raise PasskeyError("Unreadable passkey data.")
    head = data[pos]
    major, info = head >> 5, head & 0x1F
    pos += 1
    if info < 24:
        n = info
    elif info in (24, 25, 26, 27):
        size = {24: 1, 25: 2, 26: 4, 27: 8}[info]
        if pos + size > len(data):
            raise PasskeyError("Unreadable passkey data.")
        n, pos = int.from_bytes(data[pos:pos + size], "big"), pos + size
    else:
        raise PasskeyError("Unreadable passkey data.")
    if major == 0:
        return n, pos
    if major == 1:
        return -1 - n, pos
    if major in (2, 3):
        if pos + n > len(data):
            raise PasskeyError("Unreadable passkey data.")
        raw = data[pos:pos + n]
        return (raw if major == 2 else raw.decode("utf-8", "replace")), pos + n
    if major == 4:
        out = []
        for _ in range(min(n, 64)):
            v, pos = cbor_decode(data, pos, depth + 1)
            out.append(v)
        return out, pos
    if major == 5:
        out = {}
        for _ in range(min(n, 64)):
            k, pos = cbor_decode(data, pos, depth + 1)
            v, pos = cbor_decode(data, pos, depth + 1)
            out[k] = v
        return out, pos
    if major == 7:
        return {20: False, 21: True, 22: None}.get(info), pos
    raise PasskeyError("Unreadable passkey data.")


# ---------------------------------------------------------------- checks shared by both steps
def rp_hash(rp_id):
    return hashlib.sha256(rp_id.encode()).digest()


def check_client_data(client_data_json, kind, challenge, origin):
    raw = unb64u(client_data_json)
    try:
        cd = json.loads(raw)
    except ValueError:
        raise PasskeyError("That passkey reply was damaged.")
    if cd.get("type") != kind:
        raise PasskeyError("That passkey reply was for something else.")
    if cd.get("challenge") != challenge:
        raise PasskeyError("That passkey request expired or was not ours.")
    if cd.get("origin") != origin:
        raise PasskeyError("That passkey was made for a different web address.")
    return raw


def parse_auth_data(auth_data, rp_id, need_uv=True):
    """(flags, counter, rest) after checking the rp id hash, user presence and verification."""
    if len(auth_data) < 37:
        raise PasskeyError("That passkey reply was damaged.")
    if auth_data[:32] != rp_hash(rp_id):
        raise PasskeyError("That passkey belongs to a different site.")
    flags, counter = auth_data[32], struct.unpack(">I", auth_data[33:37])[0]
    if not flags & FLAG_UP:
        raise PasskeyError("The passkey was not confirmed on the device.")
    if need_uv and not flags & FLAG_UV:
        raise PasskeyError("The passkey needs your fingerprint, face or screen lock.")
    return flags, counter, auth_data[37:]


def pem_from_cose(cose):
    if not AVAILABLE:
        raise PasskeyError("Passkeys need the cryptography package on the server.")
    kty, alg = cose.get(1), cose.get(3)
    if kty == 2 and alg == ES256 and cose.get(-1) == 1 and isinstance(cose.get(-2), bytes) and isinstance(cose.get(-3), bytes):
        key = ec.EllipticCurvePublicNumbers(int.from_bytes(cose[-2], "big"), int.from_bytes(cose[-3], "big"), ec.SECP256R1()).public_key()
    elif kty == 3 and alg == RS256 and isinstance(cose.get(-1), bytes) and isinstance(cose.get(-2), bytes):
        key = rsa.RSAPublicNumbers(int.from_bytes(cose[-2], "big"), int.from_bytes(cose[-1], "big")).public_key()
    else:
        raise PasskeyError("This device uses a passkey type Emvryx does not support yet.")
    return alg, key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def verify_registration(credential, challenge, origin, rp_id):
    """The new passkey {"id", "alg", "pem", "counter"} from what the browser's `credentials.create` returned, or a PasskeyError."""
    check_client_data(credential.get("clientDataJSON", ""), "webauthn.create", challenge, origin)
    att, _ = cbor_decode(unb64u(credential.get("attestationObject", "")))
    if not isinstance(att, dict) or not isinstance(att.get("authData"), bytes):
        raise PasskeyError("That passkey reply was damaged.")
    flags, counter, rest = parse_auth_data(att["authData"], rp_id)
    if not flags & FLAG_AT or len(rest) < 18:
        raise PasskeyError("That passkey reply had no key in it.")
    cred_len = struct.unpack(">H", rest[16:18])[0]
    cred_id = rest[18:18 + cred_len]
    cose, _ = cbor_decode(rest, 18 + cred_len)
    alg, pem = pem_from_cose(cose)
    if not cred_id or b64u(cred_id) != credential.get("id"):
        raise PasskeyError("That passkey reply did not match.")
    return {"id": b64u(cred_id), "alg": alg, "pem": pem, "counter": counter}


def verify_assertion(credential, passkey, challenge, origin, rp_id):
    """The new use counter when the signature is right, or a PasskeyError."""
    raw = check_client_data(credential.get("clientDataJSON", ""), "webauthn.get", challenge, origin)
    auth_data = unb64u(credential.get("authenticatorData", ""))
    _, counter, _ = parse_auth_data(auth_data, rp_id)
    signed = auth_data + hashlib.sha256(raw).digest()
    key = serialization.load_pem_public_key(passkey["pem"].encode())
    try:
        if passkey["alg"] == ES256:
            key.verify(unb64u(credential.get("signature", "")), signed, ec.ECDSA(hashes.SHA256()))
        else:
            key.verify(unb64u(credential.get("signature", "")), signed, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        raise PasskeyError("That passkey's signature was not valid.")
    old = int(passkey.get("counter", 0))
    if (counter or old) and counter <= old:
        raise PasskeyError("That passkey looks cloned (its use counter went backwards).")
    return counter
