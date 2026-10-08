"""
summary.py - The owner's weekly summary: what happened on this Emvryx in the last seven days, in plain words.

WHAT THIS FILE DOES
    Counts (no chat is read, no question is quoted): people and new sign-ups, sign-ins and wrong tries, lockouts, messages and which models answered, reports people sent
    with the Report button, errors since the server started, and how old the newest backup is. It can be previewed any time (Settings > Owner > Overview), and when the
    owner switches it on it is sent once a week to the owner's email (if mail is set up) and as a short phone alert (if alerts are set up). Nothing is sent anywhere else.
"""
import json
import os
import threading
import time
from collections import Counter

WEEK = 7 * 86400


def _state_path(state):
    return os.path.join(state.data_dir, "summary_state.json") if state.data_dir else None


def last_sent(state):
    path = _state_path(state)
    try:
        with open(path, encoding="utf-8") as f:
            return float(json.load(f).get("last", 0))
    except (OSError, TypeError, ValueError):
        return getattr(state, "_summary_last", 0.0)


def set_last(state, when):
    state._summary_last = when
    path = _state_path(state)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"last": when}, f)


def latest_backup_age_days(state, now):
    import data_tools
    d = data_tools.backup_dir(state)
    try:
        newest = max((os.path.getmtime(os.path.join(d, f)) for f in os.listdir(d) if f.startswith("emvryx-") and f.endswith(".zip")), default=None)
    except OSError:
        newest = None
    return None if newest is None else max(0, int((now - newest) // 86400))


def build(state, now=None, days=7):
    now = time.time() if now is None else now
    since = now - days * 86400
    people = list({u["user"] for u in state.users.values()})
    msgs, by_model = 0, Counter()
    for name in people:
        try:
            m, models = state.store(name).stats(since)
        except Exception:
            continue
        msgs += m
        by_model.update(models)
    names = {m["id"]: f"{m['name']} {m.get('version', '')}".strip() for m in state.manifest["models"]}
    ev = lambda kind: state.auth.count(kind, since)
    fb = state.feedback.counts()
    backup = latest_backup_age_days(state, now)
    numbers = {"people": len(people), "new_accounts": ev("signup"), "sign_ins": ev("login_ok"), "wrong_tries": ev("login_fail"), "lockouts": ev("lockout"), "messages": msgs,
               "reports_new": fb["new"], "server_errors": state.metrics.get("errors", 0), "backup_age_days": backup}
    day = lambda t: time.strftime("%d %b", time.localtime(t))
    lines = [f"Emvryx, {day(since)} to {day(now)}", "",
             f"People: {numbers['people']} accounts, {numbers['new_accounts']} new this week.",
             f"Sign-ins: {numbers['sign_ins']}. Wrong tries: {numbers['wrong_tries']}. Lockouts: {numbers['lockouts']}.",
             f"Messages asked: {msgs}" + (" (" + ", ".join(f"{names.get(k, k or 'unknown')} {v}" for k, v in by_model.most_common(5)) + " answers)" if by_model else "") + ".",
             f"Reports under answers still to read: {fb['new']}" + (" (" + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in sorted(fb['by_kind'].items(), key=lambda kv: -kv[1])[:3]) + ")" if fb["by_kind"] else "") + ".",
             f"Server errors since it started: {numbers['server_errors']}.",
             "Backup: " + ("none found yet. Make one in Settings > Owner > Backups." if backup is None else f"the newest is {backup} day(s) old." + (" That is old: make a new one." if backup > 7 else ""))]
    return {"subject": f"Emvryx weekly summary ({day(since)} to {day(now)})", "text": "\n".join(lines), "numbers": numbers,
            "short": f"Emvryx this week: {msgs} messages, {numbers['sign_ins']} sign-ins, {numbers['wrong_tries']} wrong tries, {fb['new']} reports to read."}


def deliver(state, now=None):
    """Send the summary: by email to the owner (when mail and the owner's email exist) and as a phone alert. Returns {"text", "emailed", "alerted"}; never raises."""
    now = time.time() if now is None else now
    s = build(state, now)
    rec = state.user_record("owner") or {}
    emailed = alerted = False
    if state.mailer and rec.get("email"):
        try:
            state.mailer.send(rec["email"], s["subject"], s["text"])
            emailed = True
        except Exception as e:
            print(f"(weekly summary email failed: {e})")
    if state.security.get("alert_ntfy_topic"):
        state.alert("weekly_summary", s["short"], per_hour=2)
        alerted = True
    set_last(state, now)
    return {"text": s["text"], "subject": s["subject"], "emailed": emailed, "alerted": alerted}


def due(state, now=None):
    now = time.time() if now is None else now
    return bool(state.security.get("weekly_summary")) and now - last_sent(state) >= WEEK


def start(state, every=1800):
    """A background thread that sends the summary when a week has passed since the last one (or since it was switched on)."""
    def loop():
        while True:
            time.sleep(every)
            try:
                if due(state):
                    deliver(state)
            except Exception as e:
                print(f"(weekly summary: {e})")
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t
