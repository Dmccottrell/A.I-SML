"""
usage_limits.py - Counting usage and enforcing limits (the plan in docs/APP_SPEC.md, "Usage and limits").

WHAT THIS FILE DOES
    Everything is counted in TOKENS and turned into plain "messages left" for the screen. Three separate numbers:
      * the context window    the most ONE request may hold (not an allowance; see context_window.py)
      * the tank              what you can use right now; refills steadily (token bucket), so no cliff
      * the weekly ceiling    the total of the week; resets at a fixed time in the person's own time zone

    A message costs:  (new text x 1 + earlier chat already held x 0.1 + what Yuvra writes x 1) x the model's weight x the effort level.
    A message is allowed only if BOTH the tank and the week have room. Models running on a person's own device are never counted.

    Flow on the server (so a request can't sneak past, and a failed one isn't charged in full):
        reservation = limiter.reserve(user, model, effort, estimate)   # checks the limits, holds the estimated cost
        ... the model answers ...
        limiter.settle(reservation, fresh_in, cached_in, out)          # replaces the estimate with the real numbers
        (limiter.cancel(reservation) if the request failed before anything was used)
    Over a limit, reserve() raises LimitError, which becomes HTTP 429 with a Retry-After time (LimitError.to_http()).

    Numbers only are stored (user, model, tokens, time), never message text. Everything takes `now` (seconds since 1970) so tests
    can use a fake clock. Limits come from limits.json (a block per plan) and the model list from models.json.
"""
import json
import math
import sqlite3
import time

LIMITS_PATH = "limits.json"
STATUS_WORDS = ((50, "Plenty left"), (20, "Getting low"), (5, "Running low"), (0, "Almost out"))


class LimitError(Exception):
    """A request that may not run now. `code`: week_limit, tank_empty, model_not_in_plan, paused."""

    def __init__(self, code, message, retry_after=None, resets_at=None, choices=None):
        super().__init__(message)
        self.code, self.message, self.retry_after = code, message, retry_after
        self.resets_at, self.choices = resets_at, list(choices or [])

    def to_dict(self):
        return {"code": self.code, "message": self.message, "retry_after": self.retry_after,
                "resets_at": self.resets_at, "choices": self.choices}

    def to_http(self):
        """(status, headers, body) for the server: 429 for limits, 403 for a model the plan doesn't include, 503 when paused."""
        status = {"model_not_in_plan": 403, "paused": 503}.get(self.code, 429)
        headers = {"Retry-After": str(int(math.ceil(self.retry_after)))} if self.retry_after else {}
        return status, headers, self.to_dict()


def load_limits(path=LIMITS_PATH):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    for name, t in cfg["tiers"].items():
        for k in ("tank", "refill_per_hour", "week", "models", "windows"):
            if k not in t:
                raise ValueError(f"limits.json: plan {name!r} is missing {k!r}")
    return cfg


def counted_tokens(fresh_in, cached_in, out, weight, effort_mult, cfg):
    """Tokens charged for one request, after the counting rules, the model's weight and the effort level."""
    m = cfg["multipliers"]
    return (fresh_in * m["fresh_in"] + cached_in * m["cached_in"] + out * m["out"]) * weight * effort_mult


