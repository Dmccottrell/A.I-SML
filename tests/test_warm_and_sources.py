"""Loading the picked model in the background (no waiting on the first message), and the list of live sources."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import threading
import time
import unittest

import live_data
from tests.test_app_server import Base


class FakeRunner:
    def __init__(self):
        self.loaded = []
        self.gate = threading.Event()
        self.gate.set()

    def available(self, model_id):
        return True

    def ensure(self, model_id, ctx, cancel=None):
        self.gate.wait(5)
        self.loaded.append((model_id, ctx))
        return "http://x"

    def ready(self, model_id, ctx):
        return False


class Warm(Base):
    def setUp(self):
        super().setUp()
        self.state.runner = FakeRunner()

    def test_picking_a_model_loads_it_in_the_background(self):
        self.assertTrue(self.owner.call("POST", "/api/models/warm", {"model": "equinox-2"})[1]["ok"])
        deadline = time.time() + 5
        while not self.state.runner.loaded and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(self.state.runner.loaded[0][0], "equinox-2")

    def test_quick_switching_only_loads_the_last_pick(self):
        self.state.runner.gate.clear()
        self.owner.call("POST", "/api/models/warm", {"model": "equinox-2"})
        self.owner.call("POST", "/api/models/warm", {"model": "solstice-2"})
        self.owner.call("POST", "/api/models/warm", {"model": "equinox-2"})
        self.state.runner.gate.set()
        deadline = time.time() + 5
        while self.state._warm_thread.is_alive() and time.time() < deadline:
            time.sleep(0.02)
        ids = [m for m, _ in self.state.runner.loaded]
        self.assertEqual(ids[-1], "equinox-2")
        self.assertLessEqual(len(ids), 2)

    def test_not_while_a_reply_is_being_written(self):
        self.state.stops[("owner", 1)] = threading.Event()
        self.assertFalse(self.owner.call("POST", "/api/models/warm", {"model": "equinox-2"})[1]["ok"])
        self.assertEqual(self.state.runner.loaded, [])

    def test_nothing_to_warm_without_local_models_or_for_unknown_ones(self):
        self.assertFalse(self.owner.call("POST", "/api/models/warm", {"model": "nope"})[1]["ok"])
        self.state.runner = None
        self.assertFalse(self.owner.call("POST", "/api/models/warm", {"model": "equinox-2"})[1]["ok"])


class Sources(unittest.TestCase):
    def test_keyed_sources_are_off_until_their_key_is_set(self):
        rows = {r["id"]: r for r in live_data.sources_status({})}
        for name in ("fred", "wolfram", "releases"):
            self.assertFalse(rows[name]["active"], name)
            self.assertTrue(rows[name]["needs_key"], name)
        self.assertTrue(rows["calculator"]["active"] and rows["calculator"]["where"] == "offline")
        self.assertTrue(rows["nutrition"]["active"])                       # works without its optional key
        rows = {r["id"]: r for r in live_data.sources_status({"FRED_API_KEY": "x", "TMDB_API_KEY": "y"})}
        self.assertTrue(rows["fred"]["active"] and rows["releases"]["active"])
        self.assertFalse(rows["wolfram"]["active"])


class Endpoint(Base):
    def test_page_can_list_the_sources(self):
        j = self.sam.call("GET", "/api/live/sources")[1]
        self.assertTrue(any(s["id"] == "calculator" for s in j["sources"]))
        self.assertIn(j["web"], ("wikipedia", "tavily", "brave", "gemini"))


if __name__ == "__main__":
    unittest.main()
