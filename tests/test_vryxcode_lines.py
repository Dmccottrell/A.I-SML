"""The Claude Code-style VryxCode feed (flag vryxcode_lines): looking and running fold into one grey line that opens on a tap, the model's
words in between, file changes as chips, a plain box for the person's message, and a working line with moving dots."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import browser_check
import flags
from tests.test_app_server import Base
import tests.test_vryxcode_review as review
from tests.test_browser_check import find_browser

EVENTS = ("cEvent({kind: 'start', task: 'build the quest log'});"
          "cEvent({kind: 'step', tool: 'read_file', preview: 'read_file {\"path\": \"app.py\"}', raw: '', secs: 3});"
          "cEvent({kind: 'result', text: '1: import os'});"
          "cEvent({kind: 'step', tool: 'read_file', preview: 'read_file {\"path\": \"db.sql\"}', raw: ''});"
          "cEvent({kind: 'result', text: '1: CREATE TABLE'});"
          "cEvent({kind: 'step', tool: 'run', preview: 'run {\"command\": \"python -m pytest\"}', raw: ''});"
          "cEvent({kind: 'result', text: 'exit code 1\\nFAILED test_quests'});"
          "cEvent({kind: 'step', tool: 'edit_file', preview: 'edit quests.py\\n  - a\\n  + b', raw: 'The test fails because the table is empty. Fixing the query.<|tool_call|>{}', add: 3, del: 1});"
          "cEvent({kind: 'result', text: 'edited quests.py'});"
          "cEvent({kind: 'step', tool: 'run', preview: 'run {\"command\": \"python -m pytest\"}', raw: ''});"
          "cEvent({kind: 'result', text: 'exit code 0\\n3 passed'});")


class Flag(unittest.TestCase):
    def test_it_starts_with_the_owner_and_admins(self):
        self.assertEqual(flags.BY_ID["vryxcode_lines"]["default"], "admins")


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    page = review.Page.page                                    # the same page opened on a new session (not its tests)

    def open(self, p, on=True):
        self.state.flags.data["audiences"]["vryxcode_lines"] = "admins" if on else "off"
        return self.page(p)

    def test_steps_fold_into_lines_with_words_and_chips_between(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b, page = self.open(p)
            try:
                page.evaluate(EVENTS)
                heads = page.evaluate("[...document.querySelectorAll('#codeIn .vx-grp > .h')].map((x) => x.textContent)")
                self.assertEqual(heads, ["Thought 3s, read 2 files, ran a command", "Ran a command"])
                self.assertEqual(page.locator("#codeIn .vx-grp.vx-bad").count(), 1)                  # the first one has the failed test run in it
                order = page.evaluate("[...document.querySelectorAll('#codeIn > *')].map((x) => x.className.split(' ')[0])")
                self.assertEqual(order[:5], ["cc-user", "vx-grp", "cc-say", "cc-file", "vx-grp"])       # the words sit between the folded lines
                self.assertFalse(page.is_visible("#codeIn .vx-grp .list"))
                page.click("#codeIn .vx-grp > .h >> nth=0")
                self.assertTrue(page.is_visible("#codeIn .vx-grp .list >> nth=0"))
                page.evaluate("renderLive({phase: 'run', tool: 'run', target: 'pytest', secs: 64}, 'working')")
                self.assertTrue(page.is_visible("#codeLive .dots svg.logo-dots"))                   # the Emvryx mark, its dot as three moving dots
            finally:
                b.close()

    def test_off_keeps_the_look_as_it_was(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b, page = self.open(p, on=False)
            try:
                page.evaluate(EVENTS)
                self.assertEqual(page.locator("#codeIn .vx-grp").count(), 0)
            finally:
                b.close()


if __name__ == "__main__":
    unittest.main()
