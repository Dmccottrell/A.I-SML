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
# This first line puts the project root on Python's search path so "emvryx_paths" can be imported; that module then
# makes the other code folders importable too. (Directive comment on the line is kept.)
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
# os works with files and folders; shutil.which looks for a program on the PATH; subprocess runs other programs
# (docker); sys gives the exit function; time gives the clock.
import os
import shutil
import subprocess
import sys
import time

# The name of the Docker image (a ready-made, frozen copy of a small Linux with python, pytest and git) to run commands in.
DEFAULT_IMAGE = "emvryx/code-sandbox:1"
# The default limits per person (the server's security.json may override them): projects, MB per project, MB in all,
# coding sessions per day, minutes per session, and files per project.
QUOTA_DEFAULTS = {"code_max_projects": 20, "code_project_mb": 100, "code_total_mb": 500, "code_sessions_per_day": 50,
                  "code_session_minutes": 30, "code_max_files": 3000}


# Room for every language in the image: Java and .NET start many threads (each counts against the process limit), Go and .NET build programs in
# /tmp and then run them (so /tmp allows running; the project folder already did), and a compiler's caches live in /tmp. Still sealed: no network.
# Default container limits: 1536 MB of memory, 512 processes/threads ("pids"), and a 512 MB scratch area for /tmp.
DEFAULT_MEMORY, DEFAULT_PIDS, DEFAULT_TMP_MB = "1536m", 512, 512


def docker_prefix(image, workspace, cpus="1", memory=DEFAULT_MEMORY, pids=DEFAULT_PIDS, runtime=None, uid=None, gid=None, tmp_mb=DEFAULT_TMP_MB):
    """The words that go in front of a command so it runs in the container: prefix + ["python", "-m", "unittest"].

    image = Docker image name, workspace = the project folder (the only thing the container can see), cpus/memory/pids =
    hard limits, runtime = an optional stronger runtime such as gVisor ("runsc"), uid/gid = the user to run as
    (default: the server's own), tmp_mb = size of the scratch /tmp area. Returns the list of words (argv)."""
    # realpath resolves links so the mount really is the project folder.
    ws = os.path.realpath(workspace)
    # What the flags do: --rm deletes the container afterwards; -i keeps stdin open; --network none = no network;
    # --cap-drop ALL removes special Linux powers; no-new-privileges stops gaining powers later; --read-only makes
    # the image unwritable; --tmpfs gives a RAM-backed /tmp (exec = programs may run from it, nosuid = no setuid);
    # --pids-limit caps processes (stops a fork bomb); --memory and --memory-swap (the same number = no swap) cap
    # memory; --cpus caps CPU; --ulimit nofile caps open files; -v mounts the project at /work (-w makes it the
    # working folder); -e sets environment variables inside (HOME in /tmp, no .pyc files, UTF-8 output).
    argv = ["docker", "run", "--rm", "-i", "--network", "none", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--read-only", "--tmpfs", f"/tmp:rw,exec,nosuid,size={int(tmp_mb)}m", "--pids-limit", str(int(pids)),
            "--memory", str(memory), "--memory-swap", str(memory), "--cpus", str(cpus), "--ulimit", "nofile=256:256",
            "-v", f"{ws}:/work:rw", "-w", "/work", "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "PYTHONIOENCODING=utf-8"]
    # never root: the same user that owns the files; Windows has no user ids, and Docker Desktop lets any user write the shared folder,
    # so an ordinary user (1000) runs it there
    # os.name == "nt" means Windows, which has no getuid(), so 1000 is used there.
    if uid is None:
        uid = os.getuid() if os.name != "nt" else 1000
    if gid is None:
        gid = os.getgid() if os.name != "nt" else 1000
    argv += ["--user", f"{uid}:{gid}"]
    # Optional extra isolation layer (gVisor).
    if runtime:
        argv += ["--runtime", str(runtime)]
    # The image name goes last; the command to run is added after it by the caller.
    return argv + [image]


def available(image=DEFAULT_IMAGE, runner=subprocess.run):
    """(ok, message): Docker answers and the image exists. Never raises.

    runner is subprocess.run by default; tests pass a fake so no real Docker is needed."""
    # No docker program on the PATH at all.
    if not shutil.which("docker"):
        return False, "Docker is not installed on this server."
    # "docker image inspect" succeeds only if Docker is running AND the image exists. 20 s limit so it cannot hang.
    try:
        r = runner(["docker", "image", "inspect", image], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False, "Docker did not answer."
    # Failed: read the error text to tell "Docker is not running" apart from "the image is missing".
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
        # Do not enter folder links (they could point anywhere).
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(dirpath, d))]
        for n in names:
            full = os.path.join(dirpath, n)
            # File links are not counted either.
            if os.path.islink(full):
                continue
            # A file that vanished or cannot be read is skipped.
            try:
                total += os.path.getsize(full)
            except OSError:
                continue
            files += 1
            # Stop early: the caller only needs to know the size is over the limit, not the exact figure.
            if limit is not None and total > limit:
                return total, files
    return total, files


