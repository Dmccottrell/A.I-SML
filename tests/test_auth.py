"""auth.py: sessions, pairing links, email codes, rate limits and the audit log (no server, a fake clock)."""
import unittest

import auth as A
import mailer


class Sessions(unittest.TestCase):
    def setUp(self):
        self.db = A.AuthDB()

    def test_a_session_works_until_it_is_revoked_and_the_token_is_not_stored(self):
        sid, token = self.db.new_session("sam", "Mozilla/5.0 (Linux; Android 14) Chrome/120 Safari/537", "203.0.113.9", now=1000)
        self.assertEqual(self.db.session(token, now=1010), {"id": sid, "user": "sam"})
        stored = " ".join(str(r) for r in self.db.db.execute("SELECT * FROM sessions").fetchall())
        self.assertNotIn(token, stored)
        self.assertIn("203.0.x.x".replace("203.0", "203.0"), stored)             # only a coarse part of the address is kept
        self.assertNotIn("203.0.113.9", stored)
        self.assertTrue(self.db.revoke(sid, "sam"))
        self.assertIsNone(self.db.session(token, now=1020))

    def test_expiry_and_rolling_extension(self):
        sid, token = self.db.new_session("sam", days=1, now=0)
        self.assertIsNotNone(self.db.session(token, days=1, now=80000))          # used late in the day: extended another day
        self.assertIsNotNone(self.db.session(token, days=1, now=80000 + 80000))
        self.assertIsNone(self.db.session(token, days=1, now=80000 + 80000 + 90000))

    def test_you_can_only_revoke_your_own_and_revoke_the_others(self):
        a, ta = self.db.new_session("sam", now=0)
        b, tb = self.db.new_session("sam", now=1)
        c, tc = self.db.new_session("pat", now=2)
        self.assertFalse(self.db.revoke(c, "sam"))
        self.assertEqual(self.db.revoke_user("sam", except_id=a), 1)
        self.assertIsNotNone(self.db.session(ta, now=5))
        self.assertIsNone(self.db.session(tb, now=5))
        self.assertIsNotNone(self.db.session(tc, now=5))
        self.assertEqual([s["id"] for s in self.db.sessions_for("sam", now=5)], [a])

    def test_device_label_is_short(self):
        self.assertEqual(A.device_label("Mozilla/5.0 (iPhone; CPU iPhone OS 17) AppleWebKit Version/17 Safari/604"), "Safari on iPhone")
        self.assertEqual(A.device_label(""), "A browser on an unknown device")


class Pairing(unittest.TestCase):
    def test_a_pairing_link_works_once_and_expires(self):
        db = A.AuthDB()
        t = db.new_pair("sam", minutes=15, now=0)
        self.assertEqual(db.use_pair(t, now=60), "sam")
        self.assertIsNone(db.use_pair(t, now=61))
        late = db.new_pair("sam", minutes=15, now=0)
        self.assertIsNone(db.use_pair(late, now=16 * 60))
        self.assertIsNone(db.use_pair("nope"))
        self.assertIsNone(db.use_pair(""))


class Codes(unittest.TestCase):
    def test_code_works_once_with_limited_tries(self):
        db = A.AuthDB()
        db.put_code("Sam@Example.com", "123456", now=0)
        self.assertFalse(db.check_code("sam@example.com", "000000", now=1))
        self.assertTrue(db.check_code("sam@example.com", "123456", now=2))
        self.assertFalse(db.check_code("sam@example.com", "123456", now=3))          # used
        db.put_code("sam@example.com", "654321", now=0)
        for _ in range(5):
            db.check_code("sam@example.com", "111111", now=1)
        self.assertFalse(db.check_code("sam@example.com", "654321", now=2))          # too many wrong tries burn the code
        db.put_code("sam@example.com", "222222", minutes=10, now=0)
        self.assertFalse(db.check_code("sam@example.com", "222222", now=700))        # expired

    def test_email_and_code_shapes(self):
        self.assertEqual(A.clean_email(" Sam@Example.COM "), "sam@example.com")
        for bad in ("", "sam", "a@b", "a b@c.com", "a@@c.com", "x" * 300 + "@a.com"):
            self.assertIsNone(A.clean_email(bad), bad)
        self.assertRegex(A.make_code(), r"^\d{6}$")


class Limits(unittest.TestCase):
    def test_sliding_window(self):
        r = A.RateLimiter()
        for t in range(3):
            r.hit("ip", now=t)
        self.assertEqual(r.blocked("ip", 5, 60, now=10), 0)
        for t in range(3, 5):
            r.hit("ip", now=t)
        wait = r.blocked("ip", 5, 60, now=10)
        self.assertGreater(wait, 0)
        self.assertLessEqual(wait, 60)
        self.assertEqual(r.blocked("ip", 5, 60, now=200), 0)                        # the window moved on
        r.clear("ip")
        self.assertEqual(r.blocked("ip", 1, 60, now=0), 0)


class Audit(unittest.TestCase):
    def test_log_is_filtered_trimmed_and_coarse(self):
        db = A.AuthDB()
        db.event("login_ok", "sam", "198.51.100.7", "key")
        db.event("login_fail", "", "198.51.100.8", "bad key")
        self.assertEqual([e["kind"] for e in db.events()], ["login_fail", "login_ok"])
        self.assertEqual(db.events(kind="login_ok")[0]["ip"], "198.51.x.x")
        self.assertEqual(len(db.events(user="sam")), 1)
        A.EVENTS_KEPT, old = 3, A.EVENTS_KEPT
        try:
            for i in range(10):
                db.event("x", "u", "", str(i))
            self.assertEqual(len(db.events(limit=100)), 3)
        finally:
            A.EVENTS_KEPT = old


class Mail(unittest.TestCase):
    def test_not_set_up_without_settings_and_set_up_with_them(self):
        self.assertIsNone(mailer.from_env({}))
        m = mailer.from_env({"EMVRYX_SMTP_HOST": "smtp.example.com", "EMVRYX_SMTP_USER": "me@example.com", "EMVRYX_SMTP_PASS": "x"})
        self.assertEqual((m.host, m.port, m.sender), ("smtp.example.com", 587, "me@example.com"))
        subject, body = mailer.code_email("123456")
        self.assertIn("123456", body)


if __name__ == "__main__":
    unittest.main()
