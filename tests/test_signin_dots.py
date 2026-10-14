"""The sign-in screen's reactive dots: a canvas behind the form that redraws when the pointer moves."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest
from tests.test_editor_ui import eventually

import browser_check
from tests.test_app_server import Base
from tests.test_browser_check import find_browser


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class SignInDots(Base):
    def test_dots_follow_the_pointer(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 1400, "height": 800}).new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{self.port}/")
                page.wait_for_selector("#auth canvas.dots", state="attached", timeout=8000)
                grab = lambda: page.eval_on_selector("#auth canvas.dots", "c => c.toDataURL()")
                page.mouse.move(200, 200)
                page.wait_for_timeout(700)
                one = grab()
                page.mouse.move(1000, 600, steps=8)
                page.wait_for_timeout(700)
                two = grab()
                self.assertNotEqual(one, two)
                self.assertGreater(len(two), 5000)                    # something was really drawn
                if os.environ.get("DOTS_SHOT"):
                    page.screenshot(path=os.environ["DOTS_SHOT"])
                self.assertEqual(errors, [])
            finally:
                b.close()

    def test_violet_look_is_behind_the_flag(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                for audience, want in (("owner", True), ("off", False)):
                    self.state.flags.set_audience("violet_theme", audience)
                    page.goto(f"http://127.0.0.1:{self.port}/")
                    eventually(lambda: self.assertEqual(page.evaluate("violetOn()"), want, audience))
                    accent = lambda: page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim().toUpperCase()")
                    eventually(lambda: self.assertEqual(accent() in ("#8B5CF6", "#7C3AED"), want, audience))      # the chat itself, with a model chosen
                    eventually(lambda: self.assertEqual(page.evaluate("!!S.state && !!JSON.parse(localStorage.getItem('emvryx_looks') || '{}').vi"), want, audience))   # signed in and remembered
                    page.evaluate("S.state = null; applyTheme()")                                             # signed out: the sign-in screen remembers the look
                    self.assertEqual(accent() in ("#8B5CF6", "#7C3AED"), want, audience)
            finally:
                b.close()


if __name__ == "__main__":
    unittest.main()
