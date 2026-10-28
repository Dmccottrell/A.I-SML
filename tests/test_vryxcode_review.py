"""VryxCode review like Cursor (flag vryxcode_review): lines added and removed per change and per session, documents attached to a task, and in the page the
Working / Ready for review / Done list, quiet grey lines for looking, a chip for each changed file and a Done line listing them."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import base64
import tempfile
import unittest

import browser_check
import code_sessions as CS
import flags
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import wait_for


class Counts(unittest.TestCase):
    def test_the_flag_starts_with_the_owner_and_admins(self):
        self.assertEqual(flags.BY_ID["vryxcode_review"]["default"], "admins")

    def test_new_file_replaced_file_and_edit(self):
        d = tempfile.mkdtemp()
        self.assertEqual(CS.change_counts(d, "write_file", {"path": "a.txt", "content": "1\n2\n3\n"}), {"add": 3, "del": 0})
        with open(os.path.join(d, "a.txt"), "w") as f:
            f.write("1\n2\n3\n")
        self.assertEqual(CS.change_counts(d, "write_file", {"path": "a.txt", "content": "1\nTWO\n3\n4\n"}), {"add": 2, "del": 1})
        self.assertEqual(CS.change_counts(d, "write_file", {"path": "a.txt", "content": "5\n", "append": True}), {"add": 1, "del": 0})
        self.assertEqual(CS.change_counts(d, "edit_file", {"path": "a.txt", "old": "a\nb", "new": "a\nc\nd"}), {"add": 2, "del": 1})
        self.assertEqual(CS.change_counts(d, "read_file", {"path": "a.txt"}), {})
        self.assertEqual(CS.change_counts(d, "write_file", {"path": "../outside.txt", "content": "x"}), {"add": 1, "del": 0})   # never reads outside the project

    def test_the_session_adds_up_only_the_changes_that_went_in(self):
        s = CS.Session("s1", "sam", "p", "make it", "m", tempfile.mkdtemp())
        s.events = [{"kind": "step", "tool": "write_file", "preview": "write a.html (3 lines)", "add": 3, "del": 0}, {"kind": "result", "text": "wrote a.html"},
                    {"kind": "step", "tool": "edit_file", "preview": "edit a.html", "add": 5, "del": 2}, {"kind": "result", "text": "error: the text in 'old' is not in a.html"},
                    {"kind": "step", "tool": "edit_file", "preview": "edit b.css", "add": 1, "del": 1}, {"kind": "result", "text": "edited b.css"}]
        m = s.meta()
        self.assertEqual((m["added"], m["removed"]), (4, 1))


class Docs(Base):
    def test_attached_documents_reach_the_model_only_with_the_flag(self):
        from routes_code import RoutesCode
        lib = self.state.docs_for("owner")
        info = lib.add("brand-guidelines.md", "Use the colour teal. Headings in a serif font.".encode())
        who = self.state.who(self.state.owner_key())
        self.assertEqual(RoutesCode._docs_note(self.state, who, [info["id"]]), "")              # the test base switches the flag off
        self.state.flags.data["audiences"]["vryxcode_review"] = "admins"
        note = RoutesCode._docs_note(self.state, who, [info["id"], 999999, "x"])
        self.assertIn("### brand-guidelines.md", note)
        self.assertIn("Use the colour teal", note)
        self.assertEqual(RoutesCode._docs_note(self.state, who, None), "")


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    def page(self, p, audience="admins"):
        self.state.flags.data["audiences"]["vryxcode_review"] = audience
        b = p.chromium.launch(executable_path=find_browser())
        ctx = b.new_context(viewport={"width": 420, "height": 860}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()})
        ctx.route(lambda url: not url.startswith(f"http://127.0.0.1:{self.port}/"), lambda r: r.abort())    # only the test server: a web font that cannot load must not slow the page
        page = ctx.new_page()
        page.goto(f"http://127.0.0.1:{self.port}/")
        wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state"))
        # the welcome tour must never cover a click: on a slow machine it opens after the page is ready, so stop it from opening at all (as ready() does)
        page.evaluate("S.tourChecked = true; openTour = () => {}; document.querySelectorAll('.tour').forEach((e) => e.remove()); openCode(); newSession()")
        wait_for(lambda: page.evaluate("C.view === 'session'"))
        return b, page

    def test_a_session_started_while_vryxcode_opens_is_not_replaced_by_the_home(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b, page = self.page(p)
            try:
                page.evaluate("showHome(); openCode(); newSession()")       # New session tapped while VryxCode is still loading
                page.wait_for_timeout(1500)                                   # ...and the loading finishes afterwards
                self.assertEqual(page.evaluate("C.view"), "session")
            finally:
                b.close()

    EVENTS = ("cEvent({kind: 'start', task: 'make a landing page'});"
              "cEvent({kind: 'step', tool: 'read_file', preview: 'read_file {\"path\": \"about-acme.md\"}', raw: '', secs: 6.2});"
              "cEvent({kind: 'result', text: '1: Acme makes rockets'});"
              "cEvent({kind: 'step', tool: 'write_file', preview: 'write app/page.tsx (52 lines)\\n  + export default', raw: '', add: 52, del: 0});"
              "cEvent({kind: 'result', text: 'wrote app/page.tsx (52 lines)'});"
              "cEvent({kind: 'step', tool: 'edit_file', preview: 'edit app/globals.css\\n  - a\\n  + b', raw: '', add: 18, del: 0});"
              "cEvent({kind: 'result', text: 'edited app/globals.css'});"
              "cEvent({kind: 'end', finished: true, summary: 'Done. Fonts preload in the head.'});")

    def test_quiet_lines_file_chips_and_the_done_line(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b, page = self.page(p)
            try:
                page.evaluate(self.EVENTS)
                quiet = page.evaluate("[...document.querySelectorAll('#codeIn .cc-quiet')].map((x) => x.textContent)")
                self.assertIn("Thought 6s", quiet)
                self.assertTrue(any("about-acme.md" in q for q in quiet), quiet)
                self.assertEqual(page.locator("#codeIn .cc-tool").count(), 0)              # no big cards for looking or for changes
                chips = page.evaluate("[...document.querySelectorAll('#codeIn > .cc-file')].map((x) => x.textContent)")
                self.assertEqual(len(chips), 2)
                self.assertIn("app/page.tsx", chips[0])
                self.assertIn("+52", chips[0])
                done = page.inner_text("#codeIn .cc-done")
                self.assertIn("Changed 2 files", done)
                self.assertIn("+70", done)
            finally:
                b.close()

    def test_the_working_line_is_plain_text_not_a_card(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            for audience, plain in (("admins", True), ("off", False)):
                b, page = self.page(p, audience)
                try:
                    page.evaluate("renderLive({phase: 'run', tool: 'run', target: 'npm install', secs: 4}, 'working')")
                    self.assertEqual(page.evaluate("document.getElementById('codeLive').classList.contains('vx-q')"), plain)
                    # the VryxCode stylesheet (the card's dashed border) is added once the page knows its flags and loads in the background:
                    # wait for the look to settle instead of reading it at once
                    border = lambda: page.evaluate("getComputedStyle(document.getElementById('codeLive')).borderTopStyle")
                    wait_for(lambda: (border() == "none") == plain)
                    self.assertEqual(border() == "none", plain, border())
                finally:
                    b.close()

    def test_off_means_the_cards_as_before(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b, page = self.page(p, "off")
            try:
                page.evaluate(self.EVENTS)
                self.assertEqual(page.locator("#codeIn .cc-quiet").count(), 0)
                self.assertGreater(page.locator("#codeIn .cc-tool").count(), 0)
                self.assertEqual(page.locator("#codeIn .cc-done").count(), 0)
            finally:
                b.close()

    def test_the_list_is_grouped_and_shows_the_lines(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b, page = self.page(p)
            try:
                page.evaluate("C.sessions = [{id: 'a', title: 'Build Landing Page', project: 'site', model: 'm', state: 'done', updated: 5, age: 'now', files: 2, added: 70, removed: 0, snippet: 'Done.'},"
                              "{id: 'b', title: 'Old one', project: 'site', model: 'm', state: 'done', updated: 3, age: '1h', files: 0}];"
                              "C.filter = 'all'; const real = api, list = C.sessions; api = async (u, o) => (u === '/api/code/sessions' ? {json: async () => ({sessions: list})} : real(u, o)); renderHome()")
                # the page's own first load of the list can land after this one and empty it: draw again until the test's list is the one shown
                wait_for(lambda: page.evaluate("renderHome().then(() => document.querySelectorAll('.vx-group').length > 0)"))
                groups = page.evaluate("[...document.querySelectorAll('.vx-group')].map((x) => x.textContent)")
                self.assertEqual(groups, ["READY FOR REVIEW 1", "DONE 1"])
                self.assertIn("+70", page.inner_text("#codeList"))
            finally:
                b.close()


if __name__ == "__main__":
    unittest.main()
