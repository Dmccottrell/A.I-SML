"""Tests for saved_notes.py and the thumbs up / second try built on it."""
import unittest

import app_engine as E
import lookup_auto as L
import saved_notes as S
from tests.test_app_server import Base
from tests.test_lookup_auto import BANANA, NEWS, SPRINGFIELD, FakeWeb, FakeWiki

NOW = 1_000_000.0
NOTE = {"title": "Springfield, Illinois", "text": "Springfield is the capital of the U.S. state of Illinois.", "kind": "wikipedia", "url": None}


class Store(unittest.TestCase):
    def test_a_saved_note_answers_a_similar_question_offline(self):
        s = S.SavedNotes()
        self.assertEqual(s.save("What is the capital of Illinois?", [NOTE], NOW), 1)
        found = s.search("capital of Illinois", 3, NOW + 60)
        self.assertEqual([n["title"] for n in found], ["Springfield, Illinois"])
        self.assertEqual(s.search("What is the tallest mountain?", 3, NOW + 60), [])

    def test_recent_things_expire_after_a_day_and_stable_facts_last(self):
        s = S.SavedNotes()
        s.save("Who won the Tigers game today?", [dict(NOTE, title="Tigers win")], NOW, recent=True)
        s.save("What is the capital of Illinois?", [NOTE], NOW)
        later = NOW + 2 * S.DAY
        self.assertEqual(s.search("Who won the Tigers game today?", 3, later), [])
        self.assertEqual(len(s.search("capital of Illinois", 3, later)), 1)
        self.assertEqual(len(s.list(later)), 1)

    def test_saving_the_same_note_twice_keeps_one_copy(self):
        s = S.SavedNotes()
        s.save("capital of Illinois", [NOTE], NOW)
        self.assertEqual(s.save("What is the capital of Illinois?", [NOTE], NOW + 5), 0)
        self.assertEqual(len(s.list(NOW + 6)), 1)

    def test_delete_one_and_clear(self):
        s = S.SavedNotes()
        s.save("capital of Illinois", [NOTE, dict(NOTE, title="Illinois", text="Illinois is a state.")], NOW)
        first = s.list(NOW)[0]["id"]
        s.delete(first)
        self.assertEqual(len(s.list(NOW)), 1)
        s.clear()
        self.assertEqual(s.list(NOW), [])

    def test_gather_uses_saved_notes_first_and_skips_the_web(self):
        s = S.SavedNotes()
        s.save("What is the capital of Illinois?", [NOTE], NOW)
        web = FakeWeb([NEWS])
        notes, info = L.gather("What is the capital of Illinois?", None, web, saved=s, now=NOW + 5)
        self.assertEqual((info["saved"], info["web_tried"]), (1, False))
        self.assertEqual(notes[0]["title"], "Springfield, Illinois")
        self.assertEqual(web.calls, [])

    def test_private_chats_do_not_read_saved_notes(self):
        s = S.SavedNotes()
        s.save("What is the capital of Illinois?", [NOTE], NOW)
        self.assertEqual(L.gather("What is the capital of Illinois?", None, None, private=True, saved=s, now=NOW + 5)[0], [])

    def test_giving_up_is_recognised(self):
        for t in ("I don't know.", "The notes don't say who won.", "I'm not sure about that.", "I could not find it."):
            self.assertTrue(L.gave_up(t), t)
        self.assertFalse(L.gave_up("Springfield is the capital of Illinois."))


class Server(Base):
    backend = None
    script = "Springfield is the capital."

    def factory(model, question):                                   # noqa: N805
        Server.backend = E.FakeBackend(Server.script)
        return Server.backend

    factory = staticmethod(factory)

    def setUp(self):
        super().setUp()
        Server.script = "Springfield is the capital."
        self.web = FakeWeb([NEWS])
        self.state.wiki = FakeWiki([SPRINGFIELD])
        self.state.web_fn = self.web

    def events(self, body):
        return [(n, d) for n, d in body]

    def like(self, who, cid, mid):
        return who.call("POST", f"/api/chats/{cid}/messages/{mid}/like", {})

    def test_thumbs_up_saves_the_notes_and_the_next_question_uses_them_without_the_wiki(self):
        cid = self.new_chat(self.sam)
        ev = self.ask(self.sam, cid, "What is the capital of Illinois?")[2]
        mid = dict(ev)["done"]["message_id"]
        status, body = self.like(self.sam, cid, mid)
        self.assertEqual((status, body["saved"]), (200, 1))
        self.state.wiki = None                                            # as if offline and without the index
        ev = self.ask(self.sam, self.new_chat(self.sam), "What's the capital of Illinois?")[2]
        info = dict(ev)["notes"]
        self.assertEqual(info["saved"], 1)
        listing = self.sam.call("GET", "/api/saved-notes")[1]["notes"]
        self.assertEqual(len(listing), 1)
        self.sam.call("POST", "/api/saved-notes/delete", {"id": listing[0]["id"]})
        self.assertEqual(self.sam.call("GET", "/api/saved-notes")[1]["notes"], [])

    def test_private_chats_save_nothing(self):
        cid = self.new_chat(self.sam, private=True)
        ev = self.ask(self.sam, cid, "What is the capital of Illinois?")[2]
        status, body = self.like(self.sam, cid, dict(ev)["done"]["message_id"])
        self.assertEqual(status, 400)

    def test_one_person_cannot_read_anothers_saved_notes(self):
        cid = self.new_chat(self.sam)
        mid = dict(self.ask(self.sam, cid, "What is the capital of Illinois?")[2])["done"]["message_id"]
        self.like(self.sam, cid, mid)
        self.assertEqual(self.owner.call("GET", "/api/saved-notes")[1]["notes"], [])

    def test_delete_everything_also_clears_saved_notes(self):
        cid = self.new_chat(self.sam)
        mid = dict(self.ask(self.sam, cid, "What is the capital of Illinois?")[2])["done"]["message_id"]
        self.like(self.sam, cid, mid)
        self.sam.call("POST", "/api/delete-everything", {})
        self.assertEqual(self.sam.call("GET", "/api/saved-notes")[1]["notes"], [])

    def test_when_the_model_gives_up_the_web_is_tried_and_it_answers_again(self):
        Server.script = "I don't know."
        cid = self.new_chat(self.sam)
        ev = self.events(self.ask(self.sam, cid, "What is the capital of Illinois?")[2])
        notes = [d for n, d in ev if n == "notes"]
        self.assertEqual(len(notes), 2)
        self.assertTrue(notes[1].get("retry"))
        self.assertEqual(len(Server.backend.prompts), 2)
        self.assertIn("Tigers won", self.state.tok_for({"id": "flare-3"}).decode(Server.backend.prompts[-1]))
        saved = self.sam.call("GET", f"/api/chats/{cid}")[1]["messages"]
        self.assertEqual([m["role"] for m in saved], ["user", "assistant"])

    def test_no_second_try_when_the_web_is_off_or_the_chat_is_private(self):
        Server.script = "I don't know."
        self.sam.call("POST", "/api/settings", {"web_search": "off"})
        self.ask(self.sam, self.new_chat(self.sam), "What is the capital of Illinois?")
        self.assertEqual(self.web.calls, [])
        self.sam.call("POST", "/api/settings", {"web_search": "auto"})
        self.ask(self.sam, self.new_chat(self.sam, private=True), "What is the capital of Illinois?")
        self.assertEqual(self.web.calls, [])


if __name__ == "__main__":
    unittest.main()
