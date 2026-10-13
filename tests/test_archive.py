"""Archived chats: out of the list, but kept, searchable and still remembered."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import unittest

import app_engine as E
from tests.test_app_server import Base


def chat(store, title, user, ai):
    cid = store.new_chat(title)
    store.add(cid, "user", user)
    store.add(cid, "assistant", ai)
    return cid


class Store(unittest.TestCase):
    def setUp(self):
        self.s = E.ChatStore()
        self.car = chat(self.s, "Car trouble", "my car makes a squeaking noise when I brake", "That is usually worn brake pads. Get them checked soon.")
        self.cake = chat(self.s, "Cake", "how long do I bake a chocolate cake", "About 30 to 35 minutes at 180 C.")

    def test_archived_chats_leave_the_list_but_are_kept(self):
        self.s.set_pinned(self.car, True)
        self.s.set_archived(self.car)
        self.assertEqual([c["id"] for c in self.s.list_chats()], [self.cake])
        self.assertEqual([c["id"] for c in self.s.list_chats(archived=True)], [self.car])
        self.assertFalse(self.s.list_chats(archived=True)[0]["pinned"])           # an archived chat is not pinned any more
        self.assertEqual(len(self.s.list_chats(everything=True)), 2)
        self.assertTrue(self.s.search("squeaking"))                               # still found by chat search
        self.s.set_archived(self.car, False)
        self.assertEqual(len(self.s.list_chats()), 2)
        self.assertEqual(self.s.archive_all(), 2)
        self.assertEqual(self.s.list_chats(), [])

    def test_a_question_about_the_past_recalls_earlier_chats_archived_too(self):
        self.s.archive_all()
        now = self.s.new_chat("New")
        note = self.s.recall("what did you tell me last time about the squeaking when I brake?", exclude_chat=now)
        self.assertIn("Car trouble", note)
        self.assertIn("brake pads", note)
        self.assertNotIn("chocolate", note)

    def test_ordinary_questions_get_no_recall(self):
        self.assertEqual(self.s.recall("how do brakes work?"), "")                # no "last time" / "remember": not about the past
        self.assertEqual(self.s.recall("remember the thing?"), "")                # nothing specific to look for
        self.assertEqual(self.s.recall("what did we say last time about my car", exclude_chat=self.car), "")   # not from the same chat


class Routes(Base):
    def test_archive_one_all_list_and_bring_back(self):
        store = self.state.store("owner")
        a = chat(store, "Car trouble", "my car squeaks when I brake", "Brake pads.")
        b = chat(store, "Cake", "bake a cake", "35 minutes.")
        self.assertEqual(self.owner.call("POST", f"/api/chats/{a}/archive", {"archived": True})[0], 200)
        state = self.owner.call("GET", "/api/state")[1]
        self.assertEqual([c["id"] for c in state["chats"]], [b])
        self.assertEqual([c["id"] for c in self.owner.call("GET", "/api/chats/archived")[1]["chats"]], [a])
        self.assertEqual(self.owner.call("POST", "/api/chats/archive-all")[1]["archived"], 1)
        self.assertEqual(self.owner.call("GET", "/api/state")[1]["chats"], [])
        self.assertEqual(self.owner.call("POST", f"/api/chats/{a}/archive", {"archived": False})[0], 200)
        self.assertEqual([c["id"] for c in self.owner.call("GET", "/api/state")[1]["chats"]], [a])
        self.assertEqual(self.sam.call("POST", f"/api/chats/{b}/archive", {"archived": False})[0], 404)       # only your own chats

    def test_a_reply_uses_earlier_chats_when_asked_about_them(self):
        store = self.state.store("owner")
        old = chat(store, "Car trouble", "my car squeaks when I brake", "Worn brake pads.")
        store.set_archived(old)
        asked = []
        real = E.ChatStore.recall
        E.ChatStore.recall = lambda self, q, exclude_chat=None, **k: (asked.append(q), real(self, q, exclude_chat=exclude_chat, **k))[1]
        self.addCleanup(lambda: setattr(E.ChatStore, "recall", real))
        cid = self.owner.call("POST", "/api/chats", {})[1]["id"]
        st, h, ev = self.owner.stream(cid, {"text": "what did you say last time about my car squeaking when I brake?", "model": "flare-2", "effort": "balanced"})
        self.assertEqual(st, 200)
        self.assertTrue(asked)
        self.assertIn("brake pads", real(store, asked[0], exclude_chat=cid).lower())


@unittest.skipUnless(__import__("browser_check").available() and __import__("tests.test_browser_check", fromlist=["find_browser"]).find_browser(), "needs a browser")
class Page(Base):
    def test_archive_from_the_chat_menu_and_see_it_in_settings(self):
        from playwright.sync_api import sync_playwright
        from tests.test_browser_check import find_browser
        from tests.test_editor_ui import ready
        store = self.state.store("owner")
        a = chat(store, "Car trouble", "my car squeaks when I brake", "Brake pads.")
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 1200, "height": 850}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{self.port}/")
                ready(page)
                page.evaluate(f"archiveChat({{id: {a}, title: 'Car trouble'}}, true)")
                page.wait_for_timeout(600)
                self.assertNotIn("Car trouble", page.inner_text("#chatList"))
                page.evaluate("openArchived()")
                page.wait_for_selector(".modal >> text=Car trouble", timeout=5000)
                page.click(".modal >> text=Unarchive")
                page.wait_for_timeout(800)
                self.assertIn("Car trouble", page.inner_text("#chatList"))
                self.assertEqual(errors, [])
            finally:
                b.close()


if __name__ == "__main__":
    unittest.main()
