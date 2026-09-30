"""Tests for hub_backup.py with a stand-in for Hugging Face (no internet). Run:  python -m unittest tests.test_hub_backup -v"""
import json
import os
import shutil
import sys
import tempfile
import unittest

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hub_backup as H


class FakeHub:
    """Behaves like the parts of huggingface_hub.HfApi we use, storing files in a folder."""

    def __init__(self, root, can_write=True):
        self.root, self.can_write, self.commits, self.squashes = root, can_write, 0, 0

    def whoami(self):
        return {"name": "me"}

    def create_repo(self, repo, private, exist_ok, repo_type):
        if not self.can_write:
            raise PermissionError("403 read-only token")
        assert private

    def create_commit(self, repo_id, repo_type, operations, commit_message):
        if not self.can_write:
            raise PermissionError("403")
        for op in operations:
            dest = os.path.join(self.root, repo_id, op.path_in_repo)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            data = op.path_or_fileobj
            if isinstance(data, bytes):
                open(dest, "wb").write(data)
            else:
                shutil.copyfile(data, dest)
        self.commits += 1

    def super_squash_history(self, repo_id, repo_type):
        self.squashes += 1

    def hf_hub_download(self, repo_id, filename, local_dir):
        src = os.path.join(self.root, repo_id, filename)
        if not os.path.exists(src):
            raise FileNotFoundError(filename)
        dest = os.path.join(local_dir, filename)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(src, dest)
        return dest


def save_ckpt(path, it):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    torch.save({"iter": it, "model": {"w": torch.full((3,), float(it))}}, path)


class Backup(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        self.fake = FakeHub(os.path.join(self.d, "hub"))
        self.msgs = []

    def hub(self, fake=None):
        return H.HubBackup("me/aisml-ckpt", "v3", api=fake or self.fake, tell=self.msgs.append)

    def test_upload_then_download_on_another_machine(self):
        cloud, pc = os.path.join(self.d, "cloud"), os.path.join(self.d, "pc")
        save_ckpt(os.path.join(cloud, "latest.pt"), 2200)
        save_ckpt(os.path.join(pc, "latest.pt"), 1383)
        h = self.hub()
        self.assertTrue(h.check())
        self.assertTrue(h.upload(os.path.join(cloud, "latest.pt"), 2200))
        self.assertEqual(self.fake.squashes, 1)                      # only the newest copy is kept
        self.assertEqual(h.remote_meta()["iter"], 2200)
        self.assertEqual(h.download(pc), 2200)
        self.assertEqual(H.checkpoint_iter(os.path.join(pc, "latest.pt")), 2200)
        self.assertEqual([f for f in os.listdir(pc) if f != "latest.pt"], [])   # no leftovers

    def test_never_replaces_a_newer_local_copy(self):
        cloud, pc = os.path.join(self.d, "cloud"), os.path.join(self.d, "pc")
        save_ckpt(os.path.join(cloud, "latest.pt"), 1500)
        save_ckpt(os.path.join(pc, "latest.pt"), 2000)
        h = self.hub()
        h.upload(os.path.join(cloud, "latest.pt"), 1500)
        self.assertIsNone(h.download(pc))
        self.assertEqual(H.checkpoint_iter(os.path.join(pc, "latest.pt")), 2000)
        self.assertEqual(h.download(pc, force=True), 1500)

    def test_background_upload_uses_a_snapshot(self):
        cloud = os.path.join(self.d, "cloud")
        path = os.path.join(cloud, "latest.pt")
        save_ckpt(path, 100)
        h = self.hub()
        self.assertTrue(h.upload_in_background(path, 100))
        save_ckpt(path, 200)                        # training saves again while it uploads
        h.wait()
        self.assertEqual(h.remote_meta()["iter"], 100)
        self.assertFalse(os.path.exists(path + ".hub"))
        self.assertTrue(h.due(0))
        self.assertFalse(h.due(1))

    def test_failures_never_raise(self):
        h = self.hub(FakeHub(os.path.join(self.d, "hub2"), can_write=False))
        self.assertFalse(h.check())
        self.assertIn("WITHOUT the off-machine backup", self.msgs[-1])
        path = os.path.join(self.d, "x", "latest.pt")
        save_ckpt(path, 5)
        self.assertFalse(h.upload(path, 5))
        self.assertIn("FAILED", self.msgs[-1])
        self.assertIsNone(h.download(os.path.join(self.d, "pc")))     # nothing uploaded: says so, no crash

    def test_checkpoint_iter(self):
        p = os.path.join(self.d, "c", "latest.pt")
        self.assertEqual(H.checkpoint_iter(p), -1)
        save_ckpt(p, 42)
        self.assertEqual(H.checkpoint_iter(p), 42)


if __name__ == "__main__":
    unittest.main()
