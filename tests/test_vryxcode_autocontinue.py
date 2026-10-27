"""vryxcode_autocontinue: out of steps and not finished, VryxCode carries on by itself (at most AUTO_ROUNDS times), and the end says plainly why."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import itertools
import unittest

import code_sessions
import vryxcode
from tests.test_app_server import Base
from tests.test_code_sessions import open_to_everyone, wait_for


def busy_model(finish_after=None):
    """A model that writes a new file each step, and finishes after `finish_after` steps (never, when None)."""
    count = itertools.count(1)

    def make(model):
        def generate(messages):
            n = next(count)
            if finish_after and n > finish_after:
                return vryxcode.harness_call("finish", summary="All done.")
            return vryxcode.harness_call("write_file", path=f"part{n}.txt", content=f"part {n}\n")
        return generate
    return make


class AutoContinue(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        self.state.code.max_turns = 2

    def run_one(self):
        st, j = self.owner.call("POST", "/api/code/start", {"project": "big", "task": "build the whole thing", "model": "solstice-2", "auto_edits": True})
        self.assertEqual(st, 200, j)
        sid = j["id"]
        wait_for(lambda: self.state.code.sessions[sid].state in ("done", "stopped", "failed", "limited"), 30)
        return self.owner.call("GET", f"/api/code/sessions/{sid}")[1]["events"]

    def test_off_it_stops_and_says_it_ran_out_of_steps(self):
        self.state.code_generate = busy_model()
        events = self.run_one()
        ends = [e for e in events if e["kind"] == "end"]
        self.assertEqual(len(ends), 1)
        self.assertEqual((ends[0]["finished"], ends[0]["reason"], ends[0]["rounds"]), (False, "steps", 0))

    def test_on_it_carries_on_until_finished(self):
        self.state.flags.data["audiences"]["vryxcode_autocontinue"] = "admins"
        self.state.code_generate = busy_model(finish_after=5)                  # needs three rounds of 2 steps
        events = self.run_one()
        notes = [e["text"] for e in events if e["kind"] == "note"]
        ends = [e for e in events if e["kind"] == "end"]
        self.assertEqual(len(ends), 1)
        self.assertTrue(ends[0]["finished"])
        self.assertNotIn("reason", ends[0])
        self.assertEqual(len(notes), 2, notes)
        self.assertIn("carrying on by itself (1 of", notes[0])

    def test_on_it_still_stops_after_the_last_round(self):
        self.state.flags.data["audiences"]["vryxcode_autocontinue"] = "admins"
        self.state.code_generate = busy_model()
        events = self.run_one()
        ends = [e for e in events if e["kind"] == "end"]
        self.assertEqual(len(ends), 1)
        self.assertEqual((ends[0]["finished"], ends[0]["reason"], ends[0]["rounds"]), (False, "steps", code_sessions.AUTO_ROUNDS))


if __name__ == "__main__":
    unittest.main()
