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
    The key is a file on THIS computer (made for you by Admin > Cloud machine). The remote host's identity is remembered the first time
    (trust on first use) in the known-hosts file next to it.
"""
# argparse reads command-line options; io.BytesIO is a file that lives in memory; posixpath handles "/" paths the
# way Linux does (the remote machine); re = regular expressions (text patterns); shlex quotes text safely for a
# shell; subprocess starts other programs (ssh); tarfile reads/writes .tar archives (many files packed into one).
import argparse
import io
import os
import posixpath
import re
import shlex
import subprocess
import sys
import tarfile

# Folders never sent to the remote machine (and never copied back): version history, caches, installed libraries.
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".worktrees"}
# The most data we accept back from the remote machine: 100 MB (100 * 1024 * 1024 bytes).
MAX_DOWN = 100 * 1024 * 1024
# Two small files the remote command writes: its printed output, and its exit code (RC = "return code").
OUT, RC = ".emvryx_out", ".emvryx_rc"
# The work folder name may only use letters, digits and _ . / - (1 to 120 characters). Stops shell tricks in the name.
SAFE_DIR = re.compile(r"[A-Za-z0-9_./-]{1,120}")


def ssh_base(host, port, user, key, known_hosts):
    """The start of every ssh command line, as a list. Options used:
    BatchMode=yes (never ask for a password), StrictHostKeyChecking=accept-new (trust a new host the first time,
    refuse it later if its identity changes), UserKnownHostsFile (where hosts are remembered), ConnectTimeout (give
    up connecting after 15 s) and ServerAliveInterval (ping every 15 s so a dead link is noticed)."""
    return ["ssh", "-i", key, "-p", str(port), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={known_hosts}",
            "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=15", f"{user}@{host}"]


def pack(root):
    """The project as tar bytes, skipping the heavy and private folders."""
    # An in-memory file to build the archive in, so nothing is written to disk.
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for dirpath, dirs, files in os.walk(root):
            # Changing dirs in place (dirs[:] = ...) tells os.walk not to enter the skipped folders or folder links.
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d))]
            for f in files:
                full = os.path.join(dirpath, f)
                # Links are left out: they could point outside the project. arcname = the path stored inside the archive
                # (relative to the project, always with "/"). recursive=False because we add each file ourselves.
                if not os.path.islink(full):
                    t.add(full, arcname=os.path.relpath(full, root).replace(os.sep, "/"), recursive=False)
    return buf.getvalue()


def safe_name(name):
    """A cleaned-up file name from the fetched archive, or None if it could escape the project folder."""
    # normpath tidies the path ("a/./b//c" -> "a/b/c"); backslashes become "/" first.
    name = posixpath.normpath(str(name).replace("\\", "/"))
    # Reject: absolute paths, ".." climbing out, "." alone, Windows drive letters (C:) and any empty or ".." part.
    if name.startswith(("/", "../")) or name in ("..", ".") or re.match(r"^[A-Za-z]:", name) or any(p in ("..", "") for p in name.split("/")):
        return None
    return name


def unpack_into(data, root):
    """(output text, exit code or None): copies new and changed regular files from the fetched tar into `root`, skipping anything unsafe."""
    # out_text = the command's printed output, rc = its exit code (None until we find it), total = bytes seen so far.
    out_text, rc, total = "", None, 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as t:
        for m in t:
            name = safe_name(m.name)
            if name is None or not m.isreg():                 # links, devices, folders and escapes are never written
                continue
            # Stop reading once the size cap is passed.
            total += m.size
            if total > MAX_DOWN:
                break
            body = t.extractfile(m).read()
            # The two special files are not copied into the project; they carry the command's output and exit code.
            if name == OUT:
                out_text = body.decode("utf-8", "replace")
                continue
            if name == RC:
                try:
                    # An empty file counts as failure (1).
                    rc = int(body.decode().strip() or "1")
                except ValueError:
                    rc = 1
                continue
            # Do not copy back files inside skipped folders (e.g. node_modules).
            if any(p in SKIP_DIRS for p in name.split("/")[:-1]):
                continue
            dest = os.path.join(root, *name.split("/"))
            # Final safety check: if an existing link in the project would make this file land outside the project
            # folder, skip it. (realpath = the real location after following links.)
            if os.path.realpath(dest) != os.path.join(os.path.realpath(root), *name.split("/")) and not os.path.realpath(dest).startswith(os.path.realpath(root) + os.sep):
                continue
            # Skip files whose content is already identical, so only CHANGED or NEW files are written.
            try:
                with open(dest, "rb") as f:
                    if f.read() == body:
                        continue
            except OSError:
                # The file does not exist yet (or cannot be read): fall through and write it.
                pass
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(body)
    return out_text, rc


def run(args, command, root, runner=subprocess.run):
    """Send the project, run the command remotely, fetch changes back. Returns the exit code to use.

    args = the parsed options, command = the command as a list, root = the project folder on this computer.
    runner is subprocess.run by default; tests can pass a fake one so no real ssh is needed."""
    # Refuse a work folder name with odd characters (it goes into a shell command below).
    if not SAFE_DIR.fullmatch(args.workdir):
        print("cloud machine: the work folder name is not allowed")
        return 255
    base = ssh_base(args.host, args.port, args.user, args.key, args.known_hosts)
    # Turn the command list into one safely quoted string. A leading "python" becomes "python3" (remote machines
    # often only have python3).
    cmd = shlex.join(["python3" if a == "python" else a for a in command[:1]] + command[1:])
    # The remote work folder, inside the remote user's home folder ($HOME).
    w = '"$HOME"/' + shlex.quote(args.workdir)
    # The one shell line run on the remote machine, in order (&& = only continue if the step worked):
    # check HOME is set, wipe and recreate the work folder, unpack the tar sent on stdin, go in, then run the
    # command under `timeout` with its output saved to OUT, and write its exit code ($?) to RC.
    send = f'[ -n "$HOME" ] && rm -rf {w} && mkdir -p {w} && tar -x -C {w} && cd {w} && (timeout {int(args.timeout)} {cmd} >{OUT} 2>&1; echo $? >{RC})'
    try:
        # Step 1+2: send the packed project as input and run the command. The extra 120 s lets the copy finish.
        up = runner(base + [send], input=pack(root), capture_output=True, timeout=args.timeout + 120)
        # 255 is the code ssh itself uses when it cannot connect; we reuse it for "the machine could not be reached".
        if up.returncode != 0:
            print("cloud machine: could not copy the project over: " + (up.stderr.decode("utf-8", "replace").strip()[-300:] or f"ssh exit {up.returncode}"))
            return 255
        # Step 3: pack the remote folder into a tar and read it back. `head -c` cuts the stream at MAX_DOWN bytes.
        down = runner(base + [f'cd {w} && tar -c . | head -c {MAX_DOWN}'], capture_output=True, timeout=args.timeout + 120)
        # 141 = 128 + 13 (SIGPIPE, a pipe closed early), which is what the cut-off by head -c can cause. Fine.
        if down.returncode not in (0, 141) or not down.stdout:
            print("cloud machine: could not fetch the results: " + (down.stderr.decode("utf-8", "replace").strip()[-300:] or f"ssh exit {down.returncode}"))
            return 255
        # Copy new/changed files into the project and pick up the output text and exit code.
        text, rc = unpack_into(down.stdout, root)
    except (OSError, subprocess.SubprocessError, tarfile.TarError) as e:
        print(f"cloud machine: {e}")
        return 255
    # Step 4: show what the command printed. If no exit code came back, use 124 (the code `timeout` itself uses).
    sys.stdout.write(text)
    return 124 if rc is None else rc


def main(argv=None):
    """Read the command-line options, then run. Returns the exit code (255 if the machine could not be reached)."""
    p = argparse.ArgumentParser()
    # Options that must be given. argparse turns "known-hosts" into the attribute known_hosts.
    for name in ("host", "user", "key", "known-hosts", "workdir"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--port", default="22")
    p.add_argument("--timeout", type=int, default=60)
    # REMAINDER = everything after the options is the command to run remotely.
    p.add_argument("command", nargs=argparse.REMAINDER)
    a = p.parse_args(argv)
    a.known_hosts = getattr(a, "known_hosts")
    # Drop the leading "--" that separates our options from the command.
    command = [c for c in a.command if c != "--"] if a.command[:1] == ["--"] else a.command
    if not command:
        print("cloud machine: no command")
        return 255
    # The project is the folder we were started in.
    return run(a, command, os.getcwd())


# Only run main() when the file is started directly, not when another file imports it.
if __name__ == "__main__":
    sys.exit(main())
