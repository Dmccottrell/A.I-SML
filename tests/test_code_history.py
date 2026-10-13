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

    def test_history_survives_a_restart_and_the_session_carries_on(self):
        sid = self.run_session()
        self.state.code.sessions.clear()                              # what a restart does to the running ones
        j = self.owner.call("GET", f"/api/code/sessions/{sid}")[1]
        self.assertTrue(j["saved"])
        self.assertEqual(j["events"][0]["kind"], "start")
        before = len(j["events"])
        seen = []
        self.state.code_generate = lambda model: (lambda messages: (seen.append(messages), "Fixed it.")[1])
        st, r = self.owner.call("POST", f"/api/code/sessions/{sid}/message", {"text": "the page shows an error, fix it"})
        self.assertEqual((st, r["revived"]), (200, True), r)
        wait_for(lambda: self.state.code.sessions[sid].state in ("done", "stopped", "failed"))
        told = [m for m in seen[0] if m["role"] == "user"][-1]["content"]
        self.assertIn("continues an earlier session", told)                  # the model is told what happened before
        self.assertIn("slugify", told)
        self.assertIn("the page shows an error, fix it", told)
        j = self.owner.call("GET", f"/api/code/sessions/{sid}")[1]
        self.assertGreater(len(j["events"]), before)                          # the same session, its feed goes on
        self.assertEqual(j["events"][0]["kind"], "start")
        rows = self.owner.call("GET", "/api/code/sessions")[1]["sessions"]
        self.assertEqual([r["id"] for r in rows], [sid])                    # no new session in the list

    def test_another_model_takes_over_the_same_session(self):
        sid = self.run_session()
        seen = []
        self.state.code_generate = lambda model: (lambda messages: (seen.append((model["id"], messages)), "Done.")[1])
        st, r = self.owner.call("POST", f"/api/code/sessions/{sid}/message", {"text": "now add a docstring", "model": "equinox-2"})
        self.assertEqual((st, r["revived"]), (200, False), r)
        wait_for(lambda: self.state.code.sessions[sid].state in ("done", "stopped", "failed"))
        self.assertEqual(seen[0][0], "equinox-2")
        self.assertTrue(any("slugify" in str(m["content"]) for m in seen[0][1]))     # it sees the whole conversation so far
        s = self.state.code.sessions[sid]
        self.assertEqual(s.model_id, "equinox-2")
        ev = [e for e in s.events if e["kind"] == "model"]
        self.assertEqual((ev[0]["model"], ev[0]["previous"]), ("equinox-2", "solstice-2"))
        self.assertEqual(len(self.owner.call("GET", "/api/code/sessions")[1]["sessions"]), 1)

    def test_other_people_do_not_see_my_sessions(self):
        sid = self.run_session()
        self.assertEqual(self.sam.call("GET", "/api/code/sessions")[1]["sessions"], [])
        self.assertEqual(self.sam.call("GET", f"/api/code/sessions/{sid}")[0], 400)

    def test_changes_are_listed_per_file_and_one_can_be_undone(self):
        os.makedirs(os.path.join(self.state.code.project_path("owner", "demo")), exist_ok=True)
        with open(os.path.join(self.state.code.project_path("owner", "demo"), "keep.txt"), "w") as f:
            f.write("old\n")
        sid = self.run_session()
        ws = self.state.code.project_path("owner", "demo")
        with open(os.path.join(ws, "keep.txt"), "w") as f:
            f.write("new\n")                                                     # the session (or a person) changed a file that was there before
        rows = {r["path"]: r for r in self.owner.call("GET", f"/api/code/sessions/{sid}/changes")[1]["changes"]}
        self.assertEqual(rows["keep.txt"]["status"], "changed")
        self.assertEqual((rows["keep.txt"]["add"], rows["keep.txt"]["del"]), (1, 1))
        made = next(p for p, r in rows.items() if r["status"] == "new")
        st, j = self.owner.call("POST", f"/api/code/sessions/{sid}/reject", {"path": "keep.txt"})
        self.assertEqual((st, j["restored"]), (200, True), j)
        with open(os.path.join(ws, "keep.txt")) as f:
            self.assertEqual(f.read(), "old\n")
        st, j = self.owner.call("POST", f"/api/code/sessions/{sid}/reject", {"path": made})
        self.assertEqual((st, j["restored"]), (200, False), j)                    # a file the session made is removed
        self.assertFalse(os.path.exists(os.path.join(ws, made)))
        self.assertEqual(self.owner.call("POST", f"/api/code/sessions/{sid}/reject", {"path": "keep.txt"})[0], 400)    # nothing left to undo there
        self.assertEqual(self.owner.call("POST", f"/api/code/sessions/{sid}/reject", {"path": "../x"})[0], 400)
        self.assertNotIn("keep.txt", [r["path"] for r in self.owner.call("GET", f"/api/code/sessions/{sid}/changes")[1]["changes"]])

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
