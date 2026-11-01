"""
scheduled.py - chat_schedule: scheduled tasks. A message Emvryx answers by itself at a set time ("every weekday at 7:30: a summary of today's
news", "every Sunday at 18:00: a meal plan for the week", "on 3 May at 9:00: remind me to call the bank"), into a chat of its own, with a
notification when the answer is ready.

WHAT THIS FILE DOES
    * `Schedules` keeps each person's tasks in data_dir/schedules.json: {id, name, prompt, when, time, days, date, tz, model, effort, chat,
      last_run, next_run, runs, on}. At most MAX_TASKS each.
    * `next_run` works out the next time a task is due from its kind: "daily" (time), "weekdays" (time, Monday to Friday), "weekly" (time and a
      list of days), "once" (date and time). Times are the person's own clock: `tz` is their offset from UTC in minutes, sent by their browser.
    * `due(now)` lists the tasks whose time has come. The server's ticker (AppState.schedule_tick) answers each one like a chat message
      (chat_turn.start_turn, so the person's plan, memory and instructions apply), always into that task's own chat, then sends the push.
      A task that could not run (the PC was resting, the plan was used up) is tried again at its next time; it never piles up.
"""
import json
import os
import re
import threading
import time
import uuid

MAX_TASKS = 10                      # most scheduled tasks one person may have
# The four ways a task can repeat (see the notes at the top).
KINDS = ("daily", "weekdays", "weekly", "once")
# A regex is a text pattern. TIME matches a 24-hour clock time like "7:30" or "07:30": hour 0-23 (an optional leading 0/1, or 20-23),
# a colon, then minutes 00-59. The brackets () "capture" the hour and the minutes so we can read them out separately.
TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
# DATE matches a calendar date like "2026-05-03": four digits (year), two (month), two (day). Only the shape is checked here.
DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
MAX_PROMPT = 2000                   # longest instruction text, in characters


def _hm(t):
    """Split a clock time like "07:30" into (hour, minute) numbers. Raises ValueError with a message for the person if it is not a time."""
    m = TIME.match(str(t or ""))
    if not m:
        raise ValueError("Pick a time like 07:30.")
    return int(m.group(1)), int(m.group(2))


def next_run(task, after):
    """The next time (UTC seconds) after `after` that `task` is due, or None (a "once" task that has passed).

    `task` is a task dict (needs "when" and "time"; maybe "date", "days", "tz"). Times are "Unix seconds": seconds counted since 1 Jan 1970 UTC.
    Raises ValueError (with a sentence for the person) when the time, date or days are missing or wrong.
    """
    h, mi = _hm(task["time"])
    off = int(task.get("tz", 0)) * 60                              # the person's clock = UTC + off
    # A one-off task: build its exact moment from the date and time the person typed.
    if task["when"] == "once":
        m = DATE.match(str(task.get("date", "")))
        if not m:
            raise ValueError("Pick a date.")
        # struct_time is Python's calendar record (year, month, day, hour, minute, second, weekday, day-of-year, dst); the last 3 are unused here.
        local = time.struct_time((int(m.group(1)), int(m.group(2)), int(m.group(3)), h, mi, 0, 0, 0, 0))
        # _timegm reads the record as if it were UTC; subtracting off turns the person's clock time into the real UTC moment.
        at = _timegm(local) - off
        return at if at > after else None
    # Repeating task: first decide which weekdays count (0 = Monday ... 6 = Sunday).
    days = {"daily": set(range(7)), "weekdays": {0, 1, 2, 3, 4}}.get(task["when"])
    if days is None:
        days = {int(d) for d in task.get("days") or [] if str(d).isdigit() and 0 <= int(d) <= 6}       # 0 = Monday
        if not days:
            raise ValueError("Pick at least one day.")
    # What day is it on the person's clock? gmtime(after + off) shifts UTC by their offset. Then `base` is today's due time, in UTC.
    local_now = time.gmtime(after + off)
    base = _timegm(time.struct_time((local_now.tm_year, local_now.tm_mon, local_now.tm_mday, h, mi, 0, 0, 0, 0))) - off
    # Try today, tomorrow, ... up to 7 days ahead (8 tries covers a full week) and take the first moment that is in the future and on an allowed
    # weekday. 86400 = seconds in a day. (This ignores clock changes for summer time: the person's offset is a fixed number of minutes.)
    for add in range(0, 8):
        at = base + add * 86400
        if at > after and time.gmtime(at + off).tm_wday in days:
            return at
    return None


def _timegm(t):
    """Turn a calendar record (read as UTC) into Unix seconds. Imported inside the function because it is only needed here."""
    import calendar
    return calendar.timegm(t)


