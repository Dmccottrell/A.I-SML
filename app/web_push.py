"""
web_push.py - pwa_push: notifications for the website and the installed app, even when it is closed (the standard Web Push the browsers have).

WHAT THIS FILE DOES
    * The server has its own key pair (VAPID, made the first time, the private half kept encrypted with secret_box like the other secrets).
      The page asks the browser for permission, subscribes with the public half, and sends the subscription here.
    * `send` encrypts a short message for one browser (RFC 8291, aes128gcm) and posts it to that browser's push service (Google's for Chrome,
      Mozilla's, Apple's, Microsoft's). Only those services are ever contacted; a subscription that is gone (404/410) is forgotten.
    * What is sent: a title and one short line ("Your answer is ready", "VryxCode finished"), never the chat or the code.
"""
# Standard-library parts: base64 (bytes <-> text), json, os (files), re (a regex is a text pattern), threading (a lock and background threads),
# time, and urllib (web requests and address parsing).
import base64
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# The `cryptography` package does the maths. ec = elliptic-curve keys (a kind of public/private key pair), hashes = SHA-256,
# serialization = turning keys into bytes, AESGCM = the encryption that also detects tampering, HKDF = turns one shared secret into several keys.
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# The only push services we agree to talk to: Google (Chrome/Android), Mozilla, Apple and Microsoft. A subscription pointing anywhere else is refused,
# so the server cannot be tricked into posting to an arbitrary address.
PUSH_HOSTS = re.compile(r"(fcm\.googleapis\.com|android\.googleapis\.com|updates\.push\.services\.mozilla\.com|[\w.-]+\.push\.apple\.com|"
                        r"[\w.-]+\.notify\.windows\.com)")
# The most browsers (subscriptions) kept for one person; the oldest are dropped past this.
MAX_SUBS = 10


