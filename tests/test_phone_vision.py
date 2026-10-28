"""android_phone_vision: the picture model the Android app downloads so it can look at pictures with the PC off (app/phone_model.py vision_kit)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import hashlib
import http.client
import types

import vision
from tests.test_app_server import Base


class Serving(Base):
    def setUp(self):
        super().setUp()
        self.model, self.proj = b"m" * 300_000, b"p" * 120_000
        paths = []
        for name, data in (("Qwen3-VL-4B-Instruct-Q4_K_M.gguf", self.model), ("mmproj-Qwen3-VL-4B-Instruct-F16.gguf", self.proj)):
            p = os.path.join(self.tmp.name, name)
            with open(p, "wb") as f:
                f.write(data)
            paths.append(p)
        self.state.vision = types.SimpleNamespace(model=paths[0], mmproj=paths[1])
        for p in paths:
            self.state.phone_sha.get(p, wait=True)

    def raw(self, path, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", path, headers=dict({"Authorization": "Bearer " + self.sam_key}, **(headers or {})))
        r = c.getresponse()
        try:
            return r.status, dict(r.getheaders()), r.read()
        finally:
            c.close()

    def test_off_by_default(self):
        self.assertNotEqual(self.sam.call("GET", "/api/phone-model/vision")[0], 200)
        self.assertNotEqual(self.raw("/api/phone-model/vision/file?part=model")[0], 200)

    def test_the_two_files_with_their_checksums_and_resume(self):
        self.state.flags.data["audiences"]["android_phone_vision"] = "everyone"
        s, j = self.sam.call("GET", "/api/phone-model/vision")
        self.assertEqual(s, 200, j)
        self.assertTrue(j["available"])
        self.assertEqual(j["size"], len(self.model) + len(self.proj))
        self.assertEqual(j["parts"]["model"]["sha256"], hashlib.sha256(self.model).hexdigest())
        self.assertEqual(j["parts"]["mmproj"]["size"], len(self.proj))
        self.assertEqual(j["prompt"], vision.PROMPT)                                          # the same instructions the PC's picture helper gets
        self.assertNotIn("Qwen", str(j))                                                      # the base model is never named to people
        s, _, body = self.raw(j["parts"]["mmproj"]["file"])
        self.assertEqual((s, body), (200, self.proj))
        s, h, body = self.raw(j["parts"]["model"]["file"], {"Range": "bytes=1000-"})
        self.assertEqual((s, body), (206, self.model[1000:]))
        self.assertEqual(self.raw("/api/phone-model/vision/file?part=other")[0], 404)

    def test_no_picture_model_on_the_pc_says_so(self):
        self.state.flags.data["audiences"]["android_phone_vision"] = "everyone"
        self.state.vision = None
        s, j = self.sam.call("GET", "/api/phone-model/vision")
        self.assertEqual(s, 200)
        self.assertFalse(j["available"])
        self.assertIn("picture", j["message"])
        self.assertEqual(self.raw("/api/phone-model/vision/file?part=model")[0], 404)


if __name__ == "__main__":
    import unittest
    unittest.main()
