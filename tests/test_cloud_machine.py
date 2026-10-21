"""VryxCode's cloud machine: the SSH runner (cloud_run.py), its safety checks, and the settings. SSH itself is replaced by a stand-in `ssh` program that runs the remote command on this computer in a throwaway home folder."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import io
import shutil
import stat
import tarfile
import tempfile
import unittest
from unittest import mock

import cloud_run
import code_sessions as CS
import harness
from tests.test_app_server import Base

FAKE_SSH = r"""#!/usr/bin/env bash
# A stand-in for ssh: skips the options, then runs the remote command with bash in a fake HOME (the "remote machine").
while [ $# -gt 0 ]; do
  case "$1" in
    -i|-p|-o) shift 2 ;;
    *@*) shift; break ;;
    *) shift ;;
  esac
done
export HOME="@HOME@"
exec bash -c "$*"
"""


def tar_bytes(members):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for name, body, kind in members:
            info = tarfile.TarInfo(name)
            if kind == "file":
                info.size = len(body)
                t.addfile(info, io.BytesIO(body))
            elif kind == "link":
                info.type, info.linkname = tarfile.SYMTYPE, body
                t.addfile(info)
            elif kind == "dir":
                info.type = tarfile.DIRTYPE
                t.addfile(info)
    return buf.getvalue()


class Unpack(unittest.TestCase):
    def test_only_safe_regular_files_are_copied_back(self):
        with tempfile.TemporaryDirectory() as d:
            root = os.path.join(d, "proj")
            os.makedirs(root)
            outside = os.path.join(d, "evil.txt")
            data = tar_bytes([("good.txt", b"ok", "file"), ("sub/deep.txt", b"deep", "file"), ("../evil.txt", b"x", "file"), ("/tmp/abs_evil.txt", b"x", "file"),
                              ("a/../../evil.txt", b"x", "file"), ("link", "/etc/passwd", "link"), ("adir", b"", "dir"), (".git/config", b"x", "file"), ("node_modules/x.js", b"x", "file"),
                              (".emvryx_out", b"hello\n", "file"), (".emvryx_rc", b"3\n", "file")])
            out, rc = cloud_run.unpack_into(data, root)
            self.assertEqual((out, rc), ("hello\n", 3))
            self.assertEqual(open(os.path.join(root, "good.txt")).read(), "ok")
            self.assertEqual(open(os.path.join(root, "sub", "deep.txt")).read(), "deep")
            for bad in (outside, "/tmp/abs_evil.txt", os.path.join(root, "link"), os.path.join(root, ".git", "config"), os.path.join(root, "node_modules", "x.js"), os.path.join(root, ".emvryx_out")):
                self.assertFalse(os.path.lexists(bad), bad)

    def test_a_file_cannot_be_written_through_a_link_that_already_exists_in_the_project(self):
        with tempfile.TemporaryDirectory() as d:
            root, target = os.path.join(d, "proj"), os.path.join(d, "target")
            os.makedirs(root)
            os.makedirs(target)
            os.symlink(target, os.path.join(root, "escape"))
            cloud_run.unpack_into(tar_bytes([("escape/pwned.txt", b"x", "file")]), root)
            self.assertFalse(os.path.exists(os.path.join(target, "pwned.txt")))

    def test_pack_skips_heavy_and_private_folders(self):
        with tempfile.TemporaryDirectory() as d:
            for p in ("a.py", ".git/HEAD", "node_modules/x/y.js", "__pycache__/a.pyc", "src/b.py"):
                os.makedirs(os.path.dirname(os.path.join(d, p)), exist_ok=True)
                open(os.path.join(d, p), "w").write("x")
            names = sorted(tarfile.open(fileobj=io.BytesIO(cloud_run.pack(d))).getnames())
            self.assertEqual(names, ["a.py", "src/b.py"])


@unittest.skipUnless(shutil.which("bash") and shutil.which("timeout") and shutil.which("python3"), "needs bash, timeout and python3")
class Runner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bin, self.home, self.proj = (os.path.join(self.tmp.name, n) for n in ("bin", "home", "proj"))
        for d in (self.bin, self.home, self.proj):
            os.makedirs(d)
        path = os.path.join(self.bin, "ssh")
        with open(path, "w") as f:
            f.write(FAKE_SSH.replace("@HOME@", self.home))                 # (the command runner passes only a short list of environment variables, so the home is written into the stand-in)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        env = mock.patch.dict(os.environ, {"PATH": self.bin + os.pathsep + os.environ["PATH"]})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.tmp.cleanup)
        self.mgr = CS.CodeManager(None)
        self.mgr.cloud = {"host": "gpu.example", "port": 22, "user": "root", "key": os.path.join(self.tmp.name, "key"), "known_hosts": os.path.join(self.tmp.name, "kh"), "for_others": False}
        open(self.mgr.cloud["key"], "w").write("k")
        self.sb = harness.Sandbox(workspace=self.proj, command_prefix=self.mgr.cloud_prefix("sam", "demo"), remote=True, command_timeout=60)
        self.addCleanup(self.sb.close)

    def test_a_command_runs_on_the_remote_side_and_new_files_come_back(self):
        open(os.path.join(self.proj, "hello.py"), "w").write("open('made.txt', 'w').write('from remote'); print('printed there')\n")
        os.makedirs(os.path.join(self.proj, ".git"))
        open(os.path.join(self.proj, ".git", "HEAD"), "w").write("ref")
        out = self.sb.run("python hello.py")
        self.assertIn("exit code 0", out)
        self.assertIn("printed there", out)
        self.assertEqual(open(os.path.join(self.proj, "made.txt")).read(), "from remote")
        self.assertTrue(os.path.exists(os.path.join(self.home, "emvryx-work", "sam-demo", "hello.py")))      # it ran in its own folder on the "remote"
        self.assertFalse(os.path.exists(os.path.join(self.home, "emvryx-work", "sam-demo", ".git")))         # .git never leaves this computer

    def test_the_exit_code_and_errors_are_passed_on(self):
        open(os.path.join(self.proj, "bad.py"), "w").write("raise SystemExit(7)\n")
        self.assertIn("exit code 7", self.sb.run("python bad.py"))
        open(os.path.join(self.proj, "boom.py"), "w").write("1/0\n")
        out = self.sb.run("python boom.py")
        self.assertIn("exit code 1", out)
        self.assertIn("ZeroDivisionError", out)

    def test_git_stays_on_this_computer(self):
        if not shutil.which("git"):
            self.skipTest("no git")
        self.sb.git("init")
        self.assertTrue(os.path.isdir(os.path.join(self.proj, ".git")))                                     # made here, not on the remote

    def test_an_unreachable_machine_says_so(self):
        os.remove(os.path.join(self.bin, "ssh"))
        open(os.path.join(self.bin, "ssh"), "w").write("#!/usr/bin/env bash\necho 'ssh: connect to host gpu.example port 22: Connection timed out' >&2\nexit 255\n")
        os.chmod(os.path.join(self.bin, "ssh"), 0o755)
        out = self.sb.run("python -c 1")
        self.assertIn("exit code 255", out)
        self.assertIn("Connection timed out", out)


class Manager(unittest.TestCase):
    def test_who_may_use_it_and_why_not(self):
        m = CS.CodeManager(None)
        self.assertFalse(m.cloud_ready(True)[0])
        self.assertIn("Admin > Cloud machine", m.cloud_ready(True)[1])
        with tempfile.TemporaryDirectory() as d, mock.patch("shutil.which", return_value="/usr/bin/ssh"):
            key = os.path.join(d, "key")
            m.cloud = {"host": "gpu.example", "port": 22, "user": "root", "key": key, "known_hosts": os.path.join(d, "kh"), "for_others": False}
            self.assertIn("No SSH key", m.cloud_ready(True)[1])
            open(key, "w").write("k")
            self.assertEqual(m.cloud_ready(True), (True, "ready"))
            self.assertEqual(m.cloud_ready(False), (False, "Only the owner can use the cloud machine."))
            m.cloud["for_others"] = True
            self.assertTrue(m.cloud_ready(False)[0])
            env = {e["id"]: e for e in m.environments(True)}["cloud"]
            self.assertTrue(env["available"])
            self.assertIn("gpu.example", env["note"])
            self.assertEqual(m.resolve_env("cloud", False), "cloud")
            m.cloud["for_others"] = False
            with self.assertRaises(CS.CodeError):
                m.resolve_env("cloud", False)

    def test_the_prefix_ends_with_a_separator_and_names_a_safe_work_folder(self):
        m = CS.CodeManager(None)
        m.cloud = {"host": "h", "port": 2222, "user": "root", "key": "/k", "known_hosts": "/kh"}
        p = m.cloud_prefix("sam", "my proj/../x")
        self.assertEqual(p[-1], "--")
        self.assertEqual(p[p.index("--port") + 1], "2222")
        self.assertRegex(p[p.index("--workdir") + 1], r"^emvryx-work/[A-Za-z0-9_-]+$")


class Server(Base):
    data_dir = True

    def test_settings_validate_and_only_the_owner_can_change_them(self):
        self.assertEqual(self.sam.call("GET", "/api/admin/cloud")[0], 404)
        self.assertEqual(self.sam.call("POST", "/api/admin/cloud", {"host": "x.example"})[0], 403)
        for bad in ({"host": "bad host; rm -rf /"}, {"host": "ok.example", "user": "Root!"}, {"host": "ok.example", "port": 99999}):
            self.assertEqual(self.owner.call("POST", "/api/admin/cloud", bad)[0], 400, bad)
        s, j = self.owner.call("POST", "/api/admin/cloud", {"host": "ssh5.vast.ai", "port": 14022, "user": "root"})
        self.assertEqual((s, j["host"], j["port"]), (200, "ssh5.vast.ai", 14022))
        self.assertEqual(self.state.code.cloud["host"], "ssh5.vast.ai")
        import app_server as A
        again = A.AppState(self.tmp.name, manifest=self.manifest, ram_gb=8, pace=False)
        self.assertEqual(again.code.cloud["port"], 14022)                                                     # kept across a restart

    @unittest.skipUnless(shutil.which("ssh-keygen"), "needs ssh-keygen")
    def test_it_makes_a_key_and_shows_only_the_public_half(self):
        s, j = self.owner.call("POST", "/api/admin/cloud/keygen", {})
        self.assertEqual(s, 200, j)
        self.assertTrue(j["key_made"])
        self.assertTrue(j["public_key"].startswith("ssh-ed25519 "))
        self.assertNotIn("PRIVATE", str(j))
        private = os.path.join(self.tmp.name, "cloud_key")
        self.assertEqual(stat.S_IMODE(os.stat(private).st_mode), 0o600)
        pub = j["public_key"]
        self.assertEqual(self.owner.call("POST", "/api/admin/cloud/keygen", {})[1]["public_key"], pub)         # asking again does not replace it

    def stand_in_tools(self, home):
        """A stand-in ssh-keygen (writes a fake key pair) and ssh (runs the remote command here), put first on PATH."""
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        keygen = '#!/usr/bin/env bash\nwhile [ $# -gt 0 ]; do [ "$1" = "-f" ] && F="$2"; shift; done\necho "-----BEGIN OPENSSH PRIVATE KEY-----" > "$F"\necho "ssh-ed25519 AAAAFAKEKEY emvryx-cloud" > "$F.pub"\n'
        for name, body in (("ssh-keygen", keygen), ("ssh", FAKE_SSH.replace("@HOME@", home))):
            with open(os.path.join(d, name), "w") as f:
                f.write(body)
            os.chmod(os.path.join(d, name), 0o755)
        env = mock.patch.dict(os.environ, {"PATH": d + os.pathsep + os.environ["PATH"]})
        env.start()
        self.addCleanup(env.stop)

    def test_key_making_and_the_connection_test_with_stand_in_tools(self):
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        self.stand_in_tools(home)
        s, j = self.owner.call("POST", "/api/admin/cloud/keygen", {})
        self.assertEqual((s, j["key_made"], j["public_key"]), (200, True, "ssh-ed25519 AAAAFAKEKEY emvryx-cloud"))
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.tmp.name, "cloud_key")).st_mode), 0o600)
        self.assertEqual(self.owner.call("POST", "/api/admin/cloud/test", {})[0], 400)                         # no host yet
        self.owner.call("POST", "/api/admin/cloud", {"host": "gpu.example", "port": 22, "user": "root"})
        s, j = self.owner.call("POST", "/api/admin/cloud/test", {})
        self.assertEqual(s, 200, j)
        self.assertIn("emvryx-ok", j["text"])
        cloud = {e["id"]: e for e in self.owner.call("GET", "/api/code")[1]["environments"]}["cloud"]
        self.assertTrue(cloud["available"])
        self.assertFalse({e["id"]: e for e in self.sam.call("GET", "/api/code")[1]["environments"]}["cloud"]["available"])   # others: not unless the owner allows it
        self.owner.call("POST", "/api/admin/cloud", {"host": "gpu.example", "for_others": True})
        self.assertTrue({e["id"]: e for e in self.sam.call("GET", "/api/code")[1]["environments"]}["cloud"]["available"])

    def test_the_environment_list_tells_each_person_the_truth(self):
        s, j = self.owner.call("GET", "/api/code")
        cloud = {e["id"]: e for e in j["environments"]}["cloud"]
        self.assertFalse(cloud["available"])
        self.assertIn("Admin > Cloud machine", cloud["note"])


if __name__ == "__main__":
    unittest.main()
