"""restore_drill.py - proves a backup can really be restored, without touching the running server.

    python tools/restore_drill.py --out backups                 # takes the newest backup in the folder `backups`
    python tools/restore_drill.py --zip backups\\emvryx-2026-11-02-0300.zip

What it does, in plain words: it unpacks the backup into a temporary folder (never into the real data folder), opens every database inside it and asks
SQLite to check it is not damaged, counts the rows in each table, and says how old the backup is. Then it deletes the temporary folder.
Exit code 0 = the backup is good; 1 = something is wrong (the problem is printed). Do this once a month, and once before you invite testers: a backup
that was never restored is only a hope.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import argparse
import sqlite3
import tempfile
import time

import backup_data


def newest_zip(out_dir):
    """The newest emvryx-*.zip in the folder, or None. The names hold the date, so the biggest name is the newest."""
    names = sorted(n for n in os.listdir(out_dir) if n.startswith("emvryx-") and n.endswith(".zip")) if os.path.isdir(out_dir) else []
    return os.path.join(out_dir, names[-1]) if names else None


def drill(zip_path):
    """Restore `zip_path` into a throw-away folder and check it. Returns (problems, report): a list of problems (empty = good) and the lines to print."""
    problems, report = [], []
    with tempfile.TemporaryDirectory() as tmp:
        dest = os.path.join(tmp, "restored")
        try:
            files = backup_data.restore(zip_path, dest)
        except (SystemExit, OSError, Exception) as e:           # a damaged zip raises BadZipFile; an unsafe path raises SystemExit
            return [f"the backup could not be unpacked: {e}"], report
        report.append(f"unpacked {files} files")
        if files == 0:
            problems.append("the backup is empty")
        dbs = 0
        for dirpath, _dirs, names in os.walk(dest):
            for n in sorted(names):
                if not n.endswith(".db"):
                    continue
                dbs += 1
                full, rel = os.path.join(dirpath, n), os.path.relpath(os.path.join(dirpath, n), dest)
                try:
                    db = sqlite3.connect(f"file:{full}?mode=ro", uri=True)
                    check = db.execute("PRAGMA integrity_check").fetchone()[0]
                    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
                    rows = {t: db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
                    db.close()
                except sqlite3.Error as e:
                    problems.append(f"{rel}: cannot be read ({e})")
                    continue
                if check != "ok":
                    problems.append(f"{rel}: the database is damaged ({check})")
                report.append(f"{rel}: ok, " + (", ".join(f"{t} {c}" for t, c in rows.items()) or "no tables"))
        if dbs == 0:
            problems.append("no database inside the backup (is the data folder right?)")
    return problems, report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default="backups", help="the folder the backups are in (the newest is used)")
    p.add_argument("--zip", help="a particular backup file")
    a = p.parse_args(argv)
    zip_path = a.zip or newest_zip(a.out)
    if not zip_path or not os.path.exists(zip_path):
        print("No backup found. Make one first: python tools/backup_data.py")
        return 1
    age_days = (time.time() - os.path.getmtime(zip_path)) / 86400
    print(f"Backup: {zip_path} ({age_days:.1f} days old)")
    problems, report = drill(zip_path)
    for line in report:
        print("  " + line)
    if age_days > 3:
        problems.append(f"the newest backup is {age_days:.0f} days old: is the daily backup running?")
    if problems:
        print("PROBLEMS:")
        for line in problems:
            print("  - " + line)
        return 1
    print("The backup restores and every database is healthy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
