"""Delete or archive any VryxCode session (flag vryxcode_archive): a session can be tucked away into an Archived list (kept, with its files and history,
and brought back any time) or deleted for good. Archived sessions are not in the normal list."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import browser_check
import flags
import vryxcode
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import open_to_everyone, wait_for

FINISH = '<|tool_call|>{"name": "finish", "args": {"summary": "done"}}<|end_tool_call|>'      # a session that ends at once


class Flag(unittest.TestCase):
    def test_it_starts_with_the_owner_and_admins(self):
        self.assertEqual(flags.BY_ID["vryxcode_archive"]["default"], "admins")
        self.assertEqual(flags.BY_ID["vryxcode_archive"]["kind"], "feature")


class Server(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        self.state.flags.data["audiences"]["vryxcode_archive"] = "admins"
        self.state.code_generate = lambda model: vryxcode.ScriptedChat([FINISH])

    def make(self, project="tips", who=None):
        s, j = (who or self.owner).call("POST", "/api/code/start", {"project": project, "task": "A bill splitter in " + project, "model": "solstice-2"})
        self.assertEqual(s, 200, j)
        wait_for(lambda: self.state.code.sessions[j["id"]].state == "done")
        return j["id"]

    def ids(self, query="", who=None):
        s, j = (who or self.owner).call("GET", "/api/code/sessions" + query)
        self.assertEqual(s, 200, j)
        return [x["id"] for x in j["sessions"]]

    def test_archiving_hides_it_from_the_list_and_shows_it_in_archived(self):
        a, b = self.make("one"), self.make("two")
        self.assertEqual(set(self.ids()), {a, b})
        s, j = self.owner.call("POST", f"/api/code/sessions/{a}/archive", {"archived": True})
        self.assertEqual(s, 200, j)
        self.assertEqual(self.ids(), [b])                                   # gone from the normal list
        self.assertEqual(self.ids("?archived=1"), [a])                      # but kept
        s, j = self.owner.call("POST", f"/api/code/sessions/{a}/archive", {"archived": False})
        self.assertEqual(s, 200, j)
        self.assertEqual(set(self.ids()), {a, b})                           # brought back
        self.assertEqual(self.ids("?archived=1"), [])

    def test_a_session_read_back_from_disk_can_be_archived_too(self):
        a = self.make()
        self.state.code.sessions.pop(a)                                     # as after a server restart: only the saved history is left
        self.assertEqual(self.owner.call("POST", f"/api/code/sessions/{a}/archive", {"archived": True})[0], 200)
        self.assertEqual(self.ids(), [])
        self.assertEqual(self.ids("?archived=1"), [a])
        # still there to open
        self.assertEqual(self.owner.call("GET", f"/api/code/sessions/{a}")[0], 200)

    def test_an_archived_session_can_be_deleted_for_good(self):
        a = self.make()
        self.owner.call("POST", f"/api/code/sessions/{a}/archive", {"archived": True})
        self.assertEqual(self.owner.call("POST", f"/api/code/sessions/{a}/delete", {})[0], 200)
        self.assertEqual(self.ids("?archived=1"), [])

    def test_only_your_own_sessions_and_only_with_the_switch_on(self):
        a = self.make()
        s, j = self.sam.call("POST", f"/api/code/sessions/{a}/archive", {"archived": True})
        self.assertNotEqual(s, 200)                                          # someone else's session: not found
        self.assertEqual(self.ids(), [a])
        self.state.flags.data["audiences"]["vryxcode_archive"] = "off"
        self.assertNotEqual(self.owner.call("POST", f"/api/code/sessions/{a}/archive", {"archived": True})[0], 200)

    def test_a_running_session_cannot_be_archived(self):
        a = self.make()
        self.state.code.sessions[a].state = "working"
        self.assertNotEqual(self.owner.call("POST", f"/api/code/sessions/{a}/archive", {"archived": True})[0], 200)
        self.state.code.sessions[a].state = "done"


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    def test_a_session_has_a_menu_and_an_archived_filter(self):
        from playwright.sync_api import sync_playwright
        open_to_everyone(self.state)
        self.state.flags.data["audiences"]["vryxcode_archive"] = "admins"
        self.state.flags.data["audiences"]["vryxcode_projects"] = "admins"
        self.state.code_generate = lambda model: vryxcode.ScriptedChat([FINISH])
        ids = []
        for project in ("one", "two"):
            s, j = self.owner.call("POST", "/api/code/start", {"project": project, "task": "A bill splitter in " + project, "model": "solstice-2"})
            self.assertEqual(s, 200, j)
            wait_for(lambda: self.state.code.sessions[j["id"]].state == "done")
            ids.append(j["id"])
        self.owner.call("POST", f"/api/code/sessions/{ids[1]}/archive", {"archived": True})
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 420, "height": 860}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{self.port}/")
                wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state"))
                page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove()); openCode()")
                page.wait_for_selector(f".vx-prow[data-id='{ids[0]}'] .more")                # the normal list shows the first, with its menu
                self.assertEqual(page.locator(f".vx-prow[data-id='{ids[1]}']").count(), 0)     # the archived one is not in it
                page.evaluate("C.filter = 'archived'; renderHome()")
                page.wait_for_selector("#codeList .scard")                                    # ...but is under Archived (shown as a plain card list)
                self.assertEqual(page.locator("#codeList .scard").count(), 1)
                self.assertIn("two", page.inner_text("#codeList .scard"))
                page.evaluate("document.querySelector('#codeList .scard .more').click()")        # a script click: the welcome tour may still be on top on a slow machine
                page.wait_for_selector(".dialog >> text=Restore to the list")
                self.assertEqual(errors, [])
            finally:
                b.close()


if __name__ == "__main__":
    unittest.main()
