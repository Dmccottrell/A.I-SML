"""pwa_push (app/web_push.py): the message is encrypted so only the subscribed browser can read it (RFC 8291), signed for the push service
(VAPID), sent only to real push services, and a subscription that is gone is forgotten."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import os
import tempfile
import time
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import secret_box
import vryxcode
import web_push as W
from tests.test_app_server import Base
from tests.test_code_sessions import open_to_everyone, wait_for

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123"


def browser():
    """A browser's side: its key pair and auth secret, as a subscription."""
    key, auth = ec.generate_private_key(ec.SECP256R1()), os.urandom(16)
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return key, auth, {"endpoint": ENDPOINT, "keys": {"p256dh": W.b64u(pub), "auth": W.b64u(auth)}}


def decrypt(body, key, auth):
    """What the browser does with a message (RFC 8291)."""
    salt, idlen = body[:16], body[20]
    server_pub, data = body[21:21 + idlen], body[21 + idlen:]
    ua_pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), server_pub))
    ikm = W._hkdf(auth, b"WebPush: info\x00" + ua_pub + server_pub, 32, shared)
    cek, nonce = W._hkdf(salt, b"Content-Encoding: aes128gcm\x00", 16, ikm), W._hkdf(salt, b"Content-Encoding: nonce\x00", 12, ikm)
    plain = AESGCM(cek).decrypt(nonce, data, None)
    return plain[:plain.rindex(b"\x02")]


class Crypto(unittest.TestCase):
    def test_only_the_browser_can_read_it_and_the_push_service_can_check_who_sent_it(self):
        key, auth, sub = browser()
        posted = []
        p = W.WebPush(None, secret_box.SecretBox(None), "https://emvryx.app", post=lambda url, body, headers: posted.append((url, body, headers)) or 201)
        p.subscribe("sam", sub)
        self.assertEqual(p.send("sam", "Emvryx", "Your answer is ready", "/"), 1)
        url, body, headers = posted[0]
        self.assertEqual(url, ENDPOINT)
        self.assertEqual(json.loads(decrypt(body, key, auth)), {"title": "Emvryx", "body": "Your answer is ready", "url": "/"})
        self.assertEqual(headers["Content-Encoding"], "aes128gcm")
        t, k = headers["Authorization"][len("vapid t="):].split(", k=")
        head, claims, sig = t.split(".")
        self.assertEqual(json.loads(W.unb64u(claims))["aud"], "https://fcm.googleapis.com")
        raw = W.unb64u(sig)
        pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), W.unb64u(k))
        pub.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")), f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))

    def test_the_key_is_kept_encrypted_and_survives_a_restart(self):
        with tempfile.TemporaryDirectory() as d:
            box = secret_box.SecretBox(d)
            a = W.WebPush(d, box).public_key()
            with open(os.path.join(d, "vapid.key")) as f:
                self.assertNotIn("PRIVATE KEY", f.read())
            self.assertEqual(W.WebPush(d, box).public_key(), a)


class Subscriptions(unittest.TestCase):
    def test_only_push_services_and_gone_ones_are_forgotten(self):
        p = W.WebPush(None, secret_box.SecretBox(None), post=lambda *a: 410)
        _, _, sub = browser()
        for bad in ("http://fcm.googleapis.com/x", "https://evil.example/push", "https://127.0.0.1/x", "https://fcm.googleapis.com.evil.example/x"):
            with self.assertRaises(ValueError, msg=bad):
                p.subscribe("sam", dict(sub, endpoint=bad))
        with self.assertRaises(ValueError):
            p.subscribe("sam", dict(sub, keys={"p256dh": "x", "auth": "y"}))
        p.subscribe("sam", sub)
        self.assertEqual((p.send("sam", "t", "x"), p.subscribed("sam")), (0, 0))       # 410: the browser unsubscribed


class Server(Base):
    def test_turning_it_on_and_a_test(self):
        self.assertEqual(self.owner.call("GET", "/api/push")[0], 404)
        self.state.flags.data["audiences"]["pwa_push"] = "admins"
        sent = []
        self.state.push.post = lambda url, body, headers: sent.append(url) or 201
        s, j = self.owner.call("GET", "/api/push")
        self.assertEqual((s, j["devices"], len(W.unb64u(j["key"]))), (200, 0, 65))
        _, _, sub = browser()
        self.assertEqual(self.owner.call("POST", "/api/push/subscribe", {"subscription": dict(sub, endpoint="https://evil.example/x")})[0], 400)
        self.assertEqual(self.owner.call("POST", "/api/push/subscribe", {"subscription": sub})[1], {"devices": 1})
        self.assertEqual(self.owner.call("POST", "/api/push/test")[0], 200)
        self.assertEqual(sent, [ENDPOINT])
        self.assertEqual(self.owner.call("POST", "/api/push/unsubscribe", {"endpoint": ENDPOINT})[1], {"devices": 0})

    def test_a_finished_vryxcode_session_is_pushed(self):
        open_to_everyone(self.state)
        self.state.flags.data["audiences"]["pwa_push"] = "admins"
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(list(vryxcode.DEMO))
        told = []
        self.state.push.send_later = lambda user, title, text, url="/": told.append((user, title, text, url))
        s, j = self.owner.call("POST", "/api/code/start", {"project": "demo", "task": "write slugify with a test", "model": "solstice-2", "auto_edits": True})
        self.assertEqual(s, 200, j)
        wait_for(lambda: told, 30)
        self.assertEqual(told[0], ("owner", "VryxCode", '"demo" finished. Open it to see what it built.', "/#code"))


if __name__ == "__main__":
    unittest.main()
