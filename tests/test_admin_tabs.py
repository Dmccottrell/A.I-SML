"""The owner's tools live on the Admin screen only: Settings has no Owner section, and the Overview, Answer reports, Backups and Cloud machine tabs open."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import browser_check
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import wait_for


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class AdminOnly(Base):
    def test_settings_has_no_owner_section_and_admin_has_the_tabs(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 420, "height": 860}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                errs = []
                page.on("pageerror", lambda e: errs.append(str(e)))
                page.goto(f"http://127.0.0.1:{self.port}/")
                wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state"))
                page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove()); openSettings()")
                page.wait_for_selector(".sx-nav")
                self.assertNotIn("OWNER", page.inner_text(".sx-nav"))
                page.evaluate("closeSettings()")
                for tab, words in (("overview", ""), ("reports", ""), ("backups", "ackup"), ("cloud", "")):
                    page.evaluate(f"openAdmin('{tab}')")
                    page.wait_for_timeout(600)
                    self.assertEqual(page.evaluate("ADM.tab"), tab)
                    if words:
                        self.assertIn(words, page.inner_text("body"))
                page.evaluate("closeAdmin ? closeAdmin() : null") if page.evaluate("typeof closeAdmin === 'function'") else None
                page.evaluate("history.replaceState(null, '', '#settings/a-backups'); S.viewChecked = false; restoreView()")
                page.wait_for_timeout(400)
                self.assertEqual(page.evaluate("ADM.tab"), "backups")                        # an old link opens the Admin tab
                self.assertEqual(errs, [])
            finally:
                b.close()


if __name__ == "__main__":
    unittest.main()
