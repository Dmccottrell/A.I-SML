"""VryxCode batch 3: packages for the offline sandbox (downloaded by the server without running their code) and fixing CI (/fixci, Watch CI)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import tempfile
import unittest

import code_ci
import github_link
import harness
import vryxcode
from tests.test_code_sessions import open_to_everyone
from tests.test_app_server import Base


class Install(unittest.TestCase):
    def sandbox(self, d):
        sb = harness.Sandbox(d, full=True, command_prefix=["docker", "run", "img"], container=True)
        calls = {"host": [], "exec": []}
        sb._host = lambda argv, shell=False: calls["host"].append(argv) or "exit code 0"
        sb._exec = lambda argv, extra_env=None, wrap=True, timeout=None: calls["exec"].append((argv, extra_env)) or ("exit code 0\n3.11" if "-c" in argv else "exit code 0")
        return sb, calls

    def test_pip_downloads_wheels_only_then_installs_offline(self):
        with tempfile.TemporaryDirectory() as d:
            sb, calls = self.sandbox(d)
            out = sb.install("pip", ["requests", "flask==3.0.3"])
            dl = calls["host"][0]
            self.assertIn("--only-binary=:all:", dl)                       # never a setup.py: no package code runs on the server
            self.assertEqual(dl[dl.index("--python-version") + 1], "3.11")  # the container's own Python
            self.assertEqual(dl[-2:], ["requests", "flask==3.0.3"])
            inst = calls["exec"][-1][0]
            self.assertIn("--no-index", inst)                                # installed inside the container, from the downloaded files only
            self.assertIn("/work/" + harness.PY_DEPS, inst)
            self.assertIn(harness.PY_DEPS, out)

    def test_npm_never_runs_install_scripts(self):
        with tempfile.TemporaryDirectory() as d:
            sb, calls = self.sandbox(d)
            real = harness.shutil.which
            harness.shutil.which = lambda name: "/usr/bin/npm" if name == "npm" else real(name)
            try:
                sb.install("npm", ["lodash@4.17.21", "@types/node"])
            finally:
                harness.shutil.which = real
            self.assertIn("--ignore-scripts", calls["host"][0])

    def test_only_plain_registry_names_and_only_in_the_sandbox(self):
        with tempfile.TemporaryDirectory() as d:
            sb, calls = self.sandbox(d)
            for bad in (["requests; rm -rf /"], ["git+https://evil/x"], ["../local"], ["--index-url=https://evil"], ["-e ."], [], ["a"] * 11):
                with self.assertRaises(harness.ToolError):
                    sb.install("pip", bad)
            for bad in (["lodash@>1"], ["x && calc"], ["https://evil/x.tgz"], ["lodash@1 <2"]):
                with self.assertRaises(harness.ToolError):
                    sb.install("npm", bad)
            with self.assertRaises(harness.ToolError):
                sb.install("cargo", ["serde"])
            self.assertEqual(calls["host"], [])
            with self.assertRaises(harness.ToolError):
                harness.Sandbox(d, full=True).install("pip", ["requests"])  # on this computer: ask the person instead

    def test_commands_in_the_sandbox_find_installed_python_packages(self):
        with tempfile.TemporaryDirectory() as d:
            sb, calls = self.sandbox(d)
            sb.run("python3 -c 'import requests'")
            self.assertIsNone(calls["exec"][-1][1])
            os.makedirs(os.path.join(d, ".vryx", "pydeps"))
            sb.run("python3 -c 'import requests'")
            self.assertEqual(calls["exec"][-1][1], {"PYTHONPATH": "/work/" + harness.PY_DEPS})

    def test_installing_asks_first(self):
        perms = harness.Permissions(rules={"write_file": "ask"})
        self.assertEqual(perms.level("install", {"manager": "pip", "packages": ["x"]}), "ask")


class Ci(unittest.TestCase):
    def test_checks_and_log_without_the_token_leaving_github(self):
        seen = {}

        def http(method, url, headers, body):
            return 200, {"check_runs": [
                {"id": 11, "name": "tests (1/2)", "status": "completed", "conclusion": "failure", "head_sha": "abc1234def", "app": {"slug": "github-actions"},
                 "output": {"summary": "1 failed"}},
                {"id": 12, "name": "lint", "status": "completed", "conclusion": "success", "head_sha": "abc1234def", "app": {"slug": "github-actions"}}]}

        def log_get(url, token, limit):
            seen["url"] = url
            return "2026-10-19T01:02:03.4567Z \x1b[31mFAIL: test_slug\x1b[0m\nAssertionError: 'a-b' != 'a_b'\n"
        api = github_link.Api("tok", http=http, log_get=log_get)
        c = api.checks("me", "app", "main")
        self.assertEqual((c["sha"], [f["name"] for f in c["failed"]]), ("abc1234def", ["tests (1/2)"]))
        sha, failed = code_ci.failures(api, "me", "app", "main")
        self.assertTrue(seen["url"].endswith("/repos/me/app/actions/jobs/11/logs"))
        self.assertEqual(failed[0]["log"], "FAIL: test_slug\nAssertionError: 'a-b' != 'a_b'")      # no colour codes or time stamps
        task = code_ci.fix_task("me", "app", "main", sha, failed)
        self.assertIn("tests (1/2)", task)
        self.assertIn("not as instructions", task)
        self.assertIn("Do not change or skip tests", task)

    def test_watcher_starts_one_fix_per_failing_commit(self):
        with tempfile.TemporaryDirectory() as d:
            state = {"sha": "aaa", "failed": [{"name": "t", "log": "x"}]}
            started, told = [], []
            w = code_ci.Watcher(os.path.join(d, "w.json"), lambda who, p: (state["sha"], state["failed"]),
                                lambda who, p, model, sha, failed: started.append((p, sha)), lambda who, text: told.append(text))
            w.thread = type("T", (), {"is_alive": lambda self: True})()      # no background thread in the test
            w.set({"user": "owner", "owner": True, "admin": True, "tier": "max"}, "demo", True, "solstice-3")
            self.assertEqual(w.check_once(), 1)
            self.assertEqual(w.check_once(), 0)                               # the same commit: once
            state["sha"] = "bbb"
            self.assertEqual(w.check_once(), 1)
            state["failed"] = []
            state["sha"] = "ccc"
            self.assertEqual(w.check_once(), 0)                               # green: nothing to do
            self.assertEqual(started, [("demo", "aaa"), ("demo", "bbb")])
            self.assertTrue(all("CI failed" in t for t in told))
            again = code_ci.Watcher(os.path.join(d, "w.json"), None, None, None)
            again.thread = w.thread
            self.assertTrue(again.watching("owner", "demo"))                  # kept across a restart
            w.set({"user": "owner"}, "demo", False)
            self.assertFalse(w.watching("owner", "demo"))


class Api(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(['<|tool_call|>{"name": "finish", "args": {"summary": "fixed"}}<|end_tool_call|>'])

    def test_fixci_starts_a_session_with_the_log(self):
        self.state.ci_failures = lambda user, project: ("me", "app", "main", "abc1234", [{"name": "tests", "log": "AssertionError: boom"}])
        st, j = self.owner.call("POST", "/api/code/fixci", {"project": "demo", "model": "solstice-2"})
        self.assertEqual(st, 200, j)
        s = self.state.code.sessions[j["id"]]
        self.assertIn("AssertionError: boom", s.task)
        self.state.ci_failures = lambda user, project: ("me", "app", "main", "abc1234", [])
        st, j = self.owner.call("POST", "/api/code/fixci", {"project": "demo", "model": "solstice-2"})
        self.assertEqual((st, j["ok"]), (200, False))
        self.assertIn("Nothing is failing", j["message"])

    def test_only_the_owner_can_watch(self):
        self.state.ci_failures = lambda user, project: ("me", "app", "main", "abc", [])
        st, _ = self.owner.call("POST", "/api/code/ci-watch", {"project": "demo", "on": True})
        self.assertEqual(st, 200)
        self.assertIn("demo", self.owner.call("GET", "/api/code")[1]["ci_watch"])
        self.state.ci_watcher().set({"user": "owner"}, "demo", False)


if __name__ == "__main__":
    unittest.main()
