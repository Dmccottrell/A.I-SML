"""VryxCode's container sandbox, who may use VryxCode, quotas, and the guard on git settings."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import os
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import code_sandbox as CS
import github_link as G
import harness
import vryxcode
from tests.test_app_server import Base, Client
from tests.test_code_sessions import wait_for


class Prefix(unittest.TestCase):
    def test_on_windows_the_container_never_runs_as_root(self):
        # Windows has no user ids to pass on, and the container ran as root (found by the Windows test job). Docker Desktop lets any user
        # write the shared project folder, so it runs as an ordinary user (1000) there too.
        from unittest import mock
        with tempfile.TemporaryDirectory() as d, mock.patch.object(CS.os, "name", "nt"):
            p = CS.docker_prefix("emvryx/code-sandbox:1", d)
            self.assertIn("--user 1000:1000", " ".join(p))
            self.assertIn("--user 1001:1002", " ".join(CS.docker_prefix("emvryx/code-sandbox:1", d, uid=1001, gid=1002)))

    def test_the_container_is_locked_down(self):
        with tempfile.TemporaryDirectory() as d:
            p = CS.docker_prefix("emvryx/code-sandbox:1", d, cpus="1", memory="512m", pids=64, uid=1000, gid=1000)
            self.assertEqual(p[:3], ["docker", "run", "--rm"])
            self.assertEqual(p[-1], "emvryx/code-sandbox:1")
            joined = " ".join(p)
            for must in ("--network none", "--cap-drop ALL", "--security-opt no-new-privileges", "--read-only", "--pids-limit 64",
                         "--memory 512m", "--memory-swap 512m", "--cpus 1", "--user 1000:1000", "-w /work"):
                self.assertIn(must, joined)
            self.assertNotIn("--privileged", joined)
            self.assertNotIn("--net host", joined)
            self.assertEqual(sum(1 for x in p if x == "-v"), 1)                          # exactly one folder is visible
            self.assertIn(f"{os.path.realpath(d)}:/work:rw", p)

    def test_a_stronger_runtime_can_be_chosen(self):
        with tempfile.TemporaryDirectory() as d:
            p = CS.docker_prefix("img", d, runtime="runsc", uid=1, gid=1)
            self.assertEqual(p[p.index("--runtime") + 1], "runsc")
            self.assertNotIn("--runtime", CS.docker_prefix("img", d, uid=1, gid=1))


class Availability(unittest.TestCase):
    def fake(self, code, out=""):
        return lambda *a, **k: subprocess.CompletedProcess(a, code, out, out)

    def test_each_failure_has_its_own_plain_message(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertIn("not installed", CS.available()[1])
        with mock.patch("shutil.which", return_value="/usr/bin/docker"):
            self.assertIn("not running", CS.available(runner=self.fake(1, "Cannot connect to the Docker daemon"))[1])
            self.assertIn("not built", CS.available(runner=self.fake(1, "No such image"))[1])
            self.assertEqual(CS.available(runner=self.fake(0))[0], True)

            def boom(*a, **k):
                raise subprocess.TimeoutExpired("docker", 20)
            self.assertFalse(CS.available(runner=boom)[0])


class InsideTheContainer(unittest.TestCase):
    def test_commands_are_wrapped_and_python_is_the_images_own(self):
        seen = []

        def fake(command, **kw):
            seen.append((command, kw))
            return subprocess.CompletedProcess(command, 0, "ok", "")
        with tempfile.TemporaryDirectory() as d:
            prefix = CS.docker_prefix("img:1", d, uid=1, gid=1)
            with harness.Sandbox(workspace=d, command_prefix=prefix, container=True) as sb, mock.patch("subprocess.run", fake), \
                    mock.patch("shutil.which", return_value="/usr/bin/git"):
                sb.run("python -m unittest")
                sb.git("status")
        cmd, kw = seen[0]
        self.assertEqual(cmd[:len(prefix)], prefix)
        self.assertEqual(cmd[len(prefix):], ["sh", "-c", "python -m unittest"])            # the image's own terminal and python, not this machine's python path
        self.assertNotIn("preexec_fn", kw)                                                  # the limits are Docker's job now
        gcmd = seen[1][0]
        image_at = gcmd.index("img:1")
        self.assertIn("HOME=/tmp", gcmd[:image_at])                                         # environment goes in with -e, before the image
        self.assertTrue(any(x.startswith("GIT_AUTHOR_NAME=") for x in gcmd[:image_at]))
        self.assertEqual(gcmd[image_at + 1], "git")


class Gating(Base):
    data_dir = True

    def setUp(self):
        super().setUp()
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(list(vryxcode.DEMO))
        st, j = self.owner.call("POST", "/api/admin/users", {"user": "pro1", "tier": "pro"})
        self.pro = Client(self.port, j["key"])

    def start(self, c, project="demo", **kw):
        return c.call("POST", "/api/code/start", {"project": project, "task": "x", "model": "solstice-2", "auto_edits": True, **kw})

    def test_the_free_plan_does_not_include_vryxcode(self):
        st, j = self.start(self.sam)
        self.assertEqual(st, 400)
        self.assertIn("plan", j["message"])
        self.assertFalse(self.sam.call("GET", "/api/code")[1]["allowed"])

    def test_other_people_need_the_container_sandbox(self):
        st, j = self.start(self.pro)
        self.assertEqual(st, 400)
        self.assertIn("owner", j["message"])
        self.assertEqual(self.start(self.owner)[0], 200)                                       # the owner always may
        wait_for(lambda: self.owner.call("GET", "/api/code")[1]["running"] is None)

    def test_with_the_container_sandbox_on_they_may(self):
        self.state.code.sandbox = {"mode": "docker", "image": "img"}
        with mock.patch("code_sandbox.available", return_value=(True, "ready")):
            self.assertTrue(self.pro.call("GET", "/api/code")[1]["allowed"])
            st, j = self.start(self.pro)
            self.assertEqual(st, 200, j)
            sess = self.state.code.sessions[j["id"]]
            self.assertEqual(sess.prefix[-1], "img")                                            # its commands will run in the container
            self.assertIn("--network", sess.prefix)
            sess.request_stop()

    def test_it_fails_closed_when_docker_is_not_working(self):
        self.state.code.sandbox = {"mode": "docker", "image": "img"}
        with mock.patch("code_sandbox.available", return_value=(False, "Docker is not installed on this server.")):
            for who in (self.pro, self.owner):                                                  # even the owner: no quiet fallback to the host
                st, j = self.start(who)
                self.assertEqual(st, 400)
                self.assertIn("sandbox isn't available", j["message"])
        self.assertEqual(self.state.code.running("owner"), None)

    def test_the_owners_own_computer_choice_does_not_need_docker(self):
        # vryxcode_open_pc on, "This computer" picked: the owner's own session runs on the PC even when the PC runs everyone else in Docker and
        # Docker is not answering (it is the owner's explicit choice, not a quiet fallback). Others, and the owner with the switch off, still need Docker.
        self.state.code.sandbox = {"mode": "docker", "image": "img"}
        self.state.flags.data["audiences"]["vryxcode_open_pc"] = "owner"
        with mock.patch("code_sandbox.available", return_value=(False, "Docker did not answer.")):
            st, j = self.start(self.pro)
            self.assertEqual(st, 400)
            self.assertIn("sandbox isn't available", j["message"])
            st, j = self.start(self.owner, env="local")
            self.assertEqual(st, 200, j)
            sess = self.state.code.sessions[j["id"]]
            self.assertEqual((sess.prefix, sess.env), (None, "local"))                         # on the PC itself
            wait_for(lambda: self.owner.call("GET", "/api/code")[1]["running"] is None)
            self.assertEqual(self.start(self.owner, env="sandbox")[0], 400)                    # the sandbox picked on purpose still means the sandbox
            self.state.flags.data["audiences"]["vryxcode_open_pc"] = "off"
            self.assertEqual(self.start(self.owner, env="local")[0], 400)


    def test_admins_may_pick_this_computer_with_its_allowed_programs(self):
        # vryxcode_owner_pc: the PC runs everyone in Docker, yet an admin (the owner works from an admin account, not the owner one) picks This
        # computer for their own sessions. It runs in the project folder with the usual short list of programs (not "nothing blocked"); everyone
        # who is not an admin stays in the sandbox, whatever the switch's audience.
        self.state.code.sandbox = {"mode": "docker", "image": "img"}
        self.state.flags.data["audiences"]["vryxcode_owner_pc"] = "everyone"
        st, j = self.owner.call("POST", "/api/admin/users", {"user": "boss", "tier": "pro"})
        self.assertEqual(self.owner.call("POST", "/api/admin/access", {"user": "boss", "admin": True})[0], 200)
        boss = Client(self.port, j["key"])
        envs = lambda c: {e["id"]: e for e in c.call("GET", "/api/code")[1]["environments"]}     # noqa: E731
        self.assertTrue(envs(boss)["local"]["available"])
        self.assertTrue(envs(self.owner)["local"]["available"])
        self.assertFalse(envs(self.pro)["local"]["available"])
        with mock.patch("code_sandbox.available", return_value=(False, "Docker did not answer.")):
            st, j = self.start(boss, env="local")
            self.assertEqual(st, 200, j)
            sess = self.state.code.sessions[j["id"]]
            self.assertEqual((sess.prefix, sess.env), (None, "local"))                         # on the PC itself
            self.assertFalse(getattr(sess.generate, "open_pc", False))                         # with the allowed programs only
            wait_for(lambda: boss.call("GET", "/api/code")[1]["running"] is None)
            st, j = boss.call("POST", "/api/code/run", {"project": "demo", "command": "python -c \"print(6*7)\"", "env": "local"})
            self.assertEqual((st, j.get("env")), (200, "local"), j)
            self.assertIn("42", j["output"])
            st, j = self.start(self.pro, env="local")
            self.assertEqual(st, 400)                                                          # everyone else: the sandbox, and Docker is down
            self.state.flags.data["audiences"]["vryxcode_owner_pc"] = "off"
            self.assertEqual(self.start(boss, env="local")[0], 400)
            self.assertFalse(envs(boss)["local"]["available"])


class Quota(Base):
    data_dir = True

    def setUp(self):
        super().setUp()
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(list(vryxcode.DEMO))

    def start(self, project="demo"):
        return self.owner.call("POST", "/api/code/start", {"project": project, "task": "x", "model": "solstice-2", "auto_edits": True})

    def finish(self, sid):
        return wait_for(lambda: (lambda r: r if r["state"] in ("done", "limited", "failed", "stopped") else None)(self.owner.call("GET", f"/api/code/sessions/{sid}")[1]))

    def test_too_many_projects(self):
        self.state.code.quotas.q["code_max_projects"] = 2
        for name in ("a", "b"):
            sid = self.start(name)[1]["id"]
            self.finish(sid)
        st, j = self.start("c")
        self.assertEqual(st, 400)
        self.assertIn("2 projects", j["message"])
        self.assertEqual(self.start("a")[0], 200)                                               # an existing one is fine
        self.finish(self.state.code.by_user["owner"])

    def test_sessions_per_day(self):
        self.state.code.quotas.q["code_sessions_per_day"] = 1
        self.finish(self.start()[1]["id"])
        st, j = self.start()
        self.assertEqual(st, 400)
        self.assertIn("sessions for today", j["message"])

    def test_a_project_over_its_size_cannot_start_or_take_an_import(self):
        self.state.code.quotas.q["code_project_mb"] = 1
        import base64
        big = base64.b64encode(b"x" * (1024 * 1024 + 10)).decode()
        st, j = self.owner.call("POST", "/api/code/import", {"project": "big", "files": [{"path": "f.bin", "b64": big}]})
        self.assertEqual(st, 400)
        self.assertIn("size limit", j["message"])
        small = base64.b64encode(b"x" * 1000).decode()
        self.assertEqual(self.owner.call("POST", "/api/code/import", {"project": "ok", "files": [{"path": "f.bin", "b64": small}]})[0], 200)

    def test_a_session_that_runs_too_long_is_stopped_and_keeps_its_files(self):
        self.state.code.quotas.q["code_session_minutes"] = 0
        sid = self.start()[1]["id"]
        r = self.finish(sid)
        self.assertEqual(r["state"], "limited")
        self.assertIn("longest time", r["events"][-1]["summary"])
        self.assertIn("slug.py", self.owner.call("GET", "/api/code/files?project=demo")[1]["files"])    # the first step's work stays

    def test_a_session_that_makes_its_project_too_big_is_stopped(self):
        self.state.code.quotas.q["code_project_mb"] = 0
        sid = self.start()[1]["id"]
        r = self.finish(sid)
        self.assertEqual(r["state"], "limited")


class GitSettingsGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = self.tmp.name
        subprocess.run(["git", "init", "-q", "-b", "main", self.ws], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, key, value="x"):
        subprocess.run(["git", "config", "--local", key, value], cwd=self.ws, check=True)

    def test_settings_that_can_run_a_program_or_redirect_the_token_are_refused(self):
        for key in ("core.fsmonitor", "filter.evil.clean", "http.proxy", "url.https://evil/.insteadOf", "include.path", "alias.st",
                    "core.sshCommand", "credential.helper", "remote.origin.pushurl", "diff.external", "core.pager", "core.hooksPath"):
            with self.subTest(key=key):
                subprocess.run(["git", "init", "-q", "-b", "main", self.ws], check=True)
                self.add(key)
                with self.assertRaises(G.GitHubError) as c:
                    G.Git(self.ws, "tok").run(["status"])
                self.assertIn("not allowed", c.exception.message)
                subprocess.run(["git", "config", "--local", "--unset-all", key], cwd=self.ws)

    def test_plain_settings_pass_and_the_status_reports_the_problem_instead_of_crashing(self):
        self.add("remote.origin.url", "https://github.com/sam/app.git")
        self.add("user.name", "Sam")
        st = G.Git(self.ws, "tok").status()
        self.assertTrue(st["linked"])
        self.add("filter.x.clean", "evil")
        with self.assertRaises(G.GitHubError):
            G.Git(self.ws, "tok").status()


class Image(unittest.TestCase):
    def test_the_dockerfile_is_there_and_is_small_and_plain(self):
        text = open(os.path.join(emvryx_paths.ROOT, "docker", "code-sandbox", "Dockerfile")).read()
        self.assertIn("FROM python:3.12-slim", text)
        self.assertIn("git", text)
        self.assertNotIn("sudo", text)


if __name__ == "__main__":
    unittest.main()
