"""
handoff.py - Move a training run between your PC and a rented cloud machine.

WHAT THIS FILE DOES
    Training can run on your PC part of the day and on a rented GPU the rest. The only thing that
    has to move is the newest latest.pt (~4.7 GB for v3). This copies it with `scp` (built into
    Windows 10/11 and Linux) and refuses to overwrite a NEWER copy with an older one.

        python handoff.py up   --host root@203.0.113.5 --port 40022 --start    PC -> cloud, then start it there
        python handoff.py down --host root@203.0.113.5 --port 40022            cloud -> PC

    --host and --port are shown on the machine's page at the provider (the "SSH" connect line).
    You need an SSH key: run `ssh-keygen` once, then paste the contents of ~/.ssh/id_ed25519.pub
    into your account's SSH keys on the provider's website.

    up:    copies latest.pt (and pre_decay.pt if it exists), and with --start also starts training
           on the cloud machine inside tmux (window 21:30-13:00 in YOUR time, then it switches itself off).
    down:  copies them back to this PC.
    --with_tokenizer (first time only): also copies data/<version>/tokenizer.json. Do this BEFORE
           building the data in the cloud, so both machines use the identical tokenizer.
    --force: copy even if the destination looks newer (you would LOSE the newer training).

    Only ONE machine may train at a time. If the destination's copy is newer, this stops
    and tells you, because copying over it would throw work away.
"""
import argparse
import datetime
import os
import shlex
import subprocess
import sys

from config import add_version_arg, get_version

FILES = ["latest.pt", "pre_decay.pt"]
DOWN_ONLY = ["final.pt"]      # exists once training has finished; only worth fetching, never sending


# ---- the three things that touch the network (replaced by simple versions in tests) ----
def ssh_out(host, port, command):
    r = subprocess.run(["ssh", "-p", str(port), host, command], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"ssh failed ({r.returncode}): {r.stderr.strip() or r.stdout.strip()}\n"
                         "Check --host/--port, that the machine is running, and that your SSH key is added.")
    return r.stdout.strip()


def scp_up(host, port, local, remote):
    subprocess.run(["scp", "-p", "-P", str(port), local, f"{host}:{remote}"], check=True)


def scp_down(host, port, remote, local):
    subprocess.run(["scp", "-p", "-P", str(port), f"{host}:{remote}", local], check=True)
# -------------------------------------------------------------------------------------------


def remote_stat(host, port, path):
    """(modified time, size) of a file on the cloud machine, or (0, 0) if it isn't there."""
    out = ssh_out(host, port, f"stat -c '%Y %s' {shlex.quote(path)} 2>/dev/null || echo '0 0'")
    mtime, size = out.split()[:2]
    return float(mtime), int(size)


def up(a, V):
    local_dir = V.ckpt_dir
    remote_dir = f"{a.repo}/{V.ckpt_dir}".replace("\\", "/")
    latest = os.path.join(local_dir, "latest.pt")
    if not os.path.exists(latest):
        raise SystemExit(f"nothing to send: {latest} doesn't exist")
    if a.with_tokenizer:
        tok = os.path.join(V.data_dir, "tokenizer.json")
        rdata = f"{a.repo}/{V.data_dir}".replace("\\", "/")
        ssh_out(a.host, a.port, f"mkdir -p {shlex.quote(rdata)}")
        scp_up(a.host, a.port, tok, f"{rdata}/tokenizer.json")
        print("sent tokenizer.json")
    r_time, _ = remote_stat(a.host, a.port, f"{remote_dir}/latest.pt")
    if r_time > os.path.getmtime(latest) + 60 and not a.force:
        raise SystemExit("STOPPED: the cloud copy of latest.pt is NEWER than yours. Copying yours over it "
                         "would throw away training. Run `python handoff.py down ...` first "
                         "(or --force if you really mean it).")
    ssh_out(a.host, a.port, f"mkdir -p {shlex.quote(remote_dir)}")
    for name in FILES:
        src = os.path.join(local_dir, name)
        if not os.path.exists(src):
            continue
        print(f"sending {name} ({os.path.getsize(src) / 1e9:.1f} GB)...")
        scp_up(a.host, a.port, src, f"{remote_dir}/{name}.part")
        ssh_out(a.host, a.port, f"mv {shlex.quote(remote_dir + '/' + name + '.part')} {shlex.quote(remote_dir + '/' + name)}")
        _, size = remote_stat(a.host, a.port, f"{remote_dir}/{name}")
        if size != os.path.getsize(src):
            raise SystemExit(f"{name}: sizes differ after copying ({size} vs {os.path.getsize(src)}). Run it again.")
    print("copied OK.")
    if a.start:
        # The cloud machine's clock is usually UTC. Pass THIS PC's offset so the window means YOUR hours.
        offset = a.cloud_utc_offset if a.cloud_utc_offset is not None else \
            datetime.datetime.now().astimezone().utcoffset().total_seconds() / 3600
        run = (f"cd {a.repo} && python run_training.py --version {a.version} --window {a.cloud_window} "
               f"--utc_offset {offset:g} --exit_after_window --backup_dir ~/backups"
               + (f" --gpus {a.cloud_gpus}" if a.cloud_gpus > 1 else "")
               + (f" --notify {shlex.quote(a.notify)}" if a.notify else "") + f"; {a.stop_command}")
        ssh_out(a.host, a.port, f"tmux kill-session -t train 2>/dev/null; tmux new -d -s train {shlex.quote(run)}")
        print(f"started training on the cloud machine (window {a.cloud_window}). "
              "Look at it any time: ssh in, then `tmux attach -t train`.")


