"""The VryxCode screen's server side: projects, a scripted session, permission questions, stopping, and the guards."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import base64
import http.client
import io
import os
import time
import zipfile
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


def open_to_everyone(state):
    """For the tests of coding itself: everyone's plan includes VryxCode and the owner accepts the folder sandbox for them
    (the gating has its own tests in test_code_sandbox.py)."""
    state.security["code_unsandboxed_for_others"] = True
    for tier in state.cfg["tiers"].values():
        tier["vryxcode"] = True


class CodeTests(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
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
        report = allev[-1].get("report")                               # the end of a turn that wrote files carries its verification report
        self.assertTrue(report and report["files"] and report["files"][0]["path"] == "slug.py", report)
        self.assertIn(report["verdict"], ("verified", "checked", "not_verified"))
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
        sam = self.sam                                                   # another person (the free plan)
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

    def test_delete_project_with_read_only_files(self):
        import stat, tempfile
        import code_sessions
        folder = os.path.join(tempfile.mkdtemp(), "imported")
        os.makedirs(os.path.join(folder, ".git", "objects"))
        locked = os.path.join(folder, ".git", "objects", "pack.idx")
        with open(locked, "w") as f:
            f.write("x")
        os.chmod(locked, stat.S_IREAD)                                      # what a git checkout leaves behind on Windows
        self.assertTrue(code_sessions.remove_tree(folder))
        self.assertFalse(os.path.exists(folder))

    def test_a_session_in_another_project_does_not_block_delete(self):
        import code_sessions
        os.makedirs(self.state.code.project_path("owner", "old-one"), exist_ok=True)
        busy = type("S", (), {"project": "demo"})()
        self.state.code.running = lambda user: busy
        self.state.code.delete_project("owner", "old-one")
        self.assertFalse(os.path.isdir(self.state.code.project_path("owner", "old-one")))
        with self.assertRaises(code_sessions.CodeError):
            self.state.code.delete_project("owner", "demo")

    def test_needs_a_key(self):
        self.assertEqual(Client(self.port).call("GET", "/api/code")[0], 401)


class MoreTests(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(list(vryxcode.DEMO))

    def finish_run(self, c):
        sid = c.call("POST", "/api/code/start", {"project": "demo", "task": "x", "model": "solstice-2", "auto_edits": True})[1]["id"]
        wait_for(lambda: c.call("GET", f"/api/code/sessions/{sid}")[1]["state"] in ("done", "limited", "failed"))
        return c.call("GET", f"/api/code/sessions/{sid}")[1]

    def test_session_is_counted_against_usage(self):
        sam = self.sam
        st, info = sam.call("GET", "/api/code")
        self.assertFalse(info["usage"]["exempt"])
        before = self.state.limiter.snapshot("sam", "flare", "balanced", self.state.clock())["week"]["used"]
        j = sam.call("POST", "/api/code/start", {"project": "demo", "task": "x", "model": "equinox-2", "auto_edits": True})
        if j[0] != 200:                                           # a free plan may not include Equinox: use what it does include
            self.skipTest(j[1]["message"])
        r = self.finish_run_for(sam, j[1]["id"])
        self.assertGreater(r["used"], 0)
        self.assertGreater(r["steps"], 0)
        after = self.state.limiter.snapshot("sam", "flare", "balanced", self.state.clock())["week"]["used"]
        self.assertGreater(after, before)

    def finish_run_for(self, c, sid):
        wait_for(lambda: c.call("GET", f"/api/code/sessions/{sid}")[1]["state"] in ("done", "limited", "failed"))
        return c.call("GET", f"/api/code/sessions/{sid}")[1]

    def test_owner_is_not_limited_but_still_measured(self):
        r = self.finish_run(self.owner)
        self.assertEqual(r["state"], "done")
        self.assertTrue(r["usage"]["exempt"])

    def test_session_stops_when_usage_runs_out(self):
        st, j = self.owner.call("POST", "/api/admin/users", {"user": "pat", "tier": "pro"})
        pat = Client(self.port, j["key"])
        self.state.limiter.cfg["tiers"]["pro"]["tank"] = 1500        # room for only the first step or two
        self.state.limiter.cfg["tiers"]["pro"]["refill_per_hour"] = 1
        sid = pat.call("POST", "/api/code/start", {"project": "demo", "task": "x", "model": "equinox-2", "auto_edits": True})
        if sid[0] != 200:
            self.skipTest(sid[1]["message"])
        r = self.finish_run_for(pat, sid[1]["id"])
        self.assertEqual(r["state"], "limited")
        self.assertIn("usage ran out", r["events"][-1]["summary"])

    def test_zip_round_trip_and_import_guards(self):
        self.finish_run(self.owner)
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        c.request("GET", "/api/code/zip?project=demo", headers={"Authorization": "Bearer " + self.state.owner_key()})
        r = c.getresponse()
        data = r.read()
        self.assertEqual(r.status, 200)
        self.assertEqual(r.getheader("Content-Type"), "application/zip")
        self.assertIn("slug.py", zipfile.ZipFile(io.BytesIO(data)).namelist())
        ok = self.owner.call("POST", "/api/code/import", {"project": "copy", "zip_b64": base64.b64encode(data).decode()})
        self.assertEqual(ok[0], 200)
        self.assertIn("slug.py", self.owner.call("GET", "/api/code/files?project=copy")[1]["files"])
        evil = io.BytesIO()
        with zipfile.ZipFile(evil, "w") as z:
            z.writestr("../escape.txt", "x")
        bad = self.owner.call("POST", "/api/code/import", {"project": "copy", "zip_b64": base64.b64encode(evil.getvalue()).decode()})
        self.assertEqual(bad[0], 400)
        bad = self.owner.call("POST", "/api/code/import", {"project": "copy", "files": [{"path": "a/../../x", "b64": "eA=="}]})
        self.assertEqual(bad[0], 400)
        good = self.owner.call("POST", "/api/code/import", {"project": "copy", "files": [{"path": "sub/new.txt", "b64": "aGk="}, {"path": ".git/config", "b64": "eA=="}]})
        self.assertEqual(good[1]["imported"], 1)
        self.assertEqual(self.owner.call("POST", "/api/code/import", {"project": "copy", "zip_b64": "!!"})[0], 400)


class OutsideCoder(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(list(vryxcode.DEMO))

    def test_listed_as_an_outside_model_with_its_own_label(self):
        models = {m["id"]: m for m in self.owner.call("GET", "/api/code")[1]["models"]}
        c = models["coder-14b"]
        self.assertTrue(c["outside"])
        self.assertIn("outside model", c["label"])
        self.assertIn("not an Emvryx model", c["note"])
        self.assertFalse(models["solstice-2"]["outside"])

    def test_runs_and_is_counted_like_solstice(self):
        st, j = self.owner.call("POST", "/api/admin/users", {"user": "lee", "tier": "pro"})
        lee = Client(self.port, j["key"])
        before = self.state.limiter.snapshot("lee", "solstice", "balanced", self.state.clock())["week"]["used"]
        r = lee.call("POST", "/api/code/start", {"project": "demo", "task": "x", "model": "coder-14b", "auto_edits": True})
        self.assertEqual(r[0], 200, r)
        wait_for(lambda: lee.call("GET", f"/api/code/sessions/{r[1]['id']}")[1]["state"] == "done")
        after = self.state.limiter.snapshot("lee", "solstice", "balanced", self.state.clock())["week"]["used"]
        self.assertGreater(after, before)
        self.assertIn("slug.py", lee.call("GET", "/api/code/files?project=demo")[1]["files"])

    def test_not_in_a_plan_without_solstice(self):
        st, j = self.owner.call("POST", "/api/admin/users", {"user": "kid", "tier": "free"})
        kid = Client(self.port, j["key"])
        c = {m["id"]: m for m in kid.call("GET", "/api/code")[1]["models"]}["coder-14b"]
        self.assertEqual(c["state"], "locked")
        self.assertEqual(kid.call("POST", "/api/code/start", {"project": "p", "task": "x", "model": "coder-14b"})[0], 400)

    def test_small_emvryx_models_still_refused(self):
        self.assertEqual(self.owner.call("POST", "/api/code/start", {"project": "p", "task": "x", "model": "flare-2.5"})[0], 400)


class ThinkFilter(unittest.TestCase):
    def test_hides_reasoning_even_when_tags_are_split(self):
        import app_engine
        f = lambda pieces: "".join(app_engine.strip_think(pieces))
        self.assertEqual(f(["<thi", "nk>reason", "ing</th", "ink>\n\nHello <b", "> there"]), "Hello <b> there")
        self.assertEqual(f(["plain ", "text"]), "plain text")
        self.assertEqual(f(["<think>never closed"]), "")
        self.assertEqual(f(["Answer: 1 < 2"]), "Answer: 1 < 2")


if __name__ == "__main__":
    unittest.main()