def b64u(data):
    """Bytes -> URL-safe base64 text with the "=" padding removed (the form Web Push uses)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text):
    """URL-safe base64 text -> bytes. Puts back the missing "=" padding first (base64 text must be a multiple of 4 characters long)."""
    # Accept anything (even a number) by turning it into text first.
    text = str(text)
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hkdf(salt, info, length, key):
    """HKDF = a standard way to stretch a secret into a key. `key` is the secret, `salt` and `info` mix in context; `length` is how many bytes you get back."""
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(key)


def encrypt(payload, p256dh, auth):
    """The message as a push service carries it (aes128gcm): only the browser that subscribed can read it.

    `payload`: the bytes to send. `p256dh`: the browser's public key and `auth`: its 16-byte secret, both as URL-safe base64 text
    (they come from the browser's subscription). Returns bytes: salt + record size + our one-time public key + the encrypted body (RFC 8291).
    """
    # The browser's public key, as bytes and as a key object (P-256 is the standard curve for Web Push).
    ua_pub = unb64u(p256dh)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub)
    # A brand-new one-time key pair for this message only, so one leaked message cannot unlock others.
    mine = ec.generate_private_key(ec.SECP256R1())
    # Our public half as 65 bytes (0x04 + x + y, the "uncompressed point" form), which the browser needs to decrypt.
    my_pub = mine.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    # ECDH: our private key + the browser's public key give a secret both sides can compute. HKDF then mixes in the browser's auth secret and both public keys
    # to make the input keying material (ikm). The text "WebPush: info" and the 0 byte are fixed by the standard.
    ikm = _hkdf(unb64u(auth), b"WebPush: info\x00" + ua_pub + my_pub, 32, mine.exchange(ec.ECDH(), ua_key))
    # A random 16-byte salt, different for every message.
    salt = os.urandom(16)
    # From ikm and the salt, derive the 16-byte content-encryption key (AES-128) and a 12-byte nonce (a once-only number AES-GCM needs). The label text is fixed by the standard.
    cek = _hkdf(salt, b"Content-Encoding: aes128gcm\x00", 16, ikm)
    nonce = _hkdf(salt, b"Content-Encoding: nonce\x00", 12, ikm)
    # Encrypt the payload. The extra byte 0x02 is the standard's "this is the last record" padding marker.
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    # The standard's header: salt (16 bytes), record size 4096 as 4 bytes, the length of our public key as 1 byte, the key itself, then the encrypted body.
    return salt + (4096).to_bytes(4, "big") + bytes([len(my_pub)]) + my_pub + body


class WebPush:
    def __init__(self, data_dir, box, contact="https://emvryx.app", post=None, clock=time.time):
        """Holds the server's VAPID key, and each person's browser subscriptions. `data_dir`: folder for the saved files (None = memory only, for tests); `box`: encrypts the private key on disk (secret_box); `contact`: who the push services can contact about us; `post`: function that sends the request (swapped for a fake in tests); `clock`: gives the time (also swappable)."""
        self.dir, self.box, self.contact, self.clock = data_dir, box, contact, clock
        # Use the real sender unless a test gave a fake one.
        self.post = post or _post
        # One lock so threads do not change the subscription list at the same moment.
        self.lock = threading.Lock()
        # The server's private key is loaded or made on first use (see _private).
        self.key = None
        self.subs = {}                                      # user -> [{"endpoint", "keys": {"p256dh", "auth"}}]
        # Load saved subscriptions from push_subs.json if it exists.
        if data_dir:
            try:
                with open(os.path.join(data_dir, "push_subs.json"), encoding="utf-8") as f:
                    got = json.load(f)
                # Ignore a file that is not a dict of users.
                self.subs = got if isinstance(got, dict) else {}
            # No file or broken JSON: start with no subscriptions.
            except (OSError, ValueError):
                pass

    def _private(self):
        """The server's VAPID private key: load it (decrypting with `box`) from vapid.key, or create a new one and save it encrypted. Cached after the first call."""
        if self.key is None:
            path = os.path.join(self.dir, "vapid.key") if self.dir else None
            pem = None
            # Read and decrypt the saved key if the file exists.
            if path and os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    pem = self.box.decrypt(f.read().strip())
            # Got a key: turn the PEM text (a standard text form for keys) back into a key object.
            if pem:
                self.key = serialization.load_pem_private_key(pem.encode(), password=None)
            # No saved key: generate a new P-256 pair.
            else:
                self.key = ec.generate_private_key(ec.SECP256R1())
                # With a folder to save in, write the key as PEM text, encrypted.
                if path:
                    pem = self.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
                    # Create the file readable only by this user (0o600 = owner read/write); never leave a secret world-readable.
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(self.box.encrypt(pem))
        return self.key

    def public_key(self):
        """The server's public key as URL-safe base64. The web page passes it to the browser when subscribing."""
        return b64u(self._private().public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))

    def _save(self):
        """Write the subscription list to push_subs.json (does nothing in memory-only mode)."""
        if not self.dir:
            return
        # Write to a .tmp file first, then replace the real file in one step, so a crash mid-write cannot leave a half-written file.
        path = os.path.join(self.dir, "push_subs.json")
        fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.subs, f)
        os.replace(path + ".tmp", path)

    def subscribe(self, user, sub):
        """Save one browser's subscription for a person. `sub` is the dict the browser gives: {"endpoint": address, "keys": {"p256dh", "auth"}}.
        Raises ValueError (with a plain message) if the address is not a known push service or the keys are the wrong size."""
        # Pull out the address and keys, tolerating a missing or odd `sub`.
        endpoint = str((sub or {}).get("endpoint") or "")
        keys = (sub or {}).get("keys") or {}
        # The address must be https and its host name must match a known push service exactly (fullmatch = the whole name, not just a part).
        u = urllib.parse.urlparse(endpoint)
        if u.scheme != "https" or not PUSH_HOSTS.fullmatch(u.hostname or ""):
            raise ValueError("That is not a browser's push service.")
        # p256dh must decode to 65 bytes and auth to 16 bytes; anything else (or undecodable text) is not a real browser key.
        try:
            if len(unb64u(keys.get("p256dh", ""))) != 65 or len(unb64u(keys.get("auth", ""))) != 16:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("The browser's keys are not valid.")
        # Under the lock: drop an older entry with the same address, add this one, keep only the newest MAX_SUBS, and save.
        with self.lock:
            mine = [s for s in self.subs.get(user, []) if s["endpoint"] != endpoint]
            self.subs[user] = (mine + [{"endpoint": endpoint, "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]}}])[-MAX_SUBS:]
            self._save()

    def unsubscribe(self, user, endpoint=None):
        """Forget one browser (its endpoint) for a person. With no endpoint given, forget all of that person's browsers: the filter keeps nothing."""
        with self.lock:
            self.subs[user] = [s for s in self.subs.get(user, []) if endpoint and s["endpoint"] != endpoint]
            self._save()

    def subscribed(self, user):
        """How many browsers this person has notifications on in."""
        return len(self.subs.get(user, []))

    def _vapid(self, endpoint):
        """Build the VAPID "Authorization" header: a signed token that proves to the push service that this server is the one sending."""
        # Split the address to get the push service's origin (scheme + host).
        u = urllib.parse.urlparse(endpoint)
        # A JWT (a signed token) has three dot-separated parts: header, claims, signature. The header says it is signed with ES256 (ECDSA on P-256 with SHA-256).
        head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
        # Claims: who it is for (the push service), when it expires (12 hours from now), and a contact address.
        claims = b64u(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(self.clock()) + 12 * 3600, "sub": self.contact}).encode())
        # Sign header.claims; the signature comes back in a wrapper format, so read out the two numbers r and s.
        r, s = decode_dss_signature(self._private().sign(f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
        # Web Push wants r and s as two 32-byte numbers joined together (64 bytes). `k=` is our public key.
        return f"vapid t={head}.{claims}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}, k={self.public_key()}"

    def send(self, user, title, text, url="/"):
        """Send to every browser this person turned notifications on in. Returns how many took it."""
        # Keep the message small and safe: title at most 80 characters, body at most 160, and the link must be a path on our own site (starts with "/").
        payload = json.dumps({"title": str(title)[:80], "body": str(text)[:160], "url": url if str(url).startswith("/") else "/"}).encode()
        # `sent` counts successes; `gone` collects addresses the push service says no longer exist.
        sent, gone = 0, []
        # Loop over a copy of the list so edits to it during the loop are safe.
        for s in list(self.subs.get(user, [])):
            try:
                # Encrypt separately for each browser, then post it with the headers the standard asks for: VAPID Authorization, encoding, TTL (86400 s = keep up to a day if the device is offline), normal urgency.
                status = self.post(s["endpoint"], encrypt(payload, s["keys"]["p256dh"], s["keys"]["auth"]),
                                   {"Authorization": self._vapid(s["endpoint"]), "Content-Encoding": "aes128gcm", "TTL": "86400", "Urgency": "normal",
                                    "Content-Type": "application/octet-stream"})
            # Network trouble with this one browser: skip it and carry on with the others.
            except OSError:
                continue
            # 404/410 mean "this subscription is gone": forget it later. Any 2xx status means it was accepted.
            if status in (404, 410):
                gone.append(s["endpoint"])
            elif 200 <= status < 300:
                sent += 1
        # Remove the dead subscriptions under the lock and save.
        if gone:
            with self.lock:
                self.subs[user] = [s for s in self.subs.get(user, []) if s["endpoint"] not in gone]
                self._save()
        return sent

    def send_later(self, user, title, text, url="/"):
        """Same as send() but on a background thread so the caller (a chat request) is not slowed down; does nothing if the person has no browsers subscribed."""
        if self.subs.get(user):
            threading.Thread(target=self.send, args=(user, title, text, url), daemon=True).start()


def _post(url, body, headers):
    """Default sender: POST `body` to `url` and return the HTTP status number. An error status (like 410) is returned as a number instead of raised."""
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    # 15 seconds, so a slow push service cannot hang us.
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
