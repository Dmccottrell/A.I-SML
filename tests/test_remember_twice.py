"""Found on the iPhone work: telling the server the same "Remember ..." a second time made the whole reply fail with "Something went wrong". Saying it twice must just work
(the second time nothing new is saved, and the answer still comes)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401

from tests.test_app_server import Base


class RememberTwice(Base):
    def send(self, cid, text):
        status, _, events = self.owner.stream(cid, {"text": text, "model": "equinox-2"})
        self.assertEqual(status, 200, events)
        return events

    def test_the_same_remember_twice_still_answers(self):
        s, j = self.owner.call("POST", "/api/chats", {})
        cid = j["id"]
        first = self.send(cid, "Remember that my dentist is on Tuesday")
        second = self.send(cid, "Remember that my dentist is on Tuesday")
        for events in (first, second):
            kinds = [e for e, _ in events]
            self.assertNotIn("error", kinds, events)
            self.assertIn("done", kinds, events)
        self.assertTrue(any(e == "memory" for e, _ in first))               # the first time something is saved...
        self.assertFalse(any(e == "memory" for e, _ in second))             # ...the second time nothing new is, and nothing breaks

    def test_the_same_remember_with_other_capitals_and_spaces_is_still_one_fact(self):
        s, j = self.owner.call("POST", "/api/chats", {})
        cid = j["id"]
        self.send(cid, "Remember that my dentist is on Tuesday")
        again = self.send(cid, "remember that  my dentist is on tuesday")
        self.assertNotIn("error", [e for e, _ in again], again)
        facts = self.owner.call("GET", "/api/memory")[1]
        listed = facts if isinstance(facts, list) else facts.get("facts", [])
        self.assertEqual(len([f for f in listed if "dentist" in f["text"].lower()]), 1, listed)


if __name__ == "__main__":
    import unittest
    unittest.main()
