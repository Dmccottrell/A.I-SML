"""The message box in the chosen model's colour (flag model_bar): its own colour, not the violet look's, and a pulse in it when a model is picked."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import browser_check
import flags
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import wait_for


class Flag(unittest.TestCase):
    def test_it_starts_with_the_owner_and_admins(self):
        self.assertEqual(flags.BY_ID["model_bar"]["default"], "admins")


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    def run_page(self, audience):
        self.state.flags.data["audiences"]["model_bar"] = audience
        self.state.flags.data["audiences"]["violet_theme"] = "admins"
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                page.goto(f"http://127.0.0.1:{self.port}/")
                wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state"), 15)
                page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove()); applyTheme()")
                css = lambda name: page.evaluate(f"getComputedStyle(document.documentElement).getPropertyValue('{name}').trim()")    # noqa: E731
                out = {"on": page.evaluate("document.body.classList.contains('mbar')"), "mbar": css("--mbar"), "accent": css("--accent"),
                       "own": page.evaluate("(MODEL[curModel() ? curModel().name : 'Emvryx'] || MODEL.Flare).dark.accent")}
                page.evaluate("wash()")
                out["pulse"] = page.evaluate("[...document.querySelectorAll('.composer .card')].some((c) => c.classList.contains('mbar-swap'))")
                out["border"] = page.evaluate("getComputedStyle(document.querySelector('.composer .card')).borderTopColor")
                return out
            finally:
                b.close()

    def test_the_box_wears_the_models_own_colour(self):
        r = self.run_page("admins")
        self.assertTrue(r["on"])
        self.assertEqual(r["mbar"].lower(), r["own"].lower())                     # the model's colour, while the rest of the app is violet
        self.assertEqual(r["accent"].lower(), "#8b5cf6")
        self.assertTrue(r["pulse"])

    def test_off_means_no_change(self):
        r = self.run_page("off")
        self.assertFalse(r["on"])


if __name__ == "__main__":
    unittest.main()
