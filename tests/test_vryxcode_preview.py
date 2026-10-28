"""The preview follows the work (flag vryxcode_preview): it opens the web page the session changed last, the Done line has a Preview button,
and the model is told the preview exists (asked for a link it said it "cannot generate links or host files")."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import browser_check
import code_sessions as CS
import flags
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import wait_for


class Server(Base):
    def project(self):
        folder = self.state.code.project_path("owner", "rpg")
        os.makedirs(folder, exist_ok=True)
        for name in ("index.html", "graphical_interface.html"):
            with open(os.path.join(folder, name), "w") as f:
                f.write("<h1>" + name + "</h1>")
        return folder

    def test_the_flag_starts_with_the_owner_and_admins(self):
        self.assertEqual(flags.BY_ID["vryxcode_preview"]["default"], "admins")

    def test_the_page_changed_last_is_the_one_opened(self):
        self.project()
        ask = lambda page: self.owner.call("POST", "/api/code/preview", {"project": "rpg", "page": page})[1]["entry"]
        self.assertEqual(ask("graphical_interface.html"), "index.html")            # the test base switches the flag off: as before
        self.state.flags.data["audiences"]["vryxcode_preview"] = "admins"
        self.assertEqual(ask("graphical_interface.html"), "graphical_interface.html")
        self.assertEqual(ask("../../secret.html"), "index.html")                  # never outside the project
        self.assertEqual(ask("missing.html"), "index.html")
        self.assertEqual(ask("main.py"), "index.html")

    def test_the_model_is_told_about_the_preview(self):
        self.assertIn("press Preview", CS.PREVIEW_NOTE)
        self.assertIn("Never say you cannot make links", CS.PREVIEW_NOTE)


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    def test_the_done_line_has_a_preview_button_and_the_page_is_remembered(self):
        from playwright.sync_api import sync_playwright
        for name, flag in (("vryxcode_review", "admins"), ("vryxcode_preview", "admins")):
            self.state.flags.data["audiences"][name] = flag
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 420, "height": 860}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                page.goto(f"http://127.0.0.1:{self.port}/")
                wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state"))
                page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove()); openCode(); newSession()")
                wait_for(lambda: page.evaluate("C.view === 'session'"))
                events = ("[{kind: 'start', task: 'rpg'}, {kind: 'step', tool: 'write_file', preview: 'write graphical_interface.html (40 lines)', raw: '', add: 40, del: 0},"
                          "{kind: 'result', text: 'wrote graphical_interface.html (40 lines)'}, {kind: 'end', finished: true, summary: 'Done.'}]")
                page.evaluate(f"(() => {{ const ev = {events}; ev.forEach(cEvent); livePreview(ev); }})()")
                self.assertEqual(page.evaluate("C.pvPage"), "graphical_interface.html")
                self.assertEqual(page.locator("#codeIn .cc-done .vx-pvgo").count(), 1)
            finally:
                b.close()


if __name__ == "__main__":
    unittest.main()
