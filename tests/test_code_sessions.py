"""The VryxCode screen's server side: projects, a scripted session, permission questions, stopping, and the guards."""
import os
import time
import unittest

import harness
import vryxcode
from tests.test_app_server import Base, Client


def wait_for(fn, seconds=15):
    end = time.time() + seconds
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("timed out")


class CodeTests(Base):
    def setUp(self):
        super().setUp()
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(list(vryxcode.DEMO))

    def poll(self, c, sid, after=0):
        return c.call("GET", f"/api/code/sessions/{sid}?after={after}")[1]

    def start(self, c, **kw):
        body = {"project": "demo", "task": "write slugify", "model": "solstice-2", **kw}
        return c.call("POST", "/api/code/start", body)

    def test_lists_only_models_that_can_code(self):
        st, j = self.owner.call("GET", "/api/code")
        self.assertEqual(st, 200)
        ids = {m["id"] for m in j["models"]}
        self.assertIn("equinox-2", ids)
        self.assertIn("solstice-2", ids)
        self.assertNotIn("flare-2.5", ids)
        note = next(m for m in j["models"] if m["id"] == "equinox-2")["note"]
        self.assertIn("small", note)

    def test_refuses_a_model_too_small(self):
        st, j = self.start(self.owner, model="flare-2.5")
        self.assertEqual(st, 400)
        self.assertIn("too small", j["message"])

    def test_bad_project_names_are_refused(self):
        for name in ("../x", "a/b", "", "x" * 41):
            st, _ = self.start(self.owner, project=name)
            self.assertEqual(st, 400, name)

    def test_full_run_with_approvals(self):
        st, j = self.start(self.owner)
        self.assertEqual(st, 200, j)
        sid, seen = j["id"], 0
        asked = 0
        deadline = time.time() + 20
        while time.time() < deadline:
            r = self.poll(self.owner, sid, seen)
            seen += len(r["events"])
            if r["pending"]:
                asked += 1
                self.assertEqual(self.owner.call("POST", f"/api/code/sessions/{sid}/answer", {"id": r["pending"]["id"], "allow": True})[1]["ok"], True)
            if r["state"] in ("done", "stopped", "failed"):
                break
            time.sleep(0.05)
        self.assertEqual(r["state"], "done", r)
        self.assertGreaterEqual(asked, 1)                              # writing a file asks first
        allev = self.poll(self.owner, sid)["events"]
        kinds = [e["kind"] for e in allev]
        self.assertEqual(kinds[0], "start")
        self.assertEqual(kinds[-1], "end")
        self.assertIn("step", kinds)
        self.assertIn("result", kinds)
        files = self.owner.call("GET", "/api/code/files?project=demo")[1]["files"]
        self.assertIn("slug.py", files)
        text = self.owner.call("GET", "/api/code/file?project=demo&path=slug.py")[1]["text"]
        self.assertIn("def slugify", text)

    def test_no_answer_means_no_edit_and_stop_ends_it(self):
        sid = self.start(self.owner)[1]["id"]
        r = wait_for(lambda: (lambda x: x if x["pending"] else None)(self.poll(self.owner, sid)))
        self.assertEqual(r["state"], "asking")
        self.owner.call("POST", f"/api/code/sessions/{sid}/stop", {})
        r = wait_for(lambda: (lambda x: x if x["state"] in ("stopped", "done", "failed") else None)(self.poll(self.owner, sid)))
        self.assertEqual(r["state"], "stopped")
        self.assertEqual(self.owner.call("GET", "/api/code/files?project=demo")[1]["files"], [])

    def test_auto_approve_edits_runs_without_questions(self):
        sid = self.start(self.owner, auto_edits=True)[1]["id"]
        r = wait_for(lambda: (lambda x: x if x["state"] in ("done", "failed", "stopped") else None)(self.poll(self.owner, sid)))
        self.assertEqual(r["state"], "done")
        self.assertFalse([e for e in self.poll(self.owner, sid)["events"] if e["kind"] == "ask"])

    def test_one_session_at_a_time(self):
        self.start(self.owner)
        st, j = self.start(self.owner, project="other")
        self.assertEqual(st, 400)
        self.assertIn("already", j["message"])

    def test_people_cannot_reach_each_others_sessions_or_files(self):
        sid = self.start(self.owner, auto_edits=True)[1]["id"]
        wait_for(lambda: self.poll(self.owner, sid)["state"] == "done")
        st, j = self.owner.call("POST", "/api/admin/users", {"user": "sam", "tier": "pro"})
        sam = Client(self.port, j["key"])
        self.assertEqual(sam.call("GET", f"/api/code/sessions/{sid}")[0], 400)
        self.assertEqual(sam.call("GET", "/api/code/files?project=demo")[1]["files"], [])
        self.assertEqual(sam.call("GET", "/api/code/file?project=demo&path=slug.py")[0], 400)

    def test_file_reads_stay_inside_the_project(self):
        sid = self.start(self.owner, auto_edits=True)[1]["id"]
        wait_for(lambda: self.poll(self.owner, sid)["state"] == "done")
        for bad in ("../../users.json", "/etc/passwd", "..%2F..%2Fx"):
            self.assertEqual(self.owner.call("GET", "/api/code/file?project=demo&path=" + bad)[0], 400, bad)

    def test_model_trouble_is_reported_not_a_crash(self):
        def broken(model):
            raise SystemExit("can't reach the model")
        self.state.code_generate = broken
        sid = self.start(self.owner)[1]["id"]
        r = wait_for(lambda: (lambda x: x if x["state"] == "failed" else None)(self.poll(self.owner, sid)))
        self.assertIn("could not finish", r["events"][-1]["summary"])

    def test_delete_project(self):
        sid = self.start(self.owner, auto_edits=True)[1]["id"]
        wait_for(lambda: self.poll(self.owner, sid)["state"] == "done")
        self.assertEqual(self.owner.call("POST", "/api/code/projects/delete", {"project": "demo"})[0], 200)
        self.assertNotIn("demo", self.owner.call("GET", "/api/code")[1]["projects"])

    def test_needs_a_key(self):
        self.assertEqual(Client(self.port).call("GET", "/api/code")[0], 401)


if __name__ == "__main__":
    unittest.main()