def down(a, V):
    local_dir = V.ckpt_dir
    remote_dir = f"{a.repo}/{V.ckpt_dir}".replace("\\", "/")
    r_time, _ = remote_stat(a.host, a.port, f"{remote_dir}/latest.pt")
    if r_time == 0:
        raise SystemExit("the cloud machine has no latest.pt yet")
    latest = os.path.join(local_dir, "latest.pt")
    if os.path.exists(latest) and os.path.getmtime(latest) > r_time + 60 and not a.force:
        raise SystemExit("STOPPED: the latest.pt on THIS PC is newer than the cloud's. Copying the cloud's "
                         "over it would throw away training. Use `up` instead (or --force).")
    if ssh_out(a.host, a.port, "tmux has-session -t train 2>/dev/null && echo yes || echo no") == "yes" and not a.force:
        raise SystemExit("the cloud machine is still training (tmux session 'train'). Wait for its window to "
                         "end, or press Ctrl+C once in `tmux attach -t train`, then run this again.")
    os.makedirs(local_dir, exist_ok=True)
    for name in FILES + DOWN_ONLY:
        rfile = f"{remote_dir}/{name}"
        if remote_stat(a.host, a.port, rfile)[0] == 0:
            continue
        dest = os.path.join(local_dir, name)
        print(f"fetching {name}...")
        scp_down(a.host, a.port, rfile, dest + ".part")
        os.replace(dest + ".part", dest)
    print("copied OK. Start training here with run_training.py.")


def main():
    p = argparse.ArgumentParser(description="Move a training run between this PC and a cloud machine.")
    p.add_argument("direction", choices=["up", "down"], help="up = PC -> cloud, down = cloud -> PC")
    add_version_arg(p)
    p.add_argument("--host", required=True, help="e.g. root@203.0.113.5")
    p.add_argument("--port", type=int, default=22)
    p.add_argument("--repo", default="~/A.I-SML", help="where the project is on the cloud machine")
    p.add_argument("--start", action="store_true", help="up: also start training on the cloud machine")
    p.add_argument("--cloud_window", default="21:30-13:00", help="run window used with --start")
    p.add_argument("--notify", default=None, help="ntfy.sh topic for phone messages from the cloud run (see notify.py)")
    p.add_argument("--cloud_gpus", type=int, default=1, help="GPUs in the cloud machine (2 or more uses DDP; see docs/CLOUD.md)")
    p.add_argument("--cloud_utc_offset", type=float, default=None,
                   help="hours from UTC that --cloud_window is written in (default: this PC's current offset)")
    p.add_argument("--stop_command", default="vastai stop instance $CONTAINER_ID",
                   help="run on the cloud machine after its window, to switch it off (Vast.ai's command; "
                        "use 'true' to do nothing)")
    p.add_argument("--with_tokenizer", action="store_true", help="up: also send data/<version>/tokenizer.json")
    p.add_argument("--force", action="store_true")
    a = p.parse_args()
    V = get_version(a.version)
    (up if a.direction == "up" else down)(a, V)


if __name__ == "__main__":
    sys.exit(main())
