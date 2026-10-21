"""VryxCode projects organizer (flag vryxcode_projects): a new idea gets its own project named from it, and the list shows each project with its sessions."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import browser_check
import flags
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import wait_for


class Flag(unittest.TestCase):
    def test_it_starts_with_the_owner_and_admins(self):
        self.assertEqual(flags.BY_ID["vryxcode_projects"]["default"], "admins")


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    def page(self, p, audience="admins"):
        self.state.flags.data["audiences"]["vryxcode_projects"] = audience
        b = p.chromium.launch(executable_path=find_browser())
        page = b.new_context(viewport={"width": 420, "height": 860}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
        page.goto(f"http://127.0.0.1:{self.port}/")
        wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state"), 15)
        page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove()); openCode()")
        wait_for(lambda: page.evaluate("!!(C.info && C.info.projects)"), 15)
        return b, page

    def test_names_come_from_the_idea(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b, page = self.page(p)
            try:
                for idea, name in (("A bill splitter with tip and number of people", "bill-splitter"), ("A to-do list that saves in the browser", "to-do-list"),
                                   ("Please make me a snake game in one HTML file", "snake-game"), ("!!!", "new-project")):
                    self.assertEqual(page.evaluate("t => vxIdeaName(t)", idea), name)
                page.evaluate("C.info.projects = ['bill-splitter']")
                self.assertEqual(page.evaluate("vxFreeName(vxIdeaName('a bill splitter'))"), "bill-splitter-2")
            finally:
                b.close()

    def test_a_new_idea_starts_in_its_own_project(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b, page = self.page(p)
            try:
                sent = []
                page.route("**/api/code/start", lambda r: (sent.append(r.request.post_data_json), r.fulfill(status=400, json={"message": "stop here"})))
                page.evaluate("C.project = 'Portfolio-Page'; C.model = C.model || 'flare-2'")
                page.fill("#vxQuick", "A habit tracker with streaks")
                self.assertIn("habit-tracker", page.inner_text("#vxWhere"))
                page.evaluate("$('vxQuickGo').click()")
                for _ in range(50):                                                  # the request is seen while the page is being driven
                    if sent:
                        break
                    page.wait_for_timeout(200)
                self.assertEqual(sent[0]["project"], "habit-tracker")
            finally:
                b.close()

    def test_off_keeps_building_in_the_current_project(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b, page = self.page(p, "off")
            try:
                sent = []
                page.route("**/api/code/start", lambda r: (sent.append(r.request.post_data_json), r.fulfill(status=400, json={"message": "stop here"})))
                page.evaluate("C.project = 'Portfolio-Page'; C.model = C.model || 'flare-2'")
                page.fill("#vxQuick", "A habit tracker with streaks")
                page.evaluate("$('vxQuickGo').click()")
                for _ in range(50):                                                  # the request is seen while the page is being driven
                    if sent:
                        break
                    page.wait_for_timeout(200)
                self.assertEqual(sent[0]["project"], "Portfolio-Page")
            finally:
                b.close()

    def test_the_organizer_lists_projects_with_their_sessions(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b, page = self.page(p)
            try:
                rows_ = [{"id": "a", "title": "Landing page", "project": "site", "state": "done", "updated": 9, "age": "now", "files": 2, "added": 70, "removed": 0},
                         {"id": "b", "title": "Snake", "project": "game", "state": "working", "updated": 5, "age": "1h"},
                         {"id": "c", "title": "Fix header", "project": "site", "state": "done", "updated": 3, "age": "2h"}]
                page.route("**/api/code/sessions", lambda r: r.fulfill(json={"sessions": rows_}))
                errs = []
                page.on("pageerror", lambda e: errs.append(str(e)))
                page.evaluate("C.filter = 'all'; renderHome()")
                wait_for(lambda: page.evaluate("document.querySelectorAll('.vx-proj').length >= 2"), 10)
                self.assertEqual(errs, [])
                heads = page.evaluate("[...document.querySelectorAll('.vx-phead .nm')].map((x) => x.textContent)")
                self.assertEqual(heads[:2], ["site", "game"])                               # newest work first
                rows = page.evaluate("[...document.querySelectorAll('.vx-proj')][0].innerText")
                self.assertIn("Landing page", rows)
                self.assertIn("Fix header", rows)
                self.assertEqual(page.locator(".vx-prow.ready").count(), 1)
                page.evaluate("[...document.querySelectorAll('.vx-phead')].find((h) => h.textContent.includes('game')).querySelector('.add').click()")
                wait_for(lambda: page.evaluate("C.view === 'session' && C.project === 'game'"), 10)
            finally:
                b.close()


if __name__ == "__main__":
    unittest.main()
