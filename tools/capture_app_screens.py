"""
capture_app_screens.py - takes pictures of the REAL Emvryx screens for the feature advert (site/commercial-features.html).

WHAT THIS FILE DOES
    It starts the Emvryx server the way the tests do (a stand-in model, nothing real is asked, no one's data is shown), opens the real web app in a phone-sized browser with the
    2027 look on, puts a few example messages on the screen, and saves a picture of each screen to site/ad-screens/. The advert then plays these pictures inside a phone frame, so
    what people see is the app itself and not a drawing of it.

Usage:
    python tools/capture_app_screens.py            (writes site/ad-screens/*.png)
    python tools/capture_app_screens.py --out some/folder
Needs: playwright with a browser (EMVRYX_BROWSER can name it).
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "tests")); import emvryx_paths  # noqa: E402,F401
import argparse
import unittest

import vryxcode
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import open_to_everyone, wait_for

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "site", "ad-screens")

ANSWER = ("**Why the sky is blue**\n\nSunlight is every colour mixed together. Air bends **blue light** about ten times more than red, so blue reaches your eyes from every direction.\n\n"
          "| Colour | How much it scatters |\n|---|---|\n| Red | a little |\n| Green | some |\n| Blue | a lot |\n\nAt sunset the light travels through more air, the blue is scattered away, and the **red and orange** are what is left.")
RESEARCH = ("## Electric cars in 2026: what the sources agree on\n\n**In short:** sales keep rising, prices are falling, and charging is the thing buyers worry about most [1][2].\n\n"
            "### Prices\nThe average new electric car now costs less than it did two years ago [1], and used ones are cheaper still [3].\n\n"
            "### Charging\nMost owners charge at home; public chargers are growing but uneven by region [2][4].\n\n### What is still unsure\nBattery life after ten years has little long-term data [3].\n\n"
            "**Sources** [1] Energy agency report  [2] Transport survey  [3] Consumer guide  [4] Grid operator")


class Capture(Base):
    def open(self):
        from playwright.sync_api import sync_playwright
        for flag in ("design_2027", "vryxcode_review", "vryxcode_lines", "vryxcode_projects", "vryxcode_preview", "vryxcode_autocontinue", "chat_cite", "chat_fixes"):
            self.state.flags.data["audiences"][flag] = "owner"
        open_to_everyone(self.state)
        p = sync_playwright().start()
        self.addCleanup(p.stop)
        b = p.chromium.launch(executable_path=find_browser())
        self.addCleanup(b.close)
        self.ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()})
        page = self.ctx.new_page()
        page.goto(f"http://127.0.0.1:{self.port}/")
        wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state"), 60)
        page.evaluate("localStorage.setItem('emvryx_nudge', String(Date.now()))")
        wait_for(lambda: page.evaluate("document.body.classList.contains('d27')"))
        self.clean(page)
        page.wait_for_timeout(1500)
        return page

    def clean(self, page):
        """Take away anything that is not the app itself: the welcome tour and the security reminder."""
        page.evaluate("document.querySelectorAll('.tour, .nudge, #nudge, .toast').forEach((e) => e.remove())")

    def shot(self, page, name):
        os.makedirs(OUT, exist_ok=True)
        page.wait_for_timeout(1300)
        self.clean(page)
        page.screenshot(path=os.path.join(OUT, name + ".png"))
        print("saved", name, flush=True)

    def test_capture(self):
        page = self.open()
        self.shot(page, "chat-home")
        page.evaluate("document.getElementById('modelBtn').click()")
        self.shot(page, "model-picker")
        page.keyboard.press("Escape")
        page.evaluate("document.querySelectorAll('.menu, .pop, .sheet').forEach((e) => e.remove())")
        page.evaluate("S.messages = [{id: 1, role: 'user', content: 'Why is the sky blue?'}, {id: 2, role: 'assistant', content: %r, status: 'done'}]; renderThread()" % ANSWER)
        self.shot(page, "chat-answer")
        page.evaluate("S.messages = [{id: 1, role: 'user', content: 'Research electric cars in 2026'}, {id: 2, role: 'assistant', content: %r, status: 'done'}]; renderThread()" % RESEARCH)
        page.evaluate("document.querySelectorAll('.scroll, #thread').forEach((e) => { e.scrollTop = 0; })")
        self.shot(page, "research")
        page.evaluate("S.messages = []; S.private = true; renderThread()")
        self.shot(page, "private")
        page.evaluate("S.private = false; S.messages = [{id: 1, role: 'user', content: 'Why is the sky blue?'}, {id: 2, role: 'assistant', content: %r, status: 'done'}]; S.theme = 'light'; applyTheme(); renderThread()" % ANSWER)
        page.wait_for_timeout(1500)
        self.shot(page, "light")
        page.evaluate("S.theme = 'dark'; applyTheme()")
        # VryxCode: a session that built a page
        css = "\n".join(f"    .r{n} {{ margin: {n}px; padding: 8px; border-radius: 12px; }}" for n in range(1, 41))
        page_html = ("<!doctype html>\n<html>\n<head>\n  <meta charset='utf-8'>\n  <meta name='viewport' content='width=device-width, initial-scale=1'>\n  <title>Bill splitter</title>\n  <style>\n"
                     "    body { font-family: system-ui; margin: 0; background: #0f1119; color: #eef0f6; padding: 28px }\n    h1 { margin: 0 0 6px }\n"
                     "    .card { background: #161926; border-radius: 18px; padding: 20px; margin-top: 18px }\n    input { width: 100%; padding: 14px; border-radius: 12px; border: 0; background: #232739; color: #fff; font-size: 18px }\n"
                     "    .big { font-size: 46px; font-weight: 700; color: #a78bfa; margin-top: 10px }\n" + css + "\n  </style>\n</head>\n<body>\n  <h1>Bill splitter</h1>\n  <p>Split the bill and the tip.</p>\n"
                     "  <div class='card'>\n    <label>Total</label>\n    <input value='84.00'>\n    <div style='height:12px'></div>\n    <label>People</label>\n    <input value='4'>\n    <div class='big'>$24.15</div>\n    <p>each, with 15% tip</p>\n  </div>\n</body>\n</html>\n")
        done = "I built the bill splitter and checked it in a browser: it opens with no errors. Open Preview to try it."
        self.state.code_generate = lambda model: vryxcode.ScriptedChat([vryxcode.harness_call("write_file", path="index.html", content=page_html), vryxcode.harness_call("finish", summary=done),
                                                                        vryxcode.harness_call("finish", summary=done), vryxcode.harness_call("finish", summary=done)])
        s, j = self.owner.call("POST", "/api/code/start", {"project": "bill-splitter", "task": "Build me a bill splitter web page with a tip", "model": "solstice-2", "auto_edits": True})
        self.assertEqual(s, 200, j)
        wait_for(lambda: self.state.code.sessions[j["id"]].state in ("asking", "done"), 90)
        page.reload()
        wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state"), 60)
        self.clean(page)
        page.evaluate("openCode()")
        page.wait_for_selector(".vx-prow, .scard", timeout=30000)
        self.shot(page, "vryx-home")
        page.evaluate("document.querySelector('.vx-prow, .scard').click()")
        page.wait_for_selector("#codeIn .cc-user", timeout=30000)
        page.wait_for_timeout(2500)
        page.evaluate("document.querySelectorAll('#codeIn, .feed').forEach((e) => { e.scrollTop = 0; })")
        self.shot(page, "vryx-session")
        page.evaluate("openPreview()")
        page.wait_for_timeout(2500)
        self.shot(page, "vryx-preview")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    a, rest = ap.parse_known_args()
    if a.out:
        OUT = a.out
    unittest.main(argv=[sys.argv[0]] + rest)
