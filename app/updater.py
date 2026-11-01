"""
updater.py - "Update now": pull the newest Emvryx code onto this computer and restart the app, from the Admin screen (owner only).

WHAT THIS FILE DOES
    * check(): asks GitHub (git fetch) what is new on `main` and lists the changes, plus anything that would make an update unsafe (files edited on this
      computer, a different branch, a copy that is ahead or has split from main, replies or coding sessions in progress).
    * apply(expected): runs `git pull --ff-only` (it can only move forward, it never merges or overwrites), but only when the newest change is the one the person saw
      and was shown, then restarts the app by itself. The restart is handed to a separate one-off Windows task so it survives the app stopping.
    * Nothing here runs unless the owner presses the button and confirms.
"""
import os
import subprocess
import tempfile
import threading

BRANCH = "main"             # the git branch that holds the released code
TASK = "Emvryx App"         # name of the Windows Task Scheduler task that runs the app
GIT_TIMEOUT = 60            # seconds a single git command may take before we give up


class UpdateError(Exception):
    """An update problem with a message the screen can show as it is.

    message: what went wrong, in plain words. action: what the person can do about it ("" if nothing). code: a short machine-readable
    label for the kind of problem (such as "busy" or "timeout"), so the page can react to it.
    """

    def __init__(self, message, action="", code="update_blocked"):
        super().__init__(message)
        self.message, self.action, self.code = message, action, code


