"""Things found in the security review: spoofable addresses, link previews, timing, branch names, export size, health and alerts."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import io
import json
import os
import subprocess
import tempfile
import time
import unittest
import zipfile
from unittest import mock

import github_link as G
import mailer
from tests.test_app_server import Base, Client
from tests.test_code_sessions import open_to_everyone, wait_for


class Addresses(Base):
    def test_a_caller_cannot_dodge_the_lockout_by_writing_their_own_forwarded_for(self):
        limit = self.state.security["login_fail_limit"]
        for i in range(limit):                                              # the proxy appends the real address LAST; the caller makes up the first
            Client(self.port, "wrong").call("GET", "/api/state", headers={"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.50"})
        st, _ = Client(self.port, self.sam_key).call("GET", "/api/state", headers={"X-Forwarded-For": "10.9.9.9, 203.0.113.50"})
        self.assertEqual(st, 429)                                           # same real address: still locked out
        st, _ = Client(self.port, self.sam_key).call("GET", "/api/state", headers={"X-Forwarded-For": "10.9.9.9, 203.0.113.51"})
        self.assertEqual(st, 200)


class EmailTiming(Base):
    def test_the_sign_in_email_is_sent_in_the_background(self):
        mail = mailer.FakeMailer()
        slow = mock.Mock(wraps=mail)

        def slow_send(to, subject, body):
            time.sleep(0.4)
            mail.send(to, subject, body)
        slow.send = slow_send
        self.state.mailer = slow
        self.state.set_email("sam", "sam@example.com")
        t0 = time.time()
        st, j = Client(self.port).call("POST", "/api/login/email/start", {"email": "sam@example.com"})
        known = time.time() - t0
        t0 = time.time()
        Client(self.port).call("POST", "/api/login/email/start", {"email": "nobody@example.com"})
        unknown = time.time() - t0
        self.assertEqual(st, 200)
        self.assertLess(known, 0.3)                                         # did not wait for the slow mail server
        self.assertLess(abs(known - unknown), 0.3)                          # a known address looks the same as an unknown one
        wait_for(lambda: mail.sent)
        self.assertEqual(mail.sent[0]["to"], "sam@example.com")


class Branches(unittest.TestCase):
    def test_a_branch_name_that_looks_like_an_option_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", "-b", "main", d], check=True)
            subprocess.run(["git", "config", "remote.origin.url", "https://github.com/sam/app.git"], cwd=d, check=True)
            open(os.path.join(d, ".git", "HEAD"), "w").write("ref: refs/heads/--upload-pack=touch_pwned\n")   # something written by a container
            g = G.Git(d, "tok")
            for action in (g.pull, lambda: g.push(allow_protected=True)):
                with self.assertRaises(G.GitHubError):
                    action()
            self.assertFalse(os.path.exists(os.path.join(d, "touch_pwned")))


class Export(Base):
    data_dir = True

    def test_big_and_odd_files_are_left_out_with_a_note_not_loaded_into_memory(self):
        import data_tools
        open_to_everyone(self.state)
        ws = self.state.code.project_path("sam", "app")
        os.makedirs(ws)
        open(os.path.join(ws, "small.txt"), "w").write("hi")
        with open(os.path.join(ws, "big.bin"), "wb") as f:
            f.write(b"x" * 1000)
        os.symlink("/etc/passwd", os.path.join(ws, "link"))
        with mock.patch.object(data_tools, "EXPORT_FILE_LIMIT", 500):
            z = zipfile.ZipFile(io.BytesIO(self.sam.call("GET", "/api/export", raw=True)[2]))
        names = set(z.namelist())
        self.assertIn("projects/app/small.txt", names)
        self.assertNotIn("projects/app/big.bin", names)
        self.assertNotIn("projects/app/link", names)
        note = z.read("projects/_NOT_INCLUDED.txt").decode()
        self.assertIn("big.bin", note)
        self.assertNotIn("root:", b"".join(z.read(n) for n in names).decode("latin-1"))        # the link's target was never read

    def test_files_are_exported_byte_for_byte(self):
        ws = self.state.code.project_path("sam", "app")
        os.makedirs(ws)
        data = bytes(range(256))
        open(os.path.join(ws, "bytes.bin"), "wb").write(data)
        z = zipfile.ZipFile(io.BytesIO(self.sam.call("GET", "/api/export", raw=True)[2]))
        self.assertEqual(z.read("projects/app/bytes.bin"), data)


class HealthAndAlerts(Base):
    data_dir = True

    def test_only_the_owner_sees_health_and_it_has_the_numbers(self):
        self.assertEqual(self.sam.call("GET", "/api/admin/health")[0], 404)
        Client(self.port, "wrong").call("GET", "/api/state")
        st, j = self.owner.call("GET", "/api/admin/health")
        self.assertEqual(st, 200)
        for k in ("uptime_minutes", "server_errors", "devices_signed_in", "last_hour", "encryption", "email_sign_in", "code_sandbox", "alerts_on"):
            self.assertIn(k, j)
        self.assertGreaterEqual(j["last_hour"]["failed_tries"], 1)
        self.assertFalse(j["alerts_on"])

    def test_alerts_are_off_without_a_topic_and_capped_with_one(self):
        with mock.patch("notify.send") as send:
            self.state.alert("x", "hello")
            send.assert_not_called()
            self.state.security["alert_ntfy_topic"] = "my-topic"
            for _ in range(10):
                self.state.alert("x", "hello", per_hour=3)
            wait_for(lambda: send.call_count >= 3)
            time.sleep(0.1)
            self.assertEqual(send.call_count, 3)                              # a flood cannot flood the phone
            self.assertEqual(send.call_args[0][0], "my-topic")

    def test_a_lockout_and_an_owner_sign_in_alert_the_owner_once(self):
        self.state.security["alert_ntfy_topic"] = "my-topic"
        sent = []
        with mock.patch("notify.send", lambda topic, text, title="": sent.append(text)):
            for _ in range(self.state.security["login_fail_limit"] + 3):         # an attacker from another address
                Client(self.port, "wrong").call("GET", "/api/state", headers={"CF-Connecting-IP": "198.51.100.9"})
            token = self.owner.call("POST", "/api/admin/pairing", {"user": "owner"})[1]["pair"]
            Client(self.port).call("POST", "/pair/" + token, raw=True, headers={"CF-Connecting-IP": "198.51.100.77"})
            wait_for(lambda: len(sent) >= 2)
        texts = " | ".join(sent)
        self.assertEqual(sum(1 for t in sent if "locked out" in t), 1)       # told once, not on every refused try
        self.assertIn("the owner signed in", texts)
        self.assertNotIn(self.sam_key, texts)


if __name__ == "__main__":
    unittest.main()
