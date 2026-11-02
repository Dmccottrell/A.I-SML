"""Send feedback from the app (flag send_feedback): a person reports a bug, an idea or something confusing, from any screen. It lands in the owner's report list
tagged with where it came from, is limited to 10 an hour, and never ends up in the lessons export (it has no question and answer)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import browser_check
import flags
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import wait_for


class Flag(unittest.TestCase):
    def test_it_starts_with_the_owner_and_admins(self):
        self.assertEqual(flags.BY_ID["send_feedback"]["default"], "admins")
        self.assertEqual(flags.BY_ID["send_feedback"]["kind"], "feature")


class Server(Base):
    def setUp(self):
        super().setUp()
        self.state.flags.data["audiences"]["send_feedback"] = "admins"

    def test_a_report_is_saved_with_where_it_came_from(self):
        s, j = self.owner.call("POST", "/api/feedback", {"kind": "bug", "note": "The send button did nothing", "where": "VryxCode, Android"})
        self.assertEqual(s, 200, j)
        s, j = self.owner.call("GET", "/api/admin/feedback")
        self.assertEqual(s, 200, j)
        item = j["items"][0]
        self.assertEqual((item["kind"], item["note"], item["question"], item["model"]), ("bug", "The send button did nothing", "VryxCode, Android", "app"))
        self.assertIn("bug", j["kinds"])

    def test_an_empty_note_is_refused_and_an_odd_kind_becomes_other(self):
        s, j = self.owner.call("POST", "/api/feedback", {"kind": "bug", "note": "   "})
        self.assertEqual(s, 400, j)
        self.assertEqual(self.owner.call("POST", "/api/feedback", {"kind": "nonsense", "note": "hello"})[0], 200)
        self.assertEqual(self.owner.call("GET", "/api/admin/feedback")[1]["items"][0]["kind"], "other")

    def test_at_most_ten_an_hour(self):
        for n in range(10):
            self.assertEqual(self.owner.call("POST", "/api/feedback", {"kind": "idea", "note": f"idea {n}"})[0], 200)
        s, j = self.owner.call("POST", "/api/feedback", {"kind": "idea", "note": "one too many"})
        self.assertEqual(s, 429, j)

    def test_it_is_left_out_of_the_lessons_export(self):
        self.owner.call("POST", "/api/feedback", {"kind": "bug", "note": "x"})
        self.assertEqual(self.state.feedback.export_lines("new"), [])

    def test_with_the_switch_off_nothing_is_taken(self):
        self.state.flags.data["audiences"]["send_feedback"] = "off"
        self.assertNotEqual(self.owner.call("POST", "/api/feedback", {"kind": "bug", "note": "x"})[0], 200)
        self.assertEqual(self.state.feedback.counts()["total"], 0)


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    def test_the_button_in_settings_sends_the_note(self):
        from playwright.sync_api import sync_playwright
        self.state.flags.data["audiences"]["send_feedback"] = "admins"
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 420, "height": 860}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{self.port}/")
                wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state"))
                page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove()); openSettings('about')")
                page.wait_for_selector("text=Send feedback")
                page.evaluate("[...document.querySelectorAll('button.sbtn')].find((b) => b.textContent === 'Send feedback').click()")
                page.wait_for_selector("textarea[aria-label='Your feedback']")
                page.evaluate("document.querySelector(\"textarea[aria-label='Your feedback']\").value = 'The menu is hard to find'")
                page.evaluate("[...document.querySelectorAll('button.btn')].find((b) => b.textContent === 'Send').click()")
                wait_for(lambda: self.state.feedback.counts()["total"] == 1)
                item = self.state.feedback.list(1)[0]
                self.assertEqual((item["kind"], item["note"], item["model"]), ("bug", "The menu is hard to find", "app"))
                self.assertEqual(errors, [])
            finally:
                b.close()


if __name__ == "__main__":
    unittest.main()
