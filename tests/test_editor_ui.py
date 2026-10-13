"""The Editor layout in a real browser: files | editor | VryxCode side by side, open, edit, Save, and a file VryxCode changes while it is open."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import browser_check
from tests.test_app_server import Base, Client
from tests.test_browser_check import find_browser
from tests.test_code_sessions import open_to_everyone, wait_for


def vryx_on(page):
    """The new VryxCode look is behind a flag: wait until the page has applied it."""
    wait_for(lambda: page.evaluate("document.body.classList.contains('vxn') && !!document.getElementById('cssVryx')"), 10)


def ready(page):
    """The page has loaded and signed in (polled from Python: the page's own security rules block waiting on a script string)."""
    wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state"), 15)
    page.evaluate("S.tourChecked = true; openTour = () => {}; document.querySelectorAll('.tour').forEach((e) => e.remove())")      # the welcome tour must never cover a click


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

    def test_plus_button_starts_a_new_project_from_the_sessions_list(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 1000, "height": 800}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                page.goto(f"http://127.0.0.1:{self.port}/")
                ready(page)
                page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove()); openCode()")
                page.wait_for_selector("#codeProjNew", state="visible")                        # on the Sessions list itself, not only inside a session
                self.assertTrue(page.is_visible("#codeProj"))
                page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove())")        # the welcome tour can appear late
                page.click("#codeProjNew")
                page.fill(".dialog input", "bad name")
                page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove())")
                page.click(".dialog .btn.primary")
                self.assertIn("no spaces", page.inner_text(".dialog"))                         # a clear reason, the dialog stays open
                page.fill(".dialog input", "recipe-box")
                page.click(".dialog .btn.primary")
                page.wait_for_timeout(500)
                self.assertEqual(page.evaluate("C.project"), "recipe-box")
                self.assertEqual(page.evaluate("C.view"), "session")                           # straight to a blank session in it
                self.assertIn("recipe-box", page.inner_text("#codeProj"))
                self.assertEqual(page.evaluate("document.querySelectorAll('.dialog').length"), 0)
            finally:
                b.close()

    def test_a_garbled_step_and_the_timing_stay_in_the_feed(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 1000, "height": 800}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                page.goto(f"http://127.0.0.1:{self.port}/")
                ready(page)
                page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove()); openCode(); newSession()")
                page.wait_for_timeout(500)
                page.evaluate("cEvent({kind: 'retry', text: 'I see the issue. I will correct the tool call.', why: 'x', secs: 19.2, words: 94}); cEvent({kind: 'step', tool: 'write_file', preview: 'write index.html (3 lines)\\n  + a', raw: '', secs: 7.4, words: 52}); cEvent({kind: 'result', text: 'wrote index.html'})")
                text = page.inner_text("#codeIn")
                self.assertIn("I see the issue", text)
                self.assertIn("Retrying", text)
                self.assertIn("index.html", text)
                self.assertIn("7s", text)
                self.assertIn("52 words", text)
                page.evaluate("cEvent({kind: 'step', tool: 'edit_file', preview: 'edit a.html\\n  - x\\n  + y', raw: ''}); cEvent({kind: 'result', text: 'error: the text in old was not found'})")
                self.assertIn("Could not edit", page.inner_text("#codeIn"))                 # a failed edit does not read like a finished one
            finally:
                b.close()

    def test_update_now_card_lists_the_changes_and_asks_before_updating(self):
        from playwright.sync_api import sync_playwright
        from tests.test_updater import Server
        fake = self.state.updater = Server.Fake()
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 1000, "height": 900}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                page.goto(f"http://127.0.0.1:{self.port}/")
                ready(page)
                page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove()); const d = document.createElement('div'); d.id = 'pcTest'; document.body.append(d); admPc(d)")
                page.wait_for_selector("#pcTest >> text=Software update")
                page.click("#pcTest >> text=Check for updates")
                page.wait_for_selector("#pcTest >> text=1 new change")
                self.assertIn("x", page.inner_text("#pcTest"))
                page.on("dialog", lambda d: d.dismiss())                                   # "No" at the confirmation: nothing happens
                page.click("#pcTest >> text=Update and restart")
                page.wait_for_timeout(400)
                self.assertEqual(fake.applied, [])
            finally:
                b.close()

    def test_vryxcode_is_violet_and_the_home_starts_a_build_from_its_box(self):
        self.state.flags.set_audience("vryxcode_update", "owner", "test")
        from playwright.sync_api import sync_playwright
        import vryxcode
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(list(vryxcode.DEMO))
        st, h, css = Client(self.port).call("GET", "/vryx.css", raw=True)
        self.assertEqual(st, 200)
        self.assertIn("text/css", h["Content-Type"])
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 1200, "height": 850}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                page.goto(f"http://127.0.0.1:{self.port}/")
                ready(page)
                page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove())")
                vryx_on(page)
                page.evaluate("openCode()")
                page.wait_for_selector("#vxQuick", state="visible")
                accent = page.evaluate("getComputedStyle(document.getElementById('code')).getPropertyValue('--accent').trim().toUpperCase()")
                self.assertEqual(accent, "#8B5CF6")                                              # VryxCode's own colour, whatever the chat model's colour is
                self.assertIn("build", page.inner_text(".vx-hero h1").lower())
                page.click("#vxChips button >> nth=0")                                           # an idea chip fills the box
                self.assertIn("bill splitter", page.input_value("#vxQuick").lower())
                page.click("#vxQuickGo")
                wait_for(lambda: page.evaluate("C.view") == "session")                           # straight into a session that runs it
                wait_for(lambda: "Build" in page.inner_text("#codeIn") or "bill splitter" in page.inner_text("#codeIn").lower())
                self.assertEqual(page.evaluate("document.getElementById('vxQuick').value"), "")
            finally:
                b.close()

    def test_templates_notify_box_search_map_and_the_changes_panel(self):
        self.state.flags.set_audience("vryxcode_update", "owner", "test")
        from playwright.sync_api import sync_playwright
        import vryxcode
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(list(vryxcode.DEMO))
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 1200, "height": 850}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{self.port}/")
                ready(page)
                page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove())")
                vryx_on(page)
                page.evaluate("openCode()")
                page.wait_for_selector("#vxTpls button", state="visible")
                self.assertGreaterEqual(page.locator("#vxTpls button").count(), 5)
                self.assertTrue(page.is_visible("#vxNotifyRow"))                                  # the owner can ask for a phone notification
                page.click("#vxTpls button[data-id=todo]")                                        # pick a starter, then Build it with no words at all
                self.assertIn("to-do", page.get_attribute("#vxQuick", "placeholder").lower())
                page.evaluate("C.mode = 'auto'")
                page.click("#vxQuickGo")
                wait_for(lambda: page.evaluate("C.view") == "session")
                wait_for(lambda: "todo-app" in self.state.code.projects("owner") or "todo" in " ".join(self.state.code.projects("owner")))
                project = page.evaluate("C.project")
                self.assertTrue(project.startswith("todo"), project)
                wait_for(lambda: all(self.state.code.sessions[k].state in ("done", "stopped", "failed") for k in self.state.code.sessions))
                self.assertIn("style.css", self.state.code.files("owner", project))               # the starter's files were there from the start
                # the Files drawer: search and the project map
                page.evaluate("showDrawer(true, 'files')")
                page.fill("#codeSearch", "getElementById")
                wait_for(lambda: "app.js" in page.inner_text("#codeFiles"))
                page.fill("#codeSearch", "")
                page.click("#codeMapBtn")
                wait_for(lambda: "app.js" in page.inner_text("#codeFiles") and "files" in page.inner_text("#codeFiles"))
                # the Changes panel lists each file with Keep and Undo
                page.evaluate("showDrawer(true, 'changes')")
                page.wait_for_selector("#tabChanges details.chg", timeout=8000)
                self.assertTrue(page.locator("#tabChanges >> text=Undo this file").count() >= 1)
                self.assertEqual(errors, [])
            finally:
                b.close()

    def test_modern_look_is_a_flag_and_the_empty_chat_offers_ideas(self):
        from playwright.sync_api import sync_playwright
        st, h, css = Client(self.port).call("GET", "/modern.css", raw=True)
        self.assertEqual(st, 200)
        self.assertIn("body.ml", css.decode())
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                for audience, on in (("owner", True), ("off", False)):
                    self.state.flags.set_audience("modern_look", audience, "test")
                    page = b.new_context(viewport={"width": 1200, "height": 850}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.goto(f"http://127.0.0.1:{self.port}/")
                    ready(page)
                    page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove())")
                    page.wait_for_timeout(1200)                                                      # the page applies its look just after it has signed in
                    self.assertEqual(page.evaluate("document.body.classList.contains('ml')"), on)
                    self.assertEqual(page.evaluate("!!document.getElementById('cssModern')"), on)           # its stylesheet is not even loaded when the flag is off
                    self.assertEqual(page.is_visible(".ml-ideas"), on)                              # hidden entirely when the flag is off
                    if on:
                        page.click(".ml-ideas button >> nth=0")
                        self.assertIn("vaccines", page.input_value("#input"))
                    self.assertEqual(errors, [])
            finally:
                b.close()

    def test_open_edit_save_and_a_change_from_outside(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 1500, "height": 850}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{self.port}/")
                ready(page)
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
                ready(page)
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

    def open_editor(self, p):
        b = p.chromium.launch(executable_path=find_browser())
        page = b.new_context(viewport={"width": 1500, "height": 850}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
        self.errors = []
        page.on("pageerror", lambda x: self.errors.append(str(x)))
        page.goto(f"http://127.0.0.1:{self.port}/")
        ready(page)
        page.evaluate("document.querySelectorAll('.tour').forEach((x) => x.remove()); openCode()")
        page.wait_for_timeout(600)
        page.evaluate("C.project = 'demo'; newSession()")
        page.wait_for_timeout(400)
        page.evaluate("document.querySelectorAll('.tour').forEach((x) => x.remove())")
        page.click("#codeIdeBtn")
        page.wait_for_timeout(400)
        return b, page

    def test_output_panel_runs_tests_saves_first_and_shows_what_vryxcode_ran(self):
        from playwright.sync_api import sync_playwright
        self.save("test_a.py", "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertEqual(1 + 1, 2)\n")
        with sync_playwright() as p:
            b, page = self.open_editor(p)
            try:
                page.click("#ideOutBtn")
                page.click("#outRunTests")
                page.wait_for_selector("#ideOutLog .badge2.ok", timeout=15000)
                self.assertIn("Ran 1 test", page.inner_text("#ideOutLog"))
                # edit the test so it fails, WITHOUT saving: Run tests saves first, then runs
                page.click("#ideFiles >> text=test_a.py")
                page.wait_for_timeout(300)
                page.click("#ideBody textarea")
                page.keyboard.press("Control+End")
                page.keyboard.type("\n    def test_bad(self):\n        self.assertEqual(1, 2)\n")
                self.assertIn("\u25cf", page.inner_text("#ideTabs"))
                page.click("#outRunTests")
                page.wait_for_selector("#ideOutLog .badge2.bad", timeout=15000)
                self.assertIn("FAILED", page.inner_text("#ideOutLog"))
                self.assertIn("test_bad", self.disk("test_a.py"))                                # it was saved before it ran
                self.assertNotIn("\u25cf", page.inner_text("#ideTabs"))
                # a command of your own, and Run file
                page.fill("#outCmd", "python -c \"print(6 * 7)\"")
                page.press("#outCmd", "Enter")
                wait_for(lambda: "42" in page.inner_text("#ideOutLog"))
                page.click("#ideFiles >> text=app.py")
                page.wait_for_timeout(400)                                                       # let the editor switch to app.py before Run file reads the open file
                page.click("#outRunFile")
                wait_for(lambda: page.locator("#ideOutLog .oi").count() >= 4)
                self.assertIn("python app.py", page.inner_text("#ideOutLog"))
                # a command VryxCode ran shows up too, marked as VryxCode's
                page.evaluate("cEvent({kind: 'step', tool: 'run', preview: 'run {\"command\": \"python -m unittest -v\"}', raw: ''}); cEvent({kind: 'result', text: 'exit code 0\\nRan 5 tests\\n\\nOK'})")
                text = page.inner_text("#ideOutLog")
                self.assertIn("VRYXCODE", text.upper())
                self.assertIn("python -m unittest -v", text)
                self.assertIn("Ran 5 tests", text)
                self.assertEqual(self.errors, [])
            finally:
                b.close()

    def test_autocomplete_shows_grey_text_tab_accepts_and_escape_dismisses(self):
        import vryxcode
        from playwright.sync_api import sync_playwright
        calls = []

        def backend(model):
            calls.append(1)
            return vryxcode.ScriptedChat(["```python\nreturn a + b\n```"] * 4)
        self.state.code_generate = backend
        with sync_playwright() as p:
            b, page = self.open_editor(p)
            try:
                page.click("#ideFiles >> text=app.py")
                page.wait_for_timeout(300)
                page.click("#ideBody textarea")
                page.keyboard.press("Control+End")
                page.keyboard.type("z = ")
                page.wait_for_timeout(1500)
                self.assertEqual(calls, [])                                                     # off by default: nothing was asked
                self.assertEqual(page.locator("#ideBody .ghost").count(), 0)
                page.click("#ideAc")
                self.assertEqual(page.inner_text("#ideAc"), "Autocomplete: On")
                page.click("#ideBody textarea")
                page.keyboard.press("Control+End")
                page.keyboard.type("1")                                                         # typing starts the timer
                page.wait_for_selector("#ideBody .ghost", timeout=10000)
                self.assertIn("return a + b", page.inner_text("#ideBody .ghost"))
                self.assertNotIn("return a + b", page.input_value("#ideBody textarea"))         # the suggestion is only drawn, not in the file
                page.keyboard.press("Tab")
                self.assertTrue(page.input_value("#ideBody textarea").endswith("z = 1return a + b"))
                wait_for(lambda: page.locator("#ideBody .ghost").count() == 0)                 # the grey text goes at the next repaint
                # Escape dismisses a suggestion
                page.wait_for_selector("#ideBody .ghost", timeout=10000)
                page.keyboard.press("Escape")
                wait_for(lambda: page.locator("#ideBody .ghost").count() == 0)                 # (a repaint later, which a slow machine takes longer to reach)
                self.assertEqual(self.errors, [])
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
