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
import threading

BRANCH = "main"
TASK = "Emvryx App"
GIT_TIMEOUT = 60


class UpdateError(Exception):
    def __init__(self, message, action="", code="update_blocked"):
        super().__init__(message)
        self.message, self.action, self.code = message, action, code


def _git(root, *args, runner=subprocess.run):
    try:
        p = runner(["git", *args], cwd=root, capture_output=True, text=True, timeout=GIT_TIMEOUT, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise UpdateError("Git is not installed on this computer.", "Install Git for Windows, then try again.", "no_git")
    except subprocess.TimeoutExpired:
        raise UpdateError("Git took too long to answer.", "Check the internet connection on this computer and try again.", "timeout")
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


class Updater:
    def __init__(self, root, busy=lambda: False, restart=None, runner=subprocess.run):
        self.root, self.busy, self.runner = root, busy, runner
        self.restart = restart or self._restart_windows_task
        self.lock = threading.Lock()

    def _g(self, *args):
        return _git(self.root, *args, runner=self.runner)

    def check(self):
        """{"can_update", "reason", "branch", "current", "latest", "behind", "incoming": [{"sha", "subject"}], "dirty": [...], "deps_changed", "busy"}"""
        out = {"can_update": False, "reason": "", "branch": "", "current": "", "latest": "", "behind": 0, "ahead": 0, "incoming": [], "dirty": [], "deps_changed": False,
               "busy": bool(self.busy()), "restart": self.can_restart()}
        if not os.path.isdir(os.path.join(self.root, ".git")):
            out["reason"] = "This copy of Emvryx was not installed with git, so it cannot update itself."
            return out
        rc, branch, _ = self._g("rev-parse", "--abbrev-ref", "HEAD")
        out["branch"] = branch
        rc, cur, _ = self._g("rev-parse", "HEAD")
        out["current"] = cur[:12]
        rc, _, err = self._g("fetch", "--quiet", "origin", BRANCH)
        if rc:
            out["reason"] = "Could not reach GitHub: " + (err.splitlines() or ["no answer"])[-1][:200]
            return out
        rc, latest, _ = self._g("rev-parse", f"origin/{BRANCH}")
        out["latest"] = latest[:12]
        rc, counts, _ = self._g("rev-list", "--left-right", "--count", f"HEAD...origin/{BRANCH}")
        try:
            out["ahead"], out["behind"] = (int(x) for x in counts.split())
        except ValueError:
            out["reason"] = "Could not compare with GitHub."
            return out
        rc, log, _ = self._g("log", "--format=%h\x1f%s", "--max-count=30", f"HEAD..origin/{BRANCH}")
        out["incoming"] = [{"sha": a, "subject": b} for a, b in (line.split("\x1f", 1) for line in log.splitlines() if "\x1f" in line)]
        rc, files, _ = self._g("diff", "--name-only", f"HEAD...origin/{BRANCH}")
        out["deps_changed"] = "requirements.txt" in files.splitlines()
        rc, status, _ = self._g("status", "--porcelain", "--untracked-files=no")
        out["dirty"] = [line[3:] for line in status.splitlines()][:20]
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
        if os.name != "nt":
            return False
        try:
            return self.runner(["schtasks", "/Query", "/TN", TASK], capture_output=True, text=True, timeout=15).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def apply(self, expected, force=False):
        """Move to the newest main (only the one the person saw: `expected` is its short id) and restart. Returns what happened."""
        with self.lock:
            now = self.check()
            if not now["can_update"]:
                raise UpdateError(now["reason"] or "Nothing to update.", "", "not_updatable")
            if str(expected) != now["latest"]:
                raise UpdateError("There is a newer change than the one you looked at.", "Check again and read the list before updating.", "changed")
            if now["busy"] and not force:
                raise UpdateError("Emvryx is busy right now (a reply or a coding session is running).", "Wait for it to finish, or choose Update anyway.", "busy")
            rc, out, err = self._g("pull", "--ff-only", "--quiet", "origin", BRANCH)
            if rc:
                raise UpdateError("The update could not be applied: " + (err.splitlines() or ["git said no"])[-1][:200], "Nothing was changed.", "pull_failed")
            restarted = False
            if now["restart"]:
                try:
                    self.restart()
                    restarted = True
                except (OSError, subprocess.SubprocessError):
                    restarted = False
            return {"updated": True, "from": now["current"], "to": now["latest"], "changes": len(now["incoming"]), "restarting": restarted, "deps_changed": now["deps_changed"]}

    def _restart_windows_task(self):
        """Stop and start the 'Emvryx App' task from a separate one-off task, so the restart still happens after this app has been stopped."""
        ps = (f"Start-Sleep 3; Stop-ScheduledTask -TaskName '{TASK}' -ErrorAction SilentlyContinue; "
              "taskkill /F /IM llama-server.exe /T | Out-Null; Start-Sleep 3; "
              f"Start-ScheduledTask -TaskName '{TASK}'; schtasks /Delete /TN 'EmvryxRestart' /F | Out-Null")
        cmd = f'powershell -NoProfile -WindowStyle Hidden -Command "{ps}"'
        self.runner(["schtasks", "/Create", "/TN", "EmvryxRestart", "/TR", cmd, "/SC", "ONCE", "/ST", "00:00", "/F"], capture_output=True, text=True, timeout=20, check=True)
        self.runner(["schtasks", "/Run", "/TN", "EmvryxRestart"], capture_output=True, text=True, timeout=20, check=True)
