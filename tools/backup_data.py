"""
backup_data.py - Make (and restore) a backup of the Emvryx server's data folder.

WHAT THIS FILE DOES
    Run it from a scheduler (Task Scheduler on Windows, cron on Linux, or just by hand) and it makes a dated zip of everything the app keeps in its
    data folder (`.emvryx`): people, chats, saved notes, usage, security log, GitHub connections and VryxCode projects. It then deletes the oldest
    zips so only the newest `--keep` stay (14 by default), which is also how deleted accounts leave the backups.

        python tools/backup_data.py --data .emvryx --out backups                  # one backup, keep the 14 newest
        python tools/backup_data.py --data .emvryx --out backups --keep 30 --no-projects
        python tools/backup_data.py --restore backups\\emvryx-2026-10-06-0300.zip --to .emvryx-restored

    * SQLite databases are copied with SQLite's own backup, so a backup taken while the app is running is consistent (not half-written).
    * `secret.key` (the key that encrypts saved tokens) is NOT included unless you pass --with-key: keep it somewhere else, so a stolen backup
      holds only encrypted tokens. Without it a restored server just asks people to connect GitHub again.
    * The zip is written with owner-only permissions. Store it away from the server (another disk, another machine).
    * Restore refuses to write into a folder that already has files.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import argparse
import os
import sqlite3
import sys
import tempfile
import time
import zipfile

import private_files

SKIP = {"secret.key"}


def make_backup(data_dir, out_dir, keep=14, with_key=False, projects=True, now=None):
    if not os.path.isdir(data_dir):
        raise SystemExit(f"no data folder at {data_dir}")
    os.makedirs(out_dir, exist_ok=True)
    private_files.lock_folder(out_dir)                           # Windows: the backups folder is private too (Linux: each zip is 0600)
    stamp = time.strftime("%Y-%m-%d-%H%M", time.gmtime(time.time() if now is None else now))
    target = os.path.join(out_dir, f"emvryx-{stamp}.zip")
    tmp = target + ".part"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    count = 0
    with os.fdopen(fd, "wb") as raw, zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as z, tempfile.TemporaryDirectory() as scratch:
        for dirpath, dirs, names in os.walk(data_dir):
            rel_dir = os.path.relpath(dirpath, data_dir)
            if not projects and rel_dir.split(os.sep)[0] == "code":
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(dirpath, d))]
            for n in sorted(names):
                full = os.path.join(dirpath, n)
                if os.path.islink(full) or (n in SKIP and not with_key) or n.endswith((".tmp", ".part", "-journal", "-wal", "-shm")):
                    continue
                arc = os.path.normpath(os.path.join(rel_dir, n)).replace(os.sep, "/")
                if n.endswith(".db"):                              # a consistent copy even while the app is writing to it
                    copy = os.path.join(scratch, f"{count}.db")
                    src, dst = sqlite3.connect(full), sqlite3.connect(copy)
                    try:
                        src.backup(dst)
                    finally:
                        dst.close()
                        src.close()
                    z.write(copy, arc)
                else:
                    z.write(full, arc)
                count += 1
    os.replace(tmp, target)
    old = sorted(f for f in os.listdir(out_dir) if f.startswith("emvryx-") and f.endswith(".zip"))
    removed = []
    for f in old[:-keep] if keep > 0 else []:
        os.remove(os.path.join(out_dir, f))
        removed.append(f)
    return target, count, removed


def restore(zip_path, to_dir):
    if os.path.isdir(to_dir) and os.listdir(to_dir):
        raise SystemExit(f"{to_dir} already has files in it: restore into an empty folder, then swap it in yourself.")
    os.makedirs(to_dir, exist_ok=True)
    root = os.path.realpath(to_dir)
    n = 0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            dest = os.path.realpath(os.path.join(to_dir, info.filename))
            if not (dest == root or dest.startswith(root + os.sep)):
                raise SystemExit(f"refusing an unsafe path in the backup: {info.filename}")
            if info.is_dir():
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as out:
                out.write(src.read())
            n += 1
    return n


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", default=".emvryx")
    p.add_argument("--out", default="backups")
    p.add_argument("--keep", type=int, default=14, help="how many of the newest backups to keep (0 = keep all)")
    p.add_argument("--with-key", action="store_true", help="also include secret.key (then protect the zip like a password)")
    p.add_argument("--no-projects", action="store_true", help="leave out the VryxCode projects (they can be large)")
    p.add_argument("--restore", metavar="ZIP")
    p.add_argument("--to", metavar="FOLDER", help="with --restore: an empty folder to restore into")
    a = p.parse_args(argv)
    if a.restore:
        if not a.to:
            sys.exit("--restore needs --to FOLDER")
        print(f"Restored {restore(a.restore, a.to)} files into {a.to}")
        return 0
    target, count, removed = make_backup(a.data, a.out, a.keep, a.with_key, not a.no_projects)
    print(f"Backed up {count} files to {target}" + (f"; removed {len(removed)} older backup(s)" if removed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
