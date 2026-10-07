"""The live preview of a project: safe to open, limited to the person's own folder, and it reports the page's own errors."""
import os
import tempfile
import time
import unittest

import code_preview as P
from tests.test_app_server import Base
from tests.test_code_sessions import open_to_everyone


def make_site(files):
    d = os.path.realpath(tempfile.mkdtemp())
    for name, text in files.items():
        os.makedirs(os.path.dirname(os.path.join(d, name)) or d, exist_ok=True)
        with open(os.path.join(d, name), "w") as f:
            f.write(text)
    return d


class Serving(unittest.TestCase):
    def test_the_reporter_goes_in_after_head_and_the_file_on_disk_is_unchanged(self):
        d = make_site({"index.html": "<!doctype html><html><head><title>t</title></head><body>hi</body></html>"})
        status, ctype, body = P.serve(d, "")
        self.assertEqual((status, ctype), (200, "text/html; charset=utf-8"))
        self.assertIn(b"<head><script>", body)
        self.assertIn(b"vryxPreview", body)
        with open(os.path.join(d, "index.html")) as f:
            self.assertNotIn("vryxPreview", f.read())

    def test_a_page_without_head_still_gets_it(self):
        d = make_site({"index.html": "<h1>hi</h1>"})
        self.assertTrue(P.serve(d, "index.html")[2].startswith(b"<script>"))

    def test_other_files_are_served_with_their_type(self):
        d = make_site({"index.html": "x", "a.css": "body{}", "app.js": "1", "logo.svg": "<svg/>", "sub/page.html": "<p>s</p>", "sub/index.html": "<p>i</p>"})
        self.assertEqual(P.serve(d, "a.css")[1], "text/css; charset=utf-8")
        self.assertIn("javascript", P.serve(d, "app.js")[1])
        self.assertTrue(P.serve(d, "logo.svg")[1].startswith("image/svg+xml"))
        self.assertIn(b"<p>i</p>", P.serve(d, "sub/")[2])                       # a folder means its index.html

    def test_nothing_outside_the_folder_or_internal_is_ever_served(self):
        d = make_site({"index.html": "ok", ".git/config": "secret", ".emvryx/hooks.json": "[]"})
        outside = make_site({"secret.txt": "top secret"})
        os.symlink(os.path.join(outside, "secret.txt"), os.path.join(d, "link.txt"))
        for rel in ("../" + os.path.basename(outside) + "/secret.txt", "..%2f", "/etc/passwd", "link.txt", ".git/config", ".emvryx/hooks.json", "a\x00b", "missing.html"):
            self.assertEqual(P.serve(d, rel)[0], 404, rel)

    def test_entry_page(self):
        self.assertEqual(P.entry_page(make_site({"index.html": "", "a.html": ""})), "index.html")
        self.assertEqual(P.entry_page(make_site({"zeta.html": "", "alpha.html": ""})), "alpha.html")
        self.assertIsNone(P.entry_page(make_site({"main.py": ""})))

    def test_tokens_expire_and_are_limited(self):
        now = [1000.0]
        pv = P.Previews(clock=lambda: now[0])
        d = make_site({"index.html": "x"})
        t = pv.make("sam", d)
        self.assertEqual(pv.folder(t), d)
        now[0] += P.TOKEN_SECONDS + 1
        self.assertIsNone(pv.folder(t))
        self.assertIsNone(pv.folder("nope"))
        for _ in range(P.MAX_TOKENS + 10):
            pv.make("sam", d)
        self.assertLessEqual(len(pv.tokens), P.MAX_TOKENS)


class Over_HTTP(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)

    def project(self, user, files):
        folder = self.state.code.project_path(user, "site")
        os.makedirs(folder, exist_ok=True)
        for name, text in files.items():
            with open(os.path.join(folder, name), "w") as f:
                f.write(text)

    def get(self, url):
        """What the preview frame does: no key, no cookie, only the token in the address."""
        from tests.test_app_server import Client
        return Client(self.port).call("GET", url, raw=True)

    def test_open_preview_returns_a_link_that_serves_the_page_with_safe_headers(self):
        self.project("owner", {"index.html": "<html><head></head><body><script src='app.js'></script></body></html>", "app.js": "console.log(1)"})
        st, j = self.owner.call("POST", "/api/code/preview", {"project": "site"})
        self.assertEqual((st, j["entry"]), (200, "index.html"))
        status, headers, body = self.get(j["url"])
        self.assertEqual(status, 200)
        self.assertIn(b"vryxPreview", body)
        self.assertTrue(headers["Content-Security-Policy"].startswith("sandbox allow-scripts"))     # an empty identity: it cannot reach the app's cookies or API
        self.assertEqual(headers["Cross-Origin-Resource-Policy"], "cross-origin")
        self.assertNotIn("X-Frame-Options", headers)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(self.get(j["url"].rsplit("/", 1)[0] + "/app.js")[0], 200)                  # relative files work under the same token

    def test_no_html_means_nothing_to_preview(self):
        self.project("owner", {"main.py": "print(1)"})
        self.assertIsNone(self.owner.call("POST", "/api/code/preview", {"project": "site"})[1]["entry"])
        self.assertIsNone(self.owner.call("POST", "/api/code/preview", {"project": "nothing-here"})[1]["entry"])

    def test_a_wrong_or_expired_link_is_not_served(self):
        self.assertEqual(self.get("/preview/" + "a" * 32 + "/index.html")[0], 404)
        self.project("owner", {"index.html": "x"})
        url = self.owner.call("POST", "/api/code/preview", {"project": "site"})[1]["url"]
        token = url.split("/")[2]
        self.state.previews.tokens[token]["expires"] = time.time() - 1
        self.assertEqual(self.get(url)[0], 404)

    def test_a_person_can_only_open_a_preview_of_their_own_projects(self):
        self.project("owner", {"index.html": "owner's page"})
        st, j = self.sam.call("POST", "/api/code/preview", {"project": "site"})
        self.assertEqual(st, 200)
        self.assertIsNone(j["entry"])                                                              # sam's own "site" project is empty, not the owner's

    def test_it_is_not_open_to_someone_without_vryxcode(self):
        self.state.cfg["tiers"]["free"]["vryxcode"] = False
        self.assertEqual(self.sam.call("POST", "/api/code/preview", {"project": "site"})[0], 400)


if __name__ == "__main__":
    unittest.main()
