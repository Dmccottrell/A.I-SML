"""Share links, "Your day", and the page pieces for exporting a chat and asking a stronger model."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import unittest

import app_links as L
import shares as SH
from tests.test_app_links import Fake, ICS, NOW, reply
from tests.test_app_server import Base, Client


class Store(unittest.TestCase):
    def test_links_expire_can_be_cancelled_and_hold_only_a_copy(self):
        s = SH.Shares()
        msgs = [{"role": "user", "content": "hi", "model": ""}, {"role": "assistant", "content": "hello", "model": "Flare"}, {"role": "assistant", "content": "", "model": "x"}]
        token = s.create("sam", 1, "My chat", msgs, days=2, now=1000)
        snap = s.get(token, now=1001)
        self.assertEqual([m["content"] for m in snap["messages"]], ["hi", "hello"])             # empty messages are left out
        msgs.append({"role": "user", "content": "later", "model": ""})
        self.assertEqual(len(s.get(token, now=1001)["messages"]), 2)                              # later messages are not in the copy
        self.assertIsNone(s.get(token, now=1000 + 3 * 86400))                                     # expired
        self.assertIsNone(s.get("wrong", now=1001))
        sid = s.list("sam", now=1001)[0]["id"]
        self.assertFalse(s.revoke("kim", sid))                                                    # only the maker can cancel
        self.assertTrue(s.revoke("sam", sid))
        self.assertIsNone(s.get(token, now=1001))

    def test_limits(self):
        s = SH.Shares()
        with self.assertRaises(ValueError):
            s.create("sam", 1, "t", [])
        for _ in range(SH.MAX_ACTIVE):
            s.create("sam", 1, "t", [{"role": "user", "content": "x"}])
        with self.assertRaises(ValueError):
            s.create("sam", 1, "t", [{"role": "user", "content": "x"}])
        with self.assertRaises(ValueError):
            s.create("kim", 1, "t", [{"role": "user", "content": "x" * (SH.MAX_BYTES + 10)}])

    def test_the_page_escapes_everything(self):
        page = SH.render({"title": "<script>alert(1)</script>", "created": 0, "expires": 86400, "messages": [{"role": "user", "content": "<img src=x onerror=alert(1)>", "model": ""},
                                                                                                             {"role": "assistant", "content": "a & b", "model": "<b>Flare</b>"}]})
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("<img", page)
        self.assertNotIn("<b>Flare", page)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", page)
        self.assertIn("noindex", page)


class Server(Base):
    data_dir = True

    def chat(self, who=None):
        who = who or self.sam
        cid = self.new_chat(who)
        self.ask(who, cid, "Tell me about foxes please")
        return cid

    def test_sharing_is_off_until_the_owner_turns_it_on(self):
        cid = self.chat()
        s, j = self.sam.call("POST", f"/api/chats/{cid}/share", {})
        self.assertEqual((s, j["code"]), (403, "sharing_off"))
        self.assertEqual(self.sam.call("POST", "/api/admin/sharing", {"on": True})[0], 403)         # only the owner
        self.assertEqual(self.owner.call("POST", "/api/admin/sharing", {"on": True})[0], 200)
        self.assertTrue(self.sam.call("GET", "/api/shares")[1]["on"])

    def test_make_read_and_cancel_a_link(self):
        self.owner.call("POST", "/api/admin/sharing", {"on": True})
        cid = self.chat()
        s, j = self.sam.call("POST", f"/api/chats/{cid}/share", {"days": 3})
        self.assertEqual(s, 200, j)
        s, h, page = Client(self.port).call("GET", j["url"], raw=True)                              # no sign-in needed
        self.assertEqual(s, 200)
        text = page.decode()
        self.assertIn("Tell me about foxes please", text)
        self.assertIn("Sure thing, here is your answer.", text)
        self.assertIn("default-src 'none'", h.get("Content-Security-Policy", ""))
        self.assertEqual(self.sam.call("POST", "/api/shares/revoke", {"id": j["shares"][0]["id"]})[1]["ok"], True)
        self.assertEqual(Client(self.port).call("GET", j["url"], raw=True)[0], 404)

    def test_turning_sharing_off_stops_every_link(self):
        self.owner.call("POST", "/api/admin/sharing", {"on": True})
        url = self.sam.call("POST", f"/api/chats/{self.chat()}/share", {})[1]["url"]
        self.owner.call("POST", "/api/admin/sharing", {"on": False})
        self.assertEqual(Client(self.port).call("GET", url, raw=True)[0], 404)

    def test_private_and_other_peoples_chats_cannot_be_shared_and_bad_links_are_404(self):
        self.owner.call("POST", "/api/admin/sharing", {"on": True})
        priv = self.new_chat(self.sam, private=True)
        self.ask(self.sam, priv, "secret")
        self.assertEqual(self.sam.call("POST", f"/api/chats/{priv}/share", {})[0], 400)
        cid = self.chat()
        self.assertEqual(self.owner.call("POST", f"/api/chats/{cid}/share", {})[0], 404)
        self.assertEqual(Client(self.port).call("GET", "/s/" + "a" * 32, raw=True)[0], 404)

    def test_deleting_an_account_removes_the_links(self):
        self.owner.call("POST", "/api/admin/sharing", {"on": True})
        url = self.sam.call("POST", f"/api/chats/{self.chat()}/share", {})[1]["url"]
        self.sam.call("POST", "/api/delete-account", {"confirm": "sam"})
        self.assertEqual(Client(self.port).call("GET", url, raw=True)[0], 404)

    def test_the_page_has_the_chat_menu_the_export_and_the_stronger_model_button(self):
        page = Client(self.port).call("GET", "/", raw=True)[2].decode()
        for word in ("chatMore", "shareDialog", "chatAsText", "strongerModel", "dayCard", "Plan my day with Emvryx"):
            self.assertIn(word, page)


class Day(Base):
    data_dir = True

    def setUp(self):
        super().setUp()
        self.state.links.http = Fake({"cal.example": reply(ICS.encode()), "/api/v1/tasks": reply({"results": [{"content": "Pay rent", "due": {"string": "today"}}]}), "api.todoist.com/api/v1/projects": reply([])})
        self.state.links.clock = lambda: NOW
        self.state.links.store.connect("sam", "calendar", {"url": "https://cal.example/x.ics"}, "cal")
        self.state.links.store.connect("sam", "todoist", {"token": "t"}, "tasks")

    def test_your_day_reads_calendar_and_tasks_and_a_failing_app_only_marks_itself(self):
        s, j = self.sam.call("GET", "/api/briefing")
        self.assertEqual(s, 200)
        kinds = [x["kind"] for x in j["sections"]]
        self.assertEqual(kinds, ["Calendar today", "Open tasks"])
        self.assertTrue(any(i["title"] == "A very long title" for i in j["sections"][0]["items"]))   # 15:00 today in the test calendar
        self.assertEqual(j["sections"][1]["items"][0]["title"], "Pay rent")
        self.state.links.cache.clear()
        self.state.links.http = Fake({"cal.example": (500, b""), "/api/v1/tasks": reply({"results": [{"content": "Pay rent"}]})})
        j = self.sam.call("GET", "/api/briefing")[1]
        self.assertTrue(j["sections"][0]["error"])
        self.assertEqual(j["sections"][1]["items"][0]["title"], "Pay rent")

    def test_the_state_says_whether_there_is_a_day_to_show_and_the_setting_turns_it_off(self):
        self.assertTrue(self.sam.call("GET", "/api/state")[1]["briefing"])
        self.assertFalse(self.owner.call("GET", "/api/state")[1]["briefing"])                      # nothing connected
        self.sam.call("POST", "/api/settings", {"connected_apps": False})
        self.assertFalse(self.sam.call("GET", "/api/state")[1]["briefing"])
        self.assertEqual(self.sam.call("GET", "/api/briefing")[1]["sections"], [])

    def test_the_plain_text_form(self):
        j = L.briefing(self.state.links, "sam")
        t = L.briefing_text(j)
        self.assertIn("Calendar today (Calendar):", t)
        self.assertIn("- Pay rent", t)


if __name__ == "__main__":
    unittest.main()
