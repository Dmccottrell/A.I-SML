"""vryxcode_publish: only a web page's own files go public, on GitHub Pages, after a yes (git against a local bare repository, the API faked)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import os
import tempfile
import unittest

import github_link
import site_publish
import vryxcode
from tests.test_app_server import Base
from tests.test_github_link import TOKEN, fake_http, sh


def make(folder, files):
    for rel, text in files.items():
        os.makedirs(os.path.dirname(os.path.join(folder, rel)) or folder, exist_ok=True)
        with open(os.path.join(folder, rel), "w") as f:
            f.write(text)


class Plan(unittest.TestCase):
    def test_only_what_a_browser_needs_goes_public(self):
        with tempfile.TemporaryDirectory() as d:
            make(d, {"index.html": "<h1>hi</h1>", "style.css": "b{}", "js/app.js": "1", "img/logo.svg": "<svg/>", "app.py": "SECRET=1", ".env": "KEY=x",
                     "data.db": "x", "package.json": "{}", "node_modules/a/index.js": "x", ".git/config": "x", "tests/test_a.js": "x", "VRYX.md": "notes"})
            p = site_publish.plan(d)
        self.assertEqual(sorted(p["files"]), ["img/logo.svg", "index.html", "js/app.js", "style.css"])
        for hidden in ("app.py", ".env", "data.db", "package.json", "VRYX.md"):
            self.assertIn(hidden, p["skipped"])
        self.assertEqual(p["entry"], "index.html")

    def test_a_server_project_cannot_go_on_pages(self):
        with tempfile.TemporaryDirectory() as d:
            make(d, {"app.py": "from flask import Flask"})
            with self.assertRaises(github_link.GitHubError) as e:
                site_publish.plan(d)
        self.assertIn("cloud machine", e.exception.action)


class PublishServer(Base):
    def setUp(self):
        super().setUp()
        self.calls, self.pages, self.repos = [], {}, {}
        plain = fake_http(self.calls)

        def http(method, url, headers, body):
            path = url.split("api.github.com", 1)[-1]
            if path.startswith("/repos/"):
                self.calls.append((method, path, body))
                repo = "/".join(path.split("/")[2:4])
                if path.endswith("/pages"):
                    if method == "GET":
                        return (200, {"html_url": self.pages[repo]}) if repo in self.pages else (404, {})
                    if method == "POST":
                        self.pages[repo] = f"https://sam.github.io/{repo.split('/')[1]}/"
                        return 201, {}
                    self.pages.pop(repo, None)
                    return 204, {}
                if method == "GET":
                    return (200, self.repos[repo]) if repo in self.repos else (404, {})
                self.repos[repo].update(json.loads(body))
                return 200, self.repos[repo]
            if path == "/user/repos" and method == "POST":
                b = json.loads(body)
                self.repos["sam/" + b["name"]] = {"private": b["private"]}
            return plain(method, url, headers, body)
        self.state.github_http = http
        self.state.github_local = True
        self.state.code_generate = lambda model: vryxcode.ScriptedChat([])
        self.state.flags.data["audiences"]["vryxcode_publish"] = "admins"
        self.owner.call("POST", "/api/apps/github/connect", {"token": TOKEN})
        self.bare = os.path.join(tempfile.mkdtemp(), "site.git")
        sh("init", "-q", "--bare", self.bare)
        original = github_link.clean_url
        github_link.clean_url = lambda owner, repo: self.bare
        self.addCleanup(lambda: setattr(github_link, "clean_url", original))
        make(self.state.code.project_path("owner", "tips"), {"index.html": "<h1>Tips</h1>", "app.py": "KEY='x'"})

    def test_look_say_yes_publish_then_unpublish(self):
        st, j = self.owner.call("GET", "/api/code/publish?project=tips")
        self.assertEqual(st, 200, j)
        self.assertEqual((j["files"], j["published"], j["repo"]), (["index.html"], False, "tips-site"))
        self.assertEqual(self.owner.call("POST", "/api/code/publish", {"project": "tips"})[0], 400)          # no yes, nothing happens
        self.assertFalse(self.pages)
        st, j = self.owner.call("POST", "/api/code/publish", {"project": "tips", "confirm": True})
        self.assertEqual(st, 200, j)
        self.assertEqual(j["url"], "https://sam.github.io/tips-site/")
        self.assertEqual(self.repos["sam/tips-site"]["private"], False)
        pushed = sh("--git-dir", self.bare, "ls-tree", "-r", "--name-only", "main").split()
        self.assertEqual(sorted(pushed), [".nojekyll", "index.html"])                                   # app.py never left the computer
        self.assertTrue(self.owner.call("GET", "/api/code/publish?project=tips")[1]["published"])
        st, j = self.owner.call("POST", "/api/code/publish", {"project": "tips", "confirm": True})        # again: replaces what is there
        self.assertEqual(st, 200, j)
        st, j = self.owner.call("POST", "/api/code/publish", {"project": "tips", "confirm": True, "action": "unpublish"})
        self.assertEqual((st, j["published"]), (200, False))
        self.assertEqual((self.pages, self.repos["sam/tips-site"]["private"]), ({}, True))

    def test_switched_off_it_is_not_there(self):
        self.state.flags.data["audiences"]["vryxcode_publish"] = "off"
        self.assertEqual(self.owner.call("POST", "/api/code/publish", {"project": "tips", "confirm": True})[0], 404)


if __name__ == "__main__":
    unittest.main()
