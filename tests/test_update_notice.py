"""When Emvryx is updated on the server, a page that is already open says "A new version of Emvryx is ready" with an Update now button that reloads it
(the website, the installed app and the Windows app all show this same page). The server tells every page its current page version in /api/status."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import browser_check
import routes_get
from tests.test_app_server import Base, Client
from tests.test_browser_check import find_browser
from tests.test_code_sessions import wait_for


class Status(Base):
    def test_the_status_carries_the_page_version(self):
        s, j = Client(self.port).call("GET", "/api/status")
        self.assertEqual(s, 200)
        self.assertEqual(j["shell"], routes_get.shell_version())


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    def open(self):
        from playwright.sync_api import sync_playwright
        self.state.flags.data["audiences"]["pwa_install"] = "admins"
        p = sync_playwright().start()
        self.addCleanup(p.stop)
        b = p.chromium.launch(executable_path=find_browser())
        self.addCleanup(b.close)
        page = b.new_context(viewport={"width": 420, "height": 860}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{self.port}/")
        wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state && typeof pwaCheckUpdate === 'function'"))
        page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove())")
        return page

    def test_nothing_is_shown_until_the_server_changes(self):
        page = self.open()
        page.evaluate("pwaCheckUpdate()")
        page.wait_for_timeout(600)
        self.assertEqual(page.evaluate("!!document.getElementById('pwaUpdate')"), False)
        self.assertEqual(self.errors, [])

    def test_after_an_update_the_page_offers_update_now_and_it_reloads(self):
        page = self.open()
        page.wait_for_timeout(800)                                                       # the page has noted the version it started with
        old = routes_get.shell_version
        routes_get.shell_version = lambda: "a-newer-version"                             # the server was updated
        self.addCleanup(setattr, routes_get, "shell_version", old)
        page.evaluate("window.__stay = 1; pwaCheckUpdate()")
        page.wait_for_selector("#pwaUpdate")
        text = page.inner_text("#pwaUpdate")
        self.assertIn("A new version of Emvryx is ready", text)
        self.assertIn("Update now", text)
        page.evaluate("document.querySelector('#pwaUpdate .btn').click()")               # a script click: a late welcome tour must not block it
        def reloaded():                                                                  # the marker is gone and the new page has started
            try:
                return page.evaluate("window.__stay === undefined && typeof pwaCheckUpdate === 'function'")
            except Exception:                                                            # asked in the middle of the reload
                return False
        wait_for(reloaded)
        self.assertEqual(self.errors, [])

    def test_later_hides_it_and_with_the_switch_off_it_never_shows(self):
        page = self.open()
        page.wait_for_timeout(800)
        old = routes_get.shell_version
        routes_get.shell_version = lambda: "a-newer-version"
        self.addCleanup(setattr, routes_get, "shell_version", old)
        page.evaluate("pwaCheckUpdate()")
        page.wait_for_selector("#pwaUpdate")
        page.evaluate("document.querySelector('#pwaUpdate .icon').click()")
        self.assertEqual(page.evaluate("!!document.getElementById('pwaUpdate')"), False)
        page.evaluate("S.state.features.pwa_install = false; pwaCheckUpdate()")
        page.wait_for_timeout(600)
        self.assertEqual(page.evaluate("!!document.getElementById('pwaUpdate')"), False)


if __name__ == "__main__":
    unittest.main()
