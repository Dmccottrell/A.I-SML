"""Voice typing and live voice use the browser's speech recognition, which needs the microphone. The page's Permissions-Policy header once said microphone=(),
which made Chrome refuse it ("not-allowed") before the person could even be asked. The page must allow its own microphone use and keep everything else shut."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import browser_check
from tests.test_app_server import Base, Client
from tests.test_browser_check import find_browser

START = """() => new Promise((done) => { const R = window.SpeechRecognition || window.webkitSpeechRecognition; if (!R) return done('no api'); const r = new R();
  r.onerror = (e) => done('error:' + e.error); r.onstart = () => done('started'); try { r.start(); } catch (e) { done('throw:' + e.name); } setTimeout(() => done('timeout'), 5000); })"""


class Header(Base):
    def test_the_microphone_is_allowed_for_the_page_itself_and_the_rest_stays_shut(self):
        policy = Client(self.port).call("GET", "/", raw=True)[1]["Permissions-Policy"]
        self.assertIn("microphone=(self)", policy)
        for shut in ("camera=()", "geolocation=()", "payment=()", "usb=()"):
            self.assertIn(shut, policy)


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    def test_speech_recognition_can_start_on_the_page(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser(), args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])      # a pretend microphone, allowed without a prompt
            try:
                page = b.new_context(permissions=["microphone"]).new_page()
                page.goto(f"http://127.0.0.1:{self.port}/")
                self.assertEqual(page.evaluate(START), "started")
            finally:
                b.close()


if __name__ == "__main__":
    unittest.main()
