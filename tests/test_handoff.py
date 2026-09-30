"""Tests for handoff.py's cloud-side commands, run in a real shell. Run:  python -m unittest tests.test_handoff -v"""
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import handoff as H


@unittest.skipUnless(shutil.which("bash"), "needs bash (the cloud machine's shell)")
class CloudPaths(unittest.TestCase):
    """The cloud commands use ~/A.I-SML paths. Run them through bash with HOME set to a temp folder."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.local = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home)
        self.addCleanup(shutil.rmtree, self.local)
        env = dict(os.environ, HOME=self.home)

        def ssh_out(host, port, command):
            r = subprocess.run(["bash", "-c", command], capture_output=True, text=True, env=env)
            if r.returncode:
                raise SystemExit(r.stderr)
            return r.stdout.strip()

        def real(remote):                  # what scp does with ~/ (it means the home folder)
            return os.path.join(self.home, remote[2:]) if remote.startswith("~/") else remote

        self.saved = (H.ssh_out, H.scp_up, H.scp_down)
        H.ssh_out = ssh_out
        H.scp_up = lambda host, port, local, remote: shutil.copyfile(local, real(remote))
        H.scp_down = lambda host, port, remote, local: shutil.copyfile(real(remote), local)
        self.addCleanup(self.restore)

    def restore(self):
        H.ssh_out, H.scp_up, H.scp_down = self.saved

    def args(self, **kw):
        a = dict(host="root@x", port=22, repo="~/A.I-SML", start=False, with_tokenizer=False, force=False)
        a.update(kw)
        return types.SimpleNamespace(**a)

    def test_still_training_means_a_gpu_program_not_just_a_window(self):
        bin_dir = os.path.join(self.home, "bin")
        os.makedirs(bin_dir)
        fake = os.path.join(bin_dir, "nvidia-smi")
        env = dict(os.environ, HOME=self.home, PATH=bin_dir + os.pathsep + os.environ["PATH"])
        for pids, want in (("", "no"), ("1234\n", "yes")):
            with open(fake, "w") as f:
                f.write(f"#!/bin/sh\nprintf '{pids}'\n")
            os.chmod(fake, 0o755)
            r = subprocess.run(["bash", "-c", H.STILL_TRAINING], capture_output=True, text=True, env=env)
            self.assertEqual(r.stdout.strip(), want, pids)

    def test_quoting(self):
        self.assertEqual(H.rq("~/A.I-SML/a b"), "\"$HOME\"'/A.I-SML/a b'")
        self.assertEqual(H.rq("/root/x"), "/root/x")

    def test_up_then_down(self):
        V = types.SimpleNamespace(ckpt_dir=os.path.join(self.local, "ck"), data_dir=os.path.join(self.local, "d"))
        os.makedirs(V.ckpt_dir)
        with open(os.path.join(V.ckpt_dir, "latest.pt"), "wb") as f:
            f.write(b"x" * 1000)
        # the cloud keeps the same relative layout under ~/A.I-SML
        V_remote = types.SimpleNamespace(ckpt_dir="checkpoints/dev/v3", data_dir="data/v3")
        # up() builds remote paths from V.ckpt_dir, so give it the relative one and point local reads at ours
        cwd = os.getcwd()
        os.chdir(self.local)
        try:
            os.makedirs("checkpoints/dev/v3")
            shutil.copyfile(os.path.join(V.ckpt_dir, "latest.pt"), "checkpoints/dev/v3/latest.pt")
            H.up(self.args(), V_remote)
            cloud = os.path.join(self.home, "A.I-SML", "checkpoints", "dev", "v3")
            self.assertEqual(os.path.getsize(os.path.join(cloud, "latest.pt")), 1000)
            self.assertFalse(os.path.exists(os.path.join(cloud, "latest.pt.part")))
            self.assertFalse(os.path.exists(os.path.join(self.home, "~")))
            self.assertEqual(H.remote_stat("h", 22, "~/A.I-SML/checkpoints/dev/v3/latest.pt")[1], 1000)
            # the cloud trains: its copy becomes newer, so sending the old one again must be refused
            os.utime(os.path.join(cloud, "latest.pt"), (2e9, 2e9))
            with self.assertRaises(SystemExit) as e:
                H.up(self.args(), V_remote)
            self.assertIn("NEWER", str(e.exception))
            os.remove("checkpoints/dev/v3/latest.pt")
            H.down(self.args(), V_remote)
            self.assertEqual(os.path.getsize("checkpoints/dev/v3/latest.pt"), 1000)
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
