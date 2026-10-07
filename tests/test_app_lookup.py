"""The chat app's Auto lookup: notes reach the model, the page is told, settings and private chats are respected."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import unittest

import app_engine as E
from tests.test_app_server import Base
from tests.test_lookup_auto import BANANA, NEWS, SPRINGFIELD, FakeWeb, FakeWiki


class Server(Base):
    backend = None

    def factory(model, question):                                   # noqa: N805
        Server.backend = E.FakeBackend()
        return Server.backend

    factory = staticmethod(factory)

    def setUp(self):
        super().setUp()
        self.web = FakeWeb([NEWS])
        self.state.wiki = FakeWiki([SPRINGFIELD])
        self.state.web_fn = self.web

    def decode(self, ids):
        return self.state.tok_for({"id": "flare-2"}).decode(ids)

    def events(self, body):
        return {name: data for name, data in body}

    def test_notes_reach_the_model_and_the_page_is_told(self):
        cid = self.new_chat(self.sam)
        status, _, ev = self.ask(self.sam, cid, "What is the capital of Illinois?")
        self.assertEqual(status, 200)
        info = self.events(ev)["notes"]
        self.assertEqual((info["wiki"], info["web"]), (1, 0))
        self.assertIn("Springfield is the capital", self.decode(Server.backend.prompts[-1]))
        saved = self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"]
        self.assertNotIn("Springfield", saved[0]["content"])             # the saved question stays the plain question

    def test_small_talk_gets_no_lookup(self):
        cid = self.new_chat(self.sam)
        _, _, ev = self.ask(self.sam, cid, "hello")
        self.assertNotIn("notes", self.events(ev))
        self.assertEqual(self.state.wiki.calls, [])

    def test_recent_questions_use_the_web_unless_the_person_turned_it_off(self):
        cid = self.new_chat(self.sam)
        _, _, ev = self.ask(self.sam, cid, "What is the latest score for the Tigers?")
        self.assertEqual(self.events(ev)["notes"]["web"], 1)
        s, settings = self.sam.call("POST", "/api/settings", {"web_search": "off"})
        self.assertEqual(settings["web_search"], "off")
        before = len(self.web.calls)
        self.ask(self.sam, self.new_chat(self.sam), "What is the latest score for the Tigers?")
        self.assertEqual(len(self.web.calls), before)

    def test_private_chats_never_search_the_web(self):
        cid = self.new_chat(self.sam, private=True)
        self.ask(self.sam, cid, "What is the latest score for the Tigers?")
        self.assertEqual(self.web.calls, [])

    def test_a_server_without_sources_still_answers(self):
        self.state.wiki = None
        self.state.web_fn = None
        _, _, ev = self.ask(self.sam, self.new_chat(self.sam), "What is the capital of Illinois?")
        self.assertIn("done", self.events(ev))

    def test_the_default_setting_is_auto_and_bad_values_are_ignored(self):
        self.assertEqual(self.sam.call("GET", "/api/settings")[1]["web_search"], "auto")
        self.assertEqual(self.sam.call("POST", "/api/settings", {"web_search": "nonsense"})[1]["web_search"], "auto")


if __name__ == "__main__":
    unittest.main()
