"""The website's motion layer in a real browser: dashes that follow the pointer, things that rise into view as you scroll, and a menu that stays put."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import functools, http.server, threading, unittest
from tests.test_editor_ui import eventually

import browser_check
import build_site
from tests.test_browser_check import find_browser


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class SiteFx(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp = tempfile.TemporaryDirectory()
        build_site.build(cls.tmp.name)
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=cls.tmp.name))
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def test_home_page_moves_and_nothing_stays_hidden(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 1400, "height": 850}).new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{self.port}/index.html")
                page.wait_for_selector("canvas.fx-dots", state="attached")
                grab = lambda: page.eval_on_selector("canvas.fx-dots", "c => c.toDataURL()")
                page.mouse.move(200, 300)
                page.wait_for_timeout(600)
                one = grab()
                page.mouse.move(1000, 500, steps=6)
                eventually(lambda: self.assertNotEqual(one, grab()))  # the dashes follow the pointer
                self.assertGreater(page.evaluate("document.querySelectorAll('.fx-r').length"), 10)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                eventually(lambda: self.assertLess(abs(page.eval_on_selector(".nav", "e => e.getBoundingClientRect().top")), 1))  # the menu stays at the top
                for y in range(0, page.evaluate("document.documentElement.scrollHeight"), 500):
                    page.evaluate(f"window.scrollTo(0, {y})")
                    page.wait_for_timeout(60)
                eventually(lambda: self.assertEqual(page.evaluate("document.querySelectorAll('.fx-r:not(.fx-in)').length"), 0))  # everything rose into view
                self.assertEqual(errors, [])
            finally:
                b.close()

    def test_long_pages_do_not_go_dark_when_scrolled(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 1400, "height": 800}).new_page()
                for name in ("next.html", "scorecard.html", "whatsnew.html"):
                    page.goto(f"http://127.0.0.1:{self.port}/{name}")
                    page.wait_for_selector("canvas.fx-dots", state="attached")
                    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
                    page.wait_for_timeout(200)
                    faded = page.evaluate("[...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().height > innerHeight && parseFloat(getComputedStyle(e).opacity) < 1).length")
                    self.assertEqual(faded, 0, name)          # the text stays bright: only a headline banner may fade away
            finally:
                b.close()

    def test_still_when_asked_to_reduce_motion(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 1000, "height": 700}, reduced_motion="reduce").new_page()
                page.goto(f"http://127.0.0.1:{self.port}/index.html")
                eventually(lambda: self.assertEqual(page.evaluate("document.querySelectorAll('.fx-r').length"), 0))
                self.assertFalse(page.evaluate("document.documentElement.classList.contains('fx-on')"))
            finally:
                b.close()


if __name__ == "__main__":
    unittest.main()
