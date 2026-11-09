"""Sending in VryxCode: Enter on the keyboard sends (Shift+Enter starts a new line, like the chat), and your message is on screen the moment you send it, not after the server has
answered (there was a pause between pressing the arrow and anything happening). If the send fails, your words go back in the box."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import time
import unittest

import browser_check
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import wait_for
from tests.test_vryxcode_waiting import Page as WaitingPage


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Send(Base):
    waiting_page = WaitingPage.waiting_page

    def session_page(self):
        page = self.waiting_page("The function is in utils.py and it looks fine to me.", task="why is it slow?")
        page.evaluate("window.__clicks = 0; document.getElementById('codeGo').addEventListener('click', () => { window.__clicks++; }, true)")
        page.evaluate("window.__posts = []; const f = window.fetch; window.fetch = (u, o) => { if (String(u).includes('/message')) window.__posts.push(String(u)); return f(u, o); }")
        return page

    def test_enter_sends_and_shift_enter_makes_a_new_line(self):
        page = self.session_page()
        box = page.locator("#codeTask")
        box.focus(); box.fill("first line"); box.press("Shift+Enter"); box.type("second line")
        self.assertEqual(page.evaluate("document.getElementById('codeTask').value"), "first line\nsecond line")
        self.assertEqual(page.evaluate("window.__clicks"), 0)                  # Shift+Enter did not send
        box.press("Enter")
        wait_for(lambda: page.evaluate("window.__clicks") == 1)                # Enter did
        self.assertEqual(self.errors, [])

    def test_the_stopping_state_is_cleared_once_the_session_is_no_longer_working(self):
        # After Stop, the page remembers "stopping" and greys the Stop button. When the session has ended that must be undone, or the next
        # running session shows "Stopping" and a dead Stop button. (A line that did this sat inside a comment, so it never ran.)
        page = self.session_page()
        page.evaluate("C.stopping = true; document.getElementById('codeStop').disabled = true")
        page.evaluate("poll()")
        wait_for(lambda: page.evaluate("C.stopping") is False)
        self.assertFalse(page.evaluate("document.getElementById('codeStop').disabled"))
        self.assertEqual(self.errors, [])

    def test_enter_on_an_empty_box_does_nothing(self):
        page = self.session_page()
        page.locator("#codeTask").focus()
        page.locator("#codeTask").press("Enter")
        page.wait_for_timeout(200)
        self.assertEqual(page.evaluate("window.__clicks"), 0)

    def test_the_message_is_on_screen_at_once_and_a_failed_send_gives_the_words_back(self):
        page = self.session_page()
        held = []
        page.route("**/api/code/sessions/*/message", lambda route: held.append(route))          # the server "has not answered yet"
        box = page.locator("#codeTask")
        box.focus(); box.fill("please add a dark mode")
        t0 = time.monotonic()
        box.press("Enter")
        wait_for(lambda: page.evaluate("[...document.querySelectorAll('#codeIn .cc-user.pending')].some((n) => n.innerText.includes('please add a dark mode'))"), 3)
        self.assertLess(time.monotonic() - t0, 1.0)                              # on screen while the server has not answered at all
        self.assertEqual(page.evaluate("document.getElementById('codeTask').value"), "")      # and the box is empty, ready for the next thing
        wait_for(lambda: len(held) == 1)
        held[0].fulfill(status=500, content_type="application/json", body='{"message": "The server is busy."}')           # now it fails
        wait_for(lambda: page.evaluate("document.getElementById('codeTask').value") == "please add a dark mode")        # the words are back
        self.assertEqual(page.evaluate("document.querySelectorAll('#codeIn .cc-user.pending').length"), 0)
        self.assertEqual(self.errors, [])

    def test_the_pending_message_becomes_the_real_one_without_a_double(self):
        page = self.session_page()
        box = page.locator("#codeTask")
        box.focus(); box.fill("add a footer"); box.press("Enter")
        wait_for(lambda: page.evaluate("[...document.querySelectorAll('#codeIn .cc-user')].filter((n) => n.innerText.includes('add a footer')).length") >= 1)
        wait_for(lambda: page.evaluate("document.querySelectorAll('#codeIn .cc-user.pending').length") == 0, 30)      # the server's copy replaced it
        self.assertEqual(page.evaluate("[...document.querySelectorAll('#codeIn .cc-user')].filter((n) => n.innerText.includes('add a footer')).length"), 1)


if __name__ == "__main__":
    unittest.main()
