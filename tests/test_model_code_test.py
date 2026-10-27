"""model_code_test: recorded sessions become tasks, each model does them, and the project's tests decide."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import io
import json
import os
import tempfile
import time
import unittest
import zipfile

import code_log
import model_code_test as T
import vryxcode
from tests.test_app_server import Base
from tests.test_code_sessions import wait_for


def zipped(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue()


def record(base, sid, task, start=None, with_cp1=True):
    log = code_log.SessionLog(base)
    log.save({"id": sid, "project": "p", "updated": time.time()}, [])
    log.save_replay(sid, {"task": task, "steps": []})
    if with_cp1:
        log.save_checkpoint(sid, 1, zipped(start or {"README.md": "hi"}))
    return log


class Cases(unittest.TestCase):
    def test_only_recorded_sessions_that_kept_their_starting_point(self):
        with tempfile.TemporaryDirectory() as d:
            record(d, "a1", "write slugify with a test")
            record(d, "b2", "old one", with_cp1=False)
            log = code_log.SessionLog(d)
            log.save({"id": "c3", "project": "p", "updated": time.time()}, [])          # not recorded
            cases = T.build_cases(log)
        self.assertEqual([c["id"] for c in cases], ["a1"])
        self.assertEqual(cases[0]["task"], "write slugify with a test")

    def test_the_tests_of_each_kind_of_project(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(T.check_command(d))
            open(os.path.join(d, "test_x.py"), "w").close()
            self.assertIn("unittest", T.check_command(d))
            with open(os.path.join(d, "package.json"), "w") as f:
                json.dump({"scripts": {"test": "jest"}}, f)
            self.assertEqual(T.check_command(d), "npm test --silent")
            open(os.path.join(d, "go.mod"), "w").close()
            self.assertEqual(T.check_command(d), "npm test --silent")                     # the first that fits


class RunCase(unittest.TestCase):
    def test_a_model_that_does_the_work_passes_and_one_that_does_not_fails(self):
        case = {"id": "a", "task": "write slugify with a test", "start": zipped({"README.md": "hi"})}
        good = T.run_case(case, vryxcode.ScriptedChat(list(vryxcode.DEMO)), None)
        self.assertEqual((good["passed"], good["why"]), (True, "the tests pass"), good)
        broken = list(vryxcode.DEMO)
        broken[0] = vryxcode.harness_call("write_file", path="slug.py", content="def slugify(title):\n    return title\n")
        broken[2] = vryxcode.harness_call("list_files")
        bad = T.run_case(case, vryxcode.ScriptedChat(broken), None)
        self.assertFalse(bad["passed"])
        self.assertIn("the tests fail", bad["why"])
        lazy = T.run_case(case, vryxcode.ScriptedChat([vryxcode.harness_call("list_files")] * 3), None, max_turns=2)
        self.assertEqual((lazy["passed"], lazy["why"]), (False, "not finished after 2 steps"))


class RunnerTests(unittest.TestCase):
    def test_every_task_on_every_model_and_kept_on_disk(self):
        case = {"id": "a", "task": "write slugify with a test", "start": zipped({"README.md": "hi"})}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "code_test.json")
            r = T.Runner(path)
            with self.assertRaises(ValueError):
                r.start([], [{"id": "m", "label": "M"}], None, None)
            make = lambda mid: vryxcode.ScriptedChat(list(vryxcode.DEMO)) if mid == "good" else (_ for _ in ()).throw(RuntimeError("no file"))
            r.start([case, case], [{"id": "good", "label": "Good 1"}, {"id": "gone", "label": "Gone 1"}], make, None, by="owner")
            wait_for(lambda: r.status()["state"] == "done", 60)
            s = T.Runner(path).status()
        self.assertEqual([(m["label"], m["passed"], m["done"]) for m in s["models"]], [("Good 1", 2, 2), ("Gone 1", 0, 0)])
        self.assertEqual(s["models"][1]["error"], "no file")
        self.assertEqual(s["progress"], [4, 4])


class Server(Base):
    def test_owner_only_and_never_outside_the_sandbox(self):
        self.state.flags.data["audiences"]["model_code_test"] = "admins"
        record(self.state.code.base("owner"), "a1", "write slugify")
        st, j = self.owner.call("GET", "/api/admin/code-test")
        self.assertEqual((st, j["recorded"], j["state"]), (200, 1, "never"))
        self.assertEqual(self.sam.call("POST", "/api/admin/code-test", {"run": True})[0], 403)
        import code_sandbox
        real = code_sandbox.available
        code_sandbox.available = lambda image: (False, "Docker is not running")
        self.addCleanup(lambda: setattr(code_sandbox, "available", real))
        st, j = self.owner.call("POST", "/api/admin/code-test", {"run": True})
        self.assertEqual(st, 400)
        self.assertIn("isolated sandbox", j["message"])


if __name__ == "__main__":
    unittest.main()
