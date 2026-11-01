"""
state_ops.py - AppState's operations part: alerts, the health check and the owner's overview.

WHERE IT FITS
    AppState (the server's big shared object) is built from mixin classes, one per state_*.py file. A mixin's methods are mixed into AppState,
    so `self` here is the whole AppState (self.security, self.auth, self.users, self.code, self.secrets ... come from other parts).
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import threading
import time
import summary


class StateOps:
    """How the server is doing."""

    def alert(self, kind, text, per_hour=6):
        """A short message to the owner's phone (ntfy) when something security-relevant happens. Off until "alert_ntfy_topic" is set in security.json.
        At most `per_hour` of the same kind, so an attack cannot flood the phone. Never raises, never contains a key, code or token."""
        # ntfy is a free push-notification service; the "topic" is the channel name the owner's phone listens to. No topic = alerts are off.
        topic = str(self.security.get("alert_ntfy_topic") or "")
        if not topic:
            return
        now = time.time()
        # Rate limit: remember when this kind of alert was last sent, keep only the last hour (3600 s), and stop at `per_hour`.
        recent = [t for t in self._alerted.get(kind, []) if now - t < 3600]
        if len(recent) >= per_hour:
            return
        self._alerted[kind] = recent + [now]
        # Send in a background thread (daemon = does not stop the program exiting) so a slow network never delays the request that raised the alert.
        import notify
        threading.Thread(target=notify.send, args=(topic, text, "Emvryx security"), daemon=True).start()

    def health(self):
        """Numbers for the owner: how it is doing and whether anything looks like an attack."""
        # Look at security events from the last hour only (the newest 500 are read, then filtered by time).
        hour = time.time() - 3600
        ev = [e for e in self.auth.events(500) if e["at"] >= hour]
        # count(k): how many of those events were of kind k. (A lambda is a tiny one-line function.)
        count = lambda k: sum(1 for e in ev if e["kind"] == k)
        # Whole-server numbers first, then the last-hour security counts (failed sign-ins and lockouts can hint at someone guessing passwords),
        # then what is running now and which safety features are switched on.
        return {"uptime_minutes": int((time.time() - self.metrics["started"]) / 60), "server_errors": self.metrics["errors"],
                "devices_signed_in": self.auth.db.execute("SELECT COUNT(*) FROM sessions WHERE revoked = 0 AND expires > ?", (time.time(),)).fetchone()[0],
                "last_hour": {"sign_ins": count("login_ok"), "failed_tries": count("login_fail"), "lockouts": count("lockout"), "cross_site_refusals": count("bad_origin"),
                              "key_links_refused": count("key_link_refused")},
                "coding_running": sum(1 for x in self.code.sessions.values() if x.state in ("starting", "working", "asking")),
                "encryption": self.secrets.available, "email_sign_in": bool(self.mailer), "code_sandbox": self.code.sandbox.get("mode", "none"),
                "alerts_on": bool(self.security.get("alert_ntfy_topic"))}

    def admin_overview(self, who):
        """What the owner sees first in the Admin area: sign-up mode, invites, and a checklist of what makes this server safe to share."""
        rec = self.user_record(who["user"]) or {}
        # Is two-step sign-in on for the owner's own account?
        mfa = bool((rec.get("mfa") or {}).get("on"))
        # check(...) builds one checklist row: a short id, whether it passes, what it is, and how to fix it.
        check = lambda id_, ok, title, how: {"id": id_, "ok": bool(ok), "title": title, "how": how}
        # One entry per person (a person can have several credential entries, so key by name to count each once).
        people = list({u["user"]: u for u in self.users.values()}.values())
        # Counts for the top of the Admin screen, then the safety checklist. Each row ends with a hint pointing at the setting that fixes it.
        return {"signup_mode": self.signup_mode(), "sharing": bool(self.security.get("sharing")), "weekly_summary": bool(self.security.get("weekly_summary")), "invites": self.auth.invites(), "people": len(people), "banned": sum(1 for u in people if u.get("banned")),
                "plans": {t: sum(1 for u in people if self.usage.get_user(u["user"])["tier"] == t) for t in self.cfg["tiers"]},
                "checklist": [
                    check("password", rec.get("pw"), "Your owner account has a password", "Settings > Security > Set a password."),
                    check("mfa", mfa, "Your owner account uses two-step sign-in", "Settings > Security > Two-step sign-in."),
                    check("email", rec.get("email") and rec.get("email_verified") is not False, "Your owner account has an email address", "Settings > Account."),
                    check("encryption", self.secrets.available, "Saved tokens and two-step secrets are encrypted", "pip install cryptography, then restart."),
                    check("alerts", self.security.get("alert_ntfy_topic"), "Security alerts reach your phone", "Set alert_ntfy_topic in security.json (see docs/SECURITY.md)."),
                    check("backup", (summary.latest_backup_age_days(self, time.time()) is not None and summary.latest_backup_age_days(self, time.time()) <= 7), "A backup from the last 7 days exists", "Admin > Backups > Make a backup now."),
                    check("mail", self.mailer, "Email sign-in codes work", "Set EMVRYX_SMTP_* (see docs/DEPLOY.md). Optional.")],
                "health": self.health()}
