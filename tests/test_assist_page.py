"""The page side of Deep Research, talking with Emvryx and scheduled tasks (web/js/assist.js), in a real browser."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest
from unittest import mock

import app_engine as E
import browser_check
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import wait_for
from tests.test_editor_ui import ready

SHOT = os.environ.get("EMVRYX_SHOT_DIR")

# A stand-in for the browser's speech typing and voice (a test browser has neither a microphone nor speakers): it "hears" one sentence,
# then nothing, and speaking ends at once.
FAKE_SPEECH = """
window.__heard = ['what is the tallest mountain'];
window.__spoken = [];
class FakeRec {
  start() { const said = window.__heard.shift(); setTimeout(() => { if (said && this.onresult) this.onresult({results: [[{transcript: said}]]}); if (this.onend) this.onend(); }, 150); }
  stop() {} abort() {}
}
window.SpeechRecognition = FakeRec; window.webkitSpeechRecognition = FakeRec;
window.speechSynthesis.speak = (u) => { window.__spoken.push(u.text); setTimeout(() => u.onend && u.onend(), 50); };
"""


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    def factory(model, question):                                   # noqa: N805
        return E.FakeBackend("Mount Everest is the tallest mountain [1].")

    factory = staticmethod(factory)

    def open(self, flags, width=1300):
        for i in flags:
            self.state.flags.data["audiences"][i] = "admins"
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        b = p.chromium.launch(executable_path=find_browser())
        self.addCleanup(p.stop)
        self.addCleanup(b.close)
        ctx = b.new_context(viewport={"width": width, "height": 860}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()})
        ctx.add_init_script(FAKE_SPEECH)
        page = ctx.new_page()
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{self.port}/")
        ready(page)
        return page

    def test_off_no_buttons(self):
        page = self.open(())
        page.wait_for_timeout(1200)
        for b in ("#asResearch", "#asTalk", "#asSched"):
            self.assertEqual(page.locator(b).count(), 0, b)
        self.assertEqual(self.errors, [])

    def test_research_button_sends_a_research_request_and_shows_the_steps(self):
        searched = []

        def found(q, k=3, source="auto", read=False, **kw):
            searched.append(q)
            return [{"title": "Page " + q, "text": "About " + q, "url": "https://example.org/" + str(len(searched))}]
        page = self.open(("chat_research",))
        page.wait_for_selector("#asResearch")
        page.click("#asResearch")
        self.assertEqual(page.get_attribute("#asResearch", "aria-pressed"), "true")
        page.fill("#input", "the tallest mountains on earth")
        with mock.patch("web_search.web_notes", side_effect=found):
            page.keyboard.press("Enter")
            page.wait_for_selector("#thread .msg.ai .bubble")
            wait_for(lambda: page.evaluate("!S.busy"))
        self.assertGreaterEqual(len(searched), 3)
        self.assertEqual(page.get_attribute("#asResearch", "aria-pressed"), "false")      # one message only: the button turns itself off
        self.assertEqual(page.locator("#asSteps").count(), 0)                              # the steps make way for the report
        self.assertEqual(self.errors, [])

    def test_talk_hears_answers_out_loud_and_listens_again(self):
        page = self.open(("chat_live_voice",))
        page.wait_for_selector("#asTalk")
        page.click("#asTalk")
        page.wait_for_selector(".as-talk")
        wait_for(lambda: page.evaluate("window.__spoken.length") >= 1)
        self.assertIn("Mount Everest", page.evaluate("window.__spoken[0]"))
        self.assertNotIn("[1]", page.evaluate("window.__spoken[0]"))                       # source numbers are not read out
        wait_for(lambda: "Listening" in page.inner_text(".as-talk-state"))
        if SHOT:
            page.screenshot(path=os.path.join(SHOT, "talk.png"))
        page.click(".as-talk >> text=End")
        self.assertEqual(page.locator(".as-talk").count(), 0)
        self.assertEqual(self.errors, [])

    def test_scheduled_tasks_dialog(self):
        page = self.open(("chat_schedule",))
        page.wait_for_selector("#asSched", state="attached")
        page.evaluate("openSchedules()")
        page.wait_for_selector(".as-list")
        page.fill("textarea[aria-label='What to do']", "Give me a short summary of today's news")
        page.fill("input[aria-label='Name']", "Morning news")
        page.select_option("select[aria-label='How often']", "weekdays")
        page.click(".dialog >> text=Add")
        page.wait_for_selector(".as-task")
        self.assertIn("Every weekday at 07:30", page.inner_text(".as-task"))
        if SHOT:
            page.screenshot(path=os.path.join(SHOT, "schedules.png"))
        page.click(".as-task >> text=Pause")
        wait_for(lambda: "off" in page.inner_text(".as-task"))
        self.assertEqual([t["on"] for ts in self.state.schedules.tasks.values() for t in ts], [False])
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
