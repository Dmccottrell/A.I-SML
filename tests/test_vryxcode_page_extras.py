"""The VryxCode page parts behind the new VryxCode flags: the task box (vryxcode_taskbox), the plain Done / Not finished line with Continue
(vryxcode_autocontinue), Restore on each message (vryxcode_restore) and Save to GitHub / Publish (vryxcode_github, vryxcode_publish)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import browser_check
from tests.test_app_server import Base
import tests.test_vryxcode_review as review
from tests.test_browser_check import find_browser

SHOT = os.environ.get("EMVRYX_SHOT_DIR")                     # set it to keep a screenshot of the page


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    page = review.Page.page

    def open(self, p, *ids):
        for fid in ids:
            self.state.flags.data["audiences"][fid] = "admins"
        return self.page(p)

    def test_task_box_done_line_restore_and_ship_buttons(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b, page = self.open(p, "vryxcode_taskbox", "vryxcode_autocontinue", "vryxcode_restore", "vryxcode_github", "vryxcode_publish", "vryxcode_lines")
            try:
                page.evaluate("C.state = 'working'; cEvent({kind: 'start', task: 'build a tip calculator', turn: 1});"
                              "C.todo = [{text: 'Write the page', done: true}, {text: 'Add the tip buttons', done: false}, {text: 'Test it on a phone', done: false}]; renderTodo();")
                self.assertEqual(page.evaluate("[...document.querySelectorAll('#codeTodo .vt')].map((x) => x.className)"), ["vt is-done", "vt is-now", "vt is-todo"])
                self.assertEqual(page.locator("#codeIn .cc-user .vx-restore").count(), 1)
                page.evaluate("C.state = 'done'; renderTodo(); cEvent({kind: 'end', finished: true, summary: 'Built it.', turns: 4})")
                self.assertEqual(page.evaluate("[...document.querySelectorAll('#codeTodo .vt')].map((x) => x.className)"), ["vt is-done", "vt is-todo", "vt is-todo"])
                self.assertIn("Done: the task is finished", page.inner_text("#codeIn .vx-state.ok"))
                self.assertEqual(page.locator("#codeIn .vx-ship button").count(), 2)
                page.evaluate("cEvent({kind: 'user', text: 'now dark mode', turn: 2}); cEvent({kind: 'end', finished: false, reason: 'steps', rounds: 5, summary: '', turns: 12})")
                self.assertIn("Not finished: it used all its steps and carried on 5 times", page.inner_text("#codeIn .vx-state.no"))
                self.assertTrue(page.is_visible("#codeIn .vx-state.no button"))
                if SHOT:
                    page.screenshot(path=os.path.join(SHOT, "vryxcode_extras.png"), full_page=False)
            finally:
                b.close()

    def test_switched_off_none_of_it_shows(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b, page = self.open(p)
            try:
                page.evaluate("cEvent({kind: 'start', task: 'x', turn: 1}); C.todo = [{text: 'a', done: false}]; renderTodo(); cEvent({kind: 'end', finished: true, summary: 'ok', turns: 1})")
                self.assertEqual(page.locator("#codeTodo .vt, #codeIn .vx-restore, #codeIn .vx-state, #codeIn .vx-ship").count(), 0)
            finally:
                b.close()


if __name__ == "__main__":
    unittest.main()
