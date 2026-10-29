"""app_updates: "A new version of Emvryx is ready". The Windows app's page asks the server for the newest build (version.json next to the
newest installer on GitHub), and the server asks GitHub at most once an hour."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import json
import unittest

import app_updates
import flags
from tests.test_app_server import Base


class Latest(unittest.TestCase):
    def test_it_is_read_once_an_hour_and_a_failure_is_nothing(self):
        calls = []
        now = [1000.0]

        def fetch(url):
            calls.append(url)
            return json.dumps({"sha": "abc123", "built": "2026-10-29T12:00:00Z"}).encode()
        u = app_updates.Updates(fetch=fetch, clock=lambda: now[0])
        got = u.latest("windows")
        self.assertEqual((got["sha"], got["download"]), ("abc123", app_updates.DOWNLOADS["windows"]))
        self.assertIn("windows-latest/version.json", calls[0])
        u.latest("windows")
        self.assertEqual(len(calls), 1)                                       # kept for an hour
        now[0] += 3601
        u.latest("windows")
        self.assertEqual(len(calls), 2)
        bad = app_updates.Updates(fetch=lambda url: (_ for _ in ()).throw(OSError("no internet")), clock=lambda: 0.0)
        self.assertIsNone(bad.latest("windows"))
        self.assertIsNone(u.latest("toaster"))                                # only the apps there are


class Server(Base):
    def test_the_page_asks_the_server(self):
        self.assertEqual(flags.BY_ID["app_updates"]["default"], "admins")
        self.state.updates = app_updates.Updates(fetch=lambda url: b'{"sha": "abc123", "built": "x"}')
        self.assertNotEqual(self.owner.call("GET", "/api/app-latest?platform=windows")[0], 200)     # off in the tests' base
        self.state.flags.data["audiences"]["app_updates"] = "admins"
        s, j = self.owner.call("GET", "/api/app-latest?platform=windows")
        self.assertEqual((s, j["sha"]), (200, "abc123"))
        self.assertEqual(self.owner.call("GET", "/api/app-latest?platform=other")[1], {"sha": ""})


if __name__ == "__main__":
    unittest.main()
