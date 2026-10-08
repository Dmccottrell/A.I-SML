"""Pictures in the chat: sent with the message, shown with it, looked at by the vision helper when there is one (vision.py)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import base64
import io
import json
import unittest

import documents as D
import vision as V
from tests.test_app_server import Base


def png():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, "PNG")
    return buf.getvalue()


class FakeHelper(V.VisionHelper):
    def __init__(self, reply="A chat screenshot. The text says: I never said that."):
        super().__init__(url="http://fake")
        self.reply, self.calls = reply, []

    def _post(self, url, body):
        self.calls.append(body)
        return {"choices": [{"message": {"content": self.reply}}]}


class Helper(unittest.TestCase):
    def test_picture_goes_to_the_helper_as_a_data_uri_with_the_question(self):
        h = FakeHelper("<think>hm</think>A receipt. Total: $4.20")
        text = h.describe(1, png(), "image/png", "How much was it?")
        self.assertEqual(text, "A receipt. Total: $4.20")
        parts = h.calls[0]["messages"][0]["content"]
        self.assertTrue(parts[0]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertIn("How much was it?", parts[1]["text"])

    def test_same_picture_and_question_is_asked_once(self):
        h = FakeHelper()
        h.describe(1, png(), "image/png", "what is this")
        h.describe(1, png(), "image/png", "what is this")
        self.assertEqual(len(h.calls), 1)

    def test_not_available_without_files(self):
        self.assertFalse(V.VisionHelper(None, "/no/model.gguf", "/no/mmproj.gguf").available())

    def test_discover_finds_model_and_projector(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            d = os.path.join(root, V.VISION_DIR)
            os.makedirs(d)
            for n in ("model-f16.gguf", "model-q4_k_m.gguf", "mmproj-model-f16.gguf"):
                open(os.path.join(d, n), "wb").close()
            m, p = V.discover(root)
            self.assertTrue(m.endswith("model-q4_k_m.gguf"))
            self.assertTrue(p.endswith("mmproj-model-f16.gguf"))
            self.assertEqual(V.discover(os.path.join(root, "nowhere")), (None, None))


class InChat(Base):
    def setUp(self):
        self.factory = lambda model, question: self._backend(question)
        super().setUp()
        self.saved_ocr = D._ocr
        D._ocr = lambda b: ([[[[0, 0], [50, 0], [50, 10], [0, 10]], "he said it", 0.9]], None)

    def _backend(self, question):
        import app_engine as E
        self.state_backend = E.FakeBackend()
        return self.state_backend

    def tearDown(self):
        D._ocr = self.saved_ocr
        super().tearDown()

    def add_picture(self, who, name="shot.png"):
        s, j = who.call("POST", "/api/documents", {"name": name, "data": base64.b64encode(png()).decode()})
        self.assertEqual(s, 200, j)
        return j["id"]

    def test_picture_travels_with_the_message_and_is_shown_with_it(self):
        did = self.add_picture(self.sam)
        cid = self.new_chat(self.sam)
        self.sam.call("POST", f"/api/chats/{cid}/docs", {"ids": [did]})
        ev = self.ask(self.sam, cid, "Did he say this?")[2]
        notes = [d for e, d in ev if e == "notes"]
        self.assertEqual(notes[0]["ocr"], 1)                          # no vision helper: only the words were read, and the page says so
        msgs = self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"]
        self.assertEqual([d["id"] for d in msgs[0]["docs"]], [did])  # shown with the message that carried it
        ev2 = self.ask(self.sam, cid, "And the second part?")[2]
        msgs = self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"]
        self.assertEqual(msgs[2]["docs"], [])                         # a picture goes with one message, not every later one

    def test_helper_looks_at_the_picture(self):
        helper = FakeHelper()
        self.state.vision = helper
        did = self.add_picture(self.sam)
        cid = self.new_chat(self.sam)
        self.sam.call("POST", f"/api/chats/{cid}/docs", {"ids": [did]})
        ev = self.ask(self.sam, cid, "Did he actually say this?")[2]
        self.assertEqual([d for e, d in ev if e == "notes"][0]["pictures"], 1)
        self.assertIn("Did he actually say this?", helper.calls[0]["messages"][0]["content"][1]["text"])

    def test_a_picture_the_helper_could_not_read_and_with_no_text_is_said_plainly(self):
        class Broken(FakeHelper):
            def _post(self, url, body):
                raise OSError("the picture reader stopped")
        D._ocr = lambda b: ([], None)                                  # no words in the picture
        self.state.vision = Broken()                                   # a helper exists, so the picture is accepted ...
        did = self.add_picture(self.sam, "blurry.png")
        cid = self.new_chat(self.sam)
        self.sam.call("POST", f"/api/chats/{cid}/docs", {"ids": [did]})
        ev = self.ask(self.sam, cid, "What does this say?")[2]         # ... but it fails when asked: the model must not answer around it
        note = [d for e, d in ev if e == "notes"][0]
        self.assertEqual(note["unreadable"], ["blurry.png"])
        prompt = self.state.tok_for({"id": "flare-2"}).decode(self.state_backend.prompts[-1])
        self.assertIn("Could not read", prompt)
        self.assertIn("Do not guess what it says", prompt)

    def test_picture_can_be_fetched_by_its_owner_only(self):
        did = self.add_picture(self.sam)
        s, h, body = self.sam.call("GET", f"/api/documents/{did}/image", raw=True)
        self.assertEqual((s, h["Content-Type"]), (200, "image/png"))
        self.assertEqual(body, png())
        self.assertEqual(self.owner.call("GET", f"/api/documents/{did}/image")[0], 404)   # someone else's library has no such picture


if __name__ == "__main__":
    unittest.main()
