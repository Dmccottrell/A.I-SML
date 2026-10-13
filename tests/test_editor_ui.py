"""The Editor layout in a real browser: files | editor | VryxCode side by side, open, edit, Save, and a file VryxCode changes while it is open."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import browser_check
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import open_to_everyone


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class EditorUi(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        self.save("app.py", "def hello(name):\n    return name\n")
        self.save("web/index.html", "<h1>Hi</h1>\n")

    def save(self, path, text):
        st, j = self.owner.call("POST", "/api/code/file", {"project": "demo", "path": path, "text": text})
        self.assertEqual(st, 200, j)

    def disk(self, path):
        with open(os.path.join(self.state.code.project_path("owner", "demo"), path), encoding="utf-8") as f:
            return f.read()

    def test_open_edit_save_and_a_change_from_outside(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 1500, "height": 850}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{self.port}/")
                page.wait_for_timeout(600)
                page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove()); openCode()")
                page.wait_for_timeout(600)
                page.evaluate("C.project = 'demo'; newSession()")
                page.wait_for_timeout(400)
                page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove())")        # the welcome tour can appear late
                page.click("#codeIdeBtn")
                page.wait_for_timeout(500)
                box = lambda sel: page.eval_on_selector(sel, "e => { const r = e.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.width)]; }")
                (tl, tw), (el_, ew), (cl, cw) = box("#ideTree"), box("#ideEd"), box(".code .col")
                self.assertTrue(tl < el_ < cl, (tl, el_, cl))                                   # files | editor | VryxCode, left to right
                self.assertGreater(ew, 450)
                page.click("#ideFiles >> text=app.py")
                page.wait_for_timeout(300)
                self.assertIn("tk-k", page.inner_html("#ideBody pre.hl"))                       # coloured
                page.click("#ideBody textarea")
                page.keyboard.press("Control+End")
                page.keyboard.type("x = 1")
                page.wait_for_timeout(100)
                self.assertIn("●", page.inner_text("#ideTabs"))                            # the tab shows unsaved changes
                page.keyboard.press("Control+s")
                page.wait_for_timeout(600)
                self.assertEqual(page.inner_text("#ideStatus"), "Saved")
                self.assertEqual(self.disk("app.py"), "def hello(name):\n    return name\nx = 1")
                self.assertNotIn("●", page.inner_text("#ideTabs"))
                # VryxCode (or anything else) changes the open file on disk: the tab updates by itself when there are no edits of yours
                self.save("app.py", "def hello(name):\n    return name.title()\n")
                page.evaluate("ideSync()")
                page.wait_for_timeout(500)
                self.assertIn("title()", page.input_value("#ideBody textarea"))
                # ...and asks when there are
                page.click("#ideBody textarea")
                page.keyboard.press("Control+End")
                page.keyboard.type("# mine")
                self.save("app.py", "def hello(name):\n    return 'changed again'\n")
                page.evaluate("ideSync()")
                page.wait_for_timeout(500)
                self.assertIn("VryxCode changed this file", page.inner_text("#ideConf"))
                page.click("#ideConf >> text=Keep mine")
                self.assertIn("# mine", page.input_value("#ideBody textarea"))
                # narrower than 1100px: the Editor layout switches itself off and the normal screen comes back
                page.set_viewport_size({"width": 900, "height": 800})
                page.wait_for_timeout(300)
                self.assertFalse(page.eval_on_selector("#code", "e => e.classList.contains('ide')"))
                self.assertEqual(errors, [])
            finally:
                b.close()

    def test_edit_selection_shows_a_diff_and_changes_nothing_until_accepted(self):
        import vryxcode
        from playwright.sync_api import sync_playwright
        FILE = "def f(xs):\n    total = 0\n    for x in xs:\n        total += x\n    return total\n"
        self.save("calc.py", FILE)
        s, e = FILE.index("    total = 0"), FILE.index("    return")
        reply = {"text": "```python\ntotal = 0\nfor x in xs:\n    if x is not None:\n        total += x\n```"}
        self.state.code_generate = lambda model: vryxcode.ScriptedChat([reply["text"]])
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 1500, "height": 850}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                errors = []
                page.on("pageerror", lambda x: errors.append(str(x)))
                page.goto(f"http://127.0.0.1:{self.port}/")
                page.wait_for_timeout(600)
                page.evaluate("document.querySelectorAll('.tour').forEach((x) => x.remove()); openCode()")
                page.wait_for_timeout(600)
                page.evaluate("C.project = 'demo'; newSession()")
                page.wait_for_timeout(400)
                page.evaluate("document.querySelectorAll('.tour').forEach((x) => x.remove())")
                page.click("#codeIdeBtn")
                page.wait_for_timeout(400)
                page.click("#ideFiles >> text=calc.py")
                page.wait_for_timeout(300)
                select = lambda a, z: page.evaluate("([a, z]) => { const t = document.querySelector('#ideBody textarea'); t.focus(); t.setSelectionRange(a, z); }", [a, z])
                text = lambda: page.input_value("#ideBody textarea")
                # Ctrl+K opens the panel for the selection; the proposal is shown as a diff and the editor is untouched
                select(s, e)
                page.keyboard.press("Control+k")
                page.wait_for_selector("#ideAiIn", state="visible")
                page.fill("#ideAiIn", "skip None values")
                page.click("#ideAiGo")
                page.wait_for_selector(".idiff", timeout=8000)
                self.assertIn("if x is not None", page.inner_text(".idiff .add"))
                self.assertIn("nothing has changed yet", page.inner_text("#ideAiStat"))
                self.assertEqual(text(), FILE)
                # Reject: nothing changes
                page.click("#ideAiRes >> text=Reject")
                self.assertEqual(text(), FILE)
                self.assertTrue(page.eval_on_selector("#ideAi", "e => e.hidden"))
                # again, Accept: the editor changes (as an ordinary edit, the tab shows unsaved changes) but the file on disk does not until Save
                select(s, e)
                page.click("#ideEditSel")
                page.fill("#ideAiIn", "skip None values")
                page.click("#ideAiGo")
                page.wait_for_selector(".idiff", timeout=8000)
                page.click("#aiAccept")
                self.assertIn("    total = 0\n    for x in xs:\n        if x is not None:\n            total += x\n    return total", text())
                self.assertIn("\u25cf", page.inner_text("#ideTabs"))
                self.assertEqual(self.disk("calc.py"), FILE)
                page.keyboard.press("Control+s")
                page.wait_for_timeout(600)
                self.assertIn("if x is not None", self.disk("calc.py"))
                # Explain: words, no edit
                reply["text"] = "It adds up the numbers in the list."
                select(s, s + 20)
                page.click("#ideExplain")
                page.wait_for_selector("#ideAiRes .text", timeout=8000)
                self.assertIn("adds up", page.inner_text("#ideAiRes .text"))
                page.click("#ideAiRes >> text=Close")
                # a stale proposal is not applied over text that changed meanwhile
                reply["text"] = "```python\nx = 1\n```"
                select(s, e)
                page.click("#ideEditSel")
                page.fill("#ideAiIn", "replace it")
                page.click("#ideAiGo")
                page.wait_for_selector(".idiff", timeout=8000)
                page.evaluate("() => { const t = document.querySelector('#ideBody textarea'); t.setRangeText('#', 0, 0, 'end'); t.dispatchEvent(new Event('input')); }")
                before = text()
                page.click("#aiAccept")
                self.assertIn("text changed while the model was working", page.inner_text("#ideAiStat"))
                self.assertEqual(text(), before)
                self.assertEqual(errors, [])
            finally:
                b.close()

    def test_saving_is_refused_while_vryxcode_works_in_the_project(self):
        import vryxcode
        from tests.test_code_sessions import wait_for
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(list(vryxcode.DEMO))
        st, a = self.owner.call("POST", "/api/code/start", {"project": "demo", "task": "write slugify", "model": "solstice-2"})
        wait_for(lambda: self.owner.call("GET", f"/api/code/sessions/{a['id']}")[1]["state"] == "asking")
        st, j = self.owner.call("POST", "/api/code/file", {"project": "demo", "path": "app.py", "text": "x"})
        self.assertEqual(st, 400)
        self.assertIn("working in this project", j["message"])


if __name__ == "__main__":
    unittest.main()
