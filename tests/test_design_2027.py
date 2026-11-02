"""The 2027 look (flag design_2027, owner only until it has been reviewed): off, the page is exactly as before; on, it gets the floating glass message bar,
a ring-style send button, the sidebar in two blocks, the usage as a pill at the top, words that fade in as they arrive, and the stylesheet is served."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import browser_check
import flags
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import wait_for


class Flag(unittest.TestCase):
    def test_it_starts_with_the_owner_only(self):
        self.assertEqual(flags.BY_ID["design_2027"]["default"], "owner")
        self.assertEqual(flags.BY_ID["design_2027"]["kind"], "feature")


class Server(Base):
    def test_the_stylesheet_is_served_and_kept_for_offline(self):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/design2027.css")
        r = c.getresponse()
        body = r.read().decode()
        c.close()
        self.assertEqual(r.status, 200)
        self.assertIn("body.d27", body)
        import routes_get
        self.assertIn("/design2027.css", routes_get.shell_files())

    def test_nothing_changes_for_the_page_with_the_switch_off(self):
        s, j = self.owner.call("GET", "/api/state")
        self.assertEqual(s, 200)
        self.assertFalse(j["features"].get("design_2027"))


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    def open(self, audience):
        from playwright.sync_api import sync_playwright
        self.state.flags.data["audiences"]["design_2027"] = audience
        p = sync_playwright().start()
        self.addCleanup(p.stop)
        b = p.chromium.launch(executable_path=find_browser())
        self.addCleanup(b.close)
        page = b.new_context(viewport={"width": 420, "height": 860}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{self.port}/")
        wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state"))
        page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove())")
        return page

    def test_with_the_switch_off_the_page_is_as_before(self):
        page = self.open("off")
        self.assertFalse(page.evaluate("document.body.classList.contains('d27')"))
        self.assertFalse(page.evaluate("!!document.getElementById('cssD27')"))
        self.assertNotEqual(page.evaluate("getComputedStyle(document.querySelector('.main > .composer')).position"), "absolute")        # the bar is not floating
        self.assertEqual(page.evaluate("document.querySelectorAll('#links .d27-block').length"), 0)
        self.assertEqual(self.errors, [])

    def test_with_the_switch_on_the_page_wears_the_2027_look(self):
        page = self.open("owner")
        wait_for(lambda: page.evaluate("document.body.classList.contains('d27') && !!document.getElementById('cssD27')"))
        wait_for(lambda: page.evaluate("getComputedStyle(document.querySelector('.main > .composer')).position") == "absolute")      # the bar floats
        self.assertEqual(page.evaluate("getComputedStyle(document.getElementById('send')).backgroundColor"), "rgba(0, 0, 0, 0)")   # a ring, not a solid fill
        if page.evaluate("document.documentElement.dataset.mode") == "dark":
            wait_for(lambda: page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(0, 0, 0)")                  # pure OLED black (the page fades to it)
        wait_for(lambda: page.evaluate("document.querySelectorAll('#links .d27-block').length") == 2)                              # two bento blocks
        self.assertEqual(page.evaluate("document.querySelector('#links .d27-block.code').innerText.includes('VryxCode')"), True)
        self.assertEqual(page.evaluate("document.querySelector('#links .d27-block.chat').innerText.includes('Private chat')"), True)
        self.assertEqual(page.evaluate("document.getElementById('usage').parentNode === document.getElementById('themeBtn').parentNode"), True)   # the usage pill at the top
        self.assertEqual(self.errors, [])

    def test_only_the_new_words_fade_in(self):
        page = self.open("owner")
        wait_for(lambda: page.evaluate("document.body.classList.contains('d27')"))
        out = page.evaluate("""() => {
          const b = document.createElement('div'); document.body.append(b);
          b.replaceChildren(document.createTextNode('Hello')); d27Fade(b);
          const first = [...b.querySelectorAll('.tok')].map((s) => s.textContent);
          b.replaceChildren(document.createTextNode('Hello world')); d27Fade(b);           // the whole text drawn again, two words long now
          const second = [...b.querySelectorAll('.tok')].map((s) => s.textContent);
          return {first, second, text: b.textContent};
        }""")
        self.assertEqual(out["first"], ["Hello"])
        self.assertEqual(out["second"], [" world"])
        self.assertEqual(out["text"], "Hello world")

    def test_the_send_ring_beats_fills_with_memory_and_the_reply_gets_a_speed_line(self):
        page = self.open("owner")
        wait_for(lambda: page.evaluate("document.body.classList.contains('d27')"))
        page.evaluate("d27Tick()")                                                                       # a batch of words arrived
        self.assertTrue(page.evaluate("document.getElementById('send').classList.contains('beat')"))     # the ring beat
        page.evaluate("const c = document.getElementById('ctxBtn'); c.hidden = false; c.style.setProperty('--p', '40')")
        wait_for(lambda: page.evaluate("document.getElementById('send').style.getPropertyValue('--p')") == "40")   # the memory fill is on the send ring
        page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove()); document.getElementById('input').focus()")     # script clicks: a late welcome tour cannot block them
        page.keyboard.type("Hello")
        page.evaluate("document.getElementById('send').click()")
        wait_for(lambda: page.evaluate("document.querySelectorAll('.d27-tel').length") == 1)             # tokens a second, the model, the first word
        self.assertIn("tok/s", page.inner_text(".d27-tel"))
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
