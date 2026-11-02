"""When VryxCode ends a turn with "Not finished yet: it is waiting for your answer", it must prompt: tap-to-send answers under it, and a recommended reply greyed in the
message box (Tab or a swipe takes it). What it recommends depends on what it said: a question gets "Yes, go ahead."; anything else gets a push to save the work and explain."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import browser_check
import vryxcode
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import open_to_everyone, wait_for


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    def waiting_page(self, words, task="fix my code"):
        from playwright.sync_api import sync_playwright
        open_to_everyone(self.state)
        for flag in ("vryxcode_autocontinue", "vryxcode_suggest"):
            self.state.flags.data["audiences"][flag] = "admins"
        self.state.code_generate = lambda model: vryxcode.ScriptedChat([words])
        s, j = self.owner.call("POST", "/api/code/start", {"project": "tips", "task": task, "model": "solstice-2"})
        self.assertEqual(s, 200, j)
        wait_for(lambda: self.state.code.sessions[j["id"]].state in ("done", "stopped"))
        p = sync_playwright().start()
        self.addCleanup(p.stop)
        b = p.chromium.launch(executable_path=find_browser())
        self.addCleanup(b.close)
        page = b.new_context(viewport={"width": 420, "height": 860}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{self.port}/")
        wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state"))
        page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove()); openCode()")
        page.wait_for_selector(".vx-prow, .scard")
        page.evaluate("document.querySelector('.vx-prow, .scard').click()")
        page.wait_for_selector("#codeIn .vx-replies")
        return page

    def test_a_question_gets_yes_go_ahead_first(self):
        page = self.waiting_page("I found two files that could be the problem. Which one should I fix first?")
        chips = page.evaluate("[...document.querySelectorAll('#codeIn .vx-replies .chip')].map((b) => b.textContent)")
        self.assertEqual(chips[0], "Yes, go ahead.")
        self.assertGreaterEqual(len(chips), 3)
        self.assertEqual(page.evaluate("document.getElementById('codeTask').placeholder"), "Yes, go ahead.")      # the recommended reply, greyed in the box
        self.assertEqual(self.errors, [])

    def test_a_statement_gets_a_push_to_save_and_explain_and_a_tap_sends_it(self):
        page = self.waiting_page("The function is in utils.py and it looks fine to me.")
        chips = page.evaluate("[...document.querySelectorAll('#codeIn .vx-replies .chip')].map((b) => b.textContent)")
        self.assertIn("save", chips[0].lower())
        self.assertIn("explain", " ".join(chips).lower())
        sent = []
        page.expose_function("seen", lambda t: sent.append(t))
        page.evaluate("document.getElementById('codeGo').addEventListener('click', () => window.seen(document.getElementById('codeTask').value), true)")
        page.evaluate("document.querySelector('#codeIn .vx-replies .chip').click()")
        wait_for(lambda: len(sent) == 1)
        self.assertEqual(sent[0], chips[0])                                                                         # one tap puts it in the box and sends it
        self.assertEqual(self.errors, [])

    def test_a_question_that_was_answered_is_not_left_waiting(self):
        """After "why did it fail" and a plain explanation there is no "Not finished yet" line and no repeat of what was just asked; "Show me what you changed" opens the changes."""
        page = self.waiting_page("The test was wrong because the address had no @ symbol.", task="why did it fail")
        page.wait_for_selector("#codeIn .vx-replies")
        self.assertEqual(page.evaluate("document.querySelectorAll('#codeIn .vx-state.wait').length"), 0)
        chips = page.evaluate("[...document.querySelectorAll('#codeIn .vx-replies .chip')].map((b) => b.textContent)")
        self.assertIn("Show me what you changed.", chips)
        self.assertFalse(any("save the fix" in c for c in chips))
        page.evaluate("document.querySelector('#codeIn .vx-replies .chip').click()")
        wait_for(lambda: page.evaluate("!!document.getElementById('codeDrawer') && !document.getElementById('codeDrawer').hidden"))
        self.assertEqual(page.evaluate("document.querySelectorAll('#codeIn .cc-user').length"), 1)          # nothing was sent to the model
        self.assertEqual(self.errors, [])

    def test_a_task_that_stopped_is_still_waiting(self):
        page = self.waiting_page("The function is in utils.py and it looks fine to me.", task="fix my code")
        self.assertEqual(page.evaluate("document.querySelectorAll('#codeIn .vx-state.wait').length"), 1)


if __name__ == "__main__":
    unittest.main()
