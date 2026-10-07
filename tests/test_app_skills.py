"""Tests for the app's Skills: app_skills.py and how the server uses them."""
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

    def test_teacher_layout_matches_the_exporter(self):
        how = K.get("teacher")["how"]
        for part in ("'# '", "'## '", "Answer key"):
            self.assertIn(part, how)


class Store(unittest.TestCase):
    def test_skill_is_kept_per_chat(self):
        s = E.ChatStore()
        a, b, p = s.new_chat(skill="study"), s.new_chat(), s.new_chat(private=True, skill="story")
        self.assertEqual((s.skill(a), s.skill(b), s.skill(p)), ("study", "", "story"))


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

    def test_a_chat_without_a_skill_gets_no_instructions(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "How do fractions work")
        self.assertNotIn("How to answer this chat", self.decode(Server.backend.prompts[-1]))
        self.assertEqual(self.sam.call("GET", f"/api/chats/{cid}")[1]["skill"], "")


if __name__ == "__main__":
    unittest.main()
