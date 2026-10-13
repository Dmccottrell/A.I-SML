"""
routes_admin.py - The owner and admin web routes (/api/admin/...).
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import re
import shutil
import subprocess
import time
import data_tools
import live_data


class RoutesAdmin:
    """The admin routes."""

    def api_admin(self, path, body):
        st = self.state
        if path == "/api/admin/users":
            name, tier = str(body.get("user", "")), str(body.get("tier", "free"))
            try:
                key = st.add_user(name, tier, email=body.get("email") or None)
            except ValueError as e:
                return self._send(400, {"code": "bad_request", "message": str(e)})
            st.set_plan(name, tier)
            pair = st.auth.new_pair(name, st.security["pair_minutes"], made_by="owner")
            st.auth.event("pair_created", name, self._ip(), "by owner")
            return self._send(200, {"user": name, "tier": tier, "key": key, "pair": pair, "pair_minutes": st.security["pair_minutes"]})
        if path == "/api/admin/pairing":
            name = str(body.get("user", ""))
            if not st.user_record(name):
                return self._send(404, {"code": "not_found", "message": "No one is called that."})
            pair = st.auth.new_pair(name, st.security["pair_minutes"], made_by="owner")
            st.auth.event("pair_created", name, self._ip(), "by owner")
            return self._send(200, {"user": name, "pair": pair, "pair_minutes": st.security["pair_minutes"]})
        if path == "/api/admin/ban":
            try:
                st.set_ban(str(body.get("user", "")), bool(body.get("banned", True)))
            except ValueError as e:
                return self._send(400, {"code": "bad_request", "message": str(e)})
            return self._send(200, {"ok": True})
        if path == "/api/admin/signups":
            mode = str(body.get("mode", ""))
            if mode not in ("closed", "invite", "open"):
                return self._send(400, {"code": "bad_request", "message": "Choose closed, invite or open."})
            st.save_security(signup_mode=mode, open_signups=(mode == "open"))
            st.auth.event("signups_changed", "owner", self._ip(), mode)
            return self._send(200, {"mode": mode})
        if path == "/api/admin/invites":
            tier = str(body.get("tier", "free"))
            if tier not in st.cfg["tiers"]:
                return self._send(400, {"code": "bad_request", "message": "Unknown plan."})
            code = st.auth.new_invite(tier, int(body.get("uses") or 1), max(1, min(int(body.get("days") or 14), 90)), str(body.get("note", "")))
            st.auth.event("invite_made", "owner", self._ip(), tier)
            return self._send(200, {"code": code, "tier": tier})
        if path == "/api/admin/invites/revoke":
            return self._send(200, {"ok": st.auth.revoke_invite(str(body.get("id", "")))})
        if path == "/api/admin/mfa-reset":
            name = str(body.get("user", ""))
            if not st.user_record(name):
                return self._send(404, {"code": "not_found", "message": "No one is called that."})
            st.mfa_disable(name)
            st.auth.revoke_user(name)
            st.auth.event("mfa_reset_by_owner", name, self._ip(), "")
            return self._send(200, {"ok": True})
        if path == "/api/admin/cloud":
            host, user = str(body.get("host", "")).strip(), str(body.get("user", "root")).strip() or "root"
            try:
                port = int(body.get("port") or 22)
            except (TypeError, ValueError):
                port = 0
            if host and not re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", host):
                return self._send(400, {"code": "bad_request", "message": "That host doesn't look right.", "action": "Use the address from your provider, like ssh5.vast.ai or 203.0.113.7."})
            if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user) or not 1 <= port <= 65535:
                return self._send(400, {"code": "bad_request", "message": "The user or port doesn't look right.", "action": "Usually the user is root and the port is the one your provider shows."})
            st.save_security(cloud_host=host, cloud_user=user, cloud_port=port, cloud_for_others=bool(body.get("for_others")))
            st.apply_cloud()
            st.auth.event("cloud_changed", "owner", self._ip(), host)
            return self._send(200, st.cloud_status())
        if path == "/api/admin/cloud/keygen":
            key, _ = st.cloud_paths()
            if os.path.exists(key) and not body.get("replace"):
                return self._send(200, st.cloud_status())
            if not shutil.which("ssh-keygen"):
                return self._send(400, {"code": "no_keygen", "message": "This computer has no ssh-keygen program.", "action": "On Windows, turn on 'OpenSSH Client' in Optional features."})
            for f in (key, key + ".pub"):
                try:
                    os.remove(f)
                except OSError:
                    pass
            os.makedirs(os.path.dirname(key), exist_ok=True)
            r = subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "emvryx-cloud", "-f", key], capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                return self._send(400, {"code": "keygen", "message": "Making the key failed: " + (r.stderr or r.stdout).strip()[-160:]})
            try:
                os.chmod(key, 0o600)
            except OSError:
                pass
            st.auth.event("cloud_key_made", "owner", self._ip(), "")
            return self._send(200, st.cloud_status())
        if path == "/api/admin/cloud/test":
            ok, why = st.code.cloud_ready(True)
            if not ok:
                return self._send(400, {"code": "cloud", "message": why})
            import cloud_run
            c = st.code.cloud
            r = None
            try:
                r = subprocess.run(cloud_run.ssh_base(c["host"], c["port"], c["user"], c["key"], c["known_hosts"]) + ["echo emvryx-ok; uname -sm; (python3 --version 2>&1 || echo 'python3: missing'); (timeout --version >/dev/null 2>&1 && echo timeout-ok || echo 'timeout: missing')"],
                                   capture_output=True, text=True, timeout=45)
            except (OSError, subprocess.SubprocessError) as e:
                return self._send(400, {"code": "cloud", "message": "Could not run ssh: " + str(e)[:120]})
            if r.returncode != 0 or "emvryx-ok" not in r.stdout:
                return self._send(400, {"code": "cloud", "message": "Could not connect: " + (r.stderr.strip()[-220:] or f"ssh exit {r.returncode}"),
                                        "action": "Check the host, port and user, and that the public key is added to the machine."})
            return self._send(200, {"ok": True, "text": r.stdout.strip()})
        if path == "/api/admin/backups/now":
            if not st.data_dir:
                return self._send(400, {"code": "no_data", "message": "This server keeps nothing on disk (demo mode), so there is nothing to back up."})
            import backup_data
            try:
                target, count, removed = backup_data.make_backup(st.data_dir, data_tools.backup_dir(st), keep=14, projects=bool(body.get("projects", True)))
            except (OSError, SystemExit) as e:
                return self._send(400, {"code": "backup_failed", "message": "The backup did not work: " + str(e)[:160]})
            st.auth.event("backup_made", "owner", self._ip(), os.path.basename(target))
            return self._send(200, {"name": os.path.basename(target), "files": count, "removed": removed})
        if path == "/api/admin/summary":
            import summary as summary_mod
            if body.get("send"):
                return self._send(200, summary_mod.deliver(st))
            built = summary_mod.build(st)
            return self._send(200, {"text": built["text"], "subject": built["subject"]})
        if path == "/api/admin/summary-settings":
            on = bool(body.get("on"))
            st.save_security(weekly_summary=on)
            if on:
                import summary as summary_mod
                if not summary_mod.last_sent(st):
                    summary_mod.set_last(st, time.time())                  # the first one comes a week after switching on
            return self._send(200, {"on": on})
        if path == "/api/admin/sharing":
            st.save_security(sharing=bool(body.get("on")))
            st.auth.event("sharing_changed", "owner", self._ip(), "on" if body.get("on") else "off")
            return self._send(200, {"on": bool(st.security.get("sharing"))})
        if path == "/api/admin/feedback/handle":
            return self._send(200, {"ok": st.feedback.set_status(body.get("id", 0), "handled" if body.get("handled", True) else "new")})
        if path == "/api/admin/sources/test":
            import web_search

            def web_check(name):
                try:
                    got = web_search.SOURCES[name]("who won the most recent world cup", 3, fetch=web_search.get_json)
                except Exception as e:
                    return False, "failed: " + str(e)[:140]
                return bool(got), (f"returned {len(got)} results" if got else "answered, but with no results")
            rows = live_data.check_sources(web_check=web_check)
            st.auth.event("sources_test", "owner", self._ip(), "")
            return self._send(200, {"rows": rows, "using": web_search.pick_source("auto")})
        if path == "/api/admin/mail-test":
            rec = st.user_record("owner") or {}
            if not st.mailer:
                return self._send(400, {"code": "email_off", "message": "Email isn't set up on this server yet.", "action": "Add EMVRYX_SMTP_HOST, EMVRYX_SMTP_USER and EMVRYX_SMTP_PASS to .emvryx\\keys.env and restart (see docs/DEPLOY.md)."})
            if not rec.get("email"):
                return self._send(400, {"code": "no_email", "message": "Your owner account has no email address yet.", "action": "Add it in Settings > Account first."})
            try:
                st.mailer.send(rec["email"], "Emvryx test email", "This is a test from your Emvryx server. If you can read it, email sign-in codes will work.")
            except Exception as e:
                return self._send(400, {"code": "mail_failed", "message": "The mail server said: " + str(e)[:160], "action": "Check the host, port, login and app password."})
            st.auth.event("mail_test", "owner", self._ip(), "")
            return self._send(200, {"ok": True, "to": rec["email"]})
        if path == "/api/admin/pause":
            st.cfg["paused"] = bool(body.get("paused"))
            return self._send(200, {"paused": st.cfg["paused"]})
        self._send(404, {"code": "not_found", "message": "Not found."})