def describe(task):
    """ "Every weekday at 07:30", for the list """
    # Index 0 = Monday, matching the "days" numbers stored in a task.
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    if task["when"] == "daily":
        return f"Every day at {task['time']}"
    if task["when"] == "weekdays":
        return f"Every weekday at {task['time']}"
    if task["when"] == "weekly":
        return "Every " + ", ".join(names[int(d)] for d in sorted(task.get("days") or [])) + f" at {task['time']}"
    return f"On {task.get('date')} at {task['time']}"


class Schedules:
    """Every person's scheduled tasks, kept in memory and saved to schedules.json after each change. Thread-safe through one lock."""

    def __init__(self, data_dir, clock=time.time):
        """`data_dir`: folder for schedules.json (None = keep in memory only). `clock`: a function giving "now" in seconds; tests pass a fake one."""
        self.path = os.path.join(data_dir, "schedules.json") if data_dir else None
        self.clock = clock
        self.lock = threading.Lock()
        self.tasks = {}                                             # user -> [task]
        # Load the saved tasks if the file exists; a missing or broken file just means we start empty.
        if self.path:
            try:
                with open(self.path, encoding="utf-8") as f:
                    got = json.load(f)
                self.tasks = got if isinstance(got, dict) else {}
            except (OSError, ValueError):
                pass

    def _save(self):
        """Write all tasks to disk. Callers hold self.lock."""
        if not self.path:
            return
        # Write to a temporary file first, then swap it in with os.replace (one step), so a crash mid-write cannot leave a half-written file.
        with open(self.path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self.tasks, f)
        os.replace(self.path + ".tmp", self.path)

    def list(self, user):
        """This person's tasks, each with an extra "said" line in words ("Every weekday at 07:30"). Copies, so callers cannot change the originals."""
        return [dict(t, said=describe(t)) for t in self.tasks.get(user, [])]

    def get(self, user, task_id):
        """The one task with this id, or None. (Returns the real stored dict, not a copy.)"""
        return next((t for t in self.tasks.get(user, []) if t["id"] == task_id), None)

    def add(self, user, body):
        """Check a new task sent from the browser (`body`), store it, and return it. Raises ValueError with a message for the person if invalid."""
        prompt = str(body.get("prompt", "")).strip()
        if not prompt:
            raise ValueError("Write what Emvryx should do.")
        if len(prompt) > MAX_PROMPT:
            raise ValueError("That is too long for a scheduled task.")
        when = str(body.get("when", "daily"))
        if when not in KINDS:
            raise ValueError("Pick how often.")
        # tz must be a whole number of minutes within +/-14 hours (the real range of time zones); bool is excluded because True is an int in Python.
        tz = body.get("tz", 0)
        if not isinstance(tz, int) or isinstance(tz, bool) or not -14 * 60 <= tz <= 14 * 60:
            tz = 0
        # Build the task record, trimming every text to a safe length. The name defaults to the prompt, with extra spaces squeezed out.
        task = {"id": uuid.uuid4().hex[:12], "name": (" ".join(str(body.get("name") or prompt).split()))[:60], "prompt": prompt, "when": when,
                "time": str(body.get("time", "")), "days": [int(d) for d in body.get("days") or [] if str(d).isdigit()][:7],
                "date": str(body.get("date", ""))[:10], "tz": tz, "model": str(body.get("model", ""))[:40],
                "effort": str(body.get("effort", "balanced"))[:12], "chat": None, "last_run": None, "runs": 0, "on": True, "last_error": ""}
        # Work out when it first runs; a bad time, date or days raises ValueError here, before anything is stored.
        task["next_run"] = next_run(task, self.clock())             # raises ValueError for a bad time, date or days
        if task["next_run"] is None:
            raise ValueError("That time has already passed.")
        # Check the limit and add under the lock so two quick requests cannot both slip past it.
        with self.lock:
            mine = self.tasks.setdefault(user, [])
            if len(mine) >= MAX_TASKS:
                raise ValueError(f"You can have up to {MAX_TASKS} scheduled tasks. Delete one first.")
            mine.append(task)
            self._save()
        return dict(task, said=describe(task))

    def delete(self, user, task_id):
        """Remove a task. Returns True if one was really removed, False if there was no such task."""
        with self.lock:
            before = len(self.tasks.get(user, []))
            self.tasks[user] = [t for t in self.tasks.get(user, []) if t["id"] != task_id]
            self._save()
            return len(self.tasks[user]) < before

    def set_on(self, user, task_id, on):
        """Switch a task on or off. Returns the updated task, or None if not found. Switching on recalculates the next run from now."""
        with self.lock:
            t = self.get(user, task_id)
            if not t:
                return None
            t["on"] = bool(on)
            if on:
                t["next_run"] = next_run(t, self.clock())
            self._save()
            return dict(t, said=describe(t))

    def due(self, now=None):
        """[(user, task)] whose time has come (each is moved on to its next time at once, so it never runs twice)."""
        now = self.clock() if now is None else now
        out = []
        with self.lock:
            # Go through everyone's tasks; pick the ones that are on and whose time has passed.
            for user, tasks in self.tasks.items():
                for t in tasks:
                    if t.get("on") and t.get("next_run") and t["next_run"] <= now:
                        # Hand back a copy, then move the stored task on to its next time straight away.
                        out.append((user, dict(t)))
                        try:
                            t["next_run"] = next_run(t, now)
                        except ValueError:
                            t["next_run"] = None
                        if t["next_run"] is None:
                            t["on"] = False                          # a "once" task is done
            if out:
                self._save()
        return out

    def ran(self, user, task_id, chat_id, error=""):
        """Record that a task just ran: which chat holds its answer, when, how many successful runs, and the error text if it failed."""
        with self.lock:
            t = self.get(user, task_id)
            if not t:
                return
            t["chat"] = chat_id if chat_id is not None else t.get("chat")
            t["last_run"] = self.clock()
            t["runs"] = int(t.get("runs", 0)) + (0 if error else 1)
            t["last_error"] = str(error)[:200]
            self._save()


