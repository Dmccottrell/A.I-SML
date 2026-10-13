"""Accounts: passwords, authenticator-app codes, recovery codes, sign-up modes, invites, owner tools."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import time
import unittest

import accounts
import auth
from tests.test_app_server import Base, Client
from tests.test_signin import cookie_of

PW = "correct horse battery"


class Pieces(unittest.TestCase):
    def test_password_hash_checks_and_is_salted(self):
        a, b = accounts.hash_password(PW), accounts.hash_password(PW)
        self.assertNotEqual(a, b)
        self.assertTrue(accounts.verify_password(PW, a))
        self.assertFalse(accounts.verify_password(PW + "x", a))
        self.assertFalse(accounts.verify_password(PW, "garbage"))

    def test_password_rules(self):
        self.assertIn("at least", accounts.password_problem("short"))
        self.assertTrue(accounts.password_problem("password123"))
        self.assertTrue(accounts.password_problem("darrylmccottrell1", "darryl", ""))
        self.assertIsNone(accounts.password_problem(PW, "sam", "sam@x.com"))

    def test_names(self):
        self.assertEqual(accounts.clean_name(" sam_1 "), "sam_1")
        self.assertEqual(accounts.clean_name("Darryl McCottrell"), "Darryl_McCottrell")       # a space becomes _
        for bad in ("ab", "admin", "Owner", "x" * 40, "bad!name", "admin "):
            self.assertIsNone(accounts.clean_name(bad))

    def test_totp_matches_the_rfc_example_and_refuses_reuse(self):
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"                       # RFC 6238: "12345678901234567890"
        self.assertEqual(accounts.code_at(secret, 59 // 30), "287082")     # the RFC's value is 94287082: its last 6 digits
        now = 1_700_000_000
        code = accounts.code_at(secret, now // 30)
        c = accounts.check_totp(secret, code, 0, now)
        self.assertEqual(c, now // 30)
        self.assertIsNone(accounts.check_totp(secret, code, c, now))          # the same code twice
        self.assertEqual(accounts.check_totp(secret, accounts.code_at(secret, now // 30 - 1), 0, now), now // 30 - 1)   # a step late is fine
        self.assertIsNone(accounts.check_totp(secret, accounts.code_at(secret, now // 30 - 3), 0, now))
        self.assertIsNone(accounts.check_totp(secret, "abcdef", 0, now))

    def test_recovery_codes_work_once(self):
        codes = accounts.make_recovery_codes()
        self.assertEqual(len(set(codes)), 8)
        hashes = [accounts.hash_recovery(c) for c in codes]
        ok, left = accounts.use_recovery(hashes, codes[0].upper().replace("-", " "))
        self.assertTrue(ok)
        self.assertEqual(len(left), 7)
        self.assertFalse(accounts.use_recovery(left, codes[0])[0])

    def test_invite_codes_work_however_they_are_typed(self):
        db = auth.AuthDB(":memory:")
        code = db.new_invite("pro", uses=5, days=1, now=1000)
        flat = code.replace("-", "")
        for typed in (code, code.upper(), flat, flat.upper(), " " + code + " ", code.replace("-", " "), code[:4] + code[4:].replace("-", "")):
            self.assertEqual(db.peek_invite(typed, 1001), "pro", typed)
        self.assertIsNone(db.peek_invite(flat[:-1], 1001))
        self.assertIsNone(db.peek_invite("not-a-code", 1001))
        self.assertEqual(db.use_invite(flat.upper(), 1002), "pro")

    def test_invites(self):
        db = auth.AuthDB()
        code = db.new_invite("pro", uses=2, days=1, now=1000)
        self.assertEqual(db.peek_invite(code, 1001), "pro")
        self.assertEqual(db.use_invite(code, 1001), "pro")
        self.assertEqual(db.use_invite(code, 1002), "pro")
        self.assertIsNone(db.use_invite(code, 1003))                         # used up
        late = db.new_invite("free", days=1, now=1000)
        self.assertIsNone(db.peek_invite(late, 1000 + 2 * 86400))            # run out
        self.assertEqual(len(db.invites(now=1000)), 1)


class Flows(Base):
    data_dir = True

    def anon(self):
        return Client(self.port)

    def sign_up(self, name="newbie", email="newbie@example.com", password=PW, invite=None, client=None):
        c = client or self.anon()
        st, j = c.call("POST", "/api/signup", {"name": name, "email": email, "password": password, "invite": invite})
        return c, st, j

    def owner_mode(self, mode):
        self.assertEqual(self.owner.call("POST", "/api/admin/signups", {"mode": mode})[0], 200)

    def logged(self, name, password=PW):
        c = self.anon()
        st, h, _ = c.call("POST", "/api/login/password", {"id": name, "password": password}, raw=True)
        return c, st, h

    # ---- sign-up
    def test_signup_is_closed_by_default(self):
        _, st, j = self.sign_up()
        self.assertEqual((st, j["code"]), (403, "signups_closed"))
        self.assertEqual(self.anon().call("GET", "/api/auth-options")[1]["signup"], "closed")

    def test_open_signup_makes_a_free_account_and_signs_in(self):
        self.owner_mode("open")
        c, st, j = self.sign_up()
        self.assertEqual(st, 200, j)
        c.cookie = None
        st, h, _ = c.call("POST", "/api/signup", {"name": "x1y", "email": "x1y@example.com", "password": PW}, raw=True)
        c.cookie = cookie_of(h)
        me = c.call("GET", "/api/account")[1]
        self.assertEqual((me["user"], me["plan"], me["has_password"], me["mfa"]["on"]), ("x1y", "free", True, False))
        self.assertFalse(me["email_verified"])

    def test_signup_checks_name_email_and_password(self):
        self.owner_mode("open")
        for kw, word in ((dict(name="admin"), "reserved"), (dict(email="nope"), "email"), (dict(password="short"), "at least"), (dict(name="sam"), "taken")):
            _, st, j = self.sign_up(**kw)
            self.assertEqual(st, 400)
            self.assertIn(word, j["message"])
        self.assertEqual(self.sign_up()[1], 200)
        self.assertIn("already an account", self.sign_up(name="other1")[2]["message"])

    def test_invite_mode_needs_a_good_code_that_sets_the_plan(self):
        self.owner_mode("invite")
        self.assertEqual(self.sign_up()[1], 403)
        st, j = self.owner.call("POST", "/api/admin/invites", {"tier": "pro", "uses": 1})
        self.assertEqual(st, 200)
        c, st, _ = self.sign_up(invite=j["code"])
        self.assertEqual(st, 200)
        self.assertEqual(self.state.usage.get_user("newbie")["tier"], "pro")
        self.assertEqual(self.sign_up(name="again1", email="again1@example.com", invite=j["code"])[1], 403)     # used up

    def test_a_full_name_with_a_space_and_a_code_typed_without_dashes_both_work(self):
        self.owner_mode("invite")
        st, j = self.owner.call("POST", "/api/admin/invites", {"tier": "pro", "uses": 1})
        typed = j["code"].replace("-", "").upper()                                  # no dashes, capitals
        c, st, body = self.sign_up(name="Darryl McCottrell", email="darryl@example.com", invite=typed)
        self.assertEqual(st, 200, body)
        self.assertEqual(self.state.usage.get_user("Darryl_McCottrell")["tier"], "pro")
        for ident in ("Darryl McCottrell", "darryl_mccottrell", "Darryl_McCottrell"):    # and the name signs in however it is typed
            self.assertEqual(self.logged(ident)[1], 200, ident)

    # ---- a second owner / admin, chosen by the first owner
    def make_person(self):
        self.owner_mode("open")
        c, st, h = self.sign_up(name="Darryl McCottrell", email="darryl@example.com")
        self.assertEqual(st, 200)
        c2, st, h = self.logged("Darryl McCottrell")
        c2.cookie = cookie_of(h)
        return c2

    def test_the_first_owner_can_make_an_admin_with_a_plan_or_with_no_limits(self):
        me = self.make_person()
        state = me.call("GET", "/api/state")[1]
        self.assertEqual((state["admin"], state["owner"], state["plan"]), (False, False, "free"))
        self.assertEqual(me.call("GET", "/api/admin/users")[0], 404)                       # not an admin yet
        # admin rights with a normal Pro plan
        s, j = self.owner.call("POST", "/api/admin/access", {"user": "Darryl_McCottrell", "plan": "pro", "admin": True})
        self.assertEqual((s, j["plan"], j["admin"], j["unlimited"]), (200, "pro", True, False))
        state = me.call("GET", "/api/state")[1]
        self.assertEqual((state["admin"], state["owner"], state["plan"], state["founder"]), (True, False, "pro", False))
        self.assertEqual(me.call("GET", "/api/admin/users")[0], 200)
        self.assertEqual(me.call("POST", "/api/admin/signups", {"mode": "open"})[0], 200)
        # then no limits as well
        s, j = self.owner.call("POST", "/api/admin/access", {"user": "Darryl_McCottrell", "unlimited": True})
        self.assertEqual((s, j["plan"], j["admin"], j["unlimited"]), (200, "pro", True, True))
        state = me.call("GET", "/api/state")[1]
        self.assertEqual((state["owner"], state["admin"]), (True, True))
        self.assertTrue(self.state.usage.get_user("Darryl_McCottrell")["owner"])           # the usage code treats "no limits" like the owner
        # and back to a plan with no admin rights
        s, j = self.owner.call("POST", "/api/admin/access", {"user": "Darryl_McCottrell", "plan": "free", "unlimited": False, "admin": False})
        self.assertEqual((s, j["admin"], j["unlimited"]), (200, False, False))
        self.assertEqual(me.call("GET", "/api/admin/users")[0], 404)
        self.assertFalse(self.state.usage.get_user("Darryl_McCottrell")["owner"])

    def test_only_the_first_owner_can_hand_out_rights_and_it_cannot_be_changed_itself(self):
        me = self.make_person()
        self.owner.call("POST", "/api/admin/access", {"user": "Darryl_McCottrell", "admin": True})
        s, j = me.call("POST", "/api/admin/access", {"user": "sam", "admin": True, "unlimited": True})
        self.assertEqual(s, 403)                                                            # an admin cannot make more admins
        self.assertEqual(self.sam.call("POST", "/api/admin/access", {"user": "sam", "admin": True})[0], 403)
        self.assertEqual(self.owner.call("POST", "/api/admin/access", {"user": "owner", "plan": "free"})[0], 400)
        self.assertEqual(self.owner.call("POST", "/api/admin/access", {"user": "nobody1", "plan": "pro"})[0], 400)
        self.assertEqual(self.owner.call("POST", "/api/admin/access", {"user": "sam", "plan": "platinum"})[0], 400)
        self.assertEqual(self.owner.call("POST", "/api/admin/ban", {"user": "Darryl_McCottrell", "banned": True})[0], 400)    # an admin cannot be turned off from the People page

    def test_the_owners_own_email_account_can_grant_once_the_pc_owner_made_it_an_admin(self):
        self.owner_mode("open")
        c, st, _ = self.sign_up(name="darryl_mail", email="Darrylmccottrell16@gmail.com")
        self.assertEqual(st, 200)
        c, st, h = self.logged("darryl_mail")
        c.cookie = cookie_of(h)
        # signing up with that email gives no power at all
        self.assertEqual(c.call("GET", "/api/state")[1]["granter"], False)
        self.assertEqual(c.call("POST", "/api/admin/access", {"user": "sam", "plan": "pro"})[0], 403)
        # the PC owner makes it an admin: now it can grant too
        self.assertEqual(self.owner.call("POST", "/api/admin/access", {"user": "darryl_mail", "admin": True, "unlimited": True})[0], 200)
        state = c.call("GET", "/api/state")[1]
        self.assertEqual((state["admin"], state["granter"], state["founder"]), (True, True, False))
        s, j = c.call("POST", "/api/admin/access", {"user": "sam", "plan": "pro", "admin": True})
        self.assertEqual((s, j["plan"], j["admin"]), (200, "pro", True))
        # a second admin with a different email still cannot
        other = self.sam
        self.assertEqual(other.call("POST", "/api/admin/access", {"user": "sam", "plan": "mega"})[0], 403)
        # and the first owner account is still not editable by anyone
        self.assertEqual(c.call("POST", "/api/admin/access", {"user": "owner", "plan": "free"})[0], 400)

    def test_an_admin_with_another_email_cannot_grant(self):
        self.owner_mode("open")
        self.sign_up(name="helper1", email="helper@example.com")
        c, st, h = self.logged("helper1")
        c.cookie = cookie_of(h)
        self.assertEqual(self.owner.call("POST", "/api/admin/access", {"user": "helper1", "admin": True})[0], 200)
        self.assertEqual(c.call("GET", "/api/state")[1]["granter"], False)
        self.assertEqual(c.call("POST", "/api/admin/access", {"user": "sam", "plan": "pro"})[0], 403)

    # ---- admins deleting accounts
    def two_people(self):
        self.owner_mode("open")
        out = {}
        for name in ("helper1", "victim1"):
            self.sign_up(name=name, email=f"{name}@example.com")
            c, st, h = self.logged(name)
            c.cookie = cookie_of(h)
            out[name] = c
        return out

    def test_an_admin_can_delete_an_ordinary_account_and_everything_in_it(self):
        people = self.two_people()
        self.assertEqual(self.owner.call("POST", "/api/admin/access", {"user": "helper1", "admin": True})[0], 200)
        victim = people["victim1"]
        cid = victim.call("POST", "/api/chats", {})[1]["id"]
        self.assertEqual(victim.call("POST", "/api/admin/delete-user", {"user": "victim1"})[0], 403)           # an ordinary account cannot
        admin = people["helper1"]
        s, j = admin.call("POST", "/api/admin/delete-user", {"user": "victim1", "confirm": "wrong", "password": PW})
        self.assertEqual((s, j["code"]), (400, "confirm"))                                                       # the name has to be typed
        s, j = admin.call("POST", "/api/admin/delete-user", {"user": "victim1", "confirm": "victim1"})
        self.assertEqual((s, j["code"]), (400, "reauth"))                                                        # an admin with a password confirms it
        s, j = admin.call("POST", "/api/admin/delete-user", {"user": "victim1", "confirm": "victim1", "password": PW})
        self.assertEqual((s, j), (200, {"ok": True}))
        self.assertIsNone(self.state.user_record("victim1"))
        self.assertEqual(victim.call("GET", "/api/state")[0], 401)                                               # signed out everywhere
        self.assertEqual(self.logged("victim1")[1], 401)
        self.assertNotIn("victim1", [u["user"] for u in admin.call("GET", "/api/admin/users")[1]["users"]])
        self.assertIn("by helper1", " ".join(e["detail"] for e in self.owner.call("GET", "/api/admin/audit")[1]["events"] if e["kind"] == "account_deleted"))

    def test_nobody_can_delete_the_owner_themselves_or_a_protected_account_without_the_right(self):
        people = self.two_people()
        self.owner.call("POST", "/api/admin/access", {"user": "helper1", "admin": True})
        self.owner.call("POST", "/api/admin/access", {"user": "victim1", "admin": True, "unlimited": True})
        admin = people["helper1"]
        body = lambda u, **kw: dict({"user": u, "confirm": u, "password": PW}, **kw)
        self.assertEqual(admin.call("POST", "/api/admin/delete-user", body("owner"))[0], 400)                    # the first owner account never
        self.assertEqual(admin.call("POST", "/api/admin/delete-user", body("helper1"))[0], 400)                  # not your own: there is a button for that
        self.assertEqual(admin.call("POST", "/api/admin/delete-user", body("victim1"))[0], 403)                  # an admin / no-limits account: only the PC owner
        self.assertEqual(admin.call("POST", "/api/admin/delete-user", body("nobody1"))[0], 400)
        self.assertEqual(self.owner.call("POST", "/api/admin/delete-user", {"user": "victim1", "confirm": "victim1"})[0], 200)   # the PC owner can
        self.assertIsNone(self.state.user_record("victim1"))
        self.assertIsNotNone(self.state.user_record("owner"))

    def test_vryxcode_is_open_to_admins_but_other_people_still_need_the_container_sandbox(self):
        info = lambda: self.sam.call("GET", "/api/code")[1]
        self.assertIn("isn't included", info()["why_not"])                                                      # a free account
        self.owner.call("POST", "/api/admin/access", {"user": "sam", "plan": "pro"})
        self.assertEqual((info()["allowed"], "container sandbox" in info()["why_not"]), (False, True))        # Pro, but no sandbox: not for ordinary people
        self.owner.call("POST", "/api/admin/access", {"user": "sam", "admin": True})
        self.assertEqual(info()["allowed"], True)                                                              # an admin the owner appointed may
        self.assertEqual(self.owner.call("GET", "/api/code")[1]["allowed"], True)
        self.owner.call("POST", "/api/admin/access", {"user": "sam", "plan": "free", "admin": True})
        self.assertEqual(info()["allowed"], True)                                                              # whatever the plan: the owner trusts them

    def test_make_admin_on_the_command_line_finds_the_account_by_email(self):
        self.make_person()
        self.assertIsNone(self.state.find_login("darryl@example.com"))                       # sign-in by email needs it verified...
        rec = self.state.find_account("darryl@example.com")                                  # ...the owner's own tool does not
        self.assertEqual(rec["user"], "Darryl_McCottrell")
        out = self.state.set_access(rec["user"], "mega", True, True)
        self.assertEqual((out["plan"], out["unlimited"], out["admin"]), ("mega", True, True))

    def test_unverified_email_cannot_be_used_for_email_code_sign_in(self):
        self.owner_mode("open")
        self.sign_up()
        self.assertIsNone(self.state.user_by_email("newbie@example.com"))

    # ---- password sign-in
    def test_password_sign_in_by_name_or_email_and_wrong_ones_fail_the_same_way(self):
        self.owner_mode("open")
        self.sign_up()
        for ident in ("newbie", "NEWBIE"):
            c, st, h = self.logged(ident)
            self.assertEqual(st, 200)
            c.cookie = cookie_of(h)
            self.assertEqual(c.call("GET", "/api/state")[1]["user"], "newbie")
        a = self.logged("newbie", "wrong password here")
        b = self.logged("nobody-here", "wrong password here")
        self.assertEqual((a[1], b[1]), (401, 401))
        self.assertEqual(self.anon().call("POST", "/api/login/password", {"id": "newbie", "password": "x"})[1],
                         self.anon().call("POST", "/api/login/password", {"id": "nobody-here", "password": "x"})[1])

    def test_an_account_gets_locked_for_password_guessing(self):
        self.owner_mode("open")
        self.sign_up()
        for _ in range(20):
            self.state.rl.hit("pw:newbie")
        st, j = self.anon().call("POST", "/api/login/password", {"id": "newbie", "password": PW})
        self.assertEqual(st, 429)

    def test_banned_people_cannot_sign_in(self):
        self.owner_mode("open")
        self.sign_up()
        self.owner.call("POST", "/api/admin/ban", {"user": "newbie", "banned": True})
        self.assertEqual(self.logged("newbie")[1], 403)

    # ---- the account
    def me(self):
        self.owner_mode("open")
        c, st, _ = self.sign_up()
        st, h, _ = c.call("POST", "/api/login/password", {"id": "newbie", "password": PW}, raw=True)
        c.cookie = cookie_of(h)
        return c

    def test_changing_a_password_needs_the_old_one_and_signs_other_devices_out(self):
        c = self.me()
        other, _, h = self.logged("newbie")
        other.cookie = cookie_of(h)
        self.assertEqual(c.call("POST", "/api/account/password", {"current": "wrong wrong wrong", "new": "another long phrase"})[0], 400)
        self.assertEqual(c.call("POST", "/api/account/password", {"current": PW, "new": "short"})[0], 400)
        st, j = c.call("POST", "/api/account/password", {"current": PW, "new": "another long phrase"})
        self.assertEqual(st, 200)
        self.assertGreaterEqual(j["signed_out_others"], 1)
        self.assertEqual(other.call("GET", "/api/state")[0], 401)
        self.assertEqual(c.call("GET", "/api/state")[0], 200)
        self.assertEqual(self.logged("newbie", "another long phrase")[1], 200)
        self.assertEqual(self.logged("newbie", PW)[1], 401)

    def totp(self, c):
        st, j = c.call("POST", "/api/account/mfa/start", {"password": PW})
        self.assertEqual(st, 200, j)
        self.assertTrue(j["uri"].startswith("otpauth://totp/Emvryx"))
        secret = j["secret"].replace(" ", "")
        code = accounts.code_at(secret, int(time.time() // 30))
        return secret, code

    def test_turning_on_two_step_and_signing_in_with_it(self):
        c = self.me()
        secret, code = self.totp(c)
        self.assertEqual(c.call("POST", "/api/account/mfa/enable", {"code": "000000"})[0], 400)
        st, j = c.call("POST", "/api/account/mfa/enable", {"code": code})
        self.assertEqual(st, 200, j)
        self.assertEqual(len(j["recovery"]), 8)
        self.assertTrue(c.call("GET", "/api/account")[1]["mfa"]["on"])
        # sign-in now stops after the password and asks for a code
        d = self.anon()
        st, step = d.call("POST", "/api/login/password", {"id": "newbie", "password": PW})
        self.assertEqual((st, step["mfa"]), (200, True))
        self.assertEqual(d.call("GET", "/api/state")[0], 401)                             # no session yet
        self.assertEqual(d.call("POST", "/api/login/mfa", {"ticket": step["ticket"], "code": "123456"})[0], 401)
        nxt = accounts.code_at(secret, int(time.time() // 30) + 1)                        # the code used above cannot be used again: take the next step's
        st, h, _ = d.call("POST", "/api/login/mfa", {"ticket": step["ticket"], "code": nxt}, raw=True)
        self.assertEqual(st, 200)
        d.cookie = cookie_of(h)
        self.assertEqual(d.call("GET", "/api/state")[1]["user"], "newbie")
        # a recovery code works once
        st, step = self.anon().call("POST", "/api/login/password", {"id": "newbie", "password": PW})
        self.assertEqual(self.anon().call("POST", "/api/login/mfa", {"ticket": step["ticket"], "code": j["recovery"][0]})[0], 200)
        st, step = self.anon().call("POST", "/api/login/password", {"id": "newbie", "password": PW})
        self.assertEqual(self.anon().call("POST", "/api/login/mfa", {"ticket": step["ticket"], "code": j["recovery"][0]})[0], 401)

    def test_a_ticket_allows_five_wrong_codes(self):
        c = self.me()
        _, code = self.totp(c)
        c.call("POST", "/api/account/mfa/enable", {"code": code})
        st, step = self.anon().call("POST", "/api/login/password", {"id": "newbie", "password": PW})
        for _ in range(5):
            self.assertEqual(self.anon().call("POST", "/api/login/mfa", {"ticket": step["ticket"], "code": "111111"})[0], 401)
        self.assertNotIn(auth.digest(step["ticket"]), self.state.mfa_tickets)

    def test_the_key_and_email_code_also_ask_for_the_code_but_a_pairing_link_does_not(self):
        c = self.me()
        _, code = self.totp(c)
        c.call("POST", "/api/account/mfa/enable", {"code": code})
        self.state.set_email("newbie", "newbie@example.com")
        self.state._set_fields("newbie", email_verified=True)
        key = self.state.rotate_key("newbie")
        st, j = self.anon().call("POST", "/api/login", {"key": key})
        self.assertEqual((st, j.get("mfa")), (200, True))
        st, h = Client(self.port).use_pairing_link(self.state.auth.new_pair("newbie"))     # the owner/command-line way back in
        self.assertEqual(st, 303)

    def test_turning_two_step_off_asks_for_password_and_code_and_the_owner_can_reset_it(self):
        c = self.me()
        secret, code = self.totp(c)
        c.call("POST", "/api/account/mfa/enable", {"code": code})
        self.assertEqual(c.call("POST", "/api/account/mfa/disable", {"password": PW})[0], 400)           # no code
        self.assertEqual(c.call("POST", "/api/account/mfa/disable", {"password": "nope nope nope", "code": "123456"})[0], 400)
        st, j = c.call("POST", "/api/account/mfa/recovery", {"password": PW, "code": accounts.code_at(secret, int(time.time() // 30) + 1)})
        self.assertEqual((st, len(j["recovery"])), (200, 8))
        self.assertEqual(self.owner.call("POST", "/api/admin/mfa-reset", {"user": "newbie"})[0], 200)
        self.assertFalse(self.state.mfa_on("newbie"))
        self.assertEqual(c.call("GET", "/api/state")[0], 401)                                           # signed out everywhere

    def test_the_secret_is_not_kept_in_the_clear(self):
        c = self.me()
        secret, code = self.totp(c)
        c.call("POST", "/api/account/mfa/enable", {"code": code})
        text = open(os.path.join(self.tmp.name, "users.json")).read()
        if self.state.secrets.available:
            self.assertNotIn(secret, text)
        self.assertNotIn(PW, text)

    def test_deleting_an_account_asks_for_the_password(self):
        c = self.me()
        self.assertEqual(c.call("POST", "/api/delete-account", {"confirm": "newbie"})[0], 400)
        self.assertEqual(c.call("POST", "/api/delete-account", {"confirm": "newbie", "password": PW})[0], 200)

    # ---- owner
    def test_only_the_owner_gets_the_admin_overview(self):
        self.assertEqual(self.sam.call("GET", "/api/admin/overview")[0], 404)
        self.assertEqual(self.sam.call("POST", "/api/admin/signups", {"mode": "open"})[0], 403)
        self.assertEqual(self.sam.call("POST", "/api/admin/invites", {"tier": "pro"})[0], 403)
        st, j = self.owner.call("GET", "/api/admin/overview")
        self.assertEqual(st, 200)
        self.assertEqual({c["id"] for c in j["checklist"]}, {"password", "mfa", "email", "encryption", "alerts", "mail", "backup"})
        self.assertFalse(next(c for c in j["checklist"] if c["id"] == "mfa")["ok"])

    def test_settings_survive_a_restart(self):
        self.sam.call("POST", "/api/settings", {"web_search": "always", "thinking_pause": "off"})
        import app_server as A
        again = A.AppState(self.tmp.name, manifest=self.manifest, ram_gb=8, pace=False)
        self.assertEqual((again.get_settings("sam")["web_search"], again.get_settings("sam")["thinking_pause"]), ("always", "off"))

    def test_my_activity_shows_only_my_own_events(self):
        self.state.set_password("sam", PW)
        self.state.auth.event("login_ok", "someone-else", "", "key")
        kinds = {(e["user"], e["kind"]) for e in self.sam.call("GET", "/api/account/activity")[1]["events"]}
        self.assertIn(("sam", "password_set"), kinds)
        self.assertTrue(all(u == "sam" for u, _ in kinds))

    def test_the_page_has_the_new_sign_in_and_settings(self):
        page = self.page_text()
        for word in ('id="auth"', "Create account", "openSettings", "Two-step sign-in", "/api/login/mfa", "Sign-ups and invites"):
            self.assertIn(word, page)

    def test_the_page_reads_an_invite_link_and_draws_a_qr_code(self):
        page = self.page_text()
        for word in ("get('invite')", "function qrSvg", "Copy invite link", "history.replaceState"):
            self.assertIn(word, page)

    def test_signup_mode_survives_a_restart(self):
        self.owner_mode("invite")
        import app_server as A
        again = A.AppState(self.tmp.name, manifest=self.manifest, ram_gb=8, pace=False)
        self.assertEqual(again.signup_mode(), "invite")

    def test_owner_can_set_a_password_and_sign_in_with_it(self):
        self.state.set_password("owner", PW)
        c, st, _ = self.logged("owner")
        self.assertEqual(st, 200)
        self.assertEqual(self.owner.call("GET", "/api/admin/overview")[1]["checklist"][0]["ok"], True)


if __name__ == "__main__":
    unittest.main()
