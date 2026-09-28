"""
run_training.py - Run train.py and restart it automatically if it crashes.

WHAT THIS FILE DOES
    A pretraining run can take weeks. If train.py stops by itself (an
    out-of-memory error, a GPU driver hiccup, a Windows glitch), this script
    waits a little and starts it again. train.py resumes from latest.pt, so
    a crash costs at most `save_every` steps (about 50 minutes for v3).

    You start it exactly like train.py, just with a different file name:

        python run_training.py --version v3 --backup_dir D:\\ai-backups

    Everything after the script name is handed to train.py.

WHEN IT RESTARTS, AND WHEN IT DOESN'T
    * train.py exits normally (finished, or you paused with Ctrl+C):
      it stops. Nothing is restarted.
    * Ctrl+C (once): train.py saves and stops, and so does this script.
      Press Ctrl+C a second time to force-quit.
    * train.py crashes: wait 30 seconds, then start it again. The wait
      doubles (up to 5 minutes) while restarts keep failing to save anything.
    * It gives up, and tells you why, if it fails 3 times in a row without
      saving any progress (that is a real problem, not bad luck), or after
      50 restarts in total.
    * --fresh is only used for the FIRST start. Restarts always resume,
      otherwise every restart would erase the run.
    * --pilot is just passed through, with no restarting.
    * --window 21:00-14:00 --days mon-fri: only train inside that daily window
      (see "RUN WINDOWS" below).

RUN WINDOWS (so the PC is yours the rest of the time)
        python run_training.py --version v3 --window 21:00-14:00 --days mon-fri

    Training runs from 21:00 until 14:00 (the window may cross midnight) on
    the listed days, saves at the end of the window, waits, and starts again
    at the next one. Leave this window open and the PC awake. --days lists the
    days a window STARTS on ("mon-fri", "all", "mon,wed,sat"), so with
    mon-fri Friday's window runs until Saturday 14:00. It stops within one
    step (~30 seconds) of the end time.

    --exit_after_window: exit at the end of the window instead of waiting. On a rented cloud
    machine, run something after it that switches the machine off, so you stop paying, e.g.:

        python run_training.py --version v3 --window 21:30-13:30 --exit_after_window && <stop the machine>

    Every start, crash and restart is written to
    <checkpoint folder>/supervisor.log, so you can see what happened while
    you were away.

    "Progress" means train.py saved latest.pt during that run.
"""
import argparse
import datetime
import os
import subprocess
import sys
import time

from config import add_version_arg, get_version


def log(message, log_path=None):
    """Print a message with the time, and append it to the log file (if there is one)."""
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line, flush=True)
    if log_path:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def mtime(path):
    """When a file was last changed (0 if it doesn't exist)."""
    return os.path.getmtime(path) if os.path.exists(path) else 0.0


def parse_window(text):
    """"21:00-14:00" -> (1260, 840): start and end as minutes after midnight."""
    try:
        a, b = text.split("-")
        (h1, m1), (h2, m2) = (map(int, a.split(":")), map(int, b.split(":")))
        start, end = h1 * 60 + m1, h2 * 60 + m2
        if not (0 <= start < 1440 and 0 <= end < 1440) or start == end:
            raise ValueError
        return start, end
    except ValueError:
        raise SystemExit(f"bad --window {text!r}: use START-END in 24-hour time, e.g. 21:00-14:00")


def parse_days(text):
    """"mon-fri", "all" or "mon,wed,sat" -> a set of weekday numbers (Monday = 0)."""
    names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    text = text.lower().strip()
    if text == "all":
        return set(range(7))
    days = set()
    try:
        for part in text.split(","):
            if "-" in part:
                a, b = (names.index(x[:3]) for x in part.split("-"))
                days |= {(a + i) % 7 for i in range((b - a) % 7 + 1)}
            else:
                days.add(names.index(part[:3]))
    except ValueError:
        raise SystemExit(f"bad --days {text!r}: use e.g. mon-fri, all, or mon,wed,sat")
    return days


