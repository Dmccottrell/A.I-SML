"""vryxcode_secrets: secrets per project reach the programs VryxCode runs, never the model, and never come back to the page."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import subprocess
import tempfile
import unittest
from unittest import mock

import code_sandbox as CS
import code_secrets
import harness
import secret_box
from tests.test_app_server import Base

VALUE = "sk-live-9f8e7d6c5b4a"


class Store(unittest.TestCase):
    def test_kept_encrypted_and_only_names_listed(self):
        with tempfile.TemporaryDirectory() as d:
            s = code_secrets.ProjectSecrets(d, secret_box.SecretBox(d))
            s.set("sam", "demo", "API_KEY", VALUE)
            self.assertEqual((s.names("sam", "demo"), s.names("sam", "other"), s.names("kim", "demo")), (["API_KEY"], [], []))
            with open(os.path.join(d, "code_secrets", "sam.json")) as f:
                raw = f.read()
            self.assertNotIn(VALUE, raw)
            self.assertEqual(oct(os.stat(os.path.join(d, "code_secrets", "sam.json")).st_mode & 0o777), "0o600")
            self.assertEqual(code_secrets.ProjectSecrets(d, secret_box.SecretBox(d)).values("sam", "demo"), {"API_KEY": VALUE})   # survives a restart
            s.delete("sam", "demo", "API_KEY")
            self.assertEqual(s.values("sam", "demo"), {})

    def test_bad_names_and_values_are_refused(self):
        s = code_secrets.ProjectSecrets(None, secret_box.SecretBox(None))
        for name, value in (("api key", "x"), ("lower", "x"), ("PATH", "x"), ("LD_PRELOAD", "x"), ("OK", ""), ("OK", "x" * 5000)):
            with self.assertRaises(code_secrets.SecretsError, msg=name):
                s.set("sam", "demo", name, value)


class Sandbox(unittest.TestCase):
    def test_a_program_gets_the_value_and_the_model_sees_only_the_name(self):
        with tempfile.TemporaryDirectory() as d, harness.Sandbox(d) as sb:
            sb.secrets = {"API_KEY": VALUE}
            with open(os.path.join(d, "show.py"), "w") as f:
                f.write("import os\nprint('key is', os.environ['API_KEY'], len(os.environ['API_KEY']))\n")
            out, done = sb.call("run", {"command": "python show.py"})
            self.assertIn(f"key is [secret API_KEY] {len(VALUE)}", out)
            self.assertNotIn(VALUE, out)
            with open(os.path.join(d, "leak.txt"), "w") as f:
                f.write("token=" + VALUE)
            self.assertNotIn(VALUE, sb.call("read_file", {"path": "leak.txt"})[0])

    def test_inside_the_container_the_values_go_in_with_e(self):
        seen = []

        def fake(command, **kw):
            seen.append(command)
            return subprocess.CompletedProcess(command, 0, "ok", "")
        with tempfile.TemporaryDirectory() as d:
            prefix = CS.docker_prefix("img:1", d, uid=1, gid=1)
            with harness.Sandbox(workspace=d, command_prefix=prefix, container=True) as sb, mock.patch("subprocess.run", fake):
                sb.secrets = {"API_KEY": VALUE}
                sb.run("python -m unittest")
        at = seen[0].index("img:1")
        self.assertIn("API_KEY=" + VALUE, seen[0][:at])

    def test_the_agent_is_told_the_names_not_the_values(self):
        seen = []

        def generate(messages):
            seen.append(json.dumps(messages))
            return '{"tool": "finish", "args": {"summary": "done"}}'
        generate.secrets = {"API_KEY": VALUE}
        with tempfile.TemporaryDirectory() as d, harness.Sandbox(d) as sb:
            harness.run_agent("use the weather API", generate, sb, max_turns=2)
            self.assertEqual(sb.secrets, {"API_KEY": VALUE})
        self.assertIn("API_KEY", seen[0])
        self.assertNotIn(VALUE, seen[0])


class Server(Base):
    def test_the_page_adds_and_removes_and_never_reads_a_value(self):
        self.state.flags.data["audiences"]["vryxcode_secrets"] = "admins"
        s, j = self.owner.call("POST", "/api/code/secrets", {"project": "demo", "name": "API_KEY", "value": VALUE})
        self.assertEqual((s, j), (200, {"names": ["API_KEY"]}))
        s, j = self.owner.call("GET", "/api/code/secrets?project=demo")
        self.assertEqual((s, j), (200, {"names": ["API_KEY"]}))
        self.assertEqual(self.owner.call("POST", "/api/code/secrets", {"project": "demo", "name": "bad name", "value": "x"})[0], 400)
        self.assertEqual(self.owner.call("POST", "/api/code/secrets", {"project": "../x", "name": "A", "value": "x"})[0], 400)
        s, j = self.owner.call("POST", "/api/code/secrets", {"project": "demo", "name": "API_KEY", "delete": True})
        self.assertEqual((s, j), (200, {"names": []}))

    def test_switched_off_it_is_not_there(self):
        self.assertEqual(self.owner.call("POST", "/api/code/secrets", {"project": "demo", "name": "API_KEY", "value": VALUE})[0], 404)


if __name__ == "__main__":
    unittest.main()
