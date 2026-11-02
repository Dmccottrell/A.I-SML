"""The load test tool (tools/load_test.py) works against a real running test server, counts what worked, and refuses silly settings or a missing key."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "tools"))
import load_test
from tests.test_app_server import Base


class Tool(Base):
    def test_the_pages_scenario_counts_every_request(self):
        r = load_test.run(f"http://127.0.0.1:{self.port}", self.state.owner_key(), users=4, rounds=2, scenario="pages")
        self.assertEqual((r["requests"], r["ok"], r["failed"]), (16, 16, 0), r)
        self.assertIsNotNone(r["median"])

    def test_a_wrong_key_is_counted_as_failed_not_as_a_crash(self):
        r = load_test.run(f"http://127.0.0.1:{self.port}", "not-a-real-key", users=2, rounds=1, scenario="pages")
        self.assertGreater(r["failed"], 0, r)                    # the page itself is public, but the state needs a key

    def test_the_chat_scenario_starts_chats_and_sends(self):
        r = load_test.run(f"http://127.0.0.1:{self.port}", self.state.owner_key(), users=2, rounds=1, scenario="chat")
        self.assertEqual(r["failed"], 0, r)
        self.assertEqual(r["requests"], 4)

    def test_a_missing_key_or_silly_numbers_are_refused(self):
        old = os.environ.pop("EMVRYX_KEY", None)
        try:
            self.assertEqual(load_test.main(["--url", "http://127.0.0.1:1"]), 2)
            os.environ["EMVRYX_KEY"] = "x"
            self.assertEqual(load_test.main(["--url", "http://127.0.0.1:1", "--users", "500"]), 2)
        finally:
            os.environ.pop("EMVRYX_KEY", None)
            if old is not None:
                os.environ["EMVRYX_KEY"] = old


if __name__ == "__main__":
    unittest.main()
