"""Memory shared by every model: what the app learns about a person and gives to whichever model answers."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import json
import unittest

import app_engine as E
import data_tools
import user_memory as U
from tests.test_app_server import Base


class Facts(unittest.TestCase):
    def test_spots_the_things_worth_keeping(self):
        m = U.Memory()
        self.assertEqual(m.learn("hi my name is darryl")["saved"], ["The user's name is Darryl."])
        self.assertEqual(m.learn("I live in austin texas")["saved"], ["The user lives in or is from Austin Texas."])
        self.assertEqual(m.learn("my dog is called biscuit")["saved"], ["The user's dog is called Biscuit."])
        self.assertEqual(m.learn("my favourite colour is blue")["saved"], ["The user's favourite colour is blue."])
        self.assertEqual(m.learn("remember that I prefer Python")["saved"], ["The user asked to remember: I prefer Python."])
        self.assertIn("Darryl", m.note()["text"])

    def test_ordinary_messages_save_nothing(self):
        m = U.Memory()
        for t in ("what is the weather", "I'm tired", "call me later", "write a poem about my name", "who was the first president?"):
            self.assertEqual(m.learn(t)["saved"], [], t)
        self.assertIsNone(m.note())

    def test_nothing_secret_is_kept(self):
        m = U.Memory()
        for t in ("my password is hunter2222", "remember that my card number is 4111 1111 1111 1111", "remember my email is a@b.com", "my name is darryl and my pin is 1234"):
            m.learn(t)
        self.assertFalse(any("hunter" in f["text"] or "4111" in f["text"] or "a@b" in f["text"] for f in m.list()))
        self.assertFalse(m.add("my api key is abc"))

    def test_a_new_value_replaces_the_old_one(self):
        m = U.Memory()
        m.learn("my name is darryl")
        m.learn("actually my name is dan")
        self.assertEqual([f["text"] for f in m.list()], ["The user's name is Dan."])

    def test_forgetting(self):
        m = U.Memory()
        m.learn("my dog is called biscuit")
        m.learn("my name is darryl")
        self.assertEqual(m.learn("forget about my dog")["forgot"], 1)
        self.assertEqual([f["text"] for f in m.list()], ["The user's name is Darryl."])
        self.assertEqual(m.learn("forget everything about me")["forgot"], 1)
        self.assertIsNone(m.note())

    def test_it_never_keeps_more_than_the_limit(self):
        m = U.Memory()
        for i in range(U.MAX_FACTS + 10):
            m.add(f"The user likes thing number {i}.")
        self.assertEqual(len(m.list()), U.MAX_FACTS)


class Server(Base):
    backend = None

    def factory(model, question):                                   # noqa: N805
        Server.backend = E.FakeBackend("Nice to meet you.")
        return Server.backend

    factory = staticmethod(factory)

    def prompt_text(self, model_id="flare-2"):
        return self.state.tok_for({"id": model_id}).decode(Server.backend.prompts[-1])

    def test_a_new_chat_and_a_different_model_still_know_the_name(self):
        first = self.new_chat(self.sam)
        ev = dict(self.ask(self.sam, first, "hi my name is darryl")[2])
        self.assertIn("memory", ev)
        second = self.new_chat(self.sam)
        self.ask(self.sam, second, "what is my name?")
        self.assertIn("The user's name is Darryl.", self.prompt_text())

    def test_each_person_has_their_own_memory(self):
        self.ask(self.sam, self.new_chat(self.sam), "my name is darryl")
        self.ask(self.owner, self.new_chat(self.owner), "what is my name?")
        self.assertNotIn("Darryl", self.prompt_text())

    def test_private_chats_neither_save_nor_read(self):
        self.ask(self.sam, self.new_chat(self.sam, private=True), "my name is darryl")
        self.assertEqual(self.sam.call("GET", "/api/memory")[1]["facts"], [])
        self.ask(self.sam, self.new_chat(self.sam), "my name is darryl")
        self.ask(self.sam, self.new_chat(self.sam, private=True), "what is my name?")
        self.assertNotIn("Darryl", self.prompt_text())

    def test_turning_it_off_stops_saving_and_reading(self):
        self.sam.call("POST", "/api/settings", {"memory": False})
        self.ask(self.sam, self.new_chat(self.sam), "my name is darryl")
        self.assertEqual(self.sam.call("GET", "/api/memory")[1]["facts"], [])

    def test_list_add_delete_and_clear(self):
        self.assertEqual(self.sam.call("POST", "/api/memory/add", {"text": "I prefer short answers"})[0], 200)
        self.assertEqual(self.sam.call("POST", "/api/memory/add", {"text": "my password is hunter2222"})[0], 400)
        facts = self.sam.call("GET", "/api/memory")[1]["facts"]
        self.assertEqual(len(facts), 1)
        self.sam.call("POST", "/api/memory/delete", {"id": facts[0]["id"]})
        self.assertEqual(self.sam.call("GET", "/api/memory")[1]["facts"], [])
        self.sam.call("POST", "/api/memory/add", {"text": "I live in Austin"})
        self.sam.call("POST", "/api/memory/clear")
        self.assertEqual(self.sam.call("GET", "/api/memory")[1]["facts"], [])

    def test_it_is_in_the_download_and_gone_with_the_account(self):
        import io
        import zipfile
        self.ask(self.sam, self.new_chat(self.sam), "my name is darryl")
        zbytes = data_tools.export_zip(self.state, "sam")
        names = zipfile.ZipFile(io.BytesIO(zbytes)).namelist()
        self.assertIn("memory.json", names)
        self.assertIn("Darryl", zipfile.ZipFile(io.BytesIO(zbytes)).read("memory.json").decode())
        data_tools.delete_account(self.state, "sam")
        self.assertNotIn("sam", self.state.memories)


if __name__ == "__main__":
    unittest.main()


class Relevance(Base):
    backend = None

    def factory(model, question):                                   # noqa: N805
        Relevance.backend = E.FakeBackend("ok")
        return Relevance.backend

    factory = staticmethod(factory)

    def test_the_note_only_goes_with_questions_about_the_person(self):
        self.ask(self.sam, self.new_chat(self.sam), "my name is darryl")
        tok = self.state.tok_for({"id": "flare-2"})
        self.ask(self.sam, self.new_chat(self.sam), "who was the first president of the united states?")
        self.assertNotIn("Darryl", tok.decode(Relevance.backend.prompts[-1]))
        self.ask(self.sam, self.new_chat(self.sam), "what is my name?")
        self.assertIn("Darryl", tok.decode(Relevance.backend.prompts[-1]))

    def test_note_with_no_question_is_always_built_and_is_capped(self):
        m = U.Memory()
        for i in range(60):
            m.add(f"The user likes thing number {i} a lot.")
        self.assertLessEqual(len(m.note()["text"]), 700)
        self.assertIn("number 59", m.note()["text"])
        self.assertIsNone(m.note("who was the first president?"))


class PauseSetting(Base):
    def ask_pause(self, who, effort="balanced"):
        return self.ask(who, self.new_chat(who), "tell me about cats", effort=effort)[2][0][1]["min_first_s"]

    def test_the_pause_is_short_by_default_and_can_be_off_or_natural(self):
        self.assertEqual(self.ask_pause(self.owner), 0.48)             # 1.2 s x 0.4
        self.owner.call("POST", "/api/settings", {"thinking_pause": "off"})
        self.assertEqual(self.ask_pause(self.owner), 0.0)
        self.owner.call("POST", "/api/settings", {"thinking_pause": "natural"})
        self.assertEqual(self.ask_pause(self.owner), 1.2)
        self.assertEqual(self.owner.call("POST", "/api/settings", {"thinking_pause": "bogus"})[1]["thinking_pause"], "natural")
