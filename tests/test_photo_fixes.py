"""Photos, native (flag photo_fixes): a photo goes straight to a model that can see, the right way up, in a format and size the model opens,
a photo with no words is accepted whenever a model can look at it, and the model is told to be exact about what it sees."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import base64
import io
import unittest

import documents as D
import flags
from tests.test_app_server import Base


def picture(fmt="PNG", size=(64, 48), turn=None, colour=(30, 120, 200)):
    from PIL import Image
    img, buf, extra = Image.new("RGB", size, colour), io.BytesIO(), {}
    if turn:
        exif = Image.Exif()
        exif[0x0112] = turn
        extra["exif"] = exif
    img.save(buf, fmt, **extra)
    return buf.getvalue()


def opened(data):
    from PIL import Image
    img = Image.open(io.BytesIO(data))
    return img.format, img.size


class Cleaning(unittest.TestCase):
    def test_the_flag_starts_with_the_owner_and_admins(self):
        self.assertEqual(flags.BY_ID["photo_fixes"]["default"], "admins")

    def test_formats_the_model_cannot_open_become_jpeg(self):
        for fmt, name in (("WEBP", "a.webp"), ("BMP", "b.bmp"), ("GIF", "c.gif")):
            new, data = D.clean_picture(name, picture(fmt))
            self.assertIn(opened(data)[0], ("JPEG", "PNG"), fmt)
            self.assertTrue(new.endswith((".jpg", ".png")), new)

    def test_a_sideways_phone_photo_is_turned_upright(self):
        new, data = D.clean_picture("photo.jpg", picture("JPEG", (400, 300), turn=6))     # "turn 90 degrees" note from the camera
        self.assertEqual(opened(data), ("JPEG", (300, 400)))

    def test_a_big_photo_is_made_smaller_and_a_normal_one_is_left_alone(self):
        _, big = D.clean_picture("big.jpg", picture("JPEG", (4000, 3000)))
        self.assertEqual(max(opened(big)[1]), D.STORE_SIDE)
        small = picture("PNG")
        self.assertEqual(D.clean_picture("s.png", small), ("s.png", small))

    def test_what_the_model_gets_is_sized_for_it(self):
        self.assertEqual(max(opened(D.picture_for_model(picture("JPEG", (3000, 2000))))[1]), D.MODEL_SIDE)
        small = picture("PNG")
        self.assertIs(D.picture_for_model(small), small)
        self.assertEqual(D.picture_for_model(b"not a picture"), b"not a picture")

    def test_a_screenshot_stays_png_so_small_text_stays_sharp(self):
        _, data = D.clean_picture("shot.png", picture("PNG", (3000, 2000)))
        self.assertEqual(opened(data)[0], "PNG")

    def test_something_that_is_not_a_picture_says_how_to_send_it(self):
        with self.assertRaises(ValueError) as cm:
            D.clean_picture("x.heic", b"not really a heic")
        self.assertIn("JPG or PNG", str(cm.exception))

    def test_the_model_is_told_to_be_exact(self):
        self.assertIn("never make up".lower(), D.picture_hint(accurate=True).lower())
        self.assertNotIn("Never make up", D.picture_hint())


class InChat(Base):
    def setUp(self):
        self.factory = lambda model, question: self._backend(model)
        super().setUp()
        self.saved_ocr = D._ocr
        D._ocr = lambda b: ([], None)                                     # a photo with no words in it
        self.used = []

    def tearDown(self):
        D._ocr = self.saved_ocr
        super().tearDown()

    def _backend(self, model):
        import app_engine as E
        self.used.append(model["id"])
        self.backend = E.FakeBackend("A blue square.")
        return self.backend

    def upload(self, name, data):
        return self.sam.call("POST", "/api/documents", {"name": name, "data": base64.b64encode(data).decode()})

    def test_a_photo_with_no_words_is_refused_without_the_fix_when_only_a_model_can_see(self):
        self.state.seeing = {"apogee-3"}
        s, j = self.upload("dog.jpg", picture("JPEG"))
        self.assertEqual(s, 400)                                          # the old message: "can't describe photos yet"
        self.state.flags.data["audiences"]["photo_fixes"] = "everyone"
        s, j = self.upload("dog.jpg", picture("JPEG"))
        self.assertEqual(s, 200, j)

    def test_a_webp_is_stored_as_a_picture_the_model_can_open(self):
        self.state.seeing = {"apogee-3"}
        self.state.flags.data["audiences"]["photo_fixes"] = "everyone"
        s, j = self.upload("cat.webp", picture("WEBP"))
        self.assertEqual(s, 200, j)
        self.assertTrue(j["name"].endswith((".jpg", ".png")))

    def test_a_model_that_cannot_see_hands_the_photo_to_one_that_can(self):
        self.state.flags.data["audiences"]["photo_fixes"] = "everyone"
        cards = [c for c in self.state.catalog(self.state.who(self.sam_key))["cards"] if c.get("state") == "ready"]
        if len(cards) < 2:
            self.skipTest("needs two ready models in the test catalog")
        blind, seer = cards[0], cards[-1]
        self.state.seeing = {seer["id"]}
        s, j = self.upload("dog.jpg", picture("JPEG", (3000, 2000)))
        self.assertEqual(s, 200, j)
        cid = self.new_chat(self.sam)
        self.sam.call("POST", f"/api/chats/{cid}/docs", {"ids": [j["id"]]})
        self.ask(self.sam, cid, "What colour is this?", model=blind["id"])
        self.assertEqual(self.used[-1], seer["id"])
        sent = self.backend.prompts[-1]
        self.assertIsInstance(sent, dict)
        self.assertLessEqual(max(opened(base64.b64decode(sent["multimodal_data"][0]))[1]), D.MODEL_SIDE)
        self.assertIn("Be exact about the picture", sent["prompt_string"])
        msgs = self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"]
        self.assertEqual(msgs[-1]["model_id"], seer["id"])                  # the answer says which model wrote it


if __name__ == "__main__":
    unittest.main()