def schedule_check(window, days, now=None):
    """Are we inside a run window right now?

    Returns (inside, seconds_until_the_window_ends_or_next_starts, end_timestamp_or_None).
    `window` is (start_minute, end_minute); `days` are the weekdays a window STARTS on.
    """
    now = now or datetime.datetime.now()
    start, end = window
    mins = now.hour * 60 + now.minute
    at = lambda d, m: datetime.datetime.combine(d, datetime.time(m // 60, m % 60))
    today = now.date()
    # which day did the window we might be in start on?
    window_day = None
    if start < end:
        if start <= mins < end:
            window_day = today
    elif mins >= start:
        window_day = today
    elif mins < end:
        window_day = today - datetime.timedelta(days=1)
    if window_day is not None and window_day.weekday() in days:
        end_dt = at(window_day + datetime.timedelta(days=1 if start > end else 0), end)
        return True, (end_dt - now).total_seconds(), end_dt.timestamp()
    for offset in range(9):
        d = today + datetime.timedelta(days=offset)
        if d.weekday() in days and at(d, start) > now:
            return False, (at(d, start) - now).total_seconds(), None
    return False, 3600.0, None


PAUSED_ON_SCHEDULE = 75      # train.py's exit code for "the run window is over"


def run_once(command):
    """Run one copy of the training and wait for it.

    Returns (exit code, interrupted). `interrupted` is True if you pressed
    Ctrl+C: train.py got the same Ctrl+C, so it is saving and stopping, and
    we just wait for it. A second Ctrl+C stops it by force.
    """
    process = subprocess.Popen(command)
    presses = 0
    while True:
        try:
            # A short timeout keeps Ctrl+C responsive on Windows
            return process.wait(timeout=1), presses > 0
        except subprocess.TimeoutExpired:
            continue
        except KeyboardInterrupt:
            presses += 1
            if presses == 1:
                print("\nCtrl+C: waiting for training to save and stop "
                      "(press Ctrl+C again to force-quit)...", flush=True)
            else:
                process.kill()
                return process.wait(), True


def supervise(train_args, ckpt_dir, script="train.py", first_wait=30.0,
              max_stalled=3, max_restarts=50, window=None, days=None, exit_after_window=False):
    """Run `script` with `train_args`, restarting after crashes. Returns the exit code to use."""
    os.makedirs(ckpt_dir, exist_ok=True)
    log_path = os.path.join(ckpt_dir, "supervisor.log")
    latest = os.path.join(ckpt_dir, "latest.pt")
    args = list(train_args)
    if "--pilot" in args:                          # a trial run: no restarting
        return run_once([sys.executable, script] + args)[0]

    stalled, restarts = 0, 0
    log(f"starting: python {script} {' '.join(args)}", log_path)
    while True:
        launch = list(args)
        if window:
            inside, seconds, stop_ts = schedule_check(window, days)
            if not inside:
                log(f"outside the run window: waiting {seconds / 3600:.1f} h for the next one. "
                    "Keep this window open and the PC awake. Ctrl+C to stop.", log_path)
                try:
                    end_wait = time.time() + seconds
                    while time.time() < end_wait:        # short sleeps keep Ctrl+C responsive
                        time.sleep(min(30.0, max(0.0, end_wait - time.time())))
                except KeyboardInterrupt:
                    log("stopped by you (Ctrl+C) while waiting for the run window.", log_path)
                    return 0
                continue
            launch += ["--stop_at", str(stop_ts)]
        saved_before, started = mtime(latest), time.time()
        code, interrupted = run_once([sys.executable, script] + launch)
        args = [a for a in args if a != "--fresh"]   # restarts must RESUME, never start over
        if code == PAUSED_ON_SCHEDULE and not interrupted:
            if exit_after_window:
                log("run window over: training saved. Exiting (--exit_after_window).", log_path)
                return 0
            log("run window over: training saved and paused until the next window.", log_path)
            stalled = 0
            continue

        if interrupted:
            log("stopped by you (Ctrl+C). Run the same command to resume.", log_path)
            return 0
        if code == 0:
            log("train.py finished or paused normally, so not restarting.", log_path)
            return 0

        ran_for = time.time() - started
        progress = mtime(latest) > saved_before
        stalled = 0 if progress else stalled + 1
        # 30 s after a crash that saved something; doubling (60 s, 120 s, ...) while nothing is saved
        wait = first_wait if stalled <= 1 else min(first_wait * 2 ** (stalled - 1), 300.0)
        log(f"train.py stopped with exit code {code} after {ran_for / 60:.1f} min "
            f"({'saved progress' if progress else 'no new save'}).", log_path)
        if stalled >= max_stalled:
            log(f"giving up: {stalled} failures in a row without saving anything. That's a real "
                "problem, not bad luck: read the error above (out of memory? missing data?).", log_path)
            return 1
        restarts += 1
        if restarts > max_restarts:
            log(f"giving up after {max_restarts} restarts.", log_path)
            return 1
        log(f"restarting in {wait:.0f} s (restart {restarts}). Ctrl+C now to stop.", log_path)
        try:
            time.sleep(wait)
        except KeyboardInterrupt:
            log("stopped by you (Ctrl+C) while waiting to restart.", log_path)
            return 0


def main():
    p = argparse.ArgumentParser(allow_abbrev=False, description=__doc__.split("\n\n")[0])
    add_version_arg(p)
    p.add_argument("--script", default="train.py", help=argparse.SUPPRESS)      # for testing
    p.add_argument("--wait_seconds", type=float, default=30.0, help=argparse.SUPPRESS)
    p.add_argument("--max_restarts", type=int, default=50, help="give up after this many restarts")
    p.add_argument("--window", default=None, help="only train inside this daily window, e.g. 21:00-14:00")
    p.add_argument("--exit_after_window", action="store_true",
                   help="with --window: exit at the end of the window instead of waiting for the next one "
                        "(for rented machines, so a command after it can switch the machine off)")
    p.add_argument("--days", default="all", help="days a window starts on: mon-fri, all, mon,wed,sat (default all)")
    args, rest = p.parse_known_args()
    V = get_version(args.version)
    print("This will restart training automatically after a crash. "
          "Press Ctrl+C once to pause it safely.", flush=True)
    window = parse_window(args.window) if args.window else None
    days = parse_days(args.days)
    if window:
        print(f"Run window: {args.window} on {args.days} (days a window starts).", flush=True)
    sys.exit(supervise(["--version", args.version] + rest, V.ckpt_dir, args.script,
                       args.wait_seconds, max_restarts=args.max_restarts, window=window, days=days,
                       exit_after_window=args.exit_after_window))


if __name__ == "__main__":
    main()
