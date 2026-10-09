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

    def test_a_follow_up_is_searched_together_with_the_question_before_it(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "Who is the mayor of Springfield?")
        self.web.calls.clear()
        _, _, ev = self.ask(self.sam, cid, "Check again since August how many terms has he had")
        self.assertIn("mayor of Springfield", self.web.calls[-1])               # "he" now has a name in the search
        self.assertEqual(self.events(ev)["notes"]["web_tried"], True)
        saved = self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"]
        self.assertEqual(saved[2]["content"], "Check again since August how many terms has he had")     # the chat keeps only what was typed

    def test_look_online_always_searches_the_web_even_for_a_plain_message(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "Tell me about bananas please")
        before = len(self.web.calls)
        _, _, ev = self.ask(self.sam, cid, "Look online")
        self.assertGreater(len(self.web.calls), before)
        self.assertEqual(self.events(ev)["notes"]["web_tried"], True)

    def test_look_online_in_a_private_chat_still_never_searches(self):
        cid = self.new_chat(self.sam, private=True)
        self.ask(self.sam, cid, "Look online")
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


class Pretend(Base):
    """A model that writes "*Checking online*" when no search ran gets the real search, and answers again."""
    streams = 0

    class Backend(E.FakeBackend):
        def stream(self, ids, max_new):
            Pretend.streams += 1                                     # 1: a normal answer, 2: pretends, 3: the answer after the real search
            self.script = "I will check online. *Checking online* It says 4." if Pretend.streams == 2 else "According to the web note, the mayor is Ann."
            return super().stream(ids, max_new)

    def factory(model, question):                                   # noqa: N805
        return Pretend.Backend()

    factory = staticmethod(factory)

    def setUp(self):
        Pretend.streams = 0
        super().setUp()
        self.state.wiki = None
        self.state.web_fn = self.web = FakeWeb([{"title": "Springfield mayor", "text": "The mayor of Springfield is Ann."}])

    def test_it_searches_for_real_and_the_pretend_answer_is_replaced(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "Who is the mayor of Springfield?")
        self.web.calls.clear()
        self.state.web_fn = self.web                                 # the follow-up below has no question mark and no search words of its own
        _, _, ev = self.ask(self.sam, cid, "Hmm, are you sure about that")
        msgs = self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user", "assistant"])
        self.assertNotIn("Checking online", msgs[-1]["content"])
        self.assertIn("mayor of Springfield", self.web.calls[-1])

    def test_a_private_chat_is_never_searched_even_when_the_model_pretends(self):
        cid = self.new_chat(self.sam, private=True)
        self.ask(self.sam, cid, "Who is the mayor of Springfield?")
        self.ask(self.sam, cid, "Hmm, are you sure about that")
        self.assertEqual(self.web.calls, [])


class Answers(Base):
    """Study helper: a bare answer ("30") is shown to the model together with the question it answers, and only "30" is saved."""

    def factory(model, question):                                   # noqa: N805
        Answers.backend = E.FakeBackend("Let us practise.\nQuick check: What is 6 x 5?")
        return Answers.backend

    factory = staticmethod(factory)

    def test_the_model_is_told_what_the_answer_answers(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "Give me a multiplication practice question please", skill="study")
        self.ask(self.sam, cid, "30", skill="study")
        prompt = self.state.tok_for({"id": "flare-2"}).decode(Answers.backend.prompts[-1])
        self.assertIn('ANSWER to your last question: "What is 6 x 5?"', prompt)
        saved = self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"]
        self.assertEqual(saved[2]["content"], "30")