def _model_for(state, who, wanted):
    """Choose a model id to answer with: the one the task asked for if it is ready, else the first ready one, else `wanted` unchanged."""
    cat = state.catalog(who)
    cards = [m for m in cat["cards"] + cat["other"] if m.get("state") == "ready"]
    pick = next((m for m in cards if m["id"] == wanted), None) or (cards[0] if cards else None)
    return pick["id"] if pick else wanted


def run_task(state, user, task, wait=900):
    """Answers one scheduled task now, into its own chat, and tells the person. Returns (chat_id, error)."""
    # Imported here (not at the top of the file) to avoid a circular import: chat_turn also pulls in modules that use this one.
    import chat_turn
    # Turn the user id into their account name; None means the account was deleted since the task was made.
    who = state.who_name(user)
    if not who:
        return None, "gone"
    # Feature flag check: the owner can switch scheduled tasks off per person. Each skipped run is recorded so the list can show why.
    if not state.flags.on("chat_schedule", who):
        state.schedules.ran(user, task["id"], None, "Scheduled tasks are switched off.")
        return None, "off"
    # Gaming mode frees the PC for games, so no answers are made; the task simply waits for its next time.
    if state.cfg.get("gaming"):
        state.schedules.ran(user, task["id"], None, "Emvryx was resting (Gaming mode): it runs again at the next time.")
        return None, "resting"
    # Every task answers into its own chat: reuse it, or open a new one if it was never made or the person deleted it.
    store = state.store(user)
    cid = task.get("chat")
    if cid is None or not store.exists(cid):
        cid = store.new_chat(title="⏰ " + task["name"])
    error = ""
    try:
        # Start the chat turn exactly like a typed message. It returns a queue `q` that fills with events as the answer streams in.
        q, _stop, _model, _win, _decision = chat_turn.start_turn(state, who, cid, task["prompt"], _model_for(state, who, task.get("model")),
                                                                 task.get("effort") or "balanced")
        # Wait for the answer to finish, but give up after `wait` seconds (default 900 = 15 minutes). The loop reads events until "done" or "error".
        end = time.time() + wait
        while True:
            kind, val = q.get(timeout=max(1, end - time.time()))
            if kind == "done":
                break
            if kind == "error":
                error = getattr(val, "message", None) or str(val)
                break
    except Exception as e:                                      # a limit, no model ready, a timeout: said in the list, tried again next time
        error = getattr(e, "message", None) or str(e) or "It could not run."
    # Put the title back (the chat may have been auto-renamed), save the outcome, and send a phone notification only on success.
    store.set_title(cid, "⏰ " + task["name"])
    state.schedules.ran(user, task["id"], cid, error)
    if not error and state.flags.on("pwa_push", who):
        state.push.send_later(user, "Emvryx: " + task["name"][:40], "Your scheduled task is ready.", "/")
    return cid, error


def tick(state):
    """Called every half minute: runs the tasks whose time has come, one at a time in the background."""
    # due() returns the tasks to run and has already moved each to its next time. Each runs in its own background (daemon) thread, so one slow
    # answer does not block the others, and daemon threads never keep the program from exiting.
    for user, task in state.schedules.due():
        threading.Thread(target=run_task, args=(state, user, task), daemon=True).start()
