"""Passkeys (WebAuthn): checked against a software authenticator that builds real registration and sign-in replies."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import hashlib
import json
import struct
import unittest

import passkeys as P
from tests.test_app_server import Base, Client
from tests.test_signin import cookie_of

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
except ImportError:                                           # pragma: no cover
    ec = None


def cbor(v):
    """The small CBOR writer a software authenticator needs."""
    def head(major, n):
        if n < 24:
            return bytes([major << 5 | n])
        for info, size in ((24, 1), (25, 2), (26, 4)):
            if n < 1 << (8 * size):
                return bytes([major << 5 | info]) + n.to_bytes(size, "big")
    if isinstance(v, bool):
        return bytes([0xF5 if v else 0xF4])
    if isinstance(v, int):
        return head(0, v) if v >= 0 else head(1, -1 - v)
    if isinstance(v, bytes):
        return head(2, len(v)) + v
    if isinstance(v, str):
        return head(3, len(v.encode())) + v.encode()
    if isinstance(v, list):
        return head(4, len(v)) + b"".join(cbor(x) for x in v)
    return head(5, len(v)) + b"".join(cbor(k) + cbor(x) for k, x in v.items())


class Authenticator:
    """A phone's passkey, in software."""

    def __init__(self, rp_id, origin, kind="es256", counter=0, uv=True):
        self.rp_id, self.origin, self.counter, self.uv, self.kind = rp_id, origin, counter, uv, kind
        self.cred_id = os.urandom(16)
        self.key = ec.generate_private_key(ec.SECP256R1()) if kind == "es256" else rsa.generate_private_key(65537, 2048)

    def _flags(self, at):
        return 0x01 | (0x04 if self.uv else 0) | (0x40 if at else 0)

    def _cose(self):
        n = self.key.public_key().public_numbers()
        if self.kind == "es256":
            return {1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")}
        return {1: 3, 3: -257, -1: n.n.to_bytes(256, "big"), -2: n.e.to_bytes(3, "big")}

    def create(self, challenge, origin=None, rp_id=None):
        auth = hashlib.sha256((rp_id or self.rp_id).encode()).digest() + bytes([self._flags(True)]) + struct.pack(">I", self.counter) + b"\0" * 16 \
            + struct.pack(">H", len(self.cred_id)) + self.cred_id + cbor(self._cose())
        cd = json.dumps({"type": "webauthn.create", "challenge": challenge, "origin": origin or self.origin}).encode()
        return {"id": P.b64u(self.cred_id), "clientDataJSON": P.b64u(cd), "attestationObject": P.b64u(cbor({"fmt": "none", "attStmt": {}, "authData": auth}))}

    def get(self, challenge, origin=None, counter=None, tamper=False):
        self.counter = self.counter + 1 if counter is None else counter
        auth = hashlib.sha256(self.rp_id.encode()).digest() + bytes([self._flags(False)]) + struct.pack(">I", self.counter)
        cd = json.dumps({"type": "webauthn.get", "challenge": challenge, "origin": origin or self.origin}).encode()
        signed = auth + hashlib.sha256(cd).digest()
        sig = self.key.sign(signed, ec.ECDSA(hashes.SHA256())) if self.kind == "es256" else self.key.sign(signed, padding.PKCS1v15(), hashes.SHA256())
        if tamper:
            sig = sig[:-1] + bytes([sig[-1] ^ 1])
        return {"id": P.b64u(self.cred_id), "clientDataJSON": P.b64u(cd), "authenticatorData": P.b64u(auth), "signature": P.b64u(sig), "userHandle": ""}


@unittest.skipIf(ec is None, "cryptography is not installed")
class Pieces(unittest.TestCase):
    def test_cbor_reads_what_it_writes(self):
        v = {"a": [1, -5, b"xy", "hi", True], 3: {1: 2}, -1: 70000}
        self.assertEqual(P.cbor_decode(cbor(v))[0], v)
        with self.assertRaises(P.PasskeyError):
            P.cbor_decode(b"\xa5\x01")                                 # a map that stops short

    def test_registration_and_sign_in_for_both_key_types(self):
        for kind in ("es256", "rs256"):
            a = Authenticator("chat.emvryx.app", "https://chat.emvryx.app", kind)
            pk = P.verify_registration(a.create("CH1"), "CH1", "https://chat.emvryx.app", "chat.emvryx.app")
            self.assertEqual(pk["id"], P.b64u(a.cred_id))
            self.assertEqual(P.verify_assertion(a.get("CH2"), pk, "CH2", "https://chat.emvryx.app", "chat.emvryx.app"), 1)

    def test_every_check_can_fail(self):
        a = Authenticator("chat.emvryx.app", "https://chat.emvryx.app")
        ok = ("CH", "https://chat.emvryx.app", "chat.emvryx.app")
        pk = P.verify_registration(a.create("CH"), *ok)
        bad = [lambda: P.verify_registration(a.create("OTHER"), *ok),                                                   # wrong challenge
               lambda: P.verify_registration(a.create("CH", origin="https://evil.example"), *ok),                       # wrong origin
               lambda: P.verify_registration(a.create("CH", rp_id="evil.example"), *ok),                               # made for another site
               lambda: P.verify_registration(Authenticator("chat.emvryx.app", "https://chat.emvryx.app", uv=False).create("CH"), *ok),   # no fingerprint/face/PIN
               lambda: P.verify_assertion(a.get("CH", tamper=True), pk, *ok),                                           # bad signature
               lambda: P.verify_assertion(a.get("CH", counter=0), dict(pk, counter=5), *ok),                            # counter went backwards
               lambda: P.verify_assertion(a.get("X"), pk, *ok)]                                                         # wrong challenge
        for f in bad:
            with self.assertRaises(P.PasskeyError):
                f()


@unittest.skipIf(ec is None, "cryptography is not installed")
class Flow(Base):
    data_dir = True
    PW = "correct horse battery"

    def setUp(self):
        super().setUp()
        self.state.security["public_url"] = "https://chat.emvryx.app"
        self.state.set_password("sam", self.PW)
        st, h, _ = Client(self.port).call("POST", "/api/login/password", {"id": "sam", "password": self.PW}, raw=True)
        self.me = Client(self.port)
        self.me.cookie = cookie_of(h)
        self.anon = Client(self.port)
        self.phone = Authenticator("chat.emvryx.app", "https://chat.emvryx.app")

    def register(self, phone=None, name="My phone"):
        phone = phone or self.phone
        st, opts = self.me.call("POST", "/api/account/passkey/begin", {"password": self.PW})
        self.assertEqual(st, 200, opts)
        self.assertEqual(opts["rp"]["id"], "chat.emvryx.app")
        self.assertEqual(opts["authenticatorSelection"]["userVerification"], "required")
        return self.me.call("POST", "/api/account/passkey/finish", {"credential": phone.create(opts["challenge"]), "name": name})

    def sign_in(self, phone=None, **kw):
        phone = phone or self.phone
        st, opts = self.anon.call("POST", "/api/login/passkey/begin", {})
        self.assertEqual((st, opts["rpId"], opts["allowCredentials"]), (200, "chat.emvryx.app", []))
        return self.anon.call("POST", "/api/login/passkey/finish", {"credential": phone.get(opts["challenge"], **kw)}, raw=True)

    def test_make_a_passkey_then_sign_in_with_it(self):
        st, j = self.register()
        self.assertEqual((st, j["passkeys"][0]["name"]), (200, "My phone"))
        self.assertEqual(self.me.call("GET", "/api/account")[1]["passkeys"][0]["name"], "My phone")
        st, h, _ = self.sign_in()
        self.assertEqual(st, 200)
        c = Client(self.port)
        c.cookie = cookie_of(h)
        self.assertEqual(c.call("GET", "/api/state")[1]["user"], "sam")
        self.assertNotIn("pem", json.dumps(self.me.call("GET", "/api/account")[1]))        # the key itself is never sent back

    def test_a_passkey_skips_the_code_because_it_is_already_two_factors(self):
        import accounts, time
        secret = accounts.new_secret()
        self.state._mfa_pending["sam"] = {"secret": secret, "expires": time.time() + 900}
        self.state.mfa_enable("sam", accounts.code_at(secret, int(time.time() // 30)))
        st, opts = self.me.call("POST", "/api/account/passkey/begin", {"password": self.PW, "code": accounts.code_at(secret, int(time.time() // 30) + 1)})
        self.assertEqual(st, 200, opts)
        self.assertEqual(self.me.call("POST", "/api/account/passkey/finish", {"credential": self.phone.create(opts["challenge"])})[0], 200)
        st, h, body = self.sign_in()
        self.assertEqual(st, 200)
        self.assertNotIn(b"mfa", body)

    def test_adding_one_asks_for_the_password_again(self):
        self.assertEqual(self.me.call("POST", "/api/account/passkey/begin", {})[0], 400)
        self.assertEqual(self.me.call("POST", "/api/account/passkey/begin", {"password": "nope nope nope"})[0], 400)

    def test_replays_forgeries_and_strangers_are_refused(self):
        self.register()
        st, opts = self.anon.call("POST", "/api/login/passkey/begin", {})
        reply = self.phone.get(opts["challenge"])
        self.assertEqual(self.anon.call("POST", "/api/login/passkey/finish", {"credential": reply}, raw=True)[0], 200)
        self.assertEqual(self.anon.call("POST", "/api/login/passkey/finish", {"credential": reply}, raw=True)[0], 401)       # a challenge works once
        self.assertEqual(self.sign_in(tamper=True)[0], 401)
        self.assertEqual(self.sign_in(origin="https://evil.example")[0], 401)
        stranger = Authenticator("chat.emvryx.app", "https://chat.emvryx.app")                                              # never registered
        self.assertEqual(self.sign_in(stranger)[0], 401)

    def test_a_banned_person_cannot_use_a_passkey_and_removing_it_works(self):
        self.register()
        st, j = self.me.call("POST", "/api/account/passkey/delete", {"id": P.b64u(self.phone.cred_id), "password": self.PW})
        self.assertEqual((st, j["passkeys"]), (200, []))
        self.assertEqual(self.sign_in()[0], 401)
        self.register()
        self.state.set_ban("sam", True)
        self.assertEqual(self.sign_in()[0], 403)

    def test_a_passkey_made_for_another_address_is_refused_at_registration(self):
        st, opts = self.me.call("POST", "/api/account/passkey/begin", {"password": self.PW})
        bad = Authenticator("evil.example", "https://evil.example")
        self.assertEqual(self.me.call("POST", "/api/account/passkey/finish", {"credential": bad.create(opts["challenge"])})[0], 400)

    def test_options_say_passkeys_are_on(self):
        self.assertTrue(self.anon.call("GET", "/api/auth-options")[1]["passkeys"])


if __name__ == "__main__":
    unittest.main()
