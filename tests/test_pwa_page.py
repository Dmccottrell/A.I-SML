"""The installed app's page parts (web/js/pwa.js) in a real browser: shortcuts and sharing, the Install button, offline reading with an outbox
that sends by itself once Emvryx is back, and nothing of it when the switches are off."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import unittest

import app_engine as E
import browser_check
from tests.test_app_server import Base, Client
from tests.test_browser_check import find_browser
from tests.test_code_sessions import wait_for
from tests.test_editor_ui import ready

ALL = ("pwa_install", "pwa_offline", "pwa_push", "pwa_share")


class Manifest(Base):
    def test_shortcuts_sharing_and_files_are_declared(self):
        m = json.loads(Client(self.port).call("GET", "/manifest.webmanifest", raw=True)[2])
        self.assertEqual([s["url"] for s in m["shortcuts"]], ["/?pwa=new", "/?pwa=code", "/?pwa=voice"])
        self.assertEqual(m["share_target"]["params"], {"title": "share_title", "text": "share_text", "url": "share_url"})
        self.assertIn("application/pdf", m["file_handlers"][0]["accept"])


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    def factory(model, question):                                   # noqa: N805
        return E.FakeBackend("Paris.")

    factory = staticmethod(factory)

    def open(self, url="/", flags=ALL):
        for i in flags:
            self.state.flags.data["audiences"][i] = "admins"
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        self.addCleanup(self.pw.stop)
        b = self.pw.chromium.launch(executable_path=find_browser())
        self.addCleanup(b.close)
        self.ctx = b.new_context(viewport={"width": 412, "height": 860}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()})
        page = self.ctx.new_page()
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{self.port}{url}")
        ready(page)
        wait_for(lambda: page.evaluate("!!PWA.launched"))
        return page

    def test_shared_text_starts_a_chat_and_install_shows(self):
        page = self.open("/?share_title=Recipe&share_url=https%3A%2F%2Fexample.com%2Fsoup")
        self.assertEqual(page.evaluate("input.value"), "Recipe\nhttps://example.com/soup")
        self.assertNotIn("share_", page.url)                                        # the address is cleaned up
        page.evaluate("const e = new Event('beforeinstallprompt'); e.prompt = () => {}; e.userChoice = Promise.resolve({outcome: 'dismissed'}); dispatchEvent(e)")
        page.wait_for_selector("#pwaInstall", state="attached")                          # in the side menu (closed on a phone)
        self.assertEqual(self.errors, [])

    def test_offline_the_kept_chats_show_and_the_outbox_sends_when_back(self):
        page = self.open()
        cid = self.new_chat(self.owner)
        self.ask(self.owner, cid, "capital of France?")
        page.evaluate(f"load().then(() => openChat({cid}))")
        wait_for(lambda: page.evaluate("JSON.parse(localStorage.getItem('emvryx_offline:owner') || '{\"chats\": []}').chats.length") == 1)
        page.evaluate("pwaOffline(new Error('Failed to fetch'))")                       # what boot.js does when Emvryx cannot be reached
        page.wait_for_selector(".pwa-off")
        page.click(".pwa-off .opt")
        self.assertIn("Paris.", page.inner_text(".pwa-off"))
        page.fill(".pwa-outbox textarea", "and of Spain?")
        page.click(".pwa-outbox .btn")
        self.assertIn("1 message is waiting", page.inner_text(".pwa-off"))
        page.evaluate("document.querySelector('.pwa-off').remove(); pwaFlush()")       # Emvryx is back
        wait_for(lambda: any(m["content"] == "and of Spain?" for m in self.owner.call("GET", f"/api/chats/{cid}")[1]["messages"]))
        wait_for(lambda: page.evaluate("JSON.parse(localStorage.getItem('emvryx_outbox:owner') || '[]').length") == 0)
        self.assertEqual(self.errors, [])

    def test_off_none_of_it(self):
        page = self.open("/?share_text=hello", flags=())
        self.assertEqual(page.evaluate("input.value"), "")
        page.evaluate("const e = new Event('beforeinstallprompt'); e.prompt = () => {}; dispatchEvent(e)")
        page.wait_for_timeout(300)
        self.assertEqual(page.locator("#pwaInstall").count(), 0)
        self.assertFalse(page.evaluate("JSON.parse(localStorage.getItem('emvryx_pwa_flags')).pwa_offline"))
        page.evaluate("pwaOffline(new Error('Failed to fetch'))")
        self.assertEqual(page.locator(".pwa-off").count(), 0)                          # off: the page behaves as before
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
