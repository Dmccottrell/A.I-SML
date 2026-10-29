"""The page inside the Emvryx app for Windows (windows-app/main.cc): it says when a newer Windows app is ready (app_updates), and Settings offers
both apps to download."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import app_updates
import browser_check
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_editor_ui import ready


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    def open(self, built_from):
        if not getattr(self, "browser", None):                                          # one browser per test (Playwright starts once per thread)
            from playwright.sync_api import sync_playwright
            p = sync_playwright().start()
            self.browser = p.chromium.launch(executable_path=find_browser())
            self.addCleanup(p.stop)
            self.addCleanup(self.browser.close)
        b = self.browser
        ctx = b.new_context(viewport={"width": 1100, "height": 800}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()})
        if built_from is not None:                                                       # what main.cc puts in before the page loads
            ctx.add_init_script("window.EMVRYX_APP = {platform: 'windows', builtFrom: '%s'};" % built_from)
        page = ctx.new_page()
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{self.port}/")
        ready(page)
        return page

    def setUp(self):
        super().setUp()
        self.state.updates = app_updates.Updates(fetch=lambda url: b'{"sha": "newsha1", "built": "2026-10-29T12:00:00Z"}')
        self.state.flags.data["audiences"]["app_updates"] = "admins"

    def test_an_older_windows_app_is_told_and_later_waits_for_the_next(self):
        page = self.open("oldsha0")
        page.wait_for_selector("#appUpdate")
        self.assertIn("A new version of Emvryx is ready", page.inner_text("#appUpdate"))
        self.assertEqual(page.get_attribute("#appUpdate a", "href"), app_updates.DOWNLOADS["windows"])
        page.click("#appUpdate >> text=Later")
        self.assertEqual(page.locator("#appUpdate").count(), 0)
        page.reload()
        ready(page)
        page.wait_for_timeout(1500)
        self.assertEqual(page.locator("#appUpdate").count(), 0)                        # not asked again about this build
        self.assertEqual(self.errors, [])

    def test_the_newest_app_or_a_browser_is_not_told(self):
        for built in ("newsha1", None):
            page = self.open(built)
            page.wait_for_timeout(1500)
            self.assertEqual(page.locator("#appUpdate").count(), 0, built)
            self.assertEqual(self.errors, [])

    def test_settings_offers_both_apps(self):
        self.state.flags.data["audiences"]["apk_link"] = "admins"
        page = self.open(None)
        page.evaluate("openSettings()")
        page.wait_for_selector("text=Get the Windows app")
        self.assertEqual(page.get_attribute("a:text-is('Download for Windows')", "href"), app_updates.DOWNLOADS["windows"])
        self.assertEqual(page.get_attribute("a:text-is('Download for Android')", "href"), app_updates.DOWNLOADS["android"])
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
