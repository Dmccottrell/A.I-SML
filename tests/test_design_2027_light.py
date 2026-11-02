"""Design 2027 in light mode: the matte carbon cards were made for dark mode, so with the light theme their text was dark on near-black (suggestion cards,
the sidebar blocks, the message bar). In light mode every piece of visible text on the chat and on VryxCode must be readable against what is behind it."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

from tests.test_app_server import Base
from tests.test_browser_check import find_browser  # noqa: F401  (a real browser is needed: the test runner sorts this file with the browser tests)
from tests.test_code_sessions import wait_for
from tests.test_design_2027 import Page

# For every visible piece of text: its colour against the first colour behind it that is solid (translucent layers are mixed in), as a contrast ratio.
HARD_TO_READ = """(min) => {
  const parse = (c) => { const m = c.match(/[\\d.]+/g).map(Number); const k = c.startsWith('color(') ? 255 : 1; return [m[0] * k, m[1] * k, m[2] * k, m.length > 3 ? m[3] : 1]; };      // rgb() is 0-255, color(srgb) is 0-1
  const lum = (c) => c.slice(0, 3).reduce((s, v, i) => { v /= 255; return s + [.2126, .7152, .0722][i] * (v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4)); }, 0);
  const behind = (el) => { const layers = []; for (let e = el; e; e = e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor); if (c[3] > 0) layers.push(c); if (c[3] >= 1) break; }
    let base = [255, 255, 255, 1]; for (const c of layers.reverse()) base = base.map((v, i) => i < 3 ? c[i] * c[3] + v * (1 - c[3]) : 1); return base; };
  const bad = [];
  for (const e of document.querySelectorAll('body *')) {
    if (e.children.length || !(e.innerText || '').trim()) continue;
    const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
    if (!r.width || !r.height || st.visibility === 'hidden' || st.display === 'none' || st.opacity === '0') continue;
    if (e.closest('.tour, [hidden], .sr, script, style')) continue;
    if (st.backgroundImage !== 'none') continue;                                  // a gradient (the round avatar) is not one flat colour
    const fg = parse(st.color); if (fg[3] === 0 || st.webkitTextFillColor === 'rgba(0, 0, 0, 0)') continue;     // gradient text is painted by its background
    const bg = behind(e); const a = lum(fg) + .05, b = lum(bg) + .05; const ratio = Math.max(a, b) / Math.min(a, b);
    if (ratio < min) bad.push((e.className || e.tagName) + ' "' + e.innerText.trim().slice(0, 24) + '" ' + st.color + ' on rgb(' + bg.slice(0, 3).map(Math.round) + ') = ' + ratio.toFixed(1));
  }
  return bad; }"""


class Light(Base):
    open = Page.open

    def go_light(self, page):
        wait_for(lambda: page.evaluate("document.body.classList.contains('d27')"))
        page.evaluate("S.theme = 'light'; applyTheme()")
        wait_for(lambda: page.evaluate("document.documentElement.dataset.mode") == "light")
        page.wait_for_timeout(1800)                                                 # the page fades between its colours (0.6 s)

    def test_the_chat_is_readable_in_light_mode(self):
        page = self.open("owner")
        page.set_viewport_size({"width": 1280, "height": 800})
        self.go_light(page)
        page.evaluate("""() => { S.messages = [{id: 1, role: 'user', content: 'Hello, tell me something'}, {id: 2, role: 'assistant', content: 'Sure.', status: 'done'}]; renderThread(); }""")
        page.evaluate("localStorage.removeItem('emvryx_nudge'); S.state.admin = true; maybeNudge()")
        page.wait_for_timeout(600)
        self.assertEqual(page.evaluate(HARD_TO_READ, 4.5), [])
        self.assertNotEqual(page.evaluate("getComputedStyle(document.querySelector('.msg.user .bubble')).backgroundColor"), "rgb(22, 22, 29)")      # not the dark bubble
        self.assertEqual(self.errors, [])

    def test_the_new_chat_cards_and_sidebar_are_readable_in_light_mode(self):
        page = self.open("owner")
        page.set_viewport_size({"width": 1280, "height": 800})
        self.go_light(page)
        page.evaluate("S.messages = []; renderThread()")
        wait_for(lambda: page.evaluate("document.querySelectorAll('.ml-ideas button, #links .d27-block').length") >= 3)
        self.assertEqual(page.evaluate(HARD_TO_READ, 4.5), [])

    def test_vryxcode_is_readable_in_light_mode(self):
        from tests.test_design_2027 import Page as P
        P.build_a_session(self)
        page = self.open("owner")
        self.go_light(page)
        page.evaluate("openCode()")
        page.wait_for_selector(".vx-prow, .scard")
        page.wait_for_timeout(1800)
        self.assertEqual(page.evaluate(HARD_TO_READ, 4.5), [])
        page.evaluate("document.querySelector('.vx-prow, .scard').click()")
        page.wait_for_selector("#codeIn .cc-user")
        wait_for(lambda: page.evaluate("!!document.querySelector('#codeIn .cc-ask button')"))
        page.wait_for_timeout(2200)                                                 # the new text settles from violet to its normal colour
        self.assertEqual(page.evaluate(HARD_TO_READ, 4.5), [])
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
