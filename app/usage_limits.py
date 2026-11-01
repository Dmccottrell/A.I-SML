"""
usage_limits.py - Counting usage and enforcing limits (the plan in docs/APP_SPEC.md, "Usage and limits").

WHAT THIS FILE DOES
    Everything is counted in TOKENS and turned into plain "messages left" for the screen. Three separate numbers:
      * the context window    the most ONE request may hold (not an allowance; see context_window.py)
      * the tank              what you can use in one sitting. Default ("window" mode): the first message starts a 6-hour window and the tank is
                              back to full exactly 6 hours after it started (like a session), so the meter does not creep up while you chat.
                              "steady" mode (limits.json `refill_mode`): refills a little every hour (token bucket), no cliff
      * the weekly ceiling    the total of the week; resets at a fixed time in the person's own time zone

    A message costs:  (new text x 1 + earlier chat already held x 0.1 + what Emvryx writes x 1) x the model's weight x the effort level.
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
# json reads limits.json; math.ceil rounds the Retry-After seconds up to a whole number.
import json
import math

# SafeDB is the project's thread-safe SQLite wrapper (safe_db.py).
from safe_db import SafeDB

# File with the plans (free, plus, ...) and the counting rules. Read by load_limits().
LIMITS_PATH = "limits.json"
# Words for the status line on the Usage screen. Each pair is (percent floor, word): the first row whose floor is below the
# lowest of tank%/week% wins, so 60% left says "Plenty left" and 3% says "Almost out".
STATUS_WORDS = ((50, "Plenty left"), (20, "Getting low"), (5, "Running low"), (0, "Almost out"))


class LimitError(Exception):
    """A request that may not run now. `code`: week_limit, tank_empty, model_not_in_plan, paused.

    Raised by Limiter.reserve(). It carries what the screen needs: a plain message, how long to wait (`retry_after`, seconds),
    when the week resets (`resets_at`, seconds since 1970) and what the person can do instead (`choices`).
    """

    def __init__(self, code, message, retry_after=None, resets_at=None, choices=None):
        """Keep the code and message; `choices` defaults to an empty list so the caller never has to check for None."""
        super().__init__(message)
        # Save each piece on the object so to_dict() and to_http() can read it later.
        self.code, self.message, self.retry_after = code, message, retry_after
        self.resets_at, self.choices = resets_at, list(choices or [])

    def to_dict(self):
        """The error as a plain dict (JSON-friendly): this becomes the body of the HTTP answer."""
        return {"code": self.code, "message": self.message, "retry_after": self.retry_after,
                "resets_at": self.resets_at, "choices": self.choices}

    def to_http(self):
        """(status, headers, body) for the server: 429 for limits, 403 for a model the plan doesn't include, 503 when paused."""
        # Turn the error code into an HTTP status number. Anything not listed here (week_limit, tank_empty) is a 429 "too many requests".
        status = {"model_not_in_plan": 403, "model_unavailable": 403, "paused": 503, "gaming": 503, "bad_effort": 400,
                  "deep_needs_bigger": 409, "effort_not_available": 409}.get(self.code, 429)
        # Retry-After is a standard HTTP header telling the app how many seconds to wait. Round up so we never say "0";
        # no wait time means no header at all.
        headers = {"Retry-After": str(int(math.ceil(self.retry_after)))} if self.retry_after else {}
        return status, headers, self.to_dict()


def load_limits(path=LIMITS_PATH):
    """Read the limits file and check each plan has every setting the code needs.

    `path`: where limits.json is. Returns the parsed dict. Raises ValueError naming the plan and the missing setting, so a typo in
    the file is caught when the server starts, not in the middle of someone's chat."""
    # utf-8 so any character in the file reads the same on every machine.
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    # cfg["tiers"] maps a plan name to its settings; check each plan has all five required keys.
    for name, t in cfg["tiers"].items():
        for k in ("tank", "refill_per_hour", "week", "models", "windows"):
            if k not in t:
                raise ValueError(f"limits.json: plan {name!r} is missing {k!r}")
    return cfg


