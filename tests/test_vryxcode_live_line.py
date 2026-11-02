"""VryxCode's working line ("E..." with what it is doing and the seconds) must stay still and say what it is running, like Claude's. Two bugs made it look like it was
having a fit: the line was taken out and put back every 0.35 s (each poll), which restarted its animations, and the same field held both "is it working?" and the line's
details, so its words flipped between two sets every poll. Now it is moved only when a step is added, and it names the file or command."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import threading
import unittest

import browser_check
import vryxcode
from vryxcode import harness_call
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import open_to_everyone, wait_for


class Slow:
    """A scripted model that waits for a signal before each reply, so the session stays "working" while the page is watched."""
    def __init__(self, replies, gate):
        self.replies, self.gate, self.seen = list(replies), gate, []

    def __call__(self, messages):
        self.gate.wait(60)
        self.gate.clear()
        return self.replies.pop(0) if self.replies else harness_call("finish", summary="done")


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    def working_page(self):
        from playwright.sync_api import sync_playwright
        open_to_everyone(self.state)
        for flag in ("vryxcode_lines", "vryxcode_review", "vryxcode_projects"):
            self.state.flags.data["audiences"][flag] = "admins"
        self.gate = threading.Event()
        self.addCleanup(self.gate.set)
        self.state.code_generate = lambda model: Slow([harness_call("list_files", path=".")] * 3, self.gate)
        s, j = self.owner.call("POST", "/api/code/start", {"project": "tips", "task": "fix this code", "model": "solstice-2"})
        self.assertEqual(s, 200, j)
        self.gate.set()                                            # the first step goes through, then it waits: the line stays on the screen
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
        page.wait_for_selector("#codeLive")
        return page

    def test_the_line_is_not_taken_out_and_put_back_while_it_waits(self):
        page = self.working_page()
        page.evaluate("window.__m = 0; new MutationObserver((l) => { window.__m += l.length; }).observe(document.getElementById('codeIn'), {childList: true})")
        page.wait_for_timeout(2500)                                 # about seven polls
        self.assertEqual(page.evaluate("window.__m"), 0)
        self.assertEqual(self.errors, [])

    def test_the_word_does_not_flip_between_polls(self):
        page = self.working_page()
        seen = set()
        for _ in range(10):
            seen.add(page.evaluate("document.querySelector('#codeLive .what').textContent"))
            page.wait_for_timeout(300)
        self.assertLessEqual(len(seen), 2, seen)                    # one word, maybe changing once as time passes: never every poll
        self.assertEqual(page.evaluate("typeof C.live"), "boolean")   # C.live only says "working"; the line's details are kept apart
        self.assertEqual(self.errors, [])

    def test_it_says_what_it_is_running_and_keeps_the_e_mark(self):
        page = self.working_page()
        page.evaluate("renderLive({secs: 4, tool: 'run', target: 'python test_valid_code.py', tokens: 0, phase: 'tool'}, 'working'); paintLive()")
        page.wait_for_timeout(450)                                  # the words fade out and in (a quarter of a second)
        text = page.evaluate("document.querySelector('#codeLive .what').textContent")
        self.assertIn("python test_valid_code.py", text)
        self.assertTrue(text.endswith("…"))
        self.assertEqual(page.evaluate("!!document.querySelector('#codeLive svg.logo-dots')"), True)     # the E mark with its three dots
        self.assertIn("4s", page.evaluate("document.querySelector('#codeLive .meta').textContent"))
        page.evaluate("renderLive({secs: 5, tool: '', target: '', tokens: 0, phase: 'thinking'}, 'working'); paintLive()")
        page.wait_for_timeout(450)
        self.assertNotIn("python", page.evaluate("document.querySelector('#codeLive .what').textContent"))    # thinking: only the word
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
