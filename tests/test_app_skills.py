"""Tests for the app's Skills: app_skills.py and how the server uses them."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import unittest

import app_engine as E
import app_skills as K
from tests.test_app_server import Base


class Catalog(unittest.TestCase):
    def test_every_skill_is_complete(self):
        ids = [s["id"] for s in K.SKILLS]
        self.assertEqual(len(ids), len(set(ids)))
        for s in K.SKILLS:
            for key in ("name", "for", "does", "try", "how", "icon"):
                self.assertTrue(s[key], (s["id"], key))

    def test_catalog_does_not_send_the_instructions(self):
        self.assertTrue(all("how" not in s for s in K.catalog()["skills"]))

    def test_hint(self):
        self.assertEqual(K.hint(""), "")
        self.assertEqual(K.hint("nope"), "")
        self.assertIn("Quick check:", K.hint("study"))
        self.assertIn("answer it normally", K.hint("recipe"))               # off-topic questions in a skill chat are answered normally

    def test_teacher_layout_matches_the_exporter(self):
        how = K.get("teacher")["how"]
        for part in ("'# '", "'## '", "Answer key"):
            self.assertIn(part, how)


class Store(unittest.TestCase):
    def test_skill_is_kept_per_chat(self):
        s = E.ChatStore()
        a, b, p = s.new_chat(skill="study"), s.new_chat(), s.new_chat(private=True, skill="story")
        self.assertEqual((s.skill(a), s.skill(b), s.skill(p)), ("study", "", "story"))

    def test_chat_list_says_which_skill_each_chat_used(self):
        s = E.ChatStore()
        a, b = s.new_chat(skill="recipe"), s.new_chat()
        self.assertEqual({c["id"]: c["skill"] for c in s.list_chats()}, {a: "recipe", b: ""})


class Server(Base):
    backend = None

    def factory(model, question):                                   # noqa: N805
        Server.backend = E.FakeBackend()
        return Server.backend

    factory = staticmethod(factory)

    def decode(self, ids):
        return self.state.tok_for({"id": "flare-2"}).decode(ids)

    def test_skills_endpoint(self):
        s, j = self.sam.call("GET", "/api/skills")
        self.assertEqual(s, 200)
        self.assertIn("study", [x["id"] for x in j["skills"]])

    def test_unknown_skill_is_refused(self):
        self.assertEqual(self.sam.call("POST", "/api/chats", {"skill": "nope"})[0], 400)

    def test_the_skill_reaches_the_model_but_is_never_saved(self):
        s, j = self.sam.call("POST", "/api/chats", {"skill": "study"})
        cid = j["id"]
        self.ask(self.sam, cid, "How do fractions work")
        self.assertIn("Quick check:", self.decode(Server.backend.prompts[-1]))
        chat = self.sam.call("GET", f"/api/chats/{cid}")[1]
        self.assertEqual(chat["skill"], "study")
        self.assertNotIn("Quick check", chat["messages"][0]["content"])

    def test_the_date_reaches_the_model_when_the_question_needs_it(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "What day is christmas this year?")
        self.assertIn("Today is", self.decode(Server.backend.prompts[-1]))
        self.ask(self.sam, cid, "What is the capital of France?")
        self.assertNotIn("Today is", self.decode(Server.backend.prompts[-1]))

    def test_a_chat_without_a_skill_gets_no_instructions(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "How do fractions work")
        self.assertNotIn("How to answer this chat", self.decode(Server.backend.prompts[-1]))
        self.assertEqual(self.sam.call("GET", f"/api/chats/{cid}")[1]["skill"], "")

    # ---- custom instructions (Settings > Memory)
    def test_custom_hint(self):
        self.assertEqual(K.custom_hint(""), "")
        self.assertEqual(K.custom_hint("   "), "")
        h = K.custom_hint("Keep answers short.\n I am a nurse.")
        self.assertIn("Keep answers short. I am a nurse.", h)
        self.assertIn("answer normally", h)
        self.assertLessEqual(len(K.custom_hint("x" * 5000)), 600)

    def test_custom_instructions_reach_the_model_with_the_skill_but_are_never_saved(self):
        self.sam.call("POST", "/api/settings", {"custom_instructions": "Keep answers short."})
        self.assertEqual(self.sam.call("GET", "/api/settings")[1]["custom_instructions"], "Keep answers short.")
        cid = self.sam.call("POST", "/api/chats", {"skill": "study"})[1]["id"]
        self.ask(self.sam, cid, "How do fractions work")
        prompt = self.decode(Server.backend.prompts[-1])
        self.assertIn("Keep answers short.", prompt)
        self.assertIn("Quick check:", prompt)
        self.assertNotIn("Keep answers short", self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"][0]["content"])
        self.sam.call("POST", "/api/settings", {"custom_instructions": ""})
        self.ask(self.sam, cid, "And decimals?")
        self.assertNotIn("Keep answers short.", self.decode(Server.backend.prompts[-1]))

    def test_custom_instructions_are_per_person_and_limited(self):
        self.sam.call("POST", "/api/settings", {"custom_instructions": "y" * 900})
        self.assertEqual(len(self.sam.call("GET", "/api/settings")[1]["custom_instructions"]), K.MAX_CUSTOM)
        self.assertEqual(self.owner.call("GET", "/api/settings")[1].get("custom_instructions", ""), "")


if __name__ == "__main__":
    unittest.main()
