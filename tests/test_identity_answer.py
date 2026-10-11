"""Who or what Emvryx says it is: the owner's wording, the same for every model, never a web search."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import app_engine as E
import identity_answer as I
from tests.test_app_server import Base
from tests.test_lookup_auto import FakeWeb, FakeWiki, NEWS, SPRINGFIELD

SAY = "I am Emvryx, created by Darryl McCottrell."


class Questions(unittest.TestCase):
    def test_questions_about_the_assistant_get_the_fixed_answer(self):
        for q in ("Who are you?", "who are u", "What are you?", "what's your name", "Who made you?", "who created you", "Who is your creator?",
                  "introduce yourself", "Tell me about yourself", "what is emvryx", "what company made you", "are you a human?", "Hey, who are you exactly?"):
            self.assertEqual(I.answer(q), SAY, q)

    def test_asking_what_it_is_built_on_gets_one_more_true_sentence(self):
        for q in ("What model are you?", "Are you ChatGPT?", "are you Qwen or Llama?", "Who built you and what are you built on?", "what model are you based on?"):
            self.assertEqual(I.answer(q), SAY + " I'm built on an open foundation model.", q)

    def test_other_messages_are_left_to_the_model(self):
        for q in ("Who are you going to vote for in the election", "Write a story about who are you", "Who is the president of France?", "Who made the first telephone?",
                  "What is the capital of France?", "hello", "What are you doing today?", "Explain how a model of the economy works",
                  "Who are you and what are you going to do about the long list of things on my desk and in my car and my house today"):
            self.assertIsNone(I.answer(q), q)


class Server(Base):
    backend = None

    def factory(model, question):                                   # noqa: N805
        Server.backend = E.FakeBackend("The model answered this instead.")
        return Server.backend

    factory = staticmethod(factory)

    def setUp(self):
        super().setUp()
        self.web = FakeWeb([NEWS])
        self.wiki = FakeWiki([SPRINGFIELD])
        self.state.web_fn, self.state.wiki = self.web, self.wiki
        Server.backend = None

    def reply(self, cid):
        return self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"][-1]["content"].strip()

    def test_who_are_you_is_answered_by_the_app_without_the_model_or_the_web(self):
        cid = self.new_chat(self.sam)
        status, _, _ = self.ask(self.sam, cid, "Who are you?")
        self.assertEqual(status, 200)
        self.assertEqual(self.reply(cid), SAY)
        self.assertIsNone(Server.backend)                         # the model was never asked
        self.assertEqual((self.web.calls, self.wiki.calls), ([], []))

    def test_every_model_gives_the_same_answer_and_asking_again_still_works(self):
        for model in ("flare-2", "equinox-2"):
            cid = self.new_chat(self.sam)
            self.sam.stream(cid, {"text": "who made you?", "model": model, "effort": "balanced"})
            self.assertEqual(self.reply(cid), SAY, model)
        self.ask(self.sam, cid, "who made you?")                    # the same question twice in a row
        msgs = self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user", "assistant"])
        self.assertEqual(msgs[-1]["content"].strip(), SAY)

    def test_an_ordinary_question_still_goes_to_the_model(self):
        cid = self.new_chat(self.sam)
        self.ask(self.sam, cid, "Tell me about foxes please")
        self.assertIsNotNone(Server.backend)
        self.assertIn("The model answered", self.reply(cid))


if __name__ == "__main__":
    unittest.main()
