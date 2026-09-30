"""
hub_backup.py - Keep a copy of the training checkpoint OFF the machine (a private Hugging Face repo).

WHY
    --backup_dir copies latest.pt to another folder on the SAME machine. When a rented machine goes
    offline (it happened), that copy is stuck there too. This uploads latest.pt to a PRIVATE repo on
    Hugging Face every few hours and whenever training stops, so any machine (your PC, a new rental)
    can continue from it. The upload runs in the background: training doesn't wait for it.

ONE-TIME SETUP
    1. On huggingface.co: Settings -> Access Tokens -> Create new token -> "Fine-grained", and give it
       WRITE access to one repo, e.g. yourname/aisml-checkpoints (create the repo first: New -> Model,
       set it to PRIVATE). A token only for that repo is safer than a general write token.
    2. On each machine that uploads (the cloud machine, and the PC if you want it to upload too):
           hf auth login          (paste that token)
       Your read-only token is fine on machines that only DOWNLOAD... but only if it can see the private
       repo; the simplest is to use the same fine-grained token everywhere.
    Never paste a token into a chat, a file in the project, or a screenshot.

USE
    Training uploads it (every --hub_every_hours, default 2, and when the run window ends / you pause /
    it finishes):
        python run_training.py --version v3 --hub_backup yourname/aisml-checkpoints ...
    Get the newest copy on any machine (only replaces your latest.pt if the backup is NEWER):
        python hub_backup.py down --version v3 --repo yourname/aisml-checkpoints
    Upload by hand:
        python hub_backup.py up --version v3 --repo yourname/aisml-checkpoints
    See what's there:
        python hub_backup.py status --version v3 --repo yourname/aisml-checkpoints

    Only the newest copy is kept (older ones are removed from the repo's history), so it uses ~5 GB
    for v3, not 5 GB per upload.
"""
import argparse
import datetime
import json
import os
import shutil
import socket
import tempfile
import threading
import time

import torch


def checkpoint_iter(path):
    """The step number saved inside a checkpoint (without loading all of it into memory), or -1."""
    if not os.path.exists(path):
        return -1
    try:
        return int(torch.load(path, map_location="cpu", mmap=True, weights_only=False).get("iter", -1))
    except Exception:
        return -1


