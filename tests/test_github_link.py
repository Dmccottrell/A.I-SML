"""GitHub as a connected app: the saved token, the API calls (faked), git push/pull (against a local bare repo), and the guards."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import json
import os
import stat
import subprocess
import tempfile
import time
import unittest

import github_link as G
import harness
import vryxcode
from tests.test_app_server import Base, Client
from tests.test_code_sessions import wait_for

TOKEN = "ghp_" + "a1B2c3D4e5" * 4


def sh(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def fake_http(calls, user="sam", fail=None):
    def http(method, url, headers, body):
        calls.append((method, url, headers.get("Authorization"), body))
        if fail:
            return fail, {"message": "x"}
        if url.endswith("/user") and method == "GET":
            return 200, {"login": user, "id": 4242}
        if "/user/repos?" in url and method == "GET":
            return 200, ([{"full_name": f"{user}/app-{i}", "private": i % 2 == 0, "description": f"d{i}", "pushed_at": f"2026-10-0{i % 9 + 1}T10:00:00Z"} for i in range(3)]
                         if "page=1" in url else [])
        if url.endswith("/user/repos"):
            name = json.loads(body)["name"]
            return 201, {"full_name": f"{user}/{name}"}
        return 404, {}
    return http


class Names(unittest.TestCase):
    def test_repo_names_are_checked(self):
        self.assertEqual(G.parse_repo("sam/app"), ("sam", "app"))
        self.assertEqual(G.parse_repo("https://github.com/sam/app.git"), ("sam", "app"))
        for bad in ("", "sam", "a/b/c", "sam/..", "https://evil.com/sam/app", "sam/app;rm", "-x/app"):
            with self.assertRaises(G.GitHubError, msg=bad):
                G.parse_repo(bad)

    def test_token_shape(self):
        self.assertEqual(G.validate_token(" " + TOKEN + "\n"), TOKEN)
        for bad in ("", "short", "has space " + TOKEN, "x" * 300):
            with self.assertRaises(G.GitHubError):
                G.validate_token(bad)


class StoreTests(unittest.TestCase):
    def test_token_file_is_private_and_never_in_the_public_view(self):
        with tempfile.TemporaryDirectory() as d:
            s = G.Store(d)
            s.connect("sam", TOKEN, "sam", 1)
            path = s._path("sam")
            if os.name != "nt":                                  # Windows has no Unix file modes (only the machine is skipped)
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            self.assertNotIn(TOKEN, json.dumps(s.public("sam")))
            self.assertTrue(s.connected("sam"))
            s.log("sam", "pushed x")
            s.disconnect("sam")
            self.assertFalse(s.connected("sam"))
            self.assertNotIn(TOKEN, open(path).read())
            self.assertEqual(s.public("sam")["log"][0]["what"], "pushed x")      # the short log stays


class ApiTests(unittest.TestCase):
    def test_me_and_create(self):
        calls = []
        api = G.Api(TOKEN, fake_http(calls))
        self.assertEqual(api.me(), ("sam", 4242))
        self.assertEqual(api.create_repo("my-app", private=True), ("sam", "my-app"))
        self.assertEqual(json.loads(calls[-1][3])["private"], True)
        self.assertTrue(calls[-1][2].startswith("Bearer "))

    def test_errors_are_plain(self):
        for code, word in ((401, "did not accept"), (403, "refused"), (404, "could not find"), (422, "said no")):
            with self.assertRaises(G.GitHubError) as c:
                G.Api(TOKEN, fake_http([], fail=code)).me()
            self.assertIn(word, c.exception.message)
        with self.assertRaises(G.GitHubError):
            G.Api(TOKEN, fake_http([])).create_repo("bad name!")


class GitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bare = os.path.join(self.tmp.name, "remote.git")
        sh("init", "--bare", "-b", "main", self.bare)
        self.ws = os.path.join(self.tmp.name, "proj")
        os.makedirs(self.ws)
        self.g = G.Git(self.ws, TOKEN, allow_local=True)
        self.g.run(["init", "-b", "main"])
        self.g.run(["remote", "add", "origin", self.bare])
        open(os.path.join(self.ws, "a.txt"), "w").write("hi\n")
        self.g.run(["add", "-A"])
        self.g.run(["commit", "-m", "first"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_status_counts_unpushed_commits(self):
        st = self.g.status()
        self.assertTrue(st["linked"])
        self.assertEqual((st["branch"], st["ahead"], st["changed_files"]), ("main", 1, 0))

    def test_push_to_main_needs_an_extra_yes_and_a_branch_push_works(self):
        with self.assertRaises(G.GitHubError) as c:
            self.g.push()
        self.assertIn("extra confirmation", c.exception.message)
        self.g.run(["switch", "-c", "feature"])
        self.g.push()
        self.assertIn("feature", sh("branch", "--list", cwd=self.bare))
        self.assertEqual(self.g.status()["ahead"], 0)
        self.g.run(["switch", "main"])
        self.g.push(allow_protected=True)
        self.assertIn("main", sh("branch", "--list", cwd=self.bare))

    def test_pull_is_fast_forward_only(self):
        self.g.push(allow_protected=True)
        other = os.path.join(self.tmp.name, "other")
        sh("clone", self.bare, other)
        open(os.path.join(other, "b.txt"), "w").write("more\n")
        sh("-c", "user.name=t", "-c", "user.email=t@t", "add", "-A", cwd=other)
        sh("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "second", cwd=other)
        sh("push", "origin", "main", cwd=other)
        self.g.pull()
        self.assertTrue(os.path.exists(os.path.join(self.ws, "b.txt")))
        # diverge: a local commit and a remote commit -> pull refuses instead of merging
        open(os.path.join(other, "c.txt"), "w").write("c\n")
        sh("add", "-A", cwd=other)
        sh("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "third", cwd=other)
        sh("push", "origin", "main", cwd=other)
        open(os.path.join(self.ws, "d.txt"), "w").write("d\n")
        self.g.run(["add", "-A"])
        self.g.run(["commit", "-m", "local"])
        with self.assertRaises(G.GitHubError):
            self.g.pull()

    def test_a_remote_that_is_not_github_is_refused(self):
        strict = G.Git(self.ws, TOKEN, allow_local=False)
        strict.run(["remote", "set-url", "origin", "https://evil.example/sam/app.git"])
        with self.assertRaises(G.GitHubError):
            strict.push(allow_protected=True)
        self.assertFalse(strict.status()["linked"])
        strict.run(["remote", "set-url", "origin", "file:///tmp/whatever"])
        with self.assertRaises(G.GitHubError):
            strict.pull()

    def test_the_token_never_appears_in_output(self):
        self.assertEqual(self.g.scrub("error with " + TOKEN), "error with ***")

    def test_link_replaces_the_remote_with_a_clean_github_url(self):
        strict = G.Git(self.ws, TOKEN)
        strict.init_and_link("sam", "app")
        self.assertEqual(strict.remote(), ("sam", "app", "https://github.com/sam/app.git"))
        self.assertNotIn(TOKEN, open(os.path.join(self.ws, ".git", "config")).read())


class SandboxGuard(unittest.TestCase):
    def test_the_model_cannot_edit_the_git_folder(self):
        with harness.Sandbox() as sb:
            sb.git(["init"]) if hasattr(sb, "git") else None
            with self.assertRaises(harness.ToolError):
                sb.write_file(".git/config", "[remote]")
            with self.assertRaises(harness.ToolError):
                sb.call("write_file", {"path": "sub/.git/hooks/x", "content": "y"})


class GitTroubles(unittest.TestCase):
    """What git prints when GitHub cannot be reached, in plain words, and the settings that let git reach it from a locked-down start."""

    def test_each_failure_gets_a_plain_message_and_keeps_git_s_own_words(self):
        cases = (
            ("fatal: unable to access 'https://github.com/a/b.git/': SSL certificate problem: unable to get local issuer certificate", "trust GitHub's security certificate", "issuer certificate"),
            ("fatal: unable to access 'https://github.com/a/b.git/': Could not resolve host: github.com", "could not reach github.com", "resolve host"),
            ("fatal: Authentication failed for 'https://github.com/a/b.git/'", "did not accept the token", "Authentication failed"),
            ("remote: Repository not found.\nfatal: repository 'https://github.com/a/b.git/' not found", "could not find that repository", "not found"),
            ("something odd happened", "git said: something odd happened", ""),
        )
        for text, message, word in cases:
            m, a = G.friendly_git_error(text)
            self.assertIn(message, m, text)
            self.assertIn(word, m + a, text)

    def test_git_keeps_what_it_needs_to_reach_the_internet_but_not_the_account_settings(self):
        old = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))
        os.environ.update({"SYSTEMROOT": r"C:\Windows", "HTTPS_PROXY": "http://proxy:3128", "SSL_CERT_FILE": "/certs/ca.pem", "SECRET_THING": "x", "AWS_SECRET_ACCESS_KEY": "y"})
        env = G.Git(tempfile.mkdtemp(), TOKEN)._env("/tmp/home")
        self.assertEqual((env["SYSTEMROOT"], env["HTTPS_PROXY"], env["SSL_CERT_FILE"]), (r"C:\Windows", "http://proxy:3128", "/certs/ca.pem"))
        self.assertNotIn("SECRET_THING", env)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)
        self.assertEqual((env["HOME"], env["GIT_CONFIG_GLOBAL"], env["GIT_CONFIG_NOSYSTEM"]), ("/tmp/home", os.devnull, "1"))     # still no global or system settings

    def test_on_windows_a_certificate_failure_is_retried_with_the_windows_certificate_store(self):
        calls = []

        class P:
            def __init__(self, code, err):
                self.returncode, self.stdout, self.stderr = code, "", err

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return P(128, "fatal: unable to access: SSL certificate problem") if "http.sslBackend=schannel" not in cmd else P(0, "ok")
        old_run, old_win = G.subprocess.run, G.IS_WINDOWS
        G.subprocess.run, G.IS_WINDOWS = fake_run, True
        self.addCleanup(lambda: (setattr(G.subprocess, "run", old_run), setattr(G, "IS_WINDOWS", old_win)))
        out = G.Git(tempfile.mkdtemp(), TOKEN)._raw(["ls-remote", "https://github.com/a/b.git"])
        self.assertEqual(len(calls), 2)
        self.assertIn("http.sslBackend=schannel", calls[1])
        self.assertEqual(out, "ok")
        calls.clear()
        G.IS_WINDOWS = False                                                                   # elsewhere there is no second try
        with self.assertRaises(G.GitHubError) as e:
            G.Git(tempfile.mkdtemp(), TOKEN)._raw(["ls-remote", "https://github.com/a/b.git"])
        self.assertEqual(len(calls), 1)
        self.assertIn("certificate", e.exception.message)


class ServerTests(Base):
    def setUp(self):
        super().setUp()
        self.calls = []
        self.state.github_http = fake_http(self.calls)
        self.state.github_local = True
        self.state.code_generate = lambda model: vryxcode.ScriptedChat([])

    def test_connect_list_and_disconnect_never_leak_the_token(self):
        st, j = self.owner.call("GET", "/api/apps")
        self.assertFalse(j["connections"]["github"]["connected"])
        self.assertEqual(next(a for a in j["apps"] if a["id"] == "github")["status"], "available")
        self.assertEqual(self.owner.call("POST", "/api/apps/github/connect", {"token": "nope"})[0], 400)
        st, j = self.owner.call("POST", "/api/apps/github/connect", {"token": TOKEN})
        self.assertEqual((st, j["connected"], j["login"]), (200, True, "sam"))
        self.assertNotIn(TOKEN, json.dumps(self.owner.call("GET", "/api/apps")[1]))
        st, j = self.owner.call("POST", "/api/apps/github/disconnect", {})
        self.assertFalse(j["connected"])
        self.assertIn("disconnected", j["log"][0]["what"])

    def test_other_apps_are_still_coming_soon(self):
        self.assertEqual(self.owner.call("POST", "/api/apps/drive/connect", {})[0], 501)

    def test_actions_need_a_connection(self):
        st, j = self.owner.call("POST", "/api/code/git", {"project": "p", "action": "push"})
        self.assertEqual(st, 400)
        self.assertIn("isn't connected", j["message"])

    def test_create_repo_links_the_project_and_asks_for_the_right_things(self):
        self.owner.call("POST", "/api/apps/github/connect", {"token": TOKEN})
        st, j = self.owner.call("POST", "/api/code/git", {"project": "demo", "action": "create_repo", "name": "demo", "private": True})
        self.assertEqual(st, 200, j)
        self.assertIn("sam/demo", j["message"])
        self.assertTrue(any(c[1].endswith("/user/repos") for c in self.calls))
        st, j = self.owner.call("GET", "/api/code/git?project=demo")
        self.assertEqual((j["connected"], j["linked"], j["owner"], j["name"]), (True, True, "sam", "demo"))
        self.assertNotIn(TOKEN, json.dumps(j))

    def test_the_owner_can_list_their_repositories_to_pick_from(self):
        self.assertEqual(self.owner.call("GET", "/api/code/github/repos")[0], 400)            # not connected yet
        self.owner.call("POST", "/api/apps/github/connect", {"token": TOKEN})
        st, j = self.owner.call("GET", "/api/code/github/repos")
        self.assertEqual(st, 200, j)
        self.assertEqual([r["full_name"] for r in j["repos"]], ["sam/app-0", "sam/app-1", "sam/app-2"])
        self.assertEqual((j["repos"][0]["private"], j["repos"][1]["private"], j["repos"][0]["updated"]), (True, False, "2026-10-01"))
        self.assertEqual((j["private_seen"], j["token_kind"]), (2, "classic"))          # the page uses these to say when private repositories are missing
        self.assertNotIn(TOKEN, json.dumps(j))

    def test_importing_a_repository_makes_a_new_project_and_a_failed_copy_leaves_nothing(self):
        self.owner.call("POST", "/api/apps/github/connect", {"token": TOKEN})
        bare = os.path.join(tempfile.mkdtemp(), "app-0.git")
        work = tempfile.mkdtemp()
        sh("init", "-q", "--bare", bare)
        sh("clone", "-q", bare, work + "/w")
        open(work + "/w/README.md", "w").write("hello")
        sh("-C", work + "/w", "add", ".")
        sh("-C", work + "/w", "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-q", "-m", "first")
        sh("-C", work + "/w", "push", "-q", "origin", "HEAD")
        import github_link
        original = github_link.clean_url
        github_link.clean_url = lambda owner, repo: bare                                  # point the "GitHub address" at the local bare repository
        self.addCleanup(lambda: setattr(github_link, "clean_url", original))
        st, j = self.owner.call("POST", "/api/code/git", {"project": "other", "action": "import", "repo": "sam/app-0"})
        self.assertEqual(st, 200, j)
        self.assertEqual(j["project"], "app-0")
        files = self.owner.call("GET", "/api/code/files?project=app-0")[1]["files"]
        self.assertIn("README.md", [f["path"] if isinstance(f, dict) else f for f in files])
        st, j = self.owner.call("POST", "/api/code/git", {"project": "other", "action": "import", "repo": "sam/app-0"})       # again: the next free name
        self.assertEqual((st, j["project"]), (200, "app-0-2"))
        github_link.clean_url = lambda owner, repo: os.path.join(tempfile.gettempdir(), "does-not-exist.git")
        st, j = self.owner.call("POST", "/api/code/git", {"project": "other", "action": "import", "repo": "sam/broken"})
        self.assertEqual(st, 400)
        self.assertNotIn("broken", self.owner.call("GET", "/api/code")[1]["projects"])        # no empty leftover project

    def test_git_actions_are_refused_while_a_session_runs(self):
        self.owner.call("POST", "/api/apps/github/connect", {"token": TOKEN})
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(list(vryxcode.DEMO))
        self.owner.call("POST", "/api/code/start", {"project": "demo", "task": "x", "model": "solstice-2"})
        st, j = self.owner.call("POST", "/api/code/git", {"project": "demo", "action": "pull"})
        self.assertEqual(st, 400)
        self.assertIn("running", j["message"])

    def test_the_model_can_push_a_branch_but_only_after_the_user_allows_it(self):
        self.owner.call("POST", "/api/apps/github/connect", {"token": TOKEN})
        bare = os.path.join(self.tmp.name, "remote.git")
        sh("init", "--bare", "-b", "main", bare)
        ws = self.state.code.project_path("owner", "demo")
        os.makedirs(ws, exist_ok=True)
        g = G.Git(ws, TOKEN, allow_local=True)
        g.run(["init", "-b", "main"])
        g.run(["remote", "add", "origin", bare])
        script = [harness_call for harness_call in (
            vryxcode.harness_call("write_file", path="a.txt", content="hello\n"),
            vryxcode.harness_call("git", args="switch -c feature"),
            vryxcode.harness_call("git", args="add -A"),
            vryxcode.harness_call("git", args="commit -m first"),
            vryxcode.harness_call("github", action="push"),
            vryxcode.harness_call("finish", summary="pushed"))]
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(list(script))
        st, j = self.owner.call("POST", "/api/code/start", {"project": "demo", "task": "x", "model": "solstice-2", "auto_edits": True})
        self.assertEqual(st, 200, j)
        sid = j["id"]
        asked = []
        deadline = time.time() + 30
        while time.time() < deadline:
            r = self.owner.call("GET", f"/api/code/sessions/{sid}")[1]
            if r["pending"]:
                asked.append(r["pending"]["tool"])
                if r["pending"]["tool"] == "github":
                    self.assertIn("push", r["pending"]["preview"])
                self.owner.call("POST", f"/api/code/sessions/{sid}/answer", {"id": r["pending"]["id"], "allow": True, "always": True})
            if r["state"] in ("done", "failed", "stopped"):
                break
            time.sleep(0.05)
        events = [e for e in self.owner.call("GET", f"/api/code/sessions/{sid}")[1]["events"] if e["kind"] in ("result", "end")]
        self.assertEqual(r["state"], "done", r)
        self.assertIn("github", asked)                                  # auto-approve edits does not cover pushing
        self.assertIn("feature", sh("branch", "--list", cwd=bare), [e.get("text") or e.get("summary") for e in events])


if __name__ == "__main__":
    unittest.main()
