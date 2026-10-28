"""android_offline_model: the model the Android app downloads and runs itself when the PC is off (app/phone_model.py)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import hashlib
import http.client
import os
import tempfile
import types
import unittest

import phone_model
from tests.test_app_server import Base


class Picking(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def file(self, name, data=b"gguf"):
        p = os.path.join(self.tmp.name, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_the_newest_small_open_model_with_a_file_is_picked(self):
        man = {"models": [{"id": "flare-2", "tier": "Lite", "version": 2},                       # not an open model (the old format)
                          {"id": "flare-2.5", "tier": "Lite", "version": 2.5, "open": True},
                          {"id": "flare-3", "tier": "Lite", "version": 3, "open": True},
                          {"id": "equinox-3", "tier": "Standard", "version": 3, "open": True}]}
        files = {m["id"]: self.file(m["id"]) for m in man["models"]}
        self.assertEqual(phone_model.pick(man, files)["id"], "flare-3")
        del files["flare-3"]
        self.assertEqual(phone_model.pick(man, files)["id"], "flare-2.5")         # no file for the newest: the one that is there
        self.assertIsNone(phone_model.pick(man, {}))
        man["phone_model"] = "equinox-3"
        self.assertEqual(phone_model.pick(man, files)["id"], "equinox-3")           # models.json can choose

    def test_the_checksum_is_worked_out_once_and_kept(self):
        p = self.file("m.gguf", b"x" * 3_000_000)
        c = phone_model.Checksums(self.tmp.name)
        self.assertEqual(c.get(p, wait=True), hashlib.sha256(b"x" * 3_000_000).hexdigest())
        again = phone_model.Checksums(self.tmp.name)                                # after a restart: no second pass over 2 GB
        self.assertEqual(again.known, c.known)

    def test_ranges(self):
        self.assertIsNone(phone_model.byte_range("", 100))
        self.assertEqual(phone_model.byte_range("bytes=40-", 100), (40, 99))
        self.assertEqual(phone_model.byte_range("bytes=0-9", 100), (0, 9))
        self.assertEqual(phone_model.byte_range("bytes=100-", 100), "bad")

    def test_the_format_is_the_chat_format_the_pc_uses(self):
        import chat
        import open_tokenizer
        f = phone_model.chat_format({"think": "empty"})
        self.assertEqual(f["assistant_open"], "<|im_start|>assistant\n" + open_tokenizer.OpenTokenizer.EMPTY_THINK)
        self.assertEqual(phone_model.chat_format({})["assistant_open"], "<|im_start|>assistant\n")
        # the notes go in front of the question exactly as core/chat.py writes them for ChatML
        self.assertIn('"Notes:\\n" + format_notes(notes) + "\\n\\nQuestion: "', open(chat.__file__, encoding="utf-8").read())
        self.assertEqual(f["notes_intro"] + "[1] A: b" + f["question_intro"] + "Q", "Notes:\n" + chat.format_notes([{"title": "A", "text": "b"}]) + "\n\nQuestion: Q")


class Serving(Base):
    def setUp(self):
        super().setUp()
        self.data = bytes(range(256)) * 4000                                        # about 1 MB
        self.path = os.path.join(self.tmp.name, "flare-3.gguf")
        with open(self.path, "wb") as f:
            f.write(self.data)
        self.state.runner = types.SimpleNamespace(files={"flare-3": self.path})

    def raw(self, path, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", path, headers=dict({"Authorization": "Bearer " + self.sam_key}, **(headers or {})))
        r = c.getresponse()
        try:
            return r.status, dict(r.getheaders()), r.read()
        finally:
            c.close()

    def test_off_by_default(self):
        s, _ = self.sam.call("GET", "/api/phone-model")
        self.assertNotEqual(s, 200)
        self.assertNotEqual(self.raw("/api/phone-model/file")[0], 200)

    def test_the_kit_and_the_file_with_resume(self):
        self.state.flags.data["audiences"]["android_offline_model"] = "everyone"
        self.sam.call("POST", "/api/settings", {"custom_instructions": "Keep answers short."})
        self.sam.call("POST", "/api/memory/add", {"text": "My dog is called Rex."})
        self.state.phone_sha.get(self.path, wait=True)
        s, j = self.sam.call("GET", "/api/phone-model")
        self.assertEqual(s, 200)
        self.assertTrue(j["available"])
        self.assertEqual(j["id"], "flare-3")
        self.assertEqual(j["size"], len(self.data))
        self.assertEqual(j["sha256"], hashlib.sha256(self.data).hexdigest())
        self.assertIn("Keep answers short.", j["hints"])
        self.assertEqual(j["memory"]["facts"], ["My dog is called Rex."])
        self.assertNotIn("base", j)
        self.assertNotIn("Qwen", str(j))                                            # the base model is never named to people
        s, h, body = self.raw("/api/phone-model/file")
        self.assertEqual((s, body), (200, self.data))
        s, h, body = self.raw("/api/phone-model/file", {"Range": "bytes=1000-"})   # a download that stopped carries on
        self.assertEqual(s, 206)
        self.assertEqual(body, self.data[1000:])
        self.assertEqual(h["Content-Range"], f"bytes 1000-{len(self.data) - 1}/{len(self.data)}")
        self.assertEqual(self.raw("/api/phone-model/file", {"Range": f"bytes={len(self.data)}-"})[0], 416)

    def test_no_model_file_says_so(self):
        self.state.flags.data["audiences"]["android_offline_model"] = "everyone"
        self.state.runner = None
        s, j = self.sam.call("GET", "/api/phone-model")
        self.assertEqual(s, 200)
        self.assertFalse(j["available"])

    def test_signed_out_gets_nothing(self):
        self.state.flags.data["audiences"]["android_offline_model"] = "everyone"
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/api/phone-model/file")
        self.assertNotEqual(c.getresponse().status, 200)
        c.close()



class Syncing(Base):
    data_dir = True

    def sync(self, body, who=None):
        return (who or self.sam).call("POST", "/api/phone-sync", body)

    def test_off_by_default(self):
        self.assertNotEqual(self.sync({"sync_id": "a", "messages": [{"role": "user", "content": "hi"}]})[0], 200)

    def test_a_phone_chat_becomes_a_normal_chat_and_a_retry_adds_nothing(self):
        self.state.flags.data["audiences"]["android_offline_model"] = "everyone"
        body = {"sync_id": "s1", "title": "Tides", "model": "flare-3",
                "messages": [{"role": "user", "content": "why do tides happen"}, {"role": "assistant", "content": "The Moon pulls the sea."}]}
        s, j = self.sync(body)
        self.assertEqual(s, 200, j)
        cid = j["chat"]
        chat = self.sam.call("GET", f"/api/chats/{cid}")[1]
        self.assertEqual(chat["title"], "Tides")
        self.assertEqual([(m["role"], m["content"]) for m in chat["messages"]], [("user", "why do tides happen"), ("assistant", "The Moon pulls the sea.")])
        self.assertEqual(chat["messages"][1]["model_id"], "phone:flare-3")
        self.assertEqual(self.sync(body)[1]["chat"], cid)                                    # the phone lost the answer and tried again
        self.assertEqual(len(self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"]), 2)
        self.assertIn(cid, [c["id"] for c in self.sam.call("GET", "/api/state")[1]["chats"]])

    def test_carrying_on_a_pc_chat(self):
        self.state.flags.data["audiences"]["android_offline_model"] = "everyone"
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "hello")
        s, j = self.sync({"sync_id": "s2", "chat": cid, "messages": [{"role": "user", "content": "and then?"}, {"role": "assistant", "content": "Then this."}]})
        self.assertEqual(j["chat"], cid)
        self.assertEqual([m["content"] for m in self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"]][-2:], ["and then?", "Then this."])

    def test_someone_elses_chat_is_never_written(self):
        self.state.flags.data["audiences"]["android_offline_model"] = "everyone"
        theirs = self.new_chat(self.owner)
        s, j = self.sync({"sync_id": "s3", "chat": theirs, "messages": [{"role": "user", "content": "x"}]})
        self.assertEqual(s, 200)                                                             # each person's chats are their own: it became a new chat of sam's
        self.assertIn(j["chat"], [c["id"] for c in self.sam.call("GET", "/api/state")[1]["chats"]])
        self.assertEqual(len(self.owner.call("GET", f"/api/chats/{theirs}")[1]["messages"]), 0)

    def test_bad_input(self):
        self.state.flags.data["audiences"]["android_offline_model"] = "everyone"
        self.assertEqual(self.sync({"messages": [{"role": "user", "content": "x"}]})[0], 400)            # no sync id
        self.assertEqual(self.sync({"sync_id": "e", "messages": [{"role": "system", "content": "x"}]})[0], 400)
        self.assertEqual(self.sync({"sync_id": "e2", "messages": []})[0], 400)


if __name__ == "__main__":
    unittest.main()
