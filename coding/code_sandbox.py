"""
code_sandbox.py - Runs VryxCode's commands inside a throwaway container, and keeps each person's projects within their quotas.

WHAT THIS FILE DOES
    VryxCode lets a model run programs (python, pytest, git) in a project folder. The folder sandbox in harness.py stops a small model's
    MISTAKES, not a person who is trying to attack the server. Before strangers can use VryxCode, every command must run somewhere that an
    attack cannot get out of. This file builds the `docker run` prefix that does that:

        --network none           no internet at all from inside
        --cap-drop ALL, no-new-privileges, not privileged, a non-root user (the server's own user id, so files stay writable)
        --read-only + a small tmpfs for /tmp   the image cannot be changed; only the project folder is writable
        --memory / --memory-swap / --cpus / --pids-limit   hard limits (a fork bomb or a memory hog is stopped by Docker)
        -v <project>:/work       ONLY that one folder is visible, nothing else from this computer
        --runtime runsc          optional: gVisor, a stronger wall between the container and the kernel

    It fails closed: if the sandbox is wanted and Docker is not working, VryxCode refuses to run; it never quietly falls back to running on
    the host.  The image is built from docker/code-sandbox/Dockerfile (python, pytest, git).

    Quotas (per person): how many projects, how big each one and all of them may be, how many coding sessions a day, and how long one session
    may run. They stop a runaway or abusive session from filling the disk or the machine.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import os
import shutil
import subprocess
import sys
import time

DEFAULT_IMAGE = "emvryx/code-sandbox:1"
QUOTA_DEFAULTS = {"code_max_projects": 20, "code_project_mb": 100, "code_total_mb": 500, "code_sessions_per_day": 50,
                  "code_session_minutes": 30, "code_max_files": 3000}


# Room for every language in the image: Java and .NET start many threads (each counts against the process limit), Go and .NET build programs in
# /tmp and then run them (so /tmp allows running; the project folder already did), and a compiler's caches live in /tmp. Still sealed: no network.
DEFAULT_MEMORY, DEFAULT_PIDS, DEFAULT_TMP_MB = "1536m", 512, 512


def docker_prefix(image, workspace, cpus="1", memory=DEFAULT_MEMORY, pids=DEFAULT_PIDS, runtime=None, uid=None, gid=None, tmp_mb=DEFAULT_TMP_MB):
    """The words that go in front of a command so it runs in the container: prefix + ["python", "-m", "unittest"]."""
    ws = os.path.realpath(workspace)
    argv = ["docker", "run", "--rm", "-i", "--network", "none", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--read-only", "--tmpfs", f"/tmp:rw,exec,nosuid,size={int(tmp_mb)}m", "--pids-limit", str(int(pids)),
            "--memory", str(memory), "--memory-swap", str(memory), "--cpus", str(cpus), "--ulimit", "nofile=256:256",
            "-v", f"{ws}:/work:rw", "-w", "/work", "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "PYTHONIOENCODING=utf-8"]
    # never root: the same user that owns the files; Windows has no user ids, and Docker Desktop lets any user write the shared folder,
    # so an ordinary user (1000) runs it there
    if uid is None:
        uid = os.getuid() if os.name != "nt" else 1000
    if gid is None:
        gid = os.getgid() if os.name != "nt" else 1000
    argv += ["--user", f"{uid}:{gid}"]
    if runtime:
        argv += ["--runtime", str(runtime)]
    return argv + [image]


def available(image=DEFAULT_IMAGE, runner=subprocess.run):
    """(ok, message): Docker answers and the image exists. Never raises."""
    if not shutil.which("docker"):
        return False, "Docker is not installed on this server."
    try:
        r = runner(["docker", "image", "inspect", image], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False, "Docker did not answer."
    if r.returncode != 0:
        out = (r.stderr or r.stdout or "").lower()
        if "cannot connect" in out or "daemon" in out:
            return False, "Docker is installed but not running."
        return False, f"The sandbox image {image} is not built yet (see docker/code-sandbox/Dockerfile)."
    return True, "ready"


# ------------------------------------------------------------------ quotas
def tree_size(path, limit=None):
    """(bytes, files) under a folder without following links, stopping early once `limit` bytes is passed."""
    total = files = 0
    for dirpath, dirs, names in os.walk(path):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(dirpath, d))]
        for n in names:
            full = os.path.join(dirpath, n)
            if os.path.islink(full):
                continue
            try:
                total += os.path.getsize(full)
            except OSError:
                continue
            files += 1
            if limit is not None and total > limit:
                return total, files
    return total, files


class QuotaError(Exception):
    def __init__(self, message, action=""):
        super().__init__(message)
        self.message, self.action = message, action


class Quotas:
    """The limits for one server (from security.json; the defaults above). Each check raises QuotaError with a plain message."""

    def __init__(self, settings=None):
        self.q = dict(QUOTA_DEFAULTS)
        self.q.update({k: v for k, v in (settings or {}).items() if k in QUOTA_DEFAULTS})
        self.day = {}                                       # user -> [times a session was started in the last day]

    def new_project(self, base, name):
        if os.path.isdir(os.path.join(base, name)):
            return
        count = sum(1 for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)) and not d.startswith(".")) if os.path.isdir(base) else 0
        if count >= self.q["code_max_projects"]:
            raise QuotaError(f"You already have {count} projects, the most allowed.", "Delete one you no longer need.")

    def room(self, base, project_path, extra_bytes=0, extra_files=0):
        """Refuse when this project, or all of a person's projects, would be over its size, or the project over its file count."""
        limit_one = self.q["code_project_mb"] * 1024 * 1024
        size, files = tree_size(project_path, limit_one + extra_bytes + 1) if os.path.isdir(project_path) else (0, 0)
        if size + extra_bytes > limit_one:
            raise QuotaError(f"This project is over its size limit ({self.q['code_project_mb']} MB).", "Delete files you do not need.")
        if files + extra_files > self.q["code_max_files"]:
            raise QuotaError(f"This project has too many files (the limit is {self.q['code_max_files']}).", "Remove generated or downloaded files.")
        limit_all = self.q["code_total_mb"] * 1024 * 1024
        total = 0
        if os.path.isdir(base):
            for d in os.listdir(base):
                p = os.path.join(base, d)
                if os.path.isdir(p) and not d.startswith("."):                  # .sessions (the history and Rewind snapshots) has its own limits
                    total += tree_size(p, limit_all)[0]
                    if total + extra_bytes > limit_all:
                        raise QuotaError(f"All your projects together are over {self.q['code_total_mb']} MB.", "Delete a project you no longer need.")

    def start_session(self, user, now=None):
        now = time.time() if now is None else now
        recent = [t for t in self.day.get(user, []) if now - t < 86400]
        if len(recent) >= self.q["code_sessions_per_day"]:
            raise QuotaError(f"You have used your {self.q['code_sessions_per_day']} coding sessions for today.", "Try again tomorrow.")
        recent.append(now)
        self.day[user] = recent

    def session_deadline(self, now=None):
        return (time.time() if now is None else now) + self.q["code_session_minutes"] * 60


def self_check():
    """For the command line: `python coding/code_sandbox.py` says whether the sandbox is ready."""
    ok, msg = available()
    print(("Ready: " if ok else "Not ready: ") + msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(self_check())
