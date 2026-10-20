"""Looked-up questions answer quickly on Deep: with web or Wikipedia notes the answer is in the notes, so an Emvryx 3 model answers from them at once
instead of thinking at length first (Oct 19: "Who won the 2031 world cup?" on Deep took minutes). Without notes, Deep still thinks."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import app_engine as E
from tests.test_app_server import Base


class FastLookup(Base):
    backend = None

    def factory(model, question):                                   # noqa: N805
        FastLookup.backend = E.FakeBackend("It has not been played yet.")
        return FastLookup.backend

    factory = staticmethod(factory)

    def thinks(self, text):
        """Whether the reply was asked to think first (run_turn's think=...), for an Emvryx 3 model on Deep"""
        from unittest import mock
        import chat_turn
        seen, real = [], E.run_turn

        def spy(*a, **kw):
            seen.append(kw.get("think"))
            return real(*a, **kw)
        with mock.patch.object(chat_turn.E, "run_turn", spy):
            self.ask(self.owner, self.new_chat(self.owner), text, model="flare-3", effort="deep")
        return seen

    def test_web_notes_mean_no_long_thinking(self):
        self.state.web_fn = lambda q, k: [{"title": "FIFA World Cup", "text": "The 2030 World Cup is the next one; no 2031 tournament is planned.", "url": "https://example.org/wc"}]
        self.assertEqual(self.thinks("Who won the 2031 world cup?"), [False])

    def test_without_notes_deep_still_thinks(self):
        self.state.web_fn = None
        self.assertEqual(self.thinks("Write a short poem about rain"), [True])


if __name__ == "__main__":
    unittest.main()


class StopWhileLoading(Base):
    def factory(model, question):                                   # noqa: N805
        from app_shared import Cancelled
        raise Cancelled()                                           # what the runner raises when Stop is pressed while the model loads

    factory = staticmethod(factory)

    def test_stop_during_the_load_ends_with_a_clear_message(self):
        s, _, got = self.ask(self.owner, self.new_chat(self.owner), "hello there")
        messages = [got["message"]] if isinstance(got, dict) else [d["message"] for e, d in got if e == "error"]     # before or after the stream began
        self.assertIn("Stopped before the answer started.", messages)
