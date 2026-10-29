"""VryxCode sessions on the left (flag vryxcode_side_list): on a wide screen the VryxCode home shows the sessions list in a column on the left,
next to "What should we build?"; on a phone, and with the switch off, the list stays under it."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import browser_check
import flags
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import wait_for

SHOT = os.environ.get("EMVRYX_SHOT_DIR")


class Flag(unittest.TestCase):
    def test_it_starts_with_the_owner_and_admins(self):
        self.assertEqual(flags.BY_ID["vryxcode_side_list"]["default"], "admins")


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    def boxes(self, audience, width):
        """Where the sessions list and the "What should we build?" box are drawn: ({x, y, width}, {x, y, width})."""
        from playwright.sync_api import sync_playwright
        self.state.flags.data["audiences"]["vryxcode_side_list"] = audience
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": width, "height": 860}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{self.port}/")
                wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state"))
                page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove()); openCode()")
                wait_for(lambda: page.evaluate("!!(C.info && C.info.environments)"))
                page.wait_for_timeout(300)
                self.assertEqual(errors, [])
                if SHOT and audience != "off" and width > 1000:
                    page.screenshot(path=os.path.join(SHOT, "vryxcode-side-list.png"))
                return page.locator("#codeList").bounding_box(), page.locator(".vx-hero").bounding_box()
            finally:
                b.close()

    def test_wide_screen_puts_the_sessions_on_the_left(self):
        import vryxcode
        from tests.test_code_sessions import open_to_everyone
        open_to_everyone(self.state)
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(['<|tool_call|>{"name": "finish", "args": {"summary": "done"}}<|end_tool_call|>'])
        for project, task in (("portfolio", "Build a portfolio page with three projects"), ("tips", "A bill splitter with tip")):
            s, j = self.owner.call("POST", "/api/code/start", {"project": project, "task": task, "model": "solstice-2"})
            self.assertEqual(s, 200, j)
            wait_for(lambda: self.state.code.sessions[j["id"]].state not in ("starting", "working"))
        lst, hero = self.boxes("admins", 1300)
        self.assertLess(lst["x"] + lst["width"], hero["x"] + 1)                  # the list ends where the build box begins
        self.assertLess(abs(lst["y"] - hero["y"]), 120)                           # side by side, not one under the other

    def test_off_or_a_phone_keeps_the_list_underneath(self):
        for audience, width in (("off", 1300), ("admins", 420)):
            lst, hero = self.boxes(audience, width)
            self.assertGreater(lst["y"], hero["y"] + hero["height"] - 1, (audience, width))


if __name__ == "__main__":
    unittest.main()
