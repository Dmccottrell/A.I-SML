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

# Lower-case names (and Windows security IDs) of groups that mean 'lots of people'. If any shows up in a folder's access list, the folder is not private.
# (Everyone, all Users, Authenticated Users, and their IDs S-1-1-0, S-1-5-11, S-1-5-32-545.)
BROAD = ("everyone", "builtin\\users", "authenticated users", "s-1-1-0", "s-1-5-11", "s-1-5-32-545")


def _user():
    """The Windows account name as DOMAIN\\name (for icacls), or just the name when there is no domain. Empty string when unknown."""
    # Windows sets these two environment variables for the logged-in user.
    name = os.environ.get("USERNAME", "")
    domain = os.environ.get("USERDOMAIN", "")
    return f"{domain}\\{name}" if domain and name else name


def lock_folder(path, runner=subprocess.run):
    """Windows: only this user, SYSTEM and Administrators may open `path` and what is in it. Returns True when it was done."""
    # Only Windows needs this: elsewhere file modes already do the job. Also skip when there is no path or no known user.
    if os.name != "nt" or not path or not _user():
        return False
    # Never let a failure here stop the app starting: any error just means 'not locked'.
    try:
        # icacls is the Windows tool that edits access lists. /inheritance:r drops the permissions copied from the parent folder;
        # /grant:r then sets full control (F) for this user, SYSTEM (*S-1-5-18) and Administrators (*S-1-5-32-544).
        # (OI)(CI) means the grant passes down to files (object inherit) and sub-folders (container inherit), now and in the future.
        r = runner(["icacls", str(path), "/inheritance:r", "/grant:r", f"{_user()}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"],
                   capture_output=True, text=True, timeout=60)
        # Exit code 0 means icacls succeeded.
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def is_private(path, mode=None, runner=subprocess.run):
    """True when only its owner (and on Windows the system and administrators) can read `path`."""
    # Windows: read the access list with icacls and look for broad groups in it.
    if os.name == "nt":
        try:
            out = runner(["icacls", str(path)], capture_output=True, text=True, timeout=30).stdout.lower()
        except (OSError, subprocess.SubprocessError):
            return False
        # Private means: icacls printed something, and none of the 'everyone'-style names appear in it.
        return bool(out.strip()) and not any(b in out for b in BROAD)
    # Linux/macOS: take just the permission bits of the file.
    m = stat.S_IMODE(os.stat(path).st_mode)
    # With an exact `mode` given (e.g. 0o600) it must match exactly; otherwise it is private if the group and others bits (0o077) are all zero.
    return m == mode if mode is not None else m & 0o077 == 0
