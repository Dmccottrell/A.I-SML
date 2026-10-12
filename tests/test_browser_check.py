"""The browser check (coding/browser_check.py): the pure parts always; the real hidden browser only where one is installed."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import glob
import shutil
import tempfile
import unittest

import browser_check as B
import harness
from tests.test_code_sessions import open_to_everyone
from tests.test_app_server import Base

ORIGIN = "http://127.0.0.1:5555"


def find_browser():
    if os.environ.get("EMVRYX_BROWSER") and os.path.exists(os.environ["EMVRYX_BROWSER"]):
        return os.environ["EMVRYX_BROWSER"]
    for pattern in ("/opt/pw-browsers/chromium-*/chrome-linux/chrome", "/usr/bin/chromium", "/usr/bin/google-chrome", "/usr/bin/chromium-browser"):
        hits = glob.glob(pattern)
        if hits:
            return hits[0]
    return None


PAGE = """<!doctype html><html><head><title>Test</title></head><body><h1>Hi</h1>
<button onclick="undefinedFn()">Go</button><div style="width:900px">wide</div><img src="missing.png"><button></button>
<script>console.error('boom'); fetch('http://example.com/x', {method: 'POST'}).catch(() => {})</script></body></html>"""


class Pure(unittest.TestCase):
    def test_page_paths_stay_inside_the_project_and_must_be_html(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        os.makedirs(os.path.join(d, "sub"))
        for name in ("index.html", "sub/a.html", "notes.txt"):
            open(os.path.join(d, name), "w").write("x")
        self.assertEqual(B.safe_page_path(d, "index.html"), "index.html")
        self.assertEqual(B.safe_page_path(d, "sub/a.html"), "sub/a.html")
        for bad in ("../x.html", "notes.txt", "missing.html", "", "/etc/passwd", "sub/../../x.html"):
            self.assertIsNone(B.safe_page_path(d, bad), bad)

    def test_the_gate_lets_through_only_the_page_and_a_few_cdns_and_never_posts(self):
        ok = lambda url, method="GET": B.request_allowed(url, method, ORIGIN)
        self.assertTrue(ok(ORIGIN + "/app.js"))
        self.assertTrue(ok("data:image/png;base64,AAAA"))
        self.assertTrue(ok("https://cdn.jsdelivr.net/npm/x@1/x.js"))
        self.assertFalse(ok("https://example.com/x"))
        self.assertFalse(ok("http://cdn.jsdelivr.net/npm/x.js"))              # http, not https
        self.assertFalse(ok(ORIGIN + "/x", "POST"))
        self.assertFalse(ok("https://cdn.jsdelivr.net/x", "POST"))
        self.assertFalse(ok("http://127.0.0.1:8001/api/state"))               # another local service (the Emvryx app itself)
        self.assertFalse(ok("http://localhost:8001/"))
        self.assertFalse(ok("http://192.168.1.5/admin"))

    def test_audit_numbers_become_plain_problems(self):
        audit = {"vw": 390, "scrollWidth": 908, "overflowing": ['div "wide"'], "overflowCount": 1, "viewportMeta": False, "brokenImages": ["missing.png"],
                 "unnamed": ["button"], "smallCount": 2, "small": ["button"], "unlabeled": 1, "tinyText": 3, "imagesNoAlt": 1, "title": "", "textLength": 10}
        text = " ".join(B.issues_from_audit(audit, 390))
        for needle in ("scrolls sideways", "No viewport tag", "did not load", "no text or label", "smaller than 32px", "no label or placeholder", "smaller than 12px", "alt text", "no <title>"):
            self.assertIn(needle, text)
        self.assertEqual(B.issues_from_audit({"vw": 390, "scrollWidth": 390, "viewportMeta": True, "title": "x", "textLength": 5}, 390), [])
        self.assertIn("empty", B.issues_from_audit({"textLength": 0, "viewportMeta": True, "title": "x"}, 390)[0])

    def test_the_report_lists_errors_clicks_blocks_and_the_screenshot(self):
        r = {"page_errors": ["x is not defined"], "console_errors": ["boom"], "failed": [], "blocked": ["POST http://example.com/x"], "click_errors": ['click "Go": oops'],
             "clicked": ["Go"], "audit": {"vw": 390, "scrollWidth": 390, "viewportMeta": True, "title": "T", "textLength": 5}, "title": "T", "shot": "check-1700000000.png"}
        text = B.format_report(r, "index.html", 390, 844)
        for needle in ("loaded, with problems", "Script errors (1)", "Console errors (1)", "After clicking (1)", "Clicked: Go", "Blocked by the safety gate", "Screenshot: check-1700000000.png"):
            self.assertIn(needle, text)
        self.assertTrue(B.SHOT_RX.fullmatch("check-1700000000.png"))
        self.assertFalse(B.SHOT_RX.fullmatch("../check-1700000000.png"))
        self.assertIn("could not run", B.format_report({"error": "no browser"}, "index.html", 390, 844))
        clean = dict(r, page_errors=[], console_errors=[], click_errors=[], blocked=[])
        self.assertIn("no errors found", B.format_report(clean, "index.html", 390, 844))


@unittest.skipUnless(B.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class RealBrowser(unittest.TestCase):
    def setUp(self):
        self.old = os.environ.get("EMVRYX_BROWSER")
        os.environ["EMVRYX_BROWSER"] = find_browser()
        self.d = tempfile.mkdtemp()
        open(os.path.join(self.d, "index.html"), "w").write(PAGE)

    def tearDown(self):
        shutil.rmtree(self.d, True)
        if self.old is None:
            os.environ.pop("EMVRYX_BROWSER", None)
        else:
            os.environ["EMVRYX_BROWSER"] = self.old

    def test_finds_the_problems_clicks_and_blocks_the_post(self):
        r = B.check_page(self.d, "index.html")
        self.assertNotIn("error", r, r)
        self.assertTrue(any("boom" in e for e in r["console_errors"]))
        self.assertTrue(any("undefinedFn" in e for e in r["click_errors"]))
        self.assertTrue(any(b.startswith("POST http://example.com") for b in r["blocked"]))      # the page tried to send something out; the gate stopped it
        self.assertGreater(r["audit"]["scrollWidth"], 390)
        self.assertEqual(r["audit"]["brokenImages"], ["missing.png"])
        self.assertTrue(os.path.getsize(os.path.join(self.d, B.SHOT_DIR, r["shot"])) > 1000)
        self.assertIn("scrolls sideways", B.format_report(r, "index.html", 390, 844))


class InTheLoop(unittest.TestCase):
    def test_the_model_is_told_about_check_page_and_may_use_it_without_a_question(self):
        import vryxcode as V
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        asked = []
        called = []
        model = V.ScriptedChat([V.harness_call("check_page", path="index.html"), V.harness_call("finish", summary="checked")])
        import code_sessions
        session = code_sessions.Session("s1", "owner", "demo", "check it", "solstice-2", d)
        self.assertTrue(session.ask("check_page", {}))                        # the session never stops to ask about the browser check (it only looks)
        ask = lambda name, args: name == "check_page"
        result = V.run_task("check it", model, d, ask, tools={"check_page": lambda path="", width=390, height=844: called.append(path) or "Page check: fine"}, out=lambda *_: None)
        self.assertEqual(called, ["index.html"])
        self.assertTrue(result["finished"])
        self.assertIn("check_page(path, width, height)", model.seen[0][0]["content"])


class Tool(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)

    def test_the_tool_refuses_without_a_page_and_with_bad_paths(self):
        tool = self.state.browser_tool("owner", "demo")
        with self.assertRaises(harness.ToolError) as c:
            tool()
        self.assertIn("no web page", str(c.exception))
        with self.assertRaises(harness.ToolError):
            tool(path="../secret.html")
        with self.assertRaises(harness.ToolError):
            tool(path="x.html", width="wide")

    def test_screenshots_are_served_only_by_exact_name_to_the_project_owner(self):
        folder = self.state.code.project_path("owner", "demo")
        os.makedirs(os.path.join(folder, B.SHOT_DIR), exist_ok=True)
        with open(os.path.join(folder, B.SHOT_DIR, "check-1700000000.png"), "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\nxxxx")
        st, headers, data = self.owner.call("GET", "/api/code/shot?project=demo&name=check-1700000000.png", raw=True)
        self.assertEqual((st, headers["Content-Type"], data[:4]), (200, "image/png", b"\x89PNG"))
        self.assertEqual(self.owner.call("GET", "/api/code/shot?project=demo&name=../../x.png", raw=True)[0], 404)
        self.assertEqual(self.owner.call("GET", "/api/code/shot?project=demo&name=check-1700000001.png", raw=True)[0], 404)
        self.assertEqual(self.sam.call("GET", "/api/code/shot?project=demo&name=check-1700000000.png", raw=True)[0], 404)       # another person's project folder is a different folder


if __name__ == "__main__":
    unittest.main()