class HubBackup:
    """Upload/download one version's checkpoints to/from a private Hugging Face repo.

    api: a huggingface_hub.HfApi (or a stand-in with the same methods, for tests).
    Nothing here ever raises into the training loop: failures are reported and training goes on.
    """

    def __init__(self, repo, version, api=None, tell=print):
        if api is None:
            from huggingface_hub import HfApi
            api = HfApi()
        self.api, self.repo, self.version, self.tell = api, repo, version, tell
        self.thread = None
        self.last_upload = 0.0
        self.last_error = None

    # ---- checks ----
    def check(self):
        """Can we write to the repo? Creates it (private) if it doesn't exist. Returns True/False."""
        try:
            self.api.whoami()
            self.api.create_repo(self.repo, private=True, exist_ok=True, repo_type="model")
            return True
        except Exception as e:
            self.last_error = e
            self.tell(f"hub backup: can't write to {self.repo} ({type(e).__name__}: {str(e)[:200]}). "
                      "Training continues WITHOUT the off-machine backup. Fix: `hf auth login` with a token "
                      "that has write access to that repo (see hub_backup.py).")
            return False

    # ---- upload ----
    def _upload(self, path, iter_, name):
        from huggingface_hub import CommitOperationAdd
        meta = {"version": self.version, "file": name, "iter": iter_,
                "time": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "host": socket.gethostname()}
        t0 = time.time()
        self.api.create_commit(
            repo_id=self.repo, repo_type="model",
            operations=[CommitOperationAdd(f"{self.version}/{name}", path),
                        CommitOperationAdd(f"{self.version}/{name}.json", json.dumps(meta, indent=1).encode())],
            commit_message=f"{self.version} {name} at step {iter_}")
        try:        # keep only the newest copy, so the repo doesn't grow by ~5 GB per upload
            self.api.super_squash_history(repo_id=self.repo, repo_type="model")
        except Exception:
            pass
        self.tell(f"hub backup: uploaded {name} (step {iter_:,}) to {self.repo} in {time.time() - t0:.0f} s")

    def upload(self, path, iter_, name="latest.pt"):
        """Upload now and wait. Returns True if it worked."""
        self.wait()
        try:
            self._upload(path, iter_, name)
            self.last_upload = time.time()
            return True
        except Exception as e:
            self.last_error = e
            self.tell(f"hub backup: upload FAILED ({type(e).__name__}: {str(e)[:200]}). Training is not affected.")
            return False

    def upload_in_background(self, path, iter_, name="latest.pt"):
        """Snapshot the file (so the next save can't change it mid-upload) and upload it in a thread.
        Skipped if the previous upload is still running."""
        if self.thread and self.thread.is_alive():
            return False
        snap = path + ".hub"
        try:
            shutil.copyfile(path, snap)
        except OSError as e:
            self.tell(f"hub backup: couldn't snapshot {path} ({e}); skipped this time")
            return False

        def run():
            try:
                self.upload(snap, iter_, name)
            finally:
                try:
                    os.remove(snap)
                except OSError:
                    pass
        self.last_upload = time.time()
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        return True

    def due(self, every_hours):
        return time.time() - self.last_upload >= every_hours * 3600

    def wait(self):
        if self.thread and self.thread.is_alive() and self.thread is not threading.current_thread():
            self.thread.join()

    # ---- download ----
    def remote_meta(self, name="latest.pt"):
        """What the backup holds ({"iter", "time", "host", ...}), or None if there is no backup yet."""
        try:
            with tempfile.TemporaryDirectory() as d:
                p = self.api.hf_hub_download(repo_id=self.repo, filename=f"{self.version}/{name}.json",
                                             local_dir=d)
                with open(p) as f:
                    return json.load(f)
        except Exception as e:
            self.last_error = e
            return None

    def download(self, ckpt_dir, name="latest.pt", force=False):
        """Replace <ckpt_dir>/<name> with the backup if the backup is newer (or force). Returns the step or None."""
        meta = self.remote_meta(name)
        if meta is None:
            self.tell(f"hub backup: no {name} for {self.version} in {self.repo} "
                      f"({type(self.last_error).__name__ if self.last_error else 'nothing uploaded yet'})")
            return None
        dest = os.path.join(ckpt_dir, name)
        local = checkpoint_iter(dest)
        if local >= meta["iter"] and not force:
            self.tell(f"hub backup: your {name} (step {local:,}) is already as new as the backup "
                      f"(step {meta['iter']:,}); nothing to do")
            return None
        os.makedirs(ckpt_dir, exist_ok=True)
        tmp = tempfile.mkdtemp(dir=ckpt_dir)
        try:
            p = self.api.hf_hub_download(repo_id=self.repo, filename=f"{self.version}/{name}", local_dir=tmp)
            os.replace(p, dest)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.tell(f"hub backup: downloaded {name} (step {meta['iter']:,}, saved {meta['time']} on {meta['host']})"
                  + (f", replacing step {local:,}" if local >= 0 else ""))
        return meta["iter"]


def main():
    from config import add_version_arg, get_version
    p = argparse.ArgumentParser(description="Off-machine checkpoint backup (private Hugging Face repo)")
    p.add_argument("action", choices=["up", "down", "status"])
    add_version_arg(p)
    p.add_argument("--repo", required=True, help="e.g. yourname/aisml-checkpoints (private)")
    p.add_argument("--name", default="latest.pt", help="latest.pt (default) or final.pt")
    p.add_argument("--force", action="store_true", help="down: replace even if yours is newer")
    a = p.parse_args()
    V = get_version(a.version)
    hub = HubBackup(a.repo, V.name)
    path = os.path.join(V.ckpt_dir, a.name)
    if a.action == "status":
        meta = hub.remote_meta(a.name)
        print(f"backup: {meta}" if meta else "backup: none yet")
        print(f"this machine: {a.name} at step {checkpoint_iter(path):,}" if os.path.exists(path) else
              f"this machine: no {a.name}")
    elif a.action == "up":
        if not os.path.exists(path):
            raise SystemExit(f"nothing to upload: {path} doesn't exist")
        if hub.check():
            hub.upload(path, checkpoint_iter(path), a.name)
    else:
        hub.download(V.ckpt_dir, a.name, a.force)


if __name__ == "__main__":
    main()
