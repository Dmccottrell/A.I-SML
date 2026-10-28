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

MAX_TASKS = 10
KINDS = ("daily", "weekdays", "weekly", "once")
TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
MAX_PROMPT = 2000


def _hm(t):
    m = TIME.match(str(t or ""))
    if not m:
        raise ValueError("Pick a time like 07:30.")
    return int(m.group(1)), int(m.group(2))


def next_run(task, after):
    """The next time (UTC seconds) after `after` that `task` is due, or None (a "once" task that has passed)."""
    h, mi = _hm(task["time"])
    off = int(task.get("tz", 0)) * 60                              # the person's clock = UTC + off
    if task["when"] == "once":
        m = DATE.match(str(task.get("date", "")))
        if not m:
            raise ValueError("Pick a date.")
        local = time.struct_time((int(m.group(1)), int(m.group(2)), int(m.group(3)), h, mi, 0, 0, 0, 0))
        at = _timegm(local) - off
        return at if at > after else None
    days = {"daily": set(range(7)), "weekdays": {0, 1, 2, 3, 4}}.get(task["when"])
    if days is None:
        days = {int(d) for d in task.get("days") or [] if str(d).isdigit() and 0 <= int(d) <= 6}       # 0 = Monday
        if not days:
            raise ValueError("Pick at least one day.")
    local_now = time.gmtime(after + off)
    base = _timegm(time.struct_time((local_now.tm_year, local_now.tm_mon, local_now.tm_mday, h, mi, 0, 0, 0, 0))) - off
    for add in range(0, 8):
        at = base + add * 86400
        if at > after and time.gmtime(at + off).tm_wday in days:
            return at
    return None


def _timegm(t):
    import calendar
    return calendar.timegm(t)


def describe(task):
    """ "Every weekday at 07:30", for the list """
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    if task["when"] == "daily":
        return f"Every day at {task['time']}"
    if task["when"] == "weekdays":
        return f"Every weekday at {task['time']}"
    if task["when"] == "weekly":
        return "Every " + ", ".join(names[int(d)] for d in sorted(task.get("days") or [])) + f" at {task['time']}"
    return f"On {task.get('date')} at {task['time']}"


class Schedules:
    def __init__(self, data_dir, clock=time.time):
        self.path = os.path.join(data_dir, "schedules.json") if data_dir else None
        self.clock = clock
        self.lock = threading.Lock()
        self.tasks = {}                                             # user -> [task]
        if self.path:
            try:
                with open(self.path, encoding="utf-8") as f:
                    got = json.load(f)
                self.tasks = got if isinstance(got, dict) else {}
            except (OSError, ValueError):
                pass

    def _save(self):
        if not self.path:
            return
        with open(self.path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self.tasks, f)
        os.replace(self.path + ".tmp", self.path)

    def list(self, user):
        return [dict(t, said=describe(t)) for t in self.tasks.get(user, [])]

    def get(self, user, task_id):
        return next((t for t in self.tasks.get(user, []) if t["id"] == task_id), None)

    def add(self, user, body):
        prompt = str(body.get("prompt", "")).strip()
        if not prompt:
            raise ValueError("Write what Emvryx should do.")
        if len(prompt) > MAX_PROMPT:
            raise ValueError("That is too long for a scheduled task.")
        when = str(body.get("when", "daily"))
        if when not in KINDS:
            raise ValueError("Pick how often.")
        tz = body.get("tz", 0)
        if not isinstance(tz, int) or isinstance(tz, bool) or not -14 * 60 <= tz <= 14 * 60:
            tz = 0
        task = {"id": uuid.uuid4().hex[:12], "name": (" ".join(str(body.get("name") or prompt).split()))[:60], "prompt": prompt, "when": when,
                "time": str(body.get("time", "")), "days": [int(d) for d in body.get("days") or [] if str(d).isdigit()][:7],
                "date": str(body.get("date", ""))[:10], "tz": tz, "model": str(body.get("model", ""))[:40],
                "effort": str(body.get("effort", "balanced"))[:12], "chat": None, "last_run": None, "runs": 0, "on": True, "last_error": ""}
        task["next_run"] = next_run(task, self.clock())             # raises ValueError for a bad time, date or days
        if task["next_run"] is None:
            raise ValueError("That time has already passed.")
        with self.lock:
            mine = self.tasks.setdefault(user, [])
            if len(mine) >= MAX_TASKS:
                raise ValueError(f"You can have up to {MAX_TASKS} scheduled tasks. Delete one first.")
            mine.append(task)
            self._save()
        return dict(task, said=describe(task))

    def delete(self, user, task_id):
        with self.lock:
            before = len(self.tasks.get(user, []))
            self.tasks[user] = [t for t in self.tasks.get(user, []) if t["id"] != task_id]
            self._save()
            return len(self.tasks[user]) < before

    def set_on(self, user, task_id, on):
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
            for user, tasks in self.tasks.items():
                for t in tasks:
                    if t.get("on") and t.get("next_run") and t["next_run"] <= now:
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
    cat = state.catalog(who)
    cards = [m for m in cat["cards"] + cat["other"] if m.get("state") == "ready"]
    pick = next((m for m in cards if m["id"] == wanted), None) or (cards[0] if cards else None)
    return pick["id"] if pick else wanted


def run_task(state, user, task, wait=900):
    """Answers one scheduled task now, into its own chat, and tells the person. Returns (chat_id, error)."""
    import chat_turn
    who = state.who_name(user)
    if not who:
        return None, "gone"
    if not state.flags.on("chat_schedule", who):
        state.schedules.ran(user, task["id"], None, "Scheduled tasks are switched off.")
        return None, "off"
    if state.cfg.get("gaming"):
        state.schedules.ran(user, task["id"], None, "Emvryx was resting (Gaming mode): it runs again at the next time.")
        return None, "resting"
    store = state.store(user)
    cid = task.get("chat")
    if cid is None or not store.exists(cid):
        cid = store.new_chat(title="⏰ " + task["name"])
    error = ""
    try:
        q, _stop, _model, _win, _decision = chat_turn.start_turn(state, who, cid, task["prompt"], _model_for(state, who, task.get("model")),
                                                                 task.get("effort") or "balanced")
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
    store.set_title(cid, "⏰ " + task["name"])
    state.schedules.ran(user, task["id"], cid, error)
    if not error and state.flags.on("pwa_push", who):
        state.push.send_later(user, "Emvryx: " + task["name"][:40], "Your scheduled task is ready.", "/")
    return cid, error


def tick(state):
    """Called every half minute: runs the tasks whose time has come, one at a time in the background."""
    for user, task in state.schedules.due():
        threading.Thread(target=run_task, args=(state, user, task), daemon=True).start()
