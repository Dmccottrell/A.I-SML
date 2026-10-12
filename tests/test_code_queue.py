"""Sessions wait their turn: one model on one card, so a second session is queued and starts when the first one finishes."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import time
import unittest

import vryxcode
from tests.test_code_sessions import wait_for, open_to_everyone
from tests.test_app_server import Base


class Queue(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(list(vryxcode.DEMO))

    def start(self, task="write slugify", **kw):
        return self.owner.call("POST", "/api/code/start", {"project": "demo", "task": task, "model": "solstice-2", **kw})

    def info(self, sid):
        return self.owner.call("GET", f"/api/code/sessions/{sid}")[1]

    def allow(self, sid):
        """Say yes to every permission question until the session is over."""
        deadline = time.time() + 20
        while time.time() < deadline:
            j = self.info(sid)
            if j["state"] in ("done", "failed", "stopped"):
                return
            if j["pending"]:
                self.owner.call("POST", f"/api/code/sessions/{sid}/answer", {"id": j["pending"]["id"], "allow": True})
            time.sleep(0.05)
        raise AssertionError("session did not finish")

    def test_a_second_session_is_refused_without_queue_and_queued_with_it(self):
        st, a = self.start()
        wait_for(lambda: self.info(a["id"])["state"] == "asking")          # the first is waiting for permission to write, so it is running
        st, j = self.start("another job")
        self.assertEqual(st, 400)
        self.assertIn("already have a session running", j["message"])
        st, b = self.start("another job", queue=True)
        self.assertEqual(st, 200)
        self.assertTrue(b["queued"])
        self.assertEqual(b["position"], 1)
        self.assertEqual(self.info(b["id"])["state"], "queued")

    def test_the_queued_session_starts_by_itself_when_the_first_finishes(self):
        st, a = self.start()
        wait_for(lambda: self.info(a["id"])["state"] == "asking")
        st, b = self.start("second job", queue=True)
        self.assertEqual(self.info(b["id"])["state"], "queued")
        listed = {s["id"]: s for s in self.owner.call("GET", "/api/code/sessions")[1]["sessions"]}
        self.assertEqual((listed[b["id"]]["state"], listed[b["id"]]["position"]), ("queued", 1))
        self.allow(a["id"])                                                  # the first finishes...
        wait_for(lambda: self.info(a["id"])["state"] == "done")
        wait_for(lambda: self.info(b["id"])["state"] in ("starting", "working", "asking", "done"))      # ...and the second starts without anyone pressing anything
        self.allow(b["id"])
        self.assertEqual(self.info(b["id"])["state"], "done")
        kinds = [e["kind"] for e in self.info(b["id"])["events"]]
        self.assertEqual(kinds[0], "queued")
        self.assertIn("start", kinds)

    def test_stopping_a_queued_session_takes_it_out_and_the_next_one_still_runs(self):
        st, a = self.start()
        wait_for(lambda: self.info(a["id"])["state"] == "asking")
        _, b = self.start("second", queue=True)
        _, c = self.start("third", queue=True)
        self.assertEqual(c["position"], 2)
        self.owner.call("POST", f"/api/code/sessions/{b['id']}/stop", {})
        self.assertEqual(self.info(b["id"])["state"], "stopped")
        self.allow(a["id"])
        wait_for(lambda: self.info(c["id"])["state"] in ("starting", "working", "asking", "done"))
        self.assertEqual(self.info(b["id"])["state"], "stopped")             # the stopped one never started
        self.assertNotIn("start", [e["kind"] for e in self.info(b["id"])["events"]])

    def test_the_queue_has_a_limit(self):
        st, a = self.start()
        wait_for(lambda: self.info(a["id"])["state"] == "asking")
        for i in range(5):
            self.assertEqual(self.start(f"job {i}", queue=True)[0], 200)
        st, j = self.start("one too many", queue=True)
        self.assertEqual(st, 400)
        self.assertIn("waiting in your queue", j["message"])


if __name__ == "__main__":
    unittest.main()
