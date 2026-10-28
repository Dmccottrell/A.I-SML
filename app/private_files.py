"""
private_files.py - Keeping the data folder's secrets private on Windows as well as on Linux.

WHAT THIS FILE DOES
    * On Linux and macOS each private file is written readable by its owner only (mode 0600, where it is written). Windows ignores that mode:
      who can read a file is decided by the folder's access list, and a data folder outside the person's own profile (D:\\Emvryx\\data) lets
      every user of the PC read it.
    * `lock_folder(path)` makes the data folder private on Windows when the app starts: only this Windows user, the system and administrators,
      passed on to every file in it, now and later (icacls). On other systems it does nothing; it never stops the app starting.
    * `is_private(path)` is the check the tests use on both: no other users on Windows, mode 0600 (or the given mode) elsewhere.
"""
import os
import stat
import subprocess

BROAD = ("everyone", "builtin\\users", "authenticated users", "s-1-1-0", "s-1-5-11", "s-1-5-32-545")


def _user():
    name = os.environ.get("USERNAME", "")
    domain = os.environ.get("USERDOMAIN", "")
    return f"{domain}\\{name}" if domain and name else name


def lock_folder(path, runner=subprocess.run):
    """Windows: only this user, SYSTEM and Administrators may open `path` and what is in it. Returns True when it was done."""
    if os.name != "nt" or not path or not _user():
        return False
    try:
        r = runner(["icacls", str(path), "/inheritance:r", "/grant:r", f"{_user()}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"],
                   capture_output=True, text=True, timeout=60)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def is_private(path, mode=None, runner=subprocess.run):
    """True when only its owner (and on Windows the system and administrators) can read `path`."""
    if os.name == "nt":
        try:
            out = runner(["icacls", str(path)], capture_output=True, text=True, timeout=30).stdout.lower()
        except (OSError, subprocess.SubprocessError):
            return False
        return bool(out.strip()) and not any(b in out for b in BROAD)
    m = stat.S_IMODE(os.stat(path).st_mode)
    return m == mode if mode is not None else m & 0o077 == 0
