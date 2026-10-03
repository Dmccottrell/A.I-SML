"""Tests for Regenerate options: regen_modes.py and how the server uses them."""
import unittest

import app_engine as E
import regen_modes as R
from tests.test_app_server import Base


class Modes(unittest.TestCase):
    def test_menu_lists_every_option_in_order(self):
        m = R.menu()
        self.assertEqual([x["id"] for x in m], list(R.ORDER))
        self.assertEqual(m[0]["label"], "Try again")
        self.assertTrue(all(x["label"] and x["blurb"] for x in m))

    def test_hint_is_added_to_the_end_of_the_question_only(self):
        self.assertEqual(R.hinted("Why is the sky blue?", "again"), "Why is the sky blue?")
        out = R.hinted("Why is the sky blue?", "simpler")
        self.assertTrue(out.startswith("Why is the sky blue?\n\n"))
        self.assertIn("simple words", out)
        self.assertEqual(R.hinted("q", None), "q")

    def test_unknown_option_is_an_error(self):
        with self.assertRaises(ValueError):
            R.get("nonsense")

    def test_length_and_temperature(self):
        self.assertLess(R.length_for(320, "shorter"), 320)
        self.assertGreater(R.length_for(320, "detail"), 320)
        self.assertGreaterEqual(R.length_for(40, "shorter"), 32)
        self.assertGreater(R.sampling_for(0.8, "different"), R.sampling_for(0.8, "simpler"))
        self.assertLessEqual(R.sampling_for(1.05, "different"), R.MAX_TEMPERATURE)


class WithSampling(E.FakeBackend):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.sampling = {"temperature": 0.8}


class Server(Base):
    backend = None

    def factory(model, question):                                   # noqa: N805 - a plain function stored on the class
        Server.backend = WithSampling()
        return Server.backend

    factory = staticmethod(factory)

    def decode(self, ids):
        return self.state.tok_for({"id": "flare-3"}).decode(ids)

    def test_the_hint_reaches_the_model_but_is_never_saved(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "Why is the sky blue")
        self.ask(self.sam, cid, "", regenerate=True, regen_mode="simpler")
        prompt = self.decode(Server.backend.prompts[-1])
        self.assertIn("Why is the sky blue", prompt)
        self.assertIn("simple words", prompt)
        saved = self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"]
        self.assertEqual([m["role"] for m in saved], ["user", "assistant"])
        self.assertNotIn("simple words", saved[0]["content"])

    def test_plain_regenerate_adds_no_hint(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "Why is the sky blue")
        self.ask(self.sam, cid, "", regenerate=True)
        self.assertNotIn("simple words", self.decode(Server.backend.prompts[-1]))

    def test_a_different_answer_is_more_adventurous(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "Tell me about cats")
        self.ask(self.sam, cid, "", regenerate=True, regen_mode="different")
        self.assertGreater(Server.backend.sampling["temperature"], 0.8)
        self.ask(self.sam, cid, "", regenerate=True, regen_mode="simpler")
        self.assertEqual(Server.backend.sampling["temperature"], 0.8)

    def test_unknown_option_is_a_400_and_keeps_the_old_answer(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "hello")
        status, _, body = self.ask(self.sam, cid, "", regenerate=True, regen_mode="nonsense")
        self.assertEqual((status, body["code"]), (400, "bad_option"))
        self.assertEqual([m["role"] for m in self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"]], ["user", "assistant"])

    def test_the_page_gets_the_menu(self):
        ids = [o["id"] for o in self.sam.call("GET", "/api/state")[1]["regen_options"]]
        self.assertEqual(ids, list(R.ORDER))

    def test_a_mode_is_ignored_unless_regenerating(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "hello there", regen_mode="simpler")
        self.assertNotIn("simple words", self.decode(Server.backend.prompts[-1]))


if __name__ == "__main__":
    unittest.main()