def _git(root, *args, runner=subprocess.run):
    """Run `git <args>` inside folder `root`. Returns (exit code, stdout text, stderr text), both trimmed. Exit code 0 means success.

    `runner` is the function that really starts the program; tests pass a fake one so no real git is needed.
    """
    # stdin=DEVNULL: git must never wait for typed input (it would hang forever). timeout stops a stuck network call.
    try:
        p = runner(["git", *args], cwd=root, capture_output=True, text=True, timeout=GIT_TIMEOUT, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise UpdateError("Git is not installed on this computer.", "Install Git for Windows, then try again.", "no_git")
    except subprocess.TimeoutExpired:
        raise UpdateError("Git took too long to answer.", "Check the internet connection on this computer and try again.", "timeout")
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


class Updater:
    """Checks for and applies code updates for the folder `root` (a git copy of the project)."""

    def __init__(self, root, busy=lambda: False, restart=None, runner=subprocess.run):
        """root: the project folder. busy: a function returning True while a reply or coding session is running.
        restart: a function that restarts the app (default: the Windows task below). runner: how programs are started (replaceable for tests)."""
        self.root, self.busy, self.runner = root, busy, runner
        # If no restart function was given, use the Windows scheduled-task one.
        self.restart = restart or self._restart_windows_task
        self.lock = threading.Lock()

    def _g(self, *args):
        """Shortcut: run a git command in this project's folder with this updater's runner."""
        return _git(self.root, *args, runner=self.runner)

    def check(self):
        """{"can_update", "reason", "branch", "current", "latest", "behind", "incoming": [{"sha", "subject"}], "dirty": [...], "deps_changed", "busy"}"""
        # `out` starts as "cannot update"; each step below fills in more. Returning early leaves a "reason" the screen shows to the person.
        out = {"can_update": False, "reason": "", "branch": "", "current": "", "latest": "", "behind": 0, "ahead": 0, "incoming": [], "dirty": [], "deps_changed": False,
               "busy": bool(self.busy()), "restart": self.can_restart()}
        # No .git folder means the code was copied, not cloned, so git cannot update it.
        if not os.path.isdir(os.path.join(self.root, ".git")):
            out["reason"] = "This copy of Emvryx was not installed with git, so it cannot update itself."
            return out
        # rc = the git exit code (0 = fine). The current branch name, then the short id (first 12 characters) of the current commit.
        rc, branch, _ = self._g("rev-parse", "--abbrev-ref", "HEAD")
        out["branch"] = branch
        rc, cur, _ = self._g("rev-parse", "HEAD")
        out["current"] = cur[:12]
        # fetch downloads the newest information from GitHub without changing any files here. A failure usually means no internet.
        rc, _, err = self._g("fetch", "--quiet", "origin", BRANCH)
        if rc:
            out["reason"] = "Could not reach GitHub: " + (err.splitlines() or ["no answer"])[-1][:200]
            return out
        # The newest commit on GitHub's main (origin/main is our local record of it, just refreshed by the fetch).
        rc, latest, _ = self._g("rev-parse", f"origin/{BRANCH}")
        out["latest"] = latest[:12]
        # Count commits on each side of "HEAD...origin/main": the output is two numbers, "ahead behind" (ahead = ours not on GitHub,
        # behind = on GitHub but not here).
        rc, counts, _ = self._g("rev-list", "--left-right", "--count", f"HEAD...origin/{BRANCH}")
        try:
            out["ahead"], out["behind"] = (int(x) for x in counts.split())
        except ValueError:
            out["reason"] = "Could not compare with GitHub."
            return out
        # The new changes (up to 30): a short id and a one-line description each. \x1f is an invisible "unit separator" character used to
        # split the two parts safely, because a description may contain any normal character.
        rc, log, _ = self._g("log", "--format=%h\x1f%s", "--max-count=30", f"HEAD..origin/{BRANCH}")
        out["incoming"] = [{"sha": a, "subject": b} for a, b in (line.split("\x1f", 1) for line in log.splitlines() if "\x1f" in line)]
        # If requirements.txt changed, the person must install new packages after updating.
        rc, files, _ = self._g("diff", "--name-only", f"HEAD...origin/{BRANCH}")
        out["deps_changed"] = "requirements.txt" in files.splitlines()
        # Files edited here by hand (tracked files only). --porcelain gives a stable machine format; the file name starts at column 3.
        rc, status, _ = self._g("status", "--porcelain", "--untracked-files=no")
        out["dirty"] = [line[3:] for line in status.splitlines()][:20]
        # Decide, in order of importance, whether it is safe: right branch, nothing of our own, no hand edits, and something to get.
        if branch != BRANCH:
            out["reason"] = f"This computer is on the branch '{branch}', not '{BRANCH}', so it will not be changed."
        elif out["ahead"]:
            out["reason"] = "This computer has changes of its own that are not on GitHub, so it will not be changed."
        elif out["dirty"]:
            out["reason"] = "Files on this computer were edited by hand (" + ", ".join(out["dirty"][:3]) + "), so it will not be changed."
        elif not out["behind"]:
            out["reason"] = "Already up to date."
        else:
            out["can_update"] = True
        return out

    def can_restart(self):
        """True only on Windows, when the 'Emvryx App' scheduled task exists (so the app can be restarted after an update)."""
        # os.name is "nt" on Windows; on other systems there is no such task.
        if os.name != "nt":
            return False
        # schtasks is Windows' Task Scheduler command; /Query exits with 0 when the named task exists.
        try:
            return self.runner(["schtasks", "/Query", "/TN", TASK], capture_output=True, text=True, timeout=15).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def apply(self, expected, force=False):
        """Move to the newest main (only the one the person saw: `expected` is its short id) and restart. Returns what happened."""
        # The lock makes sure only one update runs at a time. check() is run again now (not trusted from earlier) because things may have changed.
        with self.lock:
            now = self.check()
            if not now["can_update"]:
                raise UpdateError(now["reason"] or "Nothing to update.", "", "not_updatable")
            # The person approved a specific newest change; if GitHub has moved on since, make them read the new list first.
            if str(expected) != now["latest"]:
                raise UpdateError("There is a newer change than the one you looked at.", "Check again and read the list before updating.", "changed")
            # Do not restart under a running reply or coding session, unless the person chose "Update anyway" (force).
            if now["busy"] and not force:
                raise UpdateError("Emvryx is busy right now (a reply or a coding session is running).", "Wait for it to finish, or choose Update anyway.", "busy")
            # --ff-only = "fast-forward only": git just moves forward to the newer commits and refuses anything that needs merging.
            rc, out, err = self._g("pull", "--ff-only", "--quiet", "origin", BRANCH)
            if rc:
                raise UpdateError("The update could not be applied: " + (err.splitlines() or ["git said no"])[-1][:200], "Nothing was changed.", "pull_failed")
            # Restart the app if it can be done; if the restart fails, the update still counts and we report restarting=False.
            restarted = False
            if now["restart"]:
                try:
                    self.restart()
                    restarted = True
                except (OSError, subprocess.SubprocessError):
                    restarted = False
            return {"updated": True, "from": now["current"], "to": now["latest"], "changes": len(now["incoming"]), "restarting": restarted, "deps_changed": now["deps_changed"]}

    @staticmethod
    def restart_script(pid):
        """The PowerShell the one-off restart task runs. Stopping the 'Emvryx App' task ends its cmd.exe but NOT the python server it started
        (Oct 2026: updates were pulled but the server kept running the old code for a day), so the server itself (`pid`, this process) is
        ended too; with the port free, the task starts it again on the new code."""
        # PowerShell steps, in order: wait 3 s; stop the task; force-stop this server process (`pid`, forced to a whole number so nothing else
        # can be slipped in); kill any llama-server program (the model runner) and its children; wait 3 s; start the task again; delete this
        # one-off restart task. "-ErrorAction SilentlyContinue" and "| Out-Null" keep errors and output quiet.
        return (f"Start-Sleep 3; Stop-ScheduledTask -TaskName '{TASK}' -ErrorAction SilentlyContinue; "
                f"Stop-Process -Id {int(pid)} -Force -ErrorAction SilentlyContinue; "
                "taskkill /F /IM llama-server.exe /T | Out-Null; Start-Sleep 3; "
                f"Start-ScheduledTask -TaskName '{TASK}'; schtasks /Delete /TN 'EmvryxRestart' /F | Out-Null")

    def _restart_windows_task(self, script_dir=None):
        """Stop and start the 'Emvryx App' task from a separate one-off task, so the restart still happens after this app has been stopped.
        The steps go in a small .ps1 file and the task only runs that file: schtasks refuses a command longer than 261 characters, and the
        steps written out in full were 298, so the restart task was never made and updates were pulled without the app ever restarting."""
        # Write the steps into a .ps1 (PowerShell script) file in the temp folder (or `script_dir`, which tests can set).
        path = os.path.join(script_dir or tempfile.gettempdir(), "emvryx_restart.ps1")
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.restart_script(os.getpid()) + "\n")
        # The short command the task runs: PowerShell, no user profile, hidden window, allowed to run an unsigned script, running our file.
        cmd = f'powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{path}"'
        # Create the one-off task (a "ONCE" task at 00:00 that we never wait for; /F replaces an old one) and run it at once.
        # check=True makes a failure raise an error instead of being ignored.
        self.runner(["schtasks", "/Create", "/TN", "EmvryxRestart", "/TR", cmd, "/SC", "ONCE", "/ST", "00:00", "/F"], capture_output=True, text=True, timeout=20, check=True)
        self.runner(["schtasks", "/Run", "/TN", "EmvryxRestart"], capture_output=True, text=True, timeout=20, check=True)
