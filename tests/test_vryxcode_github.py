"""vryxcode_github: Save to GitHub makes a branch, one commit and a pull request (git against a local bare repository, the GitHub API faked)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import os
import tempfile
import unittest

import github_link
import vryxcode
from tests.test_app_server import Base
from tests.test_github_link import TOKEN, fake_http, sh


class SaveToGitHub(Base):
    def setUp(self):
        super().setUp()
        self.calls, self.pulls = [], []
        plain = fake_http(self.calls)

        def http(method, url, headers, body):
            if "/pulls" in url:
                self.calls.append((method, url, headers.get("Authorization"), body))
                if method == "GET":
                    return 200, [p for p in self.pulls if p["head"] in url.replace("%3A", ":").replace("%2F", "/")]
                b = json.loads(body)
                pr = {"number": len(self.pulls) + 1, "html_url": f"https://github.com/sam/app/pull/{len(self.pulls) + 1}", "head": b["head"], "base": b["base"], "title": b["title"], "body": b["body"]}
                self.pulls.append(pr)
                return 201, pr
            return plain(method, url, headers, body)
        self.state.github_http = http
        self.state.github_local = True
        self.state.code_generate = lambda model: vryxcode.ScriptedChat([])
        self.state.flags.data["audiences"]["vryxcode_github"] = "admins"
        self.owner.call("POST", "/api/apps/github/connect", {"token": TOKEN})
        self.bare = os.path.join(tempfile.mkdtemp(), "app.git")
        sh("init", "-q", "--bare", self.bare)
        original = github_link.clean_url
        github_link.clean_url = lambda owner, repo: self.bare
        self.addCleanup(lambda: setattr(github_link, "clean_url", original))
        self.assertEqual(self.owner.call("POST", "/api/code/git", {"project": "demo", "action": "link", "repo": "sam/app"})[0], 200)
        self.folder = self.state.code.project_path("owner", "demo")

    def write(self, name, text):
        with open(os.path.join(self.folder, name), "w") as f:
            f.write(text)

    def save(self, **kw):
        return self.owner.call("POST", "/api/code/git", {"project": "demo", "action": "save_pr", **kw})

    def test_first_save_goes_to_main_then_each_save_is_a_pull_request(self):
        self.write("app.py", "print('v1')\n")
        st, j = self.save(title="A tip calculator")
        self.assertEqual(st, 200, j)
        self.assertIn("first save", j["message"])
        self.assertIn("A tip calculator", sh("--git-dir", self.bare, "log", "--format=%s", "main"))
        self.write("app.py", "print('v2')\n")
        st, j = self.save(title="Round the tip up", description="Asked for: round up.\n\nChanged: app.py")
        self.assertEqual(st, 200, j)
        self.assertIn("pull request #1", j["message"])
        self.assertTrue(j["branch"].startswith("vryxcode/round-the-tip-up-"))
        self.assertEqual((self.pulls[0]["base"], self.pulls[0]["head"], self.pulls[0]["title"]), ("main", j["branch"], "Round the tip up"))
        self.assertIn("Changed: app.py", self.pulls[0]["body"])
        self.assertIn("Round the tip up", sh("--git-dir", self.bare, "log", "--format=%s", j["branch"]))
        self.write("app.py", "print('v3')\n")                                       # saving again adds to the same pull request
        st, k = self.save(title="Fix the rounding")
        self.assertEqual((st, k["branch"], len(self.pulls)), (200, j["branch"], 1))
        self.assertIn("Added to pull request #1", k["message"])
        self.assertNotIn(TOKEN, json.dumps(k))

    def test_nothing_changed_is_said_plainly(self):
        self.write("app.py", "print('v1')\n")
        self.save(title="first")
        st, j = self.save(title="again")
        self.assertEqual(st, 400)
        self.assertIn("Nothing has changed", j["message"])

    def test_switched_off_it_is_refused(self):
        self.state.flags.data["audiences"]["vryxcode_github"] = "off"
        self.write("app.py", "x = 1\n")
        self.assertEqual(self.save(title="x")[0], 400)


if __name__ == "__main__":
    unittest.main()
