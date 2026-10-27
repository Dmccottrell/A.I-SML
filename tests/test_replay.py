"""Recording the owner's VryxCode sessions whole (flag vryxcode_record) and replaying them through newer code (tools/replay_vryx.py)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import contextlib
import glob
import importlib.util
import io
import json
import tempfile
import zipfile

import vryxcode
from tests.test_app_server import Base
from tests.test_code_sessions import open_to_everyone, wait_for

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)


def tool(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Record(Base):
    def run_one(self, client, user):
        broken = '<|tool_call|>{"name": "write_file", "args": {"path": "q.html", "content": "<p class="x">hi</p>"}}<|end_tool_call|>'
        self.state.code_generate = lambda model: vryxcode.ScriptedChat([broken, vryxcode.harness_call("write_file", path="a.py", content="print(1)\n"),
                                                                        vryxcode.harness_call("finish", summary="done")])
        st, j = client.call("POST", "/api/code/start", {"project": "p", "task": "make it", "model": "equinox-2", "auto_edits": True})
        self.assertEqual(st, 200, j)
        wait_for(lambda: client.call("GET", f"/api/code/sessions/{j['id']}")[1]["state"] not in ("starting", "working", "queued"), 30)
        wait_for(lambda: True, 1)
        return j["id"]

    def replays(self, user):
        return glob.glob(os.path.join(self.state.code.base(user), ".sessions", "*.replay"))

    def test_only_the_owner_with_the_switch_is_recorded_and_it_replays(self):
        open_to_everyone(self.state)
        self.run_one(self.owner, "owner")
        self.assertEqual(self.replays("owner"), [])                             # the switch is off
        self.state.flags.data["audiences"]["vryxcode_record"] = "admins"
        sid = self.run_one(self.owner, "owner")
        self.run_one(self.sam, "sam")
        self.assertEqual(self.replays("sam"), [])                               # never someone else's
        path = os.path.join(self.state.code.base("owner"), ".sessions", sid + ".replay")
        wait_for(lambda: os.path.exists(path), 10)
        data = json.load(open(path))
        self.assertEqual(data["steps"][0], {"user": "make it", "plan": False, "first": True, "model_text": False})
        models = [s["model"] for s in data["steps"] if "model" in s]
        self.assertGreaterEqual(len(models), 3)                                 # every reply (more when "finish" was refused until the page was checked)
        self.assertIn('"summary": "done"', models[2])
        self.assertIn('class="x"', data["steps"][1]["model"])                   # whole, not cut to a preview

        z = os.path.join(tempfile.mkdtemp(), "s.zip")
        with zipfile.ZipFile(z, "w") as zf:
            zf.write(path, f"{sid}/replay.json")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = tool("replay_vryx").main([z, "--flags", "all"])
        text = out.getvalue()
        self.assertEqual(code, 0, text)
        self.assertIn("1 sessions replayed, 0 broke", text)
        self.assertIn("finished", text)


class Export(Base):
    def test_export_finds_the_recordings_and_says_how_when_there_are_none(self):
        data = tempfile.mkdtemp()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(tool("export_sessions").main(["--data", data, "--out", os.path.join(data, "x.zip")]), 1)
        self.assertIn("No recorded sessions yet", out.getvalue())
        sessions = os.path.join(data, "code", "owner", ".sessions")
        os.makedirs(os.path.join(sessions, "s1"))
        with open(os.path.join(sessions, "s1.replay"), "w") as f:
            json.dump({"task": "t", "steps": []}, f)
        with zipfile.ZipFile(os.path.join(sessions, "s1", "cp0.zip"), "w") as z:
            z.writestr("main.py", "print(1)\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(tool("export_sessions").main(["--data", data, "--out", os.path.join(data, "x.zip")]), 0)
        self.assertEqual(sorted(zipfile.ZipFile(os.path.join(data, "x.zip")).namelist()), ["s1/replay.json", "s1/start.zip"])