class QuotaError(Exception):
    """A limit was hit. message = what happened, action = what the person can do about it (both in plain words)."""

    def __init__(self, message, action=""):
        super().__init__(message)
        self.message, self.action = message, action


class Quotas:
    """The limits for one server (from security.json; the defaults above). Each check raises QuotaError with a plain message."""

    def __init__(self, settings=None):
        """settings = optional dict of overrides; only keys that exist in QUOTA_DEFAULTS are accepted."""
        # Start from a copy of the defaults, then apply the allowed overrides.
        self.q = dict(QUOTA_DEFAULTS)
        self.q.update({k: v for k, v in (settings or {}).items() if k in QUOTA_DEFAULTS})
        self.day = {}                                       # user -> [times a session was started in the last day]

    def new_project(self, base, name):
        """Raise QuotaError if making project `name` in folder `base` would pass the project-count limit."""
        # The project already exists, so nothing new is being made.
        if os.path.isdir(os.path.join(base, name)):
            return
        # Count the real project folders (folders whose names do not start with "."; those are internal).
        count = sum(1 for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)) and not d.startswith(".")) if os.path.isdir(base) else 0
        if count >= self.q["code_max_projects"]:
            raise QuotaError(f"You already have {count} projects, the most allowed.", "Delete one you no longer need.")

    def room(self, base, project_path, extra_bytes=0, extra_files=0):
        """Refuse when this project, or all of a person's projects, would be over its size, or the project over its file count."""
        # MB -> bytes. tree_size stops counting once it is past the limit, since the exact number no longer matters.
        limit_one = self.q["code_project_mb"] * 1024 * 1024
        size, files = tree_size(project_path, limit_one + extra_bytes + 1) if os.path.isdir(project_path) else (0, 0)
        # extra_bytes / extra_files = what the caller is about to add. Check this one project first...
        if size + extra_bytes > limit_one:
            raise QuotaError(f"This project is over its size limit ({self.q['code_project_mb']} MB).", "Delete files you do not need.")
        if files + extra_files > self.q["code_max_files"]:
            raise QuotaError(f"This project has too many files (the limit is {self.q['code_max_files']}).", "Remove generated or downloaded files.")
        # ...then the total over all of the person's projects.
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
        """Count a new coding session for this user, or raise QuotaError if they used up today's allowance.
        `now` (seconds) can be given by tests; otherwise the real time is used."""
        now = time.time() if now is None else now
        # Keep only the start times from the last 24 hours (86400 seconds).
        recent = [t for t in self.day.get(user, []) if now - t < 86400]
        if len(recent) >= self.q["code_sessions_per_day"]:
            raise QuotaError(f"You have used your {self.q['code_sessions_per_day']} coding sessions for today.", "Try again tomorrow.")
        recent.append(now)
        self.day[user] = recent

    def session_deadline(self, now=None):
        """The time (in seconds, same clock as time.time()) at which a session started now must stop."""
        return (time.time() if now is None else now) + self.q["code_session_minutes"] * 60


def self_check():
    """For the command line: `python coding/code_sandbox.py` says whether the sandbox is ready."""
    ok, msg = available()
    print(("Ready: " if ok else "Not ready: ") + msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(self_check())
