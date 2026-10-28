"""
web_push.py - pwa_push: notifications for the website and the installed app, even when it is closed (the standard Web Push the browsers have).

WHAT THIS FILE DOES
    * The server has its own key pair (VAPID, made the first time, the private half kept encrypted with secret_box like the other secrets).
      The page asks the browser for permission, subscribes with the public half, and sends the subscription here.
    * `send` encrypts a short message for one browser (RFC 8291, aes128gcm) and posts it to that browser's push service (Google's for Chrome,
      Mozilla's, Apple's, Microsoft's). Only those services are ever contacted; a subscription that is gone (404/410) is forgotten.
    * What is sent: a title and one short line ("Your answer is ready", "VryxCode finished"), never the chat or the code.
"""
import base64
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PUSH_HOSTS = re.compile(r"(fcm\.googleapis\.com|android\.googleapis\.com|updates\.push\.services\.mozilla\.com|[\w.-]+\.push\.apple\.com|"
                        r"[\w.-]+\.notify\.windows\.com)")
MAX_SUBS = 10


def b64u(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text):
    text = str(text)
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hkdf(salt, info, length, key):
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(key)


def encrypt(payload, p256dh, auth):
    """The message as a push service carries it (aes128gcm): only the browser that subscribed can read it."""
    ua_pub = unb64u(p256dh)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub)
    mine = ec.generate_private_key(ec.SECP256R1())
    my_pub = mine.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    ikm = _hkdf(unb64u(auth), b"WebPush: info\x00" + ua_pub + my_pub, 32, mine.exchange(ec.ECDH(), ua_key))
    salt = os.urandom(16)
    cek = _hkdf(salt, b"Content-Encoding: aes128gcm\x00", 16, ikm)
    nonce = _hkdf(salt, b"Content-Encoding: nonce\x00", 12, ikm)
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + (4096).to_bytes(4, "big") + bytes([len(my_pub)]) + my_pub + body


class WebPush:
    def __init__(self, data_dir, box, contact="https://emvryx.app", post=None, clock=time.time):
        self.dir, self.box, self.contact, self.clock = data_dir, box, contact, clock
        self.post = post or _post
        self.lock = threading.Lock()
        self.key = None
        self.subs = {}                                      # user -> [{"endpoint", "keys": {"p256dh", "auth"}}]
        if data_dir:
            try:
                with open(os.path.join(data_dir, "push_subs.json"), encoding="utf-8") as f:
                    got = json.load(f)
                self.subs = got if isinstance(got, dict) else {}
            except (OSError, ValueError):
                pass

    def _private(self):
        if self.key is None:
            path = os.path.join(self.dir, "vapid.key") if self.dir else None
            pem = None
            if path and os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    pem = self.box.decrypt(f.read().strip())
            if pem:
                self.key = serialization.load_pem_private_key(pem.encode(), password=None)
            else:
                self.key = ec.generate_private_key(ec.SECP256R1())
                if path:
                    pem = self.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(self.box.encrypt(pem))
        return self.key

    def public_key(self):
        return b64u(self._private().public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))

    def _save(self):
        if not self.dir:
            return
        path = os.path.join(self.dir, "push_subs.json")
        fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.subs, f)
        os.replace(path + ".tmp", path)

    def subscribe(self, user, sub):
        endpoint = str((sub or {}).get("endpoint") or "")
        keys = (sub or {}).get("keys") or {}
        u = urllib.parse.urlparse(endpoint)
        if u.scheme != "https" or not PUSH_HOSTS.fullmatch(u.hostname or ""):
            raise ValueError("That is not a browser's push service.")
        try:
            if len(unb64u(keys.get("p256dh", ""))) != 65 or len(unb64u(keys.get("auth", ""))) != 16:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("The browser's keys are not valid.")
        with self.lock:
            mine = [s for s in self.subs.get(user, []) if s["endpoint"] != endpoint]
            self.subs[user] = (mine + [{"endpoint": endpoint, "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]}}])[-MAX_SUBS:]
            self._save()

    def unsubscribe(self, user, endpoint=None):
        with self.lock:
            self.subs[user] = [s for s in self.subs.get(user, []) if endpoint and s["endpoint"] != endpoint]
            self._save()

    def subscribed(self, user):
        return len(self.subs.get(user, []))

    def _vapid(self, endpoint):
        u = urllib.parse.urlparse(endpoint)
        head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
        claims = b64u(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(self.clock()) + 12 * 3600, "sub": self.contact}).encode())
        r, s = decode_dss_signature(self._private().sign(f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
        return f"vapid t={head}.{claims}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}, k={self.public_key()}"

    def send(self, user, title, text, url="/"):
        """Send to every browser this person turned notifications on in. Returns how many took it."""
        payload = json.dumps({"title": str(title)[:80], "body": str(text)[:160], "url": url if str(url).startswith("/") else "/"}).encode()
        sent, gone = 0, []
        for s in list(self.subs.get(user, [])):
            try:
                status = self.post(s["endpoint"], encrypt(payload, s["keys"]["p256dh"], s["keys"]["auth"]),
                                   {"Authorization": self._vapid(s["endpoint"]), "Content-Encoding": "aes128gcm", "TTL": "86400", "Urgency": "normal",
                                    "Content-Type": "application/octet-stream"})
            except OSError:
                continue
            if status in (404, 410):
                gone.append(s["endpoint"])
            elif 200 <= status < 300:
                sent += 1
        if gone:
            with self.lock:
                self.subs[user] = [s for s in self.subs.get(user, []) if s["endpoint"] not in gone]
                self._save()
        return sent

    def send_later(self, user, title, text, url="/"):
        if self.subs.get(user):
            threading.Thread(target=self.send, args=(user, title, text, url), daemon=True).start()


def _post(url, body, headers):
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
