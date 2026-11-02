"""Optional error reports (app/observability.py): off unless the owner sets a Sentry address; and whatever is reported has the message, variables, request data, the
computer's name and anything key-shaped taken out first. The Sentry library itself is replaced by a stand-in, so nothing is ever sent from a test."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import types
import unittest

import observability as O

GOOD_DSN = "https://0123456789abcdef0123456789abcdef@o123456.ingest.sentry.io/4510001"
CHAT = "my password is hunter2 and my address is 12 Elm Street"
KEY = "emvryx_" + "a1b2c3d4e5f6a7b8c9d0e1f2"
TOKEN = "ghp_" + "A" * 36

REAL_EVENT = {
    "event_id": "e" * 32, "timestamp": "2026-11-02T14:00:00Z", "level": "error", "platform": "python", "release": "abc123", "environment": "production",
    "server_name": "DARRYLS-GAMING-PC", "user": {"id": "u1", "username": "darryl", "ip_address": "203.0.113.9", "email": "d@example.test"},
    "message": CHAT, "logentry": {"message": CHAT},
    "request": {"method": "POST", "url": "https://chat.emvryx.app/api/chats/4/send?key=" + KEY, "headers": {"Authorization": "Bearer " + KEY, "Cookie": "s=" + KEY},
                "data": {"text": CHAT}, "cookies": {"s": KEY}, "query_string": "key=" + KEY, "env": {"REMOTE_ADDR": "203.0.113.9"}},
    "breadcrumbs": {"values": [{"message": CHAT}]},
    "extra": {"prompt": CHAT, "token": TOKEN},
    "contexts": {"device": {"name": "DARRYLS-GAMING-PC"}},
    "modules": {"requests": "2.0"},
    "tags": {"handled": "no", "mechanism": "excepthook", "user_email": "d@example.test", "runtime": "CPython 3.11"},
    "exception": {"values": [{"type": "ValueError", "module": "builtins", "value": CHAT + " " + KEY,
                              "mechanism": {"type": "generic", "handled": False},
                              "stacktrace": {"frames": [
                                  {"filename": "app/routes_chat.py", "abs_path": "C:\\Users\\Darry\\Projects\\a.i-sml\\app\\routes_chat.py", "function": "send", "lineno": 88, "in_app": True,
                                   "vars": {"text": CHAT, "api_key": KEY}, "context_line": f'text = "{CHAT}"', "pre_context": [CHAT], "post_context": [CHAT]},
                                  {"filename": "socket.py", "abs_path": "C:\\Python311\\Lib\\socket.py", "function": "recv", "lineno": 12, "in_app": False}]}}]},
}


class Scrub(unittest.TestCase):
    def setUp(self):
        self.out = O.scrub_event(REAL_EVENT)
        self.text = json.dumps(self.out)

    def test_nothing_private_survives_anywhere_in_the_report(self):
        for secret in (CHAT, "hunter2", "Elm Street", KEY, TOKEN, "DARRYLS", "203.0.113.9", "d@example.test", "darryl", "C:\\\\Users", "a.i-sml"):
            self.assertNotIn(secret, self.text, secret)

    def test_what_is_needed_to_fix_the_bug_is_kept(self):
        ex = self.out["exception"]["values"][0]
        self.assertEqual(ex["type"], "ValueError")
        self.assertEqual(ex["value"], "ValueError (message removed)")
        frames = ex["stacktrace"]["frames"]
        self.assertEqual((frames[0]["filename"], frames[0]["function"], frames[0]["lineno"]), ("app/routes_chat.py", "send", 88))
        self.assertEqual(frames[1]["filename"], "socket.py")                         # a library file: its name only, never the folder on this PC
        self.assertEqual(self.out["request"], {"method": "POST", "url": "/api/chats/4/send"})      # the path only: no host, no query string
        self.assertEqual((self.out["release"], self.out["environment"], self.out["server_name"]), ("abc123", "production", "emvryx-pc"))

    def test_variables_source_lines_breadcrumbs_and_extras_are_dropped(self):
        frame = self.out["exception"]["values"][0]["stacktrace"]["frames"][0]
        for dropped in ("vars", "context_line", "pre_context", "post_context", "abs_path"):
            self.assertNotIn(dropped, frame)
        for dropped in ("user", "breadcrumbs", "extra", "contexts", "modules", "message", "logentry"):
            self.assertNotIn(dropped, self.out)
        self.assertEqual(self.out["tags"], {"handled": "no", "mechanism": "excepthook", "runtime": "CPython 3.11"})

    def test_a_plain_log_message_is_removed_entirely(self):
        out = O.scrub_event({"message": CHAT, "level": "warning", "request": {"url": "https://x.test/p?q=1"}})
        self.assertEqual(out["message"], O.REMOVED)
        self.assertNotIn(CHAT, json.dumps(out))

    def test_garbage_in_gives_nothing_out(self):
        self.assertIsNone(O.scrub_event(None))
        self.assertIsNone(O.scrub_event("a string"))

    def test_key_shaped_text_is_caught_even_where_nothing_was_expected(self):
        for secret in (KEY, TOKEN, "sk-" + "b" * 30, "hf_" + "c" * 30, "AKIA" + "D" * 16, "xoxb" + "-1234567890-abcdefghij", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlLWJ5dGVz"):
            self.assertEqual(O._clean(f"error near {secret} ok"), f"error near {O.REMOVED} ok", secret)
        self.assertEqual(O._clean({"Authorization": "x", "ok": 1, "nested": [{"password": "p", "name": "n"}]}), {"Authorization": O.REMOVED, "ok": 1, "nested": [{"password": O.REMOVED, "name": "n"}]})


class Init(unittest.TestCase):
    def setUp(self):
        O._state["on"] = False
        self.addCleanup(O._state.__setitem__, "on", False)
        self.addCleanup(sys.modules.pop, "sentry_sdk", None)
        self.calls = []
        fake = types.ModuleType("sentry_sdk")
        fake.init = lambda **kw: self.calls.append(("init", kw))
        fake.capture_exception = lambda e=None: self.calls.append(("capture", e))
        self.fake = fake

    def test_without_an_address_nothing_starts_and_nothing_is_imported(self):
        sys.modules["sentry_sdk"] = self.fake
        self.assertEqual(O.init({}), "off")
        self.assertEqual(O.init({"EMVRYX_SENTRY_DSN": "   "}), "off")
        O.capture()
        self.assertEqual(self.calls, [])

    def test_a_malformed_address_is_refused_with_a_plain_reason(self):
        sys.modules["sentry_sdk"] = self.fake
        for bad in ("http://0123456789abcdef0123456789abcdef@o1.ingest.sentry.io/1", "https://notakey@host/1", "hello", "https://0123456789abcdef0123456789abcdef@evil.test/1/extra"):
            self.assertIn("not a Sentry address", O.init({"EMVRYX_SENTRY_DSN": bad}), bad)
        self.assertEqual(self.calls, [])

    def test_a_missing_library_is_reported_not_raised(self):
        sys.modules["sentry_sdk"] = None                                         # makes `import sentry_sdk` fail
        self.assertIn("not installed", O.init({"EMVRYX_SENTRY_DSN": GOOD_DSN}))

    def test_it_starts_with_every_privacy_option_on_and_only_the_scrubber_allowed_to_send(self):
        sys.modules["sentry_sdk"] = self.fake
        self.assertEqual(O.init({"EMVRYX_SENTRY_DSN": GOOD_DSN, "EMVRYX_RELEASE": "r1"}), "on")
        kind, kw = self.calls[0]
        self.assertEqual(kw["dsn"], GOOD_DSN)
        self.assertIs(kw["send_default_pii"], False)
        self.assertIs(kw["include_local_variables"], False)
        self.assertIs(kw["include_source_context"], False)
        self.assertEqual((kw["max_breadcrumbs"], kw["traces_sample_rate"], kw["profiles_sample_rate"]), (0, 0.0, 0.0))
        self.assertIs(kw["before_send"], O.scrub_event)
        self.assertIsNone(kw["before_send_transaction"]({}, {}))                  # performance traces are never sent
        self.assertEqual((kw["server_name"], kw["release"]), ("emvryx-pc", "r1"))
        O.capture()
        self.assertEqual(self.calls[1][0], "capture")

    def test_a_failure_while_reporting_never_breaks_the_request(self):
        self.fake.capture_exception = lambda e=None: 1 / 0
        sys.modules["sentry_sdk"] = self.fake
        O.init({"EMVRYX_SENTRY_DSN": GOOD_DSN})
        O.capture()                                                              # must not raise

    def test_the_address_is_read_from_keys_env_and_never_printed(self):
        import app_server
        env = {}
        path = os.path.join(os.path.dirname(__file__), "..", ".emvryx-test-keys.env")
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        with open(path, "w") as f:
            f.write("EMVRYX_SENTRY_DSN=" + GOOD_DSN + "\n")
        self.assertEqual(app_server.load_keys_file(path, env), ["EMVRYX_SENTRY_DSN"])      # the names are what get printed
        self.assertEqual(env["EMVRYX_SENTRY_DSN"], GOOD_DSN)


if __name__ == "__main__":
    unittest.main()