def week_start(now, tz_minutes=0, reset="mon 04:00", window="fixed"):
    """The start of the current weekly window, in seconds since 1970. Fixed: the last `reset` moment in the person's own
    time zone (tz_minutes east of UTC). Rolling: exactly 168 hours ago."""
    if window == "rolling":
        return now - 7 * 86400
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    day, hhmm = reset.split()
    hh, mm = (int(x) for x in hhmm.split(":"))
    local = now + tz_minutes * 60                         # the person's wall clock, as if it were UTC
    days_since_1970 = int(local // 86400)
    weekday = (days_since_1970 + 3) % 7                   # 1970-01-01 was a Thursday (3 with Monday = 0)
    back = (weekday - days.index(day)) % 7
    start_local = (days_since_1970 - back) * 86400 + hh * 3600 + mm * 60
    if start_local > local:
        start_local -= 7 * 86400
    return start_local - tz_minutes * 60


class UsageStore:
    """SQLite: users and their plan, the usage rows, each person's tank, and requests in flight."""

    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS users (user TEXT PRIMARY KEY, tier TEXT, tz_minutes INTEGER, owner INTEGER, overrides TEXT);
            CREATE TABLE IF NOT EXISTS usage (id INTEGER PRIMARY KEY, user TEXT, model TEXT, fresh_in INTEGER, cached_in INTEGER,
                out INTEGER, counted REAL, at REAL);
            CREATE INDEX IF NOT EXISTS usage_user_at ON usage (user, at);
            CREATE TABLE IF NOT EXISTS tank (user TEXT PRIMARY KEY, level REAL, at REAL);
            CREATE TABLE IF NOT EXISTS holds (id INTEGER PRIMARY KEY, user TEXT, model TEXT, est REAL, at REAL);""")

    def add_user(self, user, tier="free", tz_minutes=0, owner=False, overrides=None):
        self.db.execute("INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?, ?)",
                        (user, tier, tz_minutes, 1 if owner else 0, json.dumps(overrides or {})))
        self.db.commit()

    def get_user(self, user):
        r = self.db.execute("SELECT tier, tz_minutes, owner, overrides FROM users WHERE user = ?", (user,)).fetchone()
        if not r:
            raise KeyError(f"unknown user {user!r}")
        return {"user": user, "tier": r[0], "tz_minutes": r[1], "owner": bool(r[2]), "overrides": json.loads(r[3])}

    def week_used(self, user, since):
        r = self.db.execute("SELECT COALESCE(SUM(counted), 0) FROM usage WHERE user = ? AND at >= ?", (user, since)).fetchone()
        return r[0]

    def holds_total(self, user):
        return self.db.execute("SELECT COALESCE(SUM(est), 0) FROM holds WHERE user = ?", (user,)).fetchone()[0]


class Limiter:
    def __init__(self, store, cfg, models):
        """`models`: the list from models.json (each has name, id, cost_weight)."""
        self.store, self.cfg = store, cfg
        self.by_key = {}
        for m in models["models"] if isinstance(models, dict) else models:
            self.by_key[m["name"].lower()] = m                 # newest entry of a name wins (later entries overwrite)

    # ---------------------------------------------------------------- numbers
    def weight(self, model_key):
        return self.by_key[model_key]["cost_weight"] if model_key in self.by_key else 1

    def effective(self, user):
        """The plan's limits with the person's own overrides on top."""
        u = self.store.get_user(user)
        t = dict(self.cfg["tiers"][u["tier"]])
        t.update(u["overrides"])
        return u, t

    def message_cost(self, model_key, effort="balanced"):
        return self.cfg["message_tokens"] * self.weight(model_key) * self.cfg["effort"][effort]

    def tank_level(self, user, cap, refill, now):
        r = self.store.db.execute("SELECT level, at FROM tank WHERE user = ?", (user,)).fetchone()
        if not r:
            return float(cap)                                  # a new person starts with a full tank
        level, at = r
        return min(float(cap), level + refill * max(0.0, now - at) / 3600.0)

    def _set_tank(self, user, level, now):
        self.store.db.execute("INSERT OR REPLACE INTO tank VALUES (?, ?, ?)", (user, level, now))

    def _week(self, user, u, now):
        start = week_start(now, u["tz_minutes"], self.cfg["weekly_reset"], self.cfg["weekly_window"])
        resets_at = start + 7 * 86400
        return start, resets_at

    # ---------------------------------------------------------------- the flow
    def reserve(self, user, model_key, effort, est_counted, now, where="server"):
        """Check the limits and hold the estimated cost. Returns a reservation (or None when nothing is counted).
        Raises LimitError when the request may not run."""
        if where == "device":
            return None                                        # a model on the person's own device: free and uncounted
        if self.cfg.get("paused"):
            raise LimitError("paused", "Yuvra is paused for now. Please try again later.", retry_after=600)
        u, t = self.effective(user)
        allowed = t["models"]
        if allowed != "all" and model_key not in allowed and not u["owner"]:
            raise LimitError("model_not_in_plan", f"{model_key.title()} isn't in your plan.", choices=list(allowed))
        db = self.store.db
        if u["owner"]:                                         # the owner is exempt from every limit
            cur = db.execute("INSERT INTO holds (user, model, est, at) VALUES (?, ?, 0, ?)", (user, model_key, now))
            db.commit()
            return {"id": cur.lastrowid, "user": user, "model": model_key, "est": 0.0, "exempt": True}
        self._release_stale(user, now)
        start, resets_at = self._week(user, u, now)
        used = self.store.week_used(user, start) + self.store.holds_total(user)
        if used + est_counted > t["week"]:
            raise LimitError("week_limit", "You've used this week's allowance.", retry_after=max(1, resets_at - now),
                             resets_at=resets_at, choices=["smaller_model", "on_device", "wait"])
        level = self.tank_level(user, t["tank"], t["refill_per_hour"], now)
        if level < est_counted:
            wait = (est_counted - level) / t["refill_per_hour"] * 3600.0
            raise LimitError("tank_empty", "Your tank is empty for now.", retry_after=wait,
                             choices=["smaller_model", "on_device", "wait"])
        self._set_tank(user, level - est_counted, now)
        cur = db.execute("INSERT INTO holds (user, model, est, at) VALUES (?, ?, ?, ?)", (user, model_key, est_counted, now))
        db.commit()
        return {"id": cur.lastrowid, "user": user, "model": model_key, "est": float(est_counted), "exempt": False}

    def settle(self, res, fresh_in, cached_in, out, effort, now):
        """Replace the held estimate with what was really used. Returns the counted tokens."""
        if res is None:
            return 0.0
        actual = counted_tokens(fresh_in, cached_in, out, self.weight(res["model"]), self.cfg["effort"][effort], self.cfg)
        db = self.store.db
        if not res["exempt"]:
            u, t = self.effective(res["user"])
            level = self.tank_level(res["user"], t["tank"], t["refill_per_hour"], now)
            self._set_tank(res["user"], max(0.0, min(float(t["tank"]), level + res["est"] - actual)), now)
        db.execute("DELETE FROM holds WHERE id = ?", (res["id"],))
        db.execute("INSERT INTO usage (user, model, fresh_in, cached_in, out, counted, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (res["user"], res["model"], int(fresh_in), int(cached_in), int(out), actual, now))
        db.commit()
        return actual

    def cancel(self, res, now):
        """The request failed before anything was used: give the held amount back."""
        if res is None:
            return
        if not res["exempt"]:
            u, t = self.effective(res["user"])
            level = self.tank_level(res["user"], t["tank"], t["refill_per_hour"], now)
            self._set_tank(res["user"], min(float(t["tank"]), level + res["est"]), now)
        self.store.db.execute("DELETE FROM holds WHERE id = ?", (res["id"],))
        self.store.db.commit()

    def _release_stale(self, user, now, older_than=600):
        """A request that never finished (the server restarted) must not hold usage forever."""
        rows = self.store.db.execute("SELECT id, est FROM holds WHERE user = ? AND at < ?", (user, now - older_than)).fetchall()
        for hid, est in rows:
            u, t = self.effective(user)
            level = self.tank_level(user, t["tank"], t["refill_per_hour"], now)
            self._set_tank(user, min(float(t["tank"]), level + est), now)
            self.store.db.execute("DELETE FROM holds WHERE id = ?", (hid,))
        if rows:
            self.store.db.commit()

    # ---------------------------------------------------------------- what the screen shows
    def snapshot(self, user, model_key, effort, now):
        """Everything the Usage screen and the chat's usage line need, in plain numbers."""
        u, t = self.effective(user)
        cost = self.message_cost(model_key, effort)
        level = self.tank_level(user, t["tank"], t["refill_per_hour"], now)
        start, resets_at = self._week(user, u, now)
        used = self.store.week_used(user, start)
        left = max(0.0, t["week"] - used)
        tank_pct, week_pct = level / t["tank"] * 100, left / t["week"] * 100
        models = []
        for key, m in self.by_key.items():
            if t["models"] == "all" or key in t["models"]:
                models.append({"model": key, "messages_left": int(left // (self.cfg["message_tokens"] * m["cost_weight"]))})
        low = min(tank_pct, week_pct)
        word = "Out for now" if min(level, left) <= 0 else next(w for floor, w in STATUS_WORDS if low > floor or floor == 0)
        return {
            "plan": u["tier"], "exempt": u["owner"], "status": word,
            "tank": {"left": level, "cap": t["tank"], "pct": tank_pct, "messages_left": int(level // cost),
                     "full_at": now + (t["tank"] - level) / t["refill_per_hour"] * 3600.0, "refill_per_hour": t["refill_per_hour"]},
            "week": {"used": used, "left": left, "cap": t["week"], "pct_left": week_pct, "messages_left": int(left // cost),
                     "resets_at": resets_at},
            "can_send": int(min(level, left) // cost),          # messages that fit in BOTH the tank and the week
            "by_model": models,
        }


def device_use_is_free():
    """Models on a person's own device are never counted: reserve(..., where='device') returns None."""
    return True
