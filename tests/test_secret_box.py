"""Encrypted saved tokens (secret_box.py, github_link.Store) and GitHub's device sign-in."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import private_files  # noqa: E402
import json
import os
import stat
import tempfile
import time
import unittest
from unittest import mock

import github_link as G
import secret_box
from tests.test_app_server import Base, Client

TOKEN = "ghp_" + "Zz9Yy8Xx7W" * 4


class Box(unittest.TestCase):
    def test_round_trip_and_the_key_file_is_private(self):
        with tempfile.TemporaryDirectory() as d:
            box = secret_box.SecretBox(d)
            blob = box.encrypt(TOKEN)
            self.assertTrue(blob.startswith("enc1:"))
            self.assertNotIn(TOKEN, blob)
            self.assertEqual(box.decrypt(blob), TOKEN)
            self.assertTrue(private_files.is_private(os.path.join(d, "secret.key"), mode=0o600))
            again = secret_box.SecretBox(d)                                    # the same key is read back
            self.assertEqual(again.decrypt(blob), TOKEN)

    def test_a_different_key_cannot_read_it(self):
        a, b = secret_box.SecretBox(tempfile.mkdtemp()), secret_box.SecretBox(tempfile.mkdtemp())
        self.assertIsNone(b.decrypt(a.encrypt("hello")))
        self.assertIsNone(b.decrypt("enc1:garbage"))

    def test_the_key_can_come_from_the_environment_instead_of_a_file(self):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        with tempfile.TemporaryDirectory() as d:
            box = secret_box.SecretBox(d, env_key=key)
            self.assertFalse(os.path.exists(os.path.join(d, "secret.key")))
            self.assertEqual(secret_box.SecretBox(None, env_key=key).decrypt(box.encrypt("x")), "x")

    def test_a_bad_key_is_a_plain_error(self):
        with self.assertRaises(secret_box.SecretError):
            secret_box.SecretBox(None, env_key="not a key")

    def test_without_the_package_values_are_kept_plain_unless_encryption_is_required(self):
        with mock.patch.object(secret_box, "Fernet", None):
            box = secret_box.SecretBox(None)
            self.assertFalse(box.available)
            self.assertEqual(box.decrypt(box.encrypt("hello")), "hello")
            with self.assertRaises(secret_box.SecretError):
                secret_box.SecretBox(None, require=True).encrypt("hello")


class StoreOnDisk(unittest.TestCase):
    def test_the_token_is_never_in_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            s = G.Store(d)
            s.connect("sam", TOKEN, "sam", 7)
            s.log("sam", "pushed x")
            raw = open(s._path("sam")).read()
            self.assertNotIn(TOKEN, raw)
            self.assertIn("token_enc", raw)
            self.assertEqual(s.get("sam")["token"], TOKEN)
            self.assertNotIn(TOKEN, json.dumps(s.public("sam")))

    def test_an_older_plain_file_is_used_and_re_saved_encrypted(self):
        with tempfile.TemporaryDirectory() as d:
            s = G.Store(d)
            os.makedirs(os.path.join(d, "github"))
            json.dump({"token": TOKEN, "login": "sam", "id": 7, "log": []}, open(s._path("sam"), "w"))
            self.assertEqual(s.get("sam")["token"], TOKEN)
            self.assertNotIn(TOKEN, open(s._path("sam")).read())

    def test_a_changed_key_means_connect_again_not_a_crash(self):
        d = tempfile.mkdtemp()
        G.Store(d).connect("sam", TOKEN, "sam", 7)
        os.remove(os.path.join(d, "secret.key"))                              # a new key is made: the old token cannot be read
        s = G.Store(d)
        got = s.get("sam")
        self.assertTrue(got.get("unreadable"))
        self.assertFalse(s.connected("sam"))


def device_http(state):
    def http(method, url, headers, body):
        data = json.loads(body) if body else {}
        if url == G.DEVICE_CODE_URL:
            return 200, {"device_code": "DEVSECRET", "user_code": "ABCD-1234", "verification_uri": "https://github.com/login/device", "expires_in": 900, "interval": 5}
        if url == G.DEVICE_TOKEN_URL:
            state["polls"].append(data)
            return 200, state["answers"].pop(0) if state["answers"] else {"error": "authorization_pending"}
        if url.endswith("/user"):
            return 200, {"login": "sam", "id": 7}
        return 404, {}
    return http


class DeviceSignIn(Base):
    data_dir = True

    def setUp(self):
        super().setUp()
        self.fake = {"polls": [], "answers": []}
        self.state.github_http = device_http(self.fake)
        self.state.security["github_client_id"] = "Iv1.abcdef123456"

    def test_not_set_up_without_a_client_id(self):
        self.state.security["github_client_id"] = ""
        st, j = self.owner.call("POST", "/api/apps/github/device/start", {})
        self.assertEqual(st, 400)
        self.assertIn("isn't set up", j["message"])
        self.assertFalse(self.owner.call("GET", "/api/apps")[1]["connections"]["github"]["device"])

    def test_the_person_gets_a_code_and_the_device_code_stays_on_the_server(self):
        st, j = self.owner.call("POST", "/api/apps/github/device/start", {})
        self.assertEqual(st, 200)
        self.assertEqual(j["user_code"], "ABCD-1234")
        self.assertNotIn("DEVSECRET", json.dumps(j))
        self.assertTrue(self.owner.call("GET", "/api/apps")[1]["connections"]["github"]["device"])

    def test_polling_waits_then_connects_and_stores_the_token_encrypted(self):
        self.owner.call("POST", "/api/apps/github/device/start", {})
        pend = self.state.github_device["owner"]
        pend["last"] = 0
        self.fake["answers"] = [{"error": "authorization_pending"}]
        st, j = self.owner.call("POST", "/api/apps/github/device/poll", {})
        self.assertEqual(j["status"], "pending")
        st, j = self.owner.call("POST", "/api/apps/github/device/poll", {})              # too soon: GitHub is not asked again
        self.assertEqual(j["status"], "pending")
        self.assertEqual(len(self.fake["polls"]), 1)
        pend["last"] = 0
        self.fake["answers"] = [{"access_token": TOKEN}]
        st, j = self.owner.call("POST", "/api/apps/github/device/poll", {})
        self.assertEqual((st, j["status"], j["connected"], j["login"]), (200, "done", True, "sam"))
        self.assertNotIn(TOKEN, json.dumps(j))
        self.assertNotIn(TOKEN, open(self.state.github._path("owner")).read())
        self.assertEqual(self.state.github.get("owner")["token"], TOKEN)
        self.assertIn("github_connected", {e["kind"] for e in self.state.auth.events()})

    def test_slow_down_denied_and_expired(self):
        self.owner.call("POST", "/api/apps/github/device/start", {})
        pend = self.state.github_device["owner"]
        pend["last"] = 0
        self.fake["answers"] = [{"error": "slow_down"}]
        self.owner.call("POST", "/api/apps/github/device/poll", {})
        self.assertEqual(pend["interval"], 10)
        pend["last"] = 0
        self.fake["answers"] = [{"error": "access_denied"}]
        self.assertEqual(self.owner.call("POST", "/api/apps/github/device/poll", {})[1]["status"], "denied")
        self.assertEqual(self.owner.call("POST", "/api/apps/github/device/poll", {})[0], 400)       # nothing in progress now

    def test_each_person_has_their_own_sign_in(self):
        self.owner.call("POST", "/api/apps/github/device/start", {})
        self.assertEqual(self.sam.call("POST", "/api/apps/github/device/poll", {})[0], 400)


if __name__ == "__main__":
    unittest.main()
