"""Download what VryxCode built (flag vryxcode_downloads): when a session finishes, the programs it made (a Windows .exe, an Android .apk, a Linux or
Mac program, a .jar) are listed with a Download button, and a website or the whole project comes as a zip, like the files Claude makes for you."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import http.client
import io
import unittest
import zipfile

import browser_check
import flags
from tests.test_app_server import Base
from tests.test_browser_check import find_browser
from tests.test_code_sessions import wait_for

EXE = b"MZ\x90\x00" + b"\x00" * 60 + b"PE\x00\x00" + b"x" * 200
ELF = b"\x7fELF\x02\x01\x01" + b"\x00" * 100


class Server(Base):
    def setUp(self):
        super().setUp()
        self.folder = self.state.code.project_path("owner", "tips")
        files = {"dist/tips.exe": EXE, "app/build/outputs/apk/debug/tips.apk": b"PK\x03\x04apk", "build/tips": ELF, "tips.jar": b"PK\x03\x04jar",
                 "index.html": b"<h1>Tips</h1>", "main.py": b"print(1)", "notes": b"just words", "node_modules/x/evil.exe": EXE, "fake.exe": b"not a program"}
        for name, data in files.items():
            path = os.path.join(self.folder, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        os.chmod(os.path.join(self.folder, "build/tips"), 0o755)

    def raw(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", path, headers={"Authorization": "Bearer " + self.state.owner_key()})
        r = c.getresponse()
        try:
            return r.status, dict(r.getheaders()), r.read()
        finally:
            c.close()

    def test_the_flag_starts_with_the_owner_and_admins(self):
        self.assertEqual(flags.BY_ID["vryxcode_downloads"]["default"], "admins")
        self.assertEqual(flags.BY_ID["vryxcode_downloads"]["kind"], "feature")

    def test_the_model_is_told_its_programs_can_be_downloaded(self):
        import code_sessions as CS
        self.assertIn("Never say you cannot give them the file", CS.DOWNLOAD_NOTE)

    def test_off_by_default_in_the_tests(self):
        self.assertNotEqual(self.owner.call("GET", "/api/code/built?project=tips")[0], 200)

    def test_the_programs_it_built_are_found_and_nothing_else(self):
        self.state.flags.data["audiences"]["vryxcode_downloads"] = "admins"
        s, j = self.owner.call("GET", "/api/code/built?project=tips")
        self.assertEqual(s, 200, j)
        got = {f["path"]: f["kind"] for f in j["files"]}
        self.assertEqual(got, {"dist/tips.exe": "Windows program", "app/build/outputs/apk/debug/tips.apk": "Android app", "build/tips": "Linux program",
                               "tips.jar": "Java program"})                             # not the source, not node_modules, not a .exe that is not one
        self.assertTrue(j["website"])                                                    # it has a page: it can come as a website zip
        self.assertEqual(self.sam.call("GET", "/api/code/built?project=tips")[1].get("files", []), [])      # someone else sees only their own (none)

    def test_a_built_program_downloads_and_nothing_outside_it(self):
        self.state.flags.data["audiences"]["vryxcode_downloads"] = "admins"
        s, h, body = self.raw("/api/code/download?project=tips&path=dist/tips.exe")
        self.assertEqual((s, body), (200, EXE))
        self.assertIn('attachment; filename="tips.exe"', h["Content-Disposition"])
        self.assertEqual(h["Content-Type"], "application/octet-stream")
        for bad in ("main.py", "../../../etc/passwd", "node_modules/x/evil.exe", "fake.exe", "missing.exe"):
            self.assertEqual(self.raw("/api/code/download?project=tips&path=" + bad)[0], 404, bad)

    def test_the_website_comes_as_a_zip(self):
        self.state.flags.data["audiences"]["vryxcode_downloads"] = "admins"
        s, h, body = self.raw("/api/code/zip?project=tips")
        self.assertEqual(s, 200)
        self.assertIn("index.html", zipfile.ZipFile(io.BytesIO(body)).namelist())


@unittest.skipUnless(browser_check.available() and find_browser(), "needs the playwright package and a Chromium, Edge or Chrome")
class Page(Base):
    def test_a_finished_session_offers_its_downloads(self):
        from playwright.sync_api import sync_playwright
        self.state.flags.data["audiences"]["vryxcode_downloads"] = "admins"
        folder = self.state.code.project_path("owner", "tips")
        os.makedirs(os.path.join(folder, "dist"), exist_ok=True)
        with open(os.path.join(folder, "dist", "tips.exe"), "wb") as f:
            f.write(EXE)
        with open(os.path.join(folder, "index.html"), "w") as f:
            f.write("<h1>Tips</h1>")
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=find_browser())
            try:
                page = b.new_context(viewport={"width": 420, "height": 860}, extra_http_headers={"Authorization": "Bearer " + self.state.owner_key()}).new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{self.port}/")
                wait_for(lambda: page.evaluate("typeof S !== 'undefined' && !!S.state"))
                page.evaluate("document.querySelectorAll('.tour').forEach((e) => e.remove()); openCode(); newSession(); C.project = 'tips'")
                wait_for(lambda: page.evaluate("C.view === 'session'"))
                page.evaluate("[{kind: 'start', task: 'a tip calculator'}, {kind: 'end', finished: true, summary: 'Done.'}].forEach(cEvent)")
                page.wait_for_selector("#codeIn .vx-dl a[href*='dist%2Ftips.exe'], #codeIn .vx-dl a[href*='dist/tips.exe']")
                text = page.inner_text("#codeIn .vx-dl")
                self.assertIn("tips.exe", text)
                self.assertIn("Windows program", text)
                self.assertIn("Download the website (.zip)", text)
                page.evaluate("[{kind: 'user', text: 'again'}, {kind: 'end', finished: true, summary: 'Done again.'}].forEach(cEvent)")
                wait_for(lambda: page.locator("#codeIn .vx-dl").count() == 1)          # only the newest finish shows the card
                self.assertEqual(errors, [])
            finally:
                b.close()


if __name__ == "__main__":
    unittest.main()
