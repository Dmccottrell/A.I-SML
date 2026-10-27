"""apk_link: Settings has one fixed link to the newest Android app, made by the android workflow's release job (only from main)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import browser_check
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_editor_ui import ready

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
URL = "https://github.com/Dmccottrell/A.I-SML/releases/download/android-latest/emvryx.apk"


class Workflow(unittest.TestCase):
    def test_the_release_job_makes_the_file_the_link_points_to(self):
        with open(os.path.join(ROOT, ".github", "workflows", "android.yml"), encoding="utf-8") as f:
            text = f.read()
        job = text[text.index("  release:"):text.index("  screens:")]
        self.assertIn("github.ref == 'refs/heads/main'", job)                      # never from a pull request
        self.assertIn("gh release create android-latest emvryx.apk", job)
        self.assertIn("contents: write", job)


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Settings(Base):
    def shown(self, on):
        self.state.flags.data["audiences"]["apk_link"] = "admins" if on else "off"
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 420, "height": 860}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                page.goto(f"http://127.0.0.1:{self.port}/")
                ready(page)
                page.evaluate("openSettings('general')")
                page.wait_for_selector(".sx-sec")
                links = page.evaluate("[...document.querySelectorAll('a.sbtn')].map((a) => a.href)")
                if on:
                    page.click("text=Show code")
                    self.assertEqual(page.locator(".dialog svg").count(), 1)
                return URL in links
            finally:
                b.close()

    def test_on_the_link_and_its_code_are_there(self):
        self.assertTrue(self.shown(True))

    def test_off_it_is_not(self):
        self.assertFalse(self.shown(False))


if __name__ == "__main__":
    unittest.main()
