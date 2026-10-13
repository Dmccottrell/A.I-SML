"""
cloud_run.py - Runs one VryxCode command on a remote machine over SSH, and brings the changed files back.

WHAT THIS FILE DOES
    VryxCode's "Cloud machine" environment puts this program in front of every command (the same way the Docker sandbox puts `docker run` in front):

        python cloud_run.py --host H --port P --user U --key K --known-hosts F --workdir W --timeout T -- python3 -m unittest

    It runs in the project folder and does four things:
      1. packs the project (without .git, caches and virtual environments) and sends it over SSH into a fresh folder on the remote machine;
      2. runs the command there, with a time limit;
      3. fetches the folder back and copies files that CHANGED or are NEW into the project (never anything that tries to leave it: absolute
         paths, `..`, links and device files are dropped, and the total size is capped);
      4. prints what the command printed and exits with its exit code (255 if the machine could not be reached).
    The key is a file on THIS computer (made for you by Settings > Owner > Cloud machine). The remote host's identity is remembered the first time
    (trust on first use) in the known-hosts file next to it.
"""
import argparse
import io
import os
import posixpath
import re
import shlex
import subprocess
import sys
import tarfile

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".worktrees"}
MAX_DOWN = 100 * 1024 * 1024
OUT, RC = ".emvryx_out", ".emvryx_rc"
SAFE_DIR = re.compile(r"[A-Za-z0-9_./-]{1,120}")


def ssh_base(host, port, user, key, known_hosts):
    return ["ssh", "-i", key, "-p", str(port), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={known_hosts}",
            "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=15", f"{user}@{host}"]


def pack(root):
    """The project as tar bytes, skipping the heavy and private folders."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d))]
            for f in files:
                full = os.path.join(dirpath, f)
                if not os.path.islink(full):
                    t.add(full, arcname=os.path.relpath(full, root).replace(os.sep, "/"), recursive=False)
    return buf.getvalue()


def safe_name(name):
    name = posixpath.normpath(str(name).replace("\\", "/"))
    if name.startswith(("/", "../")) or name in ("..", ".") or re.match(r"^[A-Za-z]:", name) or any(p in ("..", "") for p in name.split("/")):
        return None
    return name


def unpack_into(data, root):
    """(output text, exit code or None): copies new and changed regular files from the fetched tar into `root`, skipping anything unsafe."""
    out_text, rc, total = "", None, 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as t:
        for m in t:
            name = safe_name(m.name)
            if name is None or not m.isreg():                 # links, devices, folders and escapes are never written
                continue
            total += m.size
            if total > MAX_DOWN:
                break
            body = t.extractfile(m).read()
            if name == OUT:
                out_text = body.decode("utf-8", "replace")
                continue
            if name == RC:
                try:
                    rc = int(body.decode().strip() or "1")
                except ValueError:
                    rc = 1
                continue
            if any(p in SKIP_DIRS for p in name.split("/")[:-1]):
                continue
            dest = os.path.join(root, *name.split("/"))
            if os.path.realpath(dest) != os.path.join(os.path.realpath(root), *name.split("/")) and not os.path.realpath(dest).startswith(os.path.realpath(root) + os.sep):
                continue
            try:
                with open(dest, "rb") as f:
                    if f.read() == body:
                        continue
            except OSError:
                pass
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(body)
    return out_text, rc


def run(args, command, root, runner=subprocess.run):
    if not SAFE_DIR.fullmatch(args.workdir):
        print("cloud machine: the work folder name is not allowed")
        return 255
    base = ssh_base(args.host, args.port, args.user, args.key, args.known_hosts)
    cmd = shlex.join(["python3" if a == "python" else a for a in command[:1]] + command[1:])
    w = '"$HOME"/' + shlex.quote(args.workdir)
    send = f'[ -n "$HOME" ] && rm -rf {w} && mkdir -p {w} && tar -x -C {w} && cd {w} && (timeout {int(args.timeout)} {cmd} >{OUT} 2>&1; echo $? >{RC})'
    try:
        up = runner(base + [send], input=pack(root), capture_output=True, timeout=args.timeout + 120)
        if up.returncode != 0:
            print("cloud machine: could not copy the project over: " + (up.stderr.decode("utf-8", "replace").strip()[-300:] or f"ssh exit {up.returncode}"))
            return 255
        down = runner(base + [f'cd {w} && tar -c . | head -c {MAX_DOWN}'], capture_output=True, timeout=args.timeout + 120)
        if down.returncode not in (0, 141) or not down.stdout:
            print("cloud machine: could not fetch the results: " + (down.stderr.decode("utf-8", "replace").strip()[-300:] or f"ssh exit {down.returncode}"))
            return 255
        text, rc = unpack_into(down.stdout, root)
    except (OSError, subprocess.SubprocessError, tarfile.TarError) as e:
        print(f"cloud machine: {e}")
        return 255
    sys.stdout.write(text)
    return 124 if rc is None else rc


def main(argv=None):
    p = argparse.ArgumentParser()
    for name in ("host", "user", "key", "known-hosts", "workdir"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--port", default="22")
    p.add_argument("--timeout", type=int, default=60)
    p.add_argument("command", nargs=argparse.REMAINDER)
    a = p.parse_args(argv)
    a.known_hosts = getattr(a, "known_hosts")
    command = [c for c in a.command if c != "--"] if a.command[:1] == ["--"] else a.command
    if not command:
        print("cloud machine: no command")
        return 255
    return run(a, command, os.getcwd())


if __name__ == "__main__":
    sys.exit(main())
