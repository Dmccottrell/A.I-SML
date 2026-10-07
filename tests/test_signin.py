"""Sign-in: sessions instead of key cookies, hashed keys, pairing links, rate limits, bans, email codes, the audit log."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import json
import os
import unittest

import auth
import mailer
from tests.test_app_server import Base, Client


def cookie_of(headers):
    sc = headers.get("Set-Cookie", "")
    return sc.split(";")[0] if sc else None


class SignIn(Base):
    data_dir = True

    def pair(self, name="sam", client=None):
        st, j = (client or self.owner).call("POST", "/api/admin/pairing", {"user": name})
        self.assertEqual(st, 200, j)
        return j["pair"]

    def signed_in(self, name="sam"):
        c = Client(self.port)
        st, h = c.use_pairing_link(self.pair(name))
        self.assertEqual(st, 303)
        c.cookie = cookie_of(h)
        return c

    # ---- storage
    def test_users_file_holds_only_hashes_and_an_old_file_is_migrated(self):
        text = open(os.path.join(self.tmp.name, "users.json")).read()
        self.assertNotIn(self.sam_key, text)
        self.assertIn("h:" + auth.digest(self.sam_key), text)
        d = os.path.join(self.tmp.name, "old")
        os.makedirs(d)
        json.dump({"plainkey123": {"user": "owner", "tier": "mega", "owner": True}}, open(os.path.join(d, "users.json"), "w"))
        import app_server as A
        st = A.AppState(d, manifest=self.manifest, ram_gb=8, pace=False)
        self.assertTrue(st.who("plainkey123")["owner"])                      # the old key still works ...
        self.assertNotIn("plainkey123", open(os.path.join(d, "users.json")).read())   # ... but is no longer kept

    # ---- pairing links and sessions
    def test_a_pairing_link_signs_in_once(self):
        t = self.pair("sam")
        c = Client(self.port)
        st, h = c.use_pairing_link(t)
        self.assertEqual(st, 303)
        self.assertIn("HttpOnly", h["Set-Cookie"])
        c.cookie = cookie_of(h)
        self.assertEqual(c.call("GET", "/api/state")[1]["user"], "sam")
        self.assertEqual(Client(self.port).call("GET", "/pair/" + t, raw=True)[0], 410)           # used up
        self.assertEqual(Client(self.port).call("GET", "/pair/nottherealtokenxxxx", raw=True)[0], 410)

    def test_opening_a_link_does_not_use_it_up_so_a_chat_apps_preview_cannot_burn_it(self):
        t = self.pair("sam")
        for _ in range(3):                                                           # previews, scanners, the person looking twice
            st, h, page = Client(self.port).call("GET", "/pair/" + t, raw=True)
            self.assertEqual(st, 200)
            self.assertNotIn("Set-Cookie", h)
            self.assertIn(b'<form method="post" action="/pair/', page)
            self.assertIn("form-action 'self'", h["Content-Security-Policy"])
        self.assertEqual(Client(self.port).use_pairing_link(t)[0], 303)              # only the button signs in

    def test_a_cross_site_page_cannot_press_the_button(self):
        t = self.pair("sam")
        st, _, _ = Client(self.port).call("POST", "/pair/" + t, raw=True, headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"})
        self.assertEqual(st, 403)
        self.assertEqual(Client(self.port).use_pairing_link(t)[0], 303)              # the link was not used up by the attempt

    def test_only_the_owner_makes_pairing_links(self):
        self.assertEqual(self.sam.call("POST", "/api/admin/pairing", {"user": "sam"})[0], 403)

    def test_devices_can_be_listed_and_signed_out(self):
        a, b = self.signed_in(), self.signed_in()
        sessions = a.call("GET", "/api/sessions")[1]["sessions"]
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sum(1 for s in sessions if s["current"]), 1)
        other = next(s for s in sessions if not s["current"])
        self.assertTrue(a.call("POST", "/api/sessions/revoke", {"id": other["id"]})[1]["ok"])
        self.assertEqual(b.call("GET", "/api/state")[0], 401)                        # that device is signed out
        self.assertEqual(a.call("GET", "/api/state")[0], 200)
        c = self.signed_in()
        self.assertEqual(a.call("POST", "/api/sessions/revoke-others", {})[1]["revoked"], 1)
        self.assertEqual(c.call("GET", "/api/state")[0], 401)

    def test_logout_ends_the_session(self):
        c = self.signed_in()
        c.call("POST", "/api/logout", {})
        self.assertEqual(c.call("GET", "/api/state")[0], 401)

    def test_rotating_a_key_signs_that_person_out_everywhere(self):
        c = self.signed_in()
        new = self.state.rotate_key("sam")
        self.assertEqual(c.call("GET", "/api/state")[0], 401)
        self.assertIsNone(self.state.who(self.sam_key))
        self.assertEqual(Client(self.port, new).call("GET", "/api/state")[0], 200)

    def test_the_old_key_cookie_is_swapped_for_a_session(self):
        c = Client(self.port)
        c.cookie = "emvryx_key=" + self.sam_key
        st, h, _ = c.call("GET", "/api/state", raw=True)
        self.assertEqual(st, 200)
        self.assertIn("emvryx_session=", h["Set-Cookie"])

    def test_cookie_is_secure_only_when_the_proxy_says_https(self):
        t1 = self.pair()
        h1 = Client(self.port).use_pairing_link(t1)[1]
        self.assertNotIn("Secure", h1["Set-Cookie"])
        t2 = self.pair()
        h2 = Client(self.port).use_pairing_link(t2, headers={"X-Forwarded-Proto": "https"})[1]
        self.assertIn("Secure", h2["Set-Cookie"])

    # ---- guessing and lockout
    def test_too_many_wrong_keys_lock_that_address_out_even_for_the_right_key(self):
        for _ in range(self.state.security["login_fail_limit"]):
            self.assertEqual(Client(self.port, "wrong").call("GET", "/api/state")[0], 401)
        st, h, body = Client(self.port, self.sam_key).call("GET", "/api/state", raw=True)
        self.assertEqual(st, 429)
        self.assertIn("Retry-After", h)
        self.assertEqual(Client(self.port).call("POST", "/api/login", {"key": self.sam_key})[0], 429)

    def test_lockout_is_per_address_using_the_proxy_header_only_from_a_trusted_proxy(self):
        for _ in range(self.state.security["login_fail_limit"]):
            Client(self.port, "wrong").call("GET", "/api/state", headers={"CF-Connecting-IP": "198.51.100.1"})
        # another visitor behind the same proxy is not affected
        self.assertEqual(Client(self.port, self.sam_key).call("GET", "/api/state", headers={"CF-Connecting-IP": "198.51.100.2"})[0], 200)
        self.assertEqual(Client(self.port, self.sam_key).call("GET", "/api/state", headers={"CF-Connecting-IP": "198.51.100.1"})[0], 429)
        self.state.security["trusted_proxies"] = []                                  # not behind a proxy: the header is ignored
        self.assertEqual(Client(self.port, self.sam_key).call("GET", "/api/state", headers={"CF-Connecting-IP": "198.51.100.2"})[0], 200)

    def test_a_bad_pairing_link_counts_as_a_wrong_try(self):
        good = self.pair()                                                           # made before the lockout, by the owner
        for _ in range(self.state.security["login_fail_limit"]):
            Client(self.port).call("GET", "/pair/bogusbogusbogusbogus", raw=True)
        self.assertEqual(Client(self.port).call("GET", "/pair/" + good, raw=True)[0], 429)

    # ---- bans
    def test_a_banned_person_is_refused_and_signed_out_and_the_owner_cannot_be_banned(self):
        c = self.signed_in()
        self.assertEqual(self.owner.call("POST", "/api/admin/ban", {"user": "sam", "banned": True})[0], 200)
        self.assertEqual(c.call("GET", "/api/state")[0], 401)                        # sessions were revoked
        st, j = self.sam.call("GET", "/api/state")
        self.assertEqual((st, j["code"]), (403, "banned"))
        self.assertEqual(Client(self.port).call("POST", "/api/login", {"key": self.sam_key})[0], 403)
        self.assertEqual(self.owner.call("POST", "/api/admin/ban", {"user": "owner", "banned": True})[0], 400)
        self.owner.call("POST", "/api/admin/ban", {"user": "sam", "banned": False})
        self.assertEqual(self.sam.call("GET", "/api/state")[0], 200)

    # ---- the audit log
    def test_the_owner_can_read_the_audit_log_and_it_has_no_secrets(self):
        self.signed_in()
        Client(self.port, "wrong").call("GET", "/api/state")
        st, j = self.owner.call("GET", "/api/admin/audit?limit=50")
        self.assertEqual(st, 200)
        kinds = {e["kind"] for e in j["events"]}
        self.assertTrue({"login_ok", "login_fail", "pair_created"} <= kinds)
        self.assertNotIn(self.sam_key, json.dumps(j))
        self.assertEqual(self.sam.call("GET", "/api/admin/audit")[0], 404)


class EmailSignIn(Base):
    data_dir = True

    def setUp(self):
        super().setUp()
        self.mail = mailer.FakeMailer()
        self.state.mailer = self.mail
        self.state.mail_async = False                                     # deterministic in tests
        self.state.set_email("sam", "Sam@Example.com")

    def code(self):
        return next(l for l in self.mail.sent[-1]["body"].split() if l.isdigit() and len(l) == 6)

    def test_off_without_a_mail_server(self):
        self.state.mailer = None
        self.assertEqual(Client(self.port).call("POST", "/api/login/email/start", {"email": "sam@example.com"})[0], 501)
        self.assertFalse(Client(self.port).call("GET", "/api/auth-options")[1]["email"])

    def test_a_code_signs_in_once(self):
        c = Client(self.port)
        st, j = c.call("POST", "/api/login/email/start", {"email": "sam@example.com"})
        self.assertEqual(st, 200)
        self.assertEqual(len(self.mail.sent), 1)
        self.assertEqual(self.mail.sent[0]["to"], "sam@example.com")
        code = self.code()
        st, h, _ = c.call("POST", "/api/login/email/verify", {"email": "sam@example.com", "code": code}, raw=True)
        self.assertEqual(st, 200)
        c.cookie = cookie_of(h)
        self.assertEqual(c.call("GET", "/api/state")[1]["user"], "sam")
        self.assertEqual(Client(self.port).call("POST", "/api/login/email/verify", {"email": "sam@example.com", "code": code})[0], 401)

    def test_an_unknown_address_gets_the_same_answer_and_no_email(self):
        known = Client(self.port).call("POST", "/api/login/email/start", {"email": "sam@example.com"})
        n = len(self.mail.sent)
        unknown = Client(self.port).call("POST", "/api/login/email/start", {"email": "nobody@example.com"})
        self.assertEqual(known, unknown)
        self.assertEqual(len(self.mail.sent), n)
        self.assertEqual(Client(self.port).call("POST", "/api/login/email/start", {"email": "not an email"})[0], 200)

    def test_wrong_codes_lock_the_address_out(self):
        Client(self.port).call("POST", "/api/login/email/start", {"email": "sam@example.com"})
        for _ in range(self.state.security["login_fail_limit"]):
            Client(self.port).call("POST", "/api/login/email/verify", {"email": "sam@example.com", "code": "000000"})
        self.assertEqual(Client(self.port).call("POST", "/api/login/email/verify", {"email": "sam@example.com", "code": self.code()})[0], 429)

    def test_asking_for_codes_is_rate_limited(self):
        for _ in range(self.state.security["email_start_limit"]):
            Client(self.port).call("POST", "/api/login/email/start", {"email": "sam@example.com"})
        self.assertEqual(Client(self.port).call("POST", "/api/login/email/start", {"email": "sam@example.com"})[0], 429)

    def test_a_banned_person_gets_no_code(self):
        self.state.set_ban("sam", True)
        Client(self.port).call("POST", "/api/login/email/start", {"email": "sam@example.com"})
        self.assertEqual(self.mail.sent, [])

    def test_signups_are_closed_unless_the_owner_opens_them(self):
        Client(self.port).call("POST", "/api/login/email/start", {"email": "new@example.com"})
        self.assertEqual(self.mail.sent, [])
        self.state.security["open_signups"] = True
        c = Client(self.port)
        c.call("POST", "/api/login/email/start", {"email": "new@example.com"})
        code = self.code()
        st, h, _ = c.call("POST", "/api/login/email/verify", {"email": "new@example.com", "code": code}, raw=True)
        self.assertEqual(st, 200)
        c.cookie = cookie_of(h)
        who = c.call("GET", "/api/state")[1]
        self.assertEqual((who["user"], who["plan"]), ("new", "free"))                # a free account, nothing more

    def test_an_email_belongs_to_one_person(self):
        with self.assertRaises(ValueError):
            self.state.set_email("owner", "sam@example.com")


if __name__ == "__main__":
    unittest.main()