def counted_tokens(fresh_in, cached_in, out, weight, effort_mult, cfg):
    """Tokens charged for one request, after the counting rules, the model's weight and the effort level."""
    # m holds the three counting multipliers from limits.json (fresh text x 1, remembered chat x 0.1, written reply x 1 by default).
    m = cfg["multipliers"]
    # Add up the three kinds of tokens with their multipliers, then scale by how heavy the model is and the effort level.
    return (fresh_in * m["fresh_in"] + cached_in * m["cached_in"] + out * m["out"]) * weight * effort_mult


def week_start(now, tz_minutes=0, reset="mon 04:00", window="fixed"):
    """The start of the current weekly window, in seconds since 1970. Fixed: the last `reset` moment in the person's own
    time zone (tz_minutes east of UTC). Rolling: exactly 168 hours ago."""
    # Rolling mode needs no calendar maths: the week is just the last 7 days.
    if window == "rolling":
        return now - 7 * 86400
    # Weekday names in Monday-first order, so list position = weekday number.
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    # `reset` looks like "mon 04:00": split it into the day name and the clock time, then the clock time into hours and minutes.
    day, hhmm = reset.split()
    hh, mm = (int(x) for x in hhmm.split(":"))
    local = now + tz_minutes * 60                         # the person's wall clock, as if it were UTC
    # How many whole days have passed since 1 Jan 1970 on the person's wall clock.
    days_since_1970 = int(local // 86400)
    weekday = (days_since_1970 + 3) % 7                   # 1970-01-01 was a Thursday (3 with Monday = 0)
    # How many days back to the most recent reset day (the % 7 wraps around the week).
    back = (weekday - days.index(day)) % 7
    # Midnight of that day, plus the reset hour and minute, in seconds (still in the person's wall clock).
    start_local = (days_since_1970 - back) * 86400 + hh * 3600 + mm * 60
    # If that moment is still in the future (e.g. it is Monday 03:00 and the reset is Monday 04:00), the real start was a week earlier.
    if start_local > local:
        start_local -= 7 * 86400
    # Convert back from the person's wall clock to real seconds since 1970.
    return start_local - tz_minutes * 60


class UsageStore:
    """SQLite: users and their plan, the usage rows, each person's tank, and requests in flight."""

    def __init__(self, path=":memory:"):
        """Open the database (a file, or memory when `path` is ":memory:" as in tests) and create the tables if they are missing."""
        self.db = SafeDB(path)                                   # shared by the server's threads (safe_db.py)
        # users: one row per person (plan, time zone, owner flag, personal overrides as JSON text).
        # usage: one row per finished request, numbers only (never message text).
        # tank: each person's current tank level and when it was set.  holds: estimates for requests that are running right now.
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS users (user TEXT PRIMARY KEY, tier TEXT, tz_minutes INTEGER, owner INTEGER, overrides TEXT);
            CREATE TABLE IF NOT EXISTS usage (id INTEGER PRIMARY KEY, user TEXT, model TEXT, fresh_in INTEGER, cached_in INTEGER,
                out INTEGER, counted REAL, at REAL);
            CREATE INDEX IF NOT EXISTS usage_user_at ON usage (user, at);
            CREATE TABLE IF NOT EXISTS tank (user TEXT PRIMARY KEY, level REAL, at REAL);
            CREATE TABLE IF NOT EXISTS holds (id INTEGER PRIMARY KEY, user TEXT, model TEXT, est REAL, at REAL);""")
        try:                                                     # the tank size a window started with (a raised plan then counts at once, not after the window)
            self.db.execute("ALTER TABLE tank ADD COLUMN cap REAL")
            self.db.commit()
        except Exception:                                        # noqa: BLE001 - the column is already there
            pass

    def add_user(self, user, tier="free", tz_minutes=0, owner=False, overrides=None):
        """Create or replace a person. `overrides` is a dict of personal limit changes that sit on top of the plan (e.g. a bigger week)."""
        # INSERT OR REPLACE: adding the same user again updates their row. The ? marks are filled from the tuple, which keeps values out of the SQL text.
        self.db.execute("INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?, ?)",
                        (user, tier, tz_minutes, 1 if owner else 0, json.dumps(overrides or {})))
        self.db.commit()

    def delete_user(self, user):
        """Everything stored about one person (their plan row, usage rows, tank and holds)."""
        # Same delete for each table that holds a user's rows. The table names are fixed here (not user input), so building the SQL with an f-string is safe.
        for table in ("users", "usage", "tank", "holds"):
            self.db.execute(f"DELETE FROM {table} WHERE user = ?", (user,))
        self.db.commit()

    def get_user(self, user):
        """The saved row for one person as a dict. Raises KeyError when the person is unknown."""
        r = self.db.execute("SELECT tier, tz_minutes, owner, overrides FROM users WHERE user = ?", (user,)).fetchone()
        if not r:
            raise KeyError(f"unknown user {user!r}")
        return {"user": user, "tier": r[0], "tz_minutes": r[1], "owner": bool(r[2]), "overrides": json.loads(r[3])}

    def week_used(self, user, since):
        """Total counted tokens a person has used since the time `since` (seconds since 1970). COALESCE turns "no rows" into 0."""
        r = self.db.execute("SELECT COALESCE(SUM(counted), 0) FROM usage WHERE user = ? AND at >= ?", (user, since)).fetchone()
        return r[0]

    def typical_cost(self, user, model, n=20):
        """What this person's recent messages on this model really counted, on average (None with fewer than 3): for an honest "about N messages left"."""
        # Newest-first rows for this person and model, ignoring free (0) ones; `n` caps how many we average.
        rows = self.db.execute("SELECT counted FROM usage WHERE user = ? AND model = ? AND counted > 0 ORDER BY at DESC LIMIT ?", (user, model, n)).fetchall()
        # Fewer than 3 samples is too little to trust, so give None and let the caller fall back to the plain rule.
        return sum(r[0] for r in rows) / len(rows) if len(rows) >= 3 else None

    def holds_total(self, user):
        """Tokens currently held by running requests for this person (their estimates, not yet settled)."""
        return self.db.execute("SELECT COALESCE(SUM(est), 0) FROM holds WHERE user = ?", (user,)).fetchone()[0]


class Limiter:
    """Does the checking and counting. Needs the store (database), the limits dict and the model list.

    Used from the server: reserve() before a request, settle() after, cancel() on failure, snapshot() for the Usage screen.
    """

    def __init__(self, store, cfg, models):
        """`models`: the list from models.json (each has name, id, cost_weight)."""
        self.store, self.cfg = store, cfg
        # Index the models by lowercase name so lookups by key are easy.
        self.by_key = {}
        for m in models["models"] if isinstance(models, dict) else models:
            self.by_key[m["name"].lower()] = m                 # newest entry of a name wins (later entries overwrite)

    # ---------------------------------------------------------------- numbers
    def weight(self, model_key):
        """How heavy a model is (cost_weight in models.json). Unknown models count as 1."""
        return self.by_key[model_key]["cost_weight"] if model_key in self.by_key else 1

    def effective(self, user):
        """The plan's limits with the person's own overrides on top."""
        # Start from the plan's settings (copied so we do not change the shared dict), then lay the person's own overrides on top.
        u = self.store.get_user(user)
        t = dict(self.cfg["tiers"][u["tier"]])
        t.update(u["overrides"])
        return u, t

    def code_rate(self):
        """What a VryxCode step counts compared with a chat message of the same size: every step sends the project again, so it counts less."""
        return float(self.cfg.get("code_rate", 1))

    def code_step_cost(self, model_key):
        """A typical VryxCode step after the counting rules, for the "about N coding steps" line."""
        return self.cfg.get("code_step_tokens", 6000) * self.weight(model_key) * self.code_rate()

    def message_cost(self, model_key, effort="balanced"):
        """Tokens one typical chat message costs on this model at this effort level (message_tokens x model weight x effort multiplier)."""
        return self.cfg["message_tokens"] * self.weight(model_key) * self.cfg["effort"][effort]

    # ---- the tank in "window" mode: full -> the first spend starts a window -> full again `refill_hours` after it started
    def window_mode(self):
        """True when the tank uses the 6-hour window style; False for the "steady" hourly refill."""
        return self.cfg.get("refill_mode", "steady") == "window"

    def refill_hours(self, t):
        """Hours a window lasts. A plan can set its own `refill_hours`; otherwise the global setting; otherwise 6."""
        return float(t.get("refill_hours", self.cfg.get("refill_hours", 6)))

    def _window(self, user, t, now):
        """(level, start, end) of the person's active window, or None when there is none (the tank is full)."""
        # The saved tank row: level, the time the window started (at), and the tank size it started with (cap).
        r = self.store.db.execute("SELECT level, at, cap FROM tank WHERE user = ?", (user,)).fetchone()
        if not r:
            # No row means the person has not spent anything yet: no window, tank is full.
            return None
        # The window ends `refill_hours` after it started (hours x 3600 = seconds).
        end = r[1] + self.refill_hours(t) * 3600.0
        level = r[0] + max(0.0, float(t["tank"]) - r[2]) if r[2] else r[0]      # the plan grew since the window started: the extra is there at once
        return None if now >= end else (min(float(t["tank"]), level), r[1], end)

    def level_of(self, user, t, now):
        """The tank level right now in whichever mode is on."""
        if self.window_mode():
            w = self._window(user, t, now)
            return float(t["tank"]) if w is None else w[0]
        return self.tank_level(user, t["tank"], t["refill_per_hour"], now)

    def full_at(self, user, t, now, level):
        """The moment the tank will be full again (seconds since 1970). Already full gives `now`."""
        # 1e-9 is a tiny allowance so rounding errors in decimals do not make a full tank look slightly short.
        if level >= t["tank"] - 1e-9:
            return now
        if self.window_mode():
            w = self._window(user, t, now)
            return w[2] if w else now
        # Steady mode: missing tokens divided by the refill speed (tokens per hour) gives hours; x 3600 gives seconds.
        return now + (t["tank"] - level) / t["refill_per_hour"] * 3600.0

    def wait_for(self, user, t, need, now, level):
        """Seconds until `need` tokens are available."""
        if self.window_mode():
            w = self._window(user, t, now)
            # At least 1 second so the app never gets a wait of zero.
            return max(1.0, (w[2] - now) if w else 1.0)
        return (need - level) / t["refill_per_hour"] * 3600.0

    def spend(self, user, t, new_level, now):
        """Store the level after a request starts. In window mode the first spend starts the window."""
        if self.window_mode():
            w = self._window(user, t, now)
            # A window keeps its original start time (w[1]) once running; only the first spend after a full tank starts a new one at `now`.
            self.store.db.execute("INSERT OR REPLACE INTO tank (user, level, at, cap) VALUES (?, ?, ?, ?)", (user, new_level, w[1] if w else now, float(t["tank"])))
        else:
            self._set_tank(user, new_level, now)

    def adjust(self, user, t, delta, now):
        """Give back (+) or take (-) tokens after the fact. In window mode this never starts a window (and does nothing once the window has ended)."""
        if self.window_mode():
            w = self._window(user, t, now)
            if w:
                self.store.db.execute("INSERT OR REPLACE INTO tank (user, level, at, cap) VALUES (?, ?, ?, ?)",
                                      (user, max(0.0, min(float(t["tank"]), w[0] + delta)), w[1], float(t["tank"])))
        else:
            level = self.tank_level(user, t["tank"], t["refill_per_hour"], now)
            self._set_tank(user, max(0.0, min(float(t["tank"]), level + delta)), now)

    def tank_level(self, user, cap, refill, now):
        """Steady mode: the level now = last saved level plus what refilled since, never above the tank size `cap`."""
        r = self.store.db.execute("SELECT level, at FROM tank WHERE user = ?", (user,)).fetchone()
        if not r:
            return float(cap)                                  # a new person starts with a full tank
        # refill is tokens per HOUR, elapsed time is in seconds, so divide by 3600. max(0, ...) guards against a clock that moved backwards.
        level, at = r
        return min(float(cap), level + refill * max(0.0, now - at) / 3600.0)

    def _set_tank(self, user, level, now):
        """Save the tank level and the time it was set (steady mode)."""
        self.store.db.execute("INSERT OR REPLACE INTO tank (user, level, at) VALUES (?, ?, ?)", (user, level, now))

    def _week(self, user, u, now):
        """(start, resets_at) of this person's current week, both in seconds since 1970."""
        start = week_start(now, u["tz_minutes"], self.cfg["weekly_reset"], self.cfg["weekly_window"])
        resets_at = start + 7 * 86400
        return start, resets_at

    # ---------------------------------------------------------------- the flow
    def reserve(self, *a, **k):
        """Locked wrapper around _reserve(): the lock makes the check and the hold happen as one step."""
        with self.store.db.lock:                               # check-then-spend in one piece: two requests at once cannot both pass
            return self._reserve(*a, **k)

    def _reserve(self, user, model_key, effort, est_counted, now, where="server"):
        """Check the limits and hold the estimated cost. Returns a reservation (or None when nothing is counted).
        Raises LimitError when the request may not run."""
        if where == "device":
            return None                                        # a model on the person's own device: free and uncounted
        u, t = self.effective(user)
        if self.cfg.get("gaming"):                               # Gaming mode: the model is off so the PC can be used for something else, for everyone
            raise LimitError("gaming", "Emvryx is resting while the PC is being used for something else. Please try again in a little while.", retry_after=300)
        if self.cfg.get("paused") and not u["owner"]:
            raise LimitError("paused", "Emvryx is paused for now. Please try again later.", retry_after=600)
        allowed = t["models"]
        if allowed != "all" and model_key not in allowed and not u["owner"]:
            # model_key.title() just capitalises the name for the message.
            raise LimitError("model_not_in_plan", f"{model_key.title()} isn't in your plan.", choices=list(allowed))
        db = self.store.db
        if u["owner"]:                                         # the owner is exempt from every limit
            cur = db.execute("INSERT INTO holds (user, model, est, at) VALUES (?, ?, 0, ?)", (user, model_key, now))
            db.commit()
            return {"id": cur.lastrowid, "user": user, "model": model_key, "est": 0.0, "exempt": True}
        # Drop holds from requests that died before they could settle, so they stop counting against this person.
        self._release_stale(user, now)
        start, resets_at = self._week(user, u, now)
        # This week's use so far plus what other running requests hold: otherwise two requests started together could both slip under the limit.
        used = self.store.week_used(user, start) + self.store.holds_total(user)
        if used + est_counted > t["week"]:
            raise LimitError("week_limit", "You've used this week's allowance.", retry_after=max(1, resets_at - now),
                             resets_at=resets_at, choices=["smaller_model", "on_device", "wait"])
        # How much is in the tank right now; too little means the person must wait for a refill.
        level = self.level_of(user, t, now)
        if level < est_counted:
            wait = self.wait_for(user, t, est_counted, now, level)
            raise LimitError("tank_empty", "Your tank is empty for now.", retry_after=wait,
                             choices=["smaller_model", "on_device", "wait"])
        # Take the estimate out of the tank now; settle() will correct it to the real cost afterwards.
        self.spend(user, t, level - est_counted, now)
        cur = db.execute("INSERT INTO holds (user, model, est, at) VALUES (?, ?, ?, ?)", (user, model_key, est_counted, now))
        db.commit()
        return {"id": cur.lastrowid, "user": user, "model": model_key, "est": float(est_counted), "exempt": False}

    def settle(self, *a, **k):
        """Locked wrapper around _settle()."""
        with self.store.db.lock:                               # check-then-spend in one piece: two requests at once cannot both pass
            return self._settle(*a, **k)

    def _settle(self, res, fresh_in, cached_in, out, effort, now, rate=1.0):
        """Replace the held estimate with what was really used. Returns the counted tokens. `rate`: VryxCode steps pass code_rate()."""
        if res is None:
            return 0.0
        # The real cost: the same counting rules as the estimate, but with the true token numbers (x `rate` for VryxCode steps).
        actual = counted_tokens(fresh_in, cached_in, out, self.weight(res["model"]), self.cfg["effort"][effort], self.cfg) * rate
        db = self.store.db
        if not res["exempt"]:
            u, t = self.effective(res["user"])
            # Give back (or take) the difference between what we held and what was really used.
            self.adjust(res["user"], t, res["est"] - actual, now)
        # The hold is finished; record the final numbers as a usage row (numbers only, no text).
        db.execute("DELETE FROM holds WHERE id = ?", (res["id"],))
        db.execute("INSERT INTO usage (user, model, fresh_in, cached_in, out, counted, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (res["user"], res["model"], int(fresh_in), int(cached_in), int(out), actual, now))
        db.commit()
        return actual

    def cancel(self, *a, **k):
        """Locked wrapper around _cancel()."""
        with self.store.db.lock:                               # check-then-spend in one piece: two requests at once cannot both pass
            return self._cancel(*a, **k)

    def _cancel(self, res, now):
        """The request failed before anything was used: give the held amount back."""
        if res is None:
            return
        if not res["exempt"]:
            u, t = self.effective(res["user"])
            self.adjust(res["user"], t, res["est"], now)
        self.store.db.execute("DELETE FROM holds WHERE id = ?", (res["id"],))
        self.store.db.commit()

    def _release_stale(self, user, now, older_than=600):
        """A request that never finished (the server restarted) must not hold usage forever."""
        rows = self.store.db.execute("SELECT id, est FROM holds WHERE user = ? AND at < ?", (user, now - older_than)).fetchall()
        # Each stale hold is handed back to the tank and deleted.
        for hid, est in rows:
            u, t = self.effective(user)
            self.adjust(user, t, est, now)
            self.store.db.execute("DELETE FROM holds WHERE id = ?", (hid,))
        if rows:
            self.store.db.commit()

    # ---------------------------------------------------------------- what the screen shows
    def snapshot(self, user, model_key, effort, now, real=False):
        """Everything the Usage screen and the chat's usage line need, in plain numbers. `real` (flag chat_fixes): "messages left" from what this
        person's recent messages on this model really cost (long chats and big models cost more than a short one), never fewer than the plain rule."""
        u, t = self.effective(user)
        # Cost of one message for the "messages left" maths.
        cost = self.message_cost(model_key, effort)
        if real:
            cost = max(cost, self.store.typical_cost(user, model_key) or 0)
        # Tank level now.
        level = self.level_of(user, t, now)
        # Where the week starts and when it resets.
        start, resets_at = self._week(user, u, now)
        used = self.store.week_used(user, start)
        # Tokens left in the week, never below zero.
        left = max(0.0, t["week"] - used)
        # How full the tank and the week are, as percentages.
        tank_pct, week_pct = level / t["tank"] * 100, left / t["week"] * 100
        # Per model, how many messages would fit in the rest of the week (only models in the person's plan).
        models = []
        for key, m in self.by_key.items():
            if t["models"] == "all" or key in t["models"]:
                models.append({"model": key, "messages_left": int(left // (self.cfg["message_tokens"] * m["cost_weight"]))})
        # The scarcer of tank and week decides the status word.
        low = min(tank_pct, week_pct)
        # Empty means "Out for now"; otherwise the first status row whose floor is below the percentage (a floor of 0 always matches).
        word = "Out for now" if min(level, left) <= 0 else next(w for floor, w in STATUS_WORDS if low > floor or floor == 0)
        # The answer: plain numbers for the tank, the week, how many messages can be sent now, and a per-model list.
        return {
            "plan": u["tier"], "exempt": u["owner"], "status": word,
            "tank": {"left": level, "cap": t["tank"], "pct": tank_pct, "messages_left": int(level // cost),
                     "full_at": self.full_at(user, t, now, level), "refill_per_hour": t["refill_per_hour"] if not self.window_mode() else t["tank"] / self.refill_hours(t),
                     "mode": "window" if self.window_mode() else "steady", "refill_hours": self.refill_hours(t) if self.window_mode() else t["tank"] / t["refill_per_hour"]},
            "week": {"used": used, "left": left, "cap": t["week"], "pct_left": week_pct, "messages_left": int(left // cost),
                     "resets_at": resets_at},
            "can_send": int(min(level, left) // cost),          # messages that fit in BOTH the tank and the week
            "by_model": models,
        }


def device_use_is_free():
    """Models on a person's own device are never counted: reserve(..., where='device') returns None."""
    return True
