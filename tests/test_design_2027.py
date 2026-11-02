"""The 2027 look (flag design_2027, owner only until it has been reviewed): off, the page is exactly as before; on, it gets the floating glass message bar,
a ring-style send button, the sidebar in two blocks, the usage as a pill at the top, words that fade in as they arrive, and the stylesheet is served."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import browser_check
import flags
import vryxcode
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import open_to_everyone, wait_for


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
        self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('#links .d27-block.dev')).position"), "static")           # in the list, not covering the sidebar (a block once took VryxCode's full-screen class)
        self.assertEqual(page.evaluate("document.querySelector('#links .d27-block.dev').innerText.includes('VryxCode')"), True)
        self.assertEqual(page.evaluate("document.querySelector('#links .d27-block.tools').innerText.includes('Private chat')"), True)
        self.assertEqual(page.evaluate("document.getElementById('usage').nextElementSibling === document.getElementById('account')"), True)   # the usage pill sits in the sidebar, above your name
        self.assertEqual(page.evaluate("document.querySelector('.top #usage')"), None)                                                       # ...and is gone from the top bar
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

    def test_the_four_review_fixes(self):
        """The first review: a tactile user bubble, a glass bar that really blurs (also on a touch phone), a centred title with a floating glass banner, quiet buttons under replies."""
        from playwright.sync_api import sync_playwright
        self.state.flags.data["audiences"]["design_2027"] = "owner"
        p = sync_playwright().start()
        self.addCleanup(p.stop)
        b = p.chromium.launch(executable_path=find_browser())
        self.addCleanup(b.close)
        # a touch phone: the older look switches the blur off there, so this is the case that matters
        page = b.new_context(viewport={"width": 420, "height": 860}, has_touch=True, is_mobile=True,
                             extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{self.port}/")
        wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state"))
        page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove())")
        wait_for(lambda: page.evaluate("document.body.classList.contains('d27')"))
        page.evaluate("""() => { S.messages = [{id: 1, role: 'user', content: 'Hello, tell me something'}, {id: 2, role: 'assistant', content: 'Sure.', status: 'done'}]; renderThread(); }""")
        style = lambda q, prop: page.evaluate("([q, p]) => getComputedStyle(document.querySelector(q))[p]", [q, prop])
        # 2: the bar is a translucent carbon with the 40 px blur
        wait_for(lambda: "blur(40px)" in style(".composer .card", "backdropFilter"))
        self.assertEqual(style(".composer .card", "backgroundColor"), "rgba(10, 10, 14, 0.4)")
        # 1: the user's bubble is solid matte carbon #16161D with a shadow
        self.assertEqual(style(".msg.user .bubble", "backgroundColor"), "rgb(22, 22, 29)")
        self.assertNotEqual(style(".msg.user .bubble", "boxShadow"), "none")
        # 4: the buttons under a reply have no pill and are muted grey
        self.assertEqual(style(".msg.ai .acts .chip", "backgroundColor"), "rgba(0, 0, 0, 0)")
        self.assertEqual(style(".msg.ai .acts .chip", "color"), "rgb(113, 113, 122)")
        # 3: the title is centred and bold; the usage pill is not in the top bar
        box = page.evaluate("(() => { const r = document.querySelector('.top .title').getBoundingClientRect(); return (r.left + r.right) / 2; })()")
        self.assertLess(abs(box - 210), 3)
        self.assertEqual(style(".top .title", "fontWeight"), "700")
        # ...and the security banner floats as a glass card
        page.evaluate("localStorage.removeItem('emvryx_nudge'); S.state.admin = true; maybeNudge()")
        wait_for(lambda: page.evaluate("!!document.getElementById('nudge')"))
        self.assertEqual(style("#nudge", "position"), "absolute")
        self.assertIn("blur(30px)", style("#nudge", "backdropFilter"))
        self.assertEqual(errors, [])

    def build_a_session(self):
        """A coding session that wrote one file and now waits at "Allow this?" (the permission card), so the building screen has real content."""
        open_to_everyone(self.state)
        self.state.flags.data["audiences"]["vryxcode_projects"] = "admins"        # the project list with its dense rows
        page_html = "<!doctype html><html><body><h1>Bill splitter</h1></body></html>\n"
        self.state.code_generate = lambda model: vryxcode.ScriptedChat([vryxcode.harness_call("write_file", path="index.html", content=page_html), vryxcode.harness_call("finish", summary="Built it.")])
        s, j = self.owner.call("POST", "/api/code/start", {"project": "tips", "task": "A bill splitter with tip", "model": "solstice-2"})
        self.assertEqual(s, 200, j)
        wait_for(lambda: self.state.code.sessions[j["id"]].state in ("asking", "done"))

    def test_vryxcode_with_the_switch_off_is_as_before(self):
        self.build_a_session()
        page = self.open("off")
        page.evaluate("openCode()")
        page.wait_for_selector(".vx-prow, .scard")
        page.evaluate("document.querySelector('.vx-prow, .scard').click()")
        page.wait_for_selector("#codeIn .cc-user")
        self.assertNotEqual(page.evaluate("getComputedStyle(document.querySelector('#code > .composer, #code .composer')).position"), "absolute")
        self.assertNotEqual(page.evaluate("getComputedStyle(document.querySelector('#codeIn .cc-user')).backgroundColor"), "rgb(22, 22, 29)")
        self.assertEqual(self.errors, [])

    def test_vryxcode_wears_the_2027_look_home_and_building_screen(self):
        self.build_a_session()
        page = self.open("owner")
        wait_for(lambda: page.evaluate("document.body.classList.contains('d27')"))
        style = lambda q, prop: page.evaluate("([q, p]) => getComputedStyle(document.querySelector(q))[p]", [q, prop])
        page.evaluate("openCode()")
        page.wait_for_selector(".vx-prow, .scard")
        # home: pure black, the main button is a hollow ghost, the template cards are carbon, session rows are flat with a hairline
        self.assertEqual(style("#code", "backgroundColor"), "rgb(0, 0, 0)")
        self.assertEqual(style("#codeGo", "backgroundColor"), "rgba(0, 0, 0, 0)")
        self.assertEqual(style(".vx-prow", "borderBottomWidth"), "1px")
        self.assertEqual(style(".vx-prow", "borderRadius"), "0px")
        # the building screen: open the session
        page.evaluate("document.querySelector('.vx-prow, .scard').click()")
        page.wait_for_selector("#codeIn .cc-user")
        wait_for(lambda: page.evaluate("!!document.querySelector('#codeIn .cc-ask button')"))
        # your task is solid carbon with a shadow
        self.assertEqual(style("#codeIn .cc-user", "backgroundColor"), "rgb(22, 22, 29)")
        self.assertNotEqual(style("#codeIn .cc-user", "boxShadow"), "none")
        # the message bar floats and is translucent glass with the 40 px blur
        bar = lambda prop: page.evaluate("(p) => getComputedStyle(document.getElementById('codeTask').closest('.composer'))[p]", prop)      # the session's own bar (the home screen has another)
        card = lambda prop: page.evaluate("(p) => getComputedStyle(document.getElementById('codeTask').closest('.card'))[p]", prop)
        self.assertEqual(bar("position"), "absolute")
        self.assertEqual(card("backgroundColor"), "rgba(10, 10, 14, 0.4)")
        self.assertIn("blur(40px)", card("backdropFilter"))
        # "Allow this?" is a carbon card with hollow ghost answers
        self.assertEqual(style("#codeIn .cc-ask", "backgroundColor"), "rgb(12, 12, 16)")
        self.assertEqual(style("#codeIn .cc-ask button", "backgroundColor"), "rgba(0, 0, 0, 0)")
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
