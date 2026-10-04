"""Tests for connected_apps.py and its server endpoints."""
import unittest

import connected_apps as C
from tests.test_app_server import Base


class Catalog(unittest.TestCase):
    def test_list_is_valid(self):
        self.assertEqual(C.check(), [])

    def test_nothing_is_connectable_yet(self):
        self.assertTrue(all(a["status"] == "soon" for a in C.APPS))

    def test_every_app_that_changes_things_asks_first(self):
        for a in C.APPS:
            if "confirm" not in (a["does"] + a["permission"]).lower() and "never" not in a["permission"].lower():
                self.assertIn("read", a["permission"].lower(), a["id"])

    def test_rules_say_read_only_and_confirm(self):
        text = " ".join(C.RULES).lower()
        for word in ("off", "read-only", "confirm", "disconnect", "own device"):
            self.assertIn(word, text)


class Server(Base):
    def test_the_page_gets_the_list(self):
        s, j = self.sam.call("GET", "/api/apps")
        self.assertEqual(s, 200)
        self.assertEqual({a["id"] for a in j["apps"]}, {a["id"] for a in C.APPS})
        self.assertTrue(j["rules"])

    def test_connecting_says_coming_soon(self):
        s, j = self.sam.call("POST", "/api/apps/github/connect", {})
        self.assertEqual((s, j["code"]), (501, "coming_soon"))
        self.assertEqual(self.sam.call("POST", "/api/apps/nothing/connect", {})[0], 404)

    def test_needs_a_key(self):
        from tests.test_app_server import Client
        self.assertEqual(Client(self.port).call("GET", "/api/apps")[0], 401)


if __name__ == "__main__":
    unittest.main()
