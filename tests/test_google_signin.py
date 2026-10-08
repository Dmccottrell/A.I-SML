"""Continue with Google: the pure checks, and the two-step flow in the server with Google replaced by a stand-in."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import base64
import json
import time
import unittest
import urllib.parse
from unittest import mock

import accounts
import google_signin as G
from tests.test_app_server import Base, Client

CID = "client-123.apps.googleusercontent.com"


def id_token(**kw):
    payload = dict({"iss": "https://accounts.google.com", "aud": CID, "exp": time.time() + 600, "email": "kim@gmail.com", "email_verified": True}, **kw)
    enc = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b"=").decode()
    return enc({"alg": "RS256"}) + "." + enc(payload) + ".sig"


class Pieces(unittest.TestCase):
    def test_pkce_challenge_matches_the_verifier(self):
        import hashlib
        v, c = G.pkce()
        self.assertEqual(c, base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode())
        self.assertGreaterEqual(len(v), 43)

    def test_auth_url_has_state_pkce_and_only_the_email_scope(self):
        u = urllib.parse.urlparse(G.auth_url(CID, "https://chat.emvryx.app/auth/google/callback", "S", "CH"))
        q = urllib.parse.parse_qs(u.query)
        self.assertEqual(u.netloc, "accounts.google.com")
        self.assertEqual((q["state"], q["code_challenge"], q["code_challenge_method"], q["scope"]), (["S"], ["CH"], ["S256"], ["openid email"]))

    def test_the_id_token_is_checked(self):
        self.assertEqual(G.email_from_id_token(id_token(), CID), "kim@gmail.com")
        self.assertEqual(G.email_from_id_token(id_token(email="Kim@Gmail.com"), CID), "kim@gmail.com")
        for bad in (id_token(aud="someone-else"), id_token(iss="https://evil.example"), id_token(exp=time.time() - 3600), id_token(email_verified=False), id_token(email=""), "garbage", ""):
            self.assertIsNone(G.email_from_id_token(bad, CID))


class Flow(Base):
    data_dir = True

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"GOOGLE_CLIENT_ID": CID, "GOOGLE_CLIENT_SECRET": "shh"})
        env.start()
        self.addCleanup(env.stop)
        self.token = id_token()
        self.calls = []
        self.state.google_http = lambda method, url, data=None: (self.calls.append((method, url, data)), (200, {"id_token": self.token}))[1]
        self.anon = Client(self.port)

    def start(self, invite=""):
        st, h, _ = self.anon.call("GET", "/auth/google/start" + (f"?invite={invite}" if invite else ""), raw=True)
        self.assertEqual(st, 302)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(h["Location"]).query)
        return q["state"][0]

    def callback(self, state, cookie_state=None, code="abc", extra=""):
        c = Client(self.port)
        c.cookie = "emvryx_oauth=" + (state if cookie_state is None else cookie_state)
        st, h, _ = c.call("GET", f"/auth/google/callback?state={state}&code={code}{extra}", raw=True)
        return st, h["Location"]

    def test_button_only_shows_when_it_is_set_up(self):
        self.assertTrue(self.anon.call("GET", "/api/auth-options")[1]["google"])
        with mock.patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": ""}):
            self.assertFalse(self.anon.call("GET", "/api/auth-options")[1]["google"])
            self.assertEqual(self.anon.call("GET", "/auth/google/start", raw=True)[1]["Location"], "/?gerr=off")

    def test_start_sets_a_lax_cookie_and_goes_to_google(self):
        st, h, _ = self.anon.call("GET", "/auth/google/start", raw=True)
        self.assertTrue(h["Location"].startswith("https://accounts.google.com/"))
        self.assertIn("emvryx_oauth=", h["Set-Cookie"])
        self.assertIn("SameSite=Lax", h["Set-Cookie"])
        self.assertIn("HttpOnly", h["Set-Cookie"])

    def test_a_person_whose_email_matches_is_signed_in(self):
        self.state.set_email("sam", "kim@gmail.com")
        state = self.start()
        st, where = self.callback(state)
        self.assertEqual((st, where), (302, "/"))
        self.assertEqual(len(self.state.auth.sessions_for("sam")), 1)
        form = urllib.parse.parse_qs(self.calls[0][2].decode())
        self.assertEqual(form["grant_type"], ["authorization_code"])
        self.assertTrue(form["code_verifier"][0])                                         # PKCE is used in the exchange
        self.assertEqual(self.callback(state)[1], "/?gerr=state")                         # a state works once

    def test_the_cookie_must_match_the_state(self):
        self.state.set_email("sam", "kim@gmail.com")
        state = self.start()
        self.assertEqual(self.callback(state, cookie_state="forged")[1], "/?gerr=state")
        self.assertEqual(len(self.state.auth.sessions_for("sam")), 0)

    def test_an_unknown_state_or_a_bad_token_signs_nobody_in(self):
        self.state.set_email("sam", "kim@gmail.com")
        self.assertEqual(self.callback("never-issued")[1], "/?gerr=state")
        state = self.start()
        self.token = id_token(aud="other-app")
        self.assertEqual(self.callback(state)[1], "/?gerr=token")
        state = self.start()
        self.assertEqual(self.callback(state, extra="&error=access_denied", code="")[1], "/?gerr=denied")

    def test_closed_invite_and_open_signup(self):
        state = self.start()
        self.assertEqual(self.callback(state)[1], "/?gerr=closed")                        # no account, sign-ups closed
        self.state.save_security(signup_mode="invite")
        self.assertEqual(self.callback(self.start())[1], "/?gerr=invite")
        code = self.state.auth.new_invite("pro", 1)
        self.assertEqual(self.callback(self.start(code))[1], "/")
        self.assertEqual(self.state.usage.get_user("kim")["tier"], "pro")
        self.assertIsNone(self.state.auth.peek_invite(code))                              # used up
        self.state.save_security(signup_mode="open")
        self.token = id_token(email="lee@gmail.com")
        self.assertEqual(self.callback(self.start())[1], "/")
        self.assertEqual(self.state.usage.get_user("lee")["tier"], "free")

    def test_an_unverified_typed_email_is_never_taken_over(self):
        self.state.save_security(signup_mode="open")
        self.state.create_account("squatter", "kim@gmail.com", "a long steady phrase 77")
        self.assertEqual(self.callback(self.start())[1], "/?gerr=unverified")
        self.assertEqual(len(self.state.auth.sessions_for("squatter")), 0)

    def test_two_step_still_applies_and_banned_people_are_refused(self):
        self.state.set_email("sam", "kim@gmail.com")
        secret = accounts.new_secret()
        self.state._mfa_pending["sam"] = {"secret": secret, "expires": time.time() + 900}
        self.state.mfa_enable("sam", accounts.code_at(secret, int(time.time() // 30)))
        st, where = self.callback(self.start())
        self.assertTrue(where.startswith("/?mfa="))
        self.assertEqual(len(self.state.auth.sessions_for("sam")), 0)                     # no session until the code
        ticket = where.split("=", 1)[1]
        st, j = self.anon.call("POST", "/api/login/mfa", {"ticket": ticket, "code": accounts.code_at(secret, int(time.time() // 30) + 1)})
        self.assertEqual(st, 200)
        self.state.mfa_disable("sam")
        self.state.set_ban("sam", True)
        self.assertEqual(self.callback(self.start())[1], "/?gerr=banned")

    def test_reserved_and_short_names_are_not_handed_out(self):
        self.state.save_security(signup_mode="open")
        for email, expect in (("admin@gmail.com", "adminuser"), ("ab@gmail.com", "abuser")):
            self.token = id_token(email=email)
            self.assertEqual(self.callback(self.start())[1], "/")
            self.assertTrue(self.state.user_record(expect), expect)


if __name__ == "__main__":
    unittest.main()
