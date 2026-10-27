"""cloud_guide: Admin > Cloud machine walks through a free Oracle Cloud machine, and fills in the Oracle user and port."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import browser_check
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import wait_for
from tests.test_editor_ui import ready


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Guide(Base):
    def open(self, on):
        self.state.flags.data["audiences"]["cloud_guide"] = "admins" if on else "off"
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        b = p.chromium.launch(executable_path=find_browser())
        self.addCleanup(p.stop)
        self.addCleanup(b.close)
        page = b.new_context(viewport={"width": 420, "height": 860}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{self.port}/")
        ready(page)
        page.evaluate("openAdmin('cloud')")
        wait_for(lambda: page.locator("text=Test the connection").count() > 0)
        return page, errors

    def test_on_the_steps_are_there_and_fill_in_the_oracle_user(self):
        page, errors = self.open(True)
        text = page.inner_text("#admBody")
        for words in ("Free machine on Oracle Cloud", "VM.Standard.A1.Flex", "Never press Upgrade to Pay As You Go", "never open 3389"):
            self.assertIn(words, text)
        page.click("text=Fill in ubuntu and 22")
        self.assertEqual(page.evaluate("[...document.querySelectorAll('#admBody input')].map((i) => i.value).slice(1, 3)"), ["22", "ubuntu"])
        self.assertNotIn("null", page.evaluate("[...document.getElementById('sxAdmin').childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join('')"))
        self.assertEqual(errors, [])

    def test_off_it_is_not_there(self):
        page, errors = self.open(False)
        self.assertNotIn("Oracle", page.inner_text("#admBody"))


if __name__ == "__main__":
    unittest.main()
