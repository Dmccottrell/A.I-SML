"""VryxCode's Sessions list (kept on disk), where a session runs, and Rewind."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import time
import unittest

import code_log
import vryxcode
from tests.test_app_server import Base
from tests.test_code_sessions import open_to_everyone, wait_for


class History(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(list(vryxcode.DEMO))

    def run_session(self, c=None, **kw):
        c = c or self.owner
        st, j = c.call("POST", "/api/code/start", {"project": "demo", "task": "write slugify with a test", "model": "solstice-2", "auto_edits": True, **kw})
        self.assertEqual(st, 200, j)
        sid = j["id"]
        wait_for(lambda: c.call("GET", f"/api/code/sessions/{sid}")[1]["state"] in ("done", "stopped", "failed"))
        wait_for(lambda: self.state.code.sessions[sid].state in ("done", "stopped", "failed"))
        return sid

    def test_session_appears_in_the_list_with_what_it_did(self):
        sid = self.run_session()
        rows = self.owner.call("GET", "/api/code/sessions")[1]["sessions"]
        row = next(r for r in rows if r["id"] == sid)
        self.assertEqual((row["project"], row["env"]), ("demo", "local"))
        self.assertIn("slugify", row["title"])
        self.assertGreater(row["steps"], 0)
        self.assertEqual(len(row["checkpoints"]), 1)
        self.assertTrue(row["age"])

    def test_history_survives_a_restart_and_is_read_only(self):
        sid = self.run_session()
        self.state.code.sessions.clear()                              # what a restart does to the running ones
        j = self.owner.call("GET", f"/api/code/sessions/{sid}")[1]
        self.assertTrue(j["saved"])
        self.assertEqual(j["events"][0]["kind"], "start")
        self.assertEqual(self.owner.call("POST", f"/api/code/sessions/{sid}/message", {"text": "more"})[0], 400)
        self.assertEqual(self.owner.call("GET", "/api/code/sessions")[1]["sessions"][0]["id"], sid)

    def test_other_people_do_not_see_my_sessions(self):
        sid = self.run_session()
        self.assertEqual(self.sam.call("GET", "/api/code/sessions")[1]["sessions"], [])
        self.assertEqual(self.sam.call("GET", f"/api/code/sessions/{sid}")[0], 400)

    def test_rewind_removes_what_the_session_made(self):
        sid = self.run_session()
        before = self.owner.call("GET", "/api/code/files?project=demo")[1]["files"]
        self.assertTrue(before)
        st, j = self.owner.call("POST", f"/api/code/sessions/{sid}/rewind", {"turn": 1})
        self.assertEqual(st, 200, j)
        self.assertEqual(self.owner.call("GET", "/api/code/files?project=demo")[1]["files"], [])
        last = self.owner.call("GET", f"/api/code/sessions/{sid}")[1]["events"][-1]
        self.assertEqual(last["kind"], "rewind")

    def test_rewind_to_a_point_that_is_not_kept(self):
        sid = self.run_session()
        st, j = self.owner.call("POST", f"/api/code/sessions/{sid}/rewind", {"turn": 9})
        self.assertEqual(st, 400)
        self.assertIn("no longer kept", j["message"])

    def test_delete_a_session(self):
        sid = self.run_session()
        self.assertEqual(self.owner.call("POST", f"/api/code/sessions/{sid}/delete", {})[0], 200)
        self.assertEqual(self.owner.call("GET", "/api/code/sessions")[1]["sessions"], [])

    def test_project_list_does_not_show_the_history_folder(self):
        self.run_session()
        self.assertEqual(self.owner.call("GET", "/api/code")[1]["projects"], ["demo"])


class Environments(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(list(vryxcode.DEMO))

    def test_the_page_is_told_what_is_available(self):
        envs = {e["id"]: e for e in self.owner.call("GET", "/api/code")[1]["environments"]}
        self.assertTrue(envs["local"]["available"])
        self.assertFalse(envs["cloud"]["available"])
        self.assertIn("Not set up", envs["cloud"]["note"])

    def test_cloud_is_refused_plainly(self):
        st, j = self.owner.call("POST", "/api/code/start", {"project": "demo", "task": "x", "model": "solstice-2", "env": "cloud"})
        self.assertEqual(st, 400)
        self.assertIn("cloud machine isn't available", j["message"])

    def test_sandbox_without_docker_is_refused_not_quietly_run_on_the_host(self):
        self.state.code._docker = (False, "Docker is not installed on this server.")
        self.state.code._docker_at = time.time()
        st, j = self.owner.call("POST", "/api/code/start", {"project": "demo", "task": "x", "model": "solstice-2", "env": "sandbox"})
        self.assertEqual(st, 400)
        self.assertIn("isolated sandbox isn't available", j["message"])

    def test_age_words(self):
        now = 1_800_000_000
        self.assertEqual([code_log.age_words(now, now - s) for s in (5, 300, 7200, 172800)], ["now", "5m", "2h", "2d"])


if __name__ == "__main__":
    unittest.main()
