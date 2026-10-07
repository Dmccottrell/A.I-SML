"""Headers, the content security policy, the cross-site request check, and key links being off by default."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import re

from tests.test_app_server import Base, Client


class Headers(Base):
    def test_every_answer_carries_the_protective_headers(self):
        for path, auth in (("/", False), ("/api/state", True), ("/icon.svg", False), ("/manifest.webmanifest", False)):
            c = Client(self.port, self.state.owner_key() if auth else None)
            st, h, _ = c.call("GET", path, raw=True)
            self.assertEqual(st, 200, path)
            self.assertEqual(h["X-Frame-Options"], "DENY")
            self.assertEqual(h["Referrer-Policy"], "no-referrer")
            self.assertEqual(h["X-Content-Type-Options"], "nosniff")
            self.assertIn("frame-ancestors 'none'", h["Content-Security-Policy"])
            self.assertIn("noindex", h["X-Robots-Tag"])
            self.assertIn("camera=()", h["Permissions-Policy"])

    def test_the_page_policy_allows_only_its_own_script_by_nonce(self):
        st, h, page = Client(self.port).call("GET", "/", raw=True)
        csp = h["Content-Security-Policy"]
        nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
        self.assertIn(b'<script nonce="' + nonce.encode() + b'">', page)
        self.assertNotIn(b"<script>", page)
        self.assertIn("script-src 'self' 'nonce-", csp)
        self.assertNotIn("unsafe-eval", csp)
        self.assertNotIn("script-src 'self' 'unsafe-inline'", csp)
        self.assertIn("object-src 'none'", csp)
        again = Client(self.port).call("GET", "/", raw=True)[1]["Content-Security-Policy"]
        self.assertNotEqual(csp, again)                                      # a new nonce each time

    def test_json_answers_allow_nothing(self):
        h = Client(self.port, self.state.owner_key()).call("GET", "/api/state", raw=True)[1]
        self.assertTrue(h["Content-Security-Policy"].startswith("default-src 'none'"))

    def test_hsts_only_when_the_proxy_says_https(self):
        self.assertNotIn("Strict-Transport-Security", Client(self.port).call("GET", "/", raw=True)[1])
        h = Client(self.port).call("GET", "/", raw=True, headers={"X-Forwarded-Proto": "https"})[1]
        self.assertIn("max-age=31536000", h["Strict-Transport-Security"])
        self.state.security["trusted_proxies"] = []                          # a caller that is not our proxy cannot claim https
        self.assertNotIn("Strict-Transport-Security", Client(self.port).call("GET", "/", raw=True, headers={"X-Forwarded-Proto": "https"})[1])


class CrossSite(Base):
    def post(self, headers):
        return self.sam.call("POST", "/api/chats", {}, headers=headers)[0]

    def test_a_request_from_another_website_is_refused(self):
        self.assertEqual(self.post({"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"}), 403)
        self.assertEqual(self.post({"Origin": "https://evil.example"}), 403)
        self.assertEqual(self.post({"Origin": "null"}), 403)
        self.assertEqual(self.post({"Sec-Fetch-Site": "same-site", "Origin": "https://evil.emvryx.app"}), 403)

    def test_the_apps_own_pages_and_plain_programs_are_let_through(self):
        self.assertEqual(self.post({"Sec-Fetch-Site": "same-origin", "Origin": "https://chat.emvryx.app"}), 200)   # even if the proxy rewrote Host
        self.assertEqual(self.post({"Origin": f"http://127.0.0.1:{self.port}", "Host": f"127.0.0.1:{self.port}"}), 200)
        self.assertEqual(self.post({}), 200)                                  # curl, scripts: not a browser

    def test_an_origin_can_be_allowed_by_setting(self):
        self.assertEqual(self.post({"Origin": "https://chat.emvryx.app"}), 403)
        self.state.security["allowed_origins"] = ["https://chat.emvryx.app"]
        self.assertEqual(self.post({"Origin": "https://chat.emvryx.app"}), 200)

    def test_delete_is_checked_too_and_the_refusal_is_logged(self):
        cid = self.new_chat(self.sam)
        st, _ = self.sam.call("DELETE", f"/api/chats/{cid}", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(st, 403)
        self.assertEqual(self.sam.call("GET", f"/api/chats/{cid}")[0], 200)
        self.assertIn("bad_origin", {e["kind"] for e in self.state.auth.events()})


class KeyLinks(Base):
    def test_key_links_are_off_by_default(self):
        st, h, _ = Client(self.port).call("GET", "/?key=" + self.sam_key, raw=True)
        self.assertEqual(st, 302)
        self.assertEqual(h["Location"], "/?notice=keylink")                   # the key is dropped from the address at once
        self.assertNotIn("Set-Cookie", h)
        self.assertIn("key_link_refused", {e["kind"] for e in self.state.auth.events()})

    def test_the_owner_can_turn_them_back_on(self):
        self.state.security["allow_key_links"] = True
        st, h, _ = Client(self.port).call("GET", "/?key=" + self.sam_key, raw=True)
        self.assertEqual(h["Location"], "/")
        self.assertIn("emvryx_session=", h["Set-Cookie"])


if __name__ == "__main__":
    import unittest
    unittest.main()
