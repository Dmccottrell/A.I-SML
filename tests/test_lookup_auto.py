"""Tests for lookup_auto.py: when the app looks things up, and which notes the model gets."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import unittest

import lookup_auto as L


class FakeWiki:
    def __init__(self, notes):
        self.notes, self.calls = notes, []

    def search(self, question, k):
        self.calls.append(question)
        return self.notes[:k]


class FakeWeb:
    def __init__(self, notes=None, fail=False):
        self.notes, self.fail, self.calls = notes or [], fail, []

    def __call__(self, question, k):
        self.calls.append(question)
        if self.fail:
            raise OSError("offline")
        return self.notes[:k]


SPRINGFIELD = {"title": "Springfield, Illinois", "text": "Springfield is the capital of the U.S. state of Illinois."}
BANANA = {"title": "Banana", "text": "A banana is an elongated, edible fruit."}
NEWS = {"title": "Tigers win - sportswire.net, Oct 4, 2026", "text": "The Tigers won the final 3-1.", "url": "https://sportswire.net/x"}


class WhenToLookUp(unittest.TestCase):
    def test_questions_look_things_up(self):
        for q in ("What is the capital of Illinois?", "Who was Abraham Lincoln", "how many legs does a spider have",
                  "give me the population of Texas", "Tell me about the Eiffel Tower?"):
            self.assertTrue(L.wants_lookup(q), q)

    def test_chat_and_jobs_do_not(self):
        for q in ("hi", "Hello there", "thanks!", "write me a poem about rain", "List 3 fruits", "Translate this into French",
                  "remember that my dog is Max", "ok"):
            self.assertFalse(L.wants_lookup(q), q)

    def test_recent_things_are_flagged(self):
        for q in ("Who won the game last night? The latest score", "What is the price of gold today?", "Who is the current president?",
                  "what happened in 2026"):
            self.assertTrue(L.time_sensitive(q), q)
        self.assertFalse(L.time_sensitive("What is the capital of Illinois?"))

    def test_upcoming_releases_count_as_recent(self):
        for q in ("When is gta 6 coming out", "when does the new iphone launch", "when is the next season of Severance out", "release date of the new Zelda"):
            self.assertTrue(L.time_sensitive(q), q)
        for q in ("Who is gordon ramsay", "when was the printing press invented", "how do plants make food"):
            self.assertFalse(L.time_sensitive(q), q)

    def test_date_note_only_for_questions_that_need_the_date(self):
        import time
        now = time.mktime((2026, 10, 7, 12, 0, 0, 0, 0, -1))
        self.assertEqual(L.date_note("What day is christmas this year?", now)["text"], "Today is Wednesday, October 7, 2026.")
        self.assertIsNotNone(L.date_note("what's the date today", now))
        self.assertIsNone(L.date_note("What is the capital of Illinois?", now))
        self.assertIsNone(L.date_note("", now))

    def test_weak_notes_do_not_match_the_question(self):
        self.assertFalse(L.notes_weak([SPRINGFIELD], "What is the capital of Illinois?"))
        self.assertTrue(L.notes_weak([BANANA], "What is the capital of Illinois?"))
        self.assertTrue(L.notes_weak([], "What is the capital of Illinois?"))


class Gathering(unittest.TestCase):
    def test_a_good_wikipedia_answer_needs_no_web(self):
        wiki, web = FakeWiki([SPRINGFIELD]), FakeWeb([NEWS])
        notes, info = L.gather("What is the capital of Illinois?", wiki, web)
        self.assertEqual([n["title"] for n in notes], ["Springfield, Illinois"])
        self.assertEqual(web.calls, [])
        self.assertEqual((info["wiki"], info["web"], info["web_tried"]), (1, 0, False))

    def test_weak_wikipedia_notes_bring_in_the_web(self):
        wiki, web = FakeWiki([BANANA]), FakeWeb([NEWS])
        notes, info = L.gather("Who won the Tigers game?", wiki, web)
        self.assertEqual(len(web.calls), 1)
        self.assertEqual(info["web"], 1)

    def test_recent_questions_use_the_web_and_put_it_first(self):
        wiki, web = FakeWiki([SPRINGFIELD]), FakeWeb([NEWS])
        notes, info = L.gather("What is the latest score for the Tigers?", wiki, web)
        self.assertEqual(notes[0]["title"], NEWS["title"])
        self.assertEqual(info["sources"][0]["url"], NEWS["url"])

    def test_private_chats_and_the_off_setting_never_use_the_web(self):
        for kwargs in ({"private": True}, {"mode": "off"}):
            web = FakeWeb([NEWS])
            L.gather("What is the latest score for the Tigers?", FakeWiki([]), web, **kwargs)
            self.assertEqual(web.calls, [], kwargs)

    def test_always_searches_the_web_for_facts_but_not_for_chat(self):
        web = FakeWeb([NEWS])
        L.gather("What is the capital of Illinois?", FakeWiki([SPRINGFIELD]), web, mode="always")
        self.assertEqual(len(web.calls), 1)
        L.gather("hello", FakeWiki([SPRINGFIELD]), web, mode="always")
        self.assertEqual(len(web.calls), 1)

    def test_offline_or_missing_sources_just_mean_fewer_notes(self):
        notes, info = L.gather("Who won the Tigers game?", FakeWiki([]), FakeWeb(fail=True))
        self.assertEqual(notes, [])
        self.assertTrue(info["web_tried"])
        self.assertEqual(L.gather("What is the capital of Illinois?", None, None)[0], [])

    def test_the_model_never_gets_more_notes_than_the_limit(self):
        notes, _ = L.gather("What is the latest news on the capital of Illinois?", FakeWiki([SPRINGFIELD] * 3),
                            FakeWeb([NEWS] * 3), max_notes=3)
        self.assertEqual(len(notes), 3)


if __name__ == "__main__":
    unittest.main()
