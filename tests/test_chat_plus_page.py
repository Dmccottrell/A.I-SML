"""The page side of the chat parts behind the chat_* flags (web/js/chatplus.js), in a real browser."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import app_engine as E
import browser_check
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import wait_for
from tests.test_editor_ui import ready

ALL = ("chat_panel", "chat_versions", "chat_lines", "chat_followups", "chat_projects", "chat_commands", "chat_steer", "search_all", "chat_taskbox", "chat_voice")
PAGE = "Here is your page:\n\n```html\n<!doctype html><html><body><h1 id=t>Tip calculator</h1><script>document.getElementById('t').textContent += ' ready'</script></body></html>\n```"
SHOT = os.environ.get("EMVRYX_SHOT_DIR")


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    def factory(model, question):                                   # noqa: N805
        return E.FakeBackend(PAGE)

    factory = staticmethod(factory)

    def open(self, flags=ALL, width=1300):
        for i in flags:
            self.state.flags.data["audiences"][i] = "admins"
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        b = p.chromium.launch(executable_path=find_browser())
        self.addCleanup(p.stop)
        self.addCleanup(b.close)
        page = b.new_context(viewport={"width": width, "height": 860}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{self.port}/")
        ready(page)
        return page

    def chat(self, page):
        cid = self.new_chat(self.owner)
        self.ask(self.owner, cid, "make me a tip calculator page")
        page.evaluate(f"openChat({cid})")
        page.wait_for_selector("#thread .msg.ai")
        return cid

    def test_the_panel_follow_ups_read_aloud_and_versions(self):
        page = self.open()
        cid = self.chat(page)
        page.click("text=Open in panel")
        frame = page.wait_for_selector(".cp-panel iframe.cp-frame")
        self.assertIn("allow-scripts", frame.get_attribute("sandbox"))
        self.assertNotIn("allow-same-origin", frame.get_attribute("sandbox"))
        wait_for(lambda: "Tip calculator ready" in (frame.content_frame().inner_text("body") if frame.content_frame() else ""))   # its own script ran
        page.click(".cp-panel .seg >> text=Code")
        self.assertIn("<h1 id=t>", page.inner_text(".cp-code"))
        wait_for(lambda: page.locator("#cpFollow .chip").count() >= 2)
        self.assertIn("Read aloud", page.inner_text("#thread .msg.ai .acts"))
        if SHOT:
            page.evaluate("$('cpFollow').scrollIntoView()")
            page.screenshot(path=os.path.join(SHOT, "chat_panel.png"))
        page.click(".cp-panel [aria-label='Close the panel']")
        q = self.owner.call("GET", f"/api/chats/{cid}")[1]["messages"][0]["id"]
        self.owner.call("POST", f"/api/chats/{cid}/messages/{q}/edit", {"text": "make it blue"})
        self.ask(self.owner, cid, regenerate=True, text="")
        page.evaluate(f"openChat({cid})")
        page.wait_for_selector(".cp-ver")
        self.assertEqual(page.inner_text(".cp-ver span"), "2/2")
        page.click(".cp-ver [aria-label='Earlier version']")
        wait_for(lambda: page.inner_text(".cp-ver span") == "1/2")
        self.assertIn("tip calculator", page.inner_text("#thread .msg.user .bubble"))
        self.assertEqual(self.errors, [])

    def test_commands_search_tasks_projects_quiet_lines_and_steer(self):
        page = self.open()
        page.click("#input")
        page.keyboard.type("/sum")
        page.wait_for_selector(".cp-cmd")
        page.keyboard.press("Enter")                                                      # picks the command: it must not also send the message
        page.wait_for_timeout(400)
        self.assertEqual((page.evaluate("input.value"), page.evaluate("S.chatId"), page.evaluate("S.busy")), ("Summarize this chat so far in a few short points.", None, False))
        page.evaluate("input.value = ''")
        self.assertIn("PROJECTS", page.inner_text("#chatList"))
        page.keyboard.press("Control+K")
        page.wait_for_selector(".modal input[type=search]")
        page.fill(".modal input[type=search]", "theme")
        wait_for(lambda: "Setting" in page.inner_text(".cp-results"))
        page.click(".modal .btn.ghost")
        page.evaluate("S.messages = [{id: 1, role: 'user', content: 'capital of Italy?'}, {id: 2, role: 'assistant', content: 'Rome.', status: 'done', model_id: 'flare-2', thought_s: 4,"
                      " looked: {wiki: 1, web: 2, sources: [{title: 'Rome', url: 'https://en.wikipedia.org/wiki/Rome'}]}}]; S.chatId = 1; renderThread();")
        self.assertEqual(page.inner_text(".cp-q"), "Thought 4s, Read 1 from Wikipedia, Searched the web: 2 sources ›")
        self.assertEqual(page.inner_text(".cp-chips"), "en.wikipedia.org")
        page.evaluate("const t = el('div', {}); $('thread').append(t); plusEvent('thinking', {effort: 'deep'}, t); plusEvent('notes', {wiki: 2}, t);")
        self.assertEqual(page.evaluate("[...document.querySelectorAll('.cp-tasks .vt')].map((x) => x.className + ':' + x.textContent)"),
                         ["vt is-done:✓Read your question", "vt is-now:Think it through", "vt is-todo:Write the answer", "vt is-done:✓Look it up: 2 sources"])
        page.evaluate("plusEvent('piece', {}, null); plusEvent('done', {}, null); plusEvent('end', null, null)")
        page.evaluate("S.busy = true; input.value = 'shorter please'")
        self.assertTrue(page.evaluate("steering()"))                                     # typing while it answers steers instead of stopping
        page.evaluate("S.busy = false; input.value = ''")
        self.assertEqual(self.errors, [])

    def test_off_none_of_it_is_there(self):
        page = self.open(flags=())
        self.chat(page)
        self.assertEqual(page.locator("text=Open in panel").count() + page.locator("#cpFollow, #cpMic, #cpSearchAll, .cp-plabel").count(), 0)
        page.click("#input")
        page.keyboard.type("/sum")
        self.assertEqual(page.locator(".cp-cmd").count(), 0)
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
