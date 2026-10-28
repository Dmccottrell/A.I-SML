"""VryxCode drafts written on the phone with the PC off (coding/code_drafts.py): kept on the PC, and run in VryxCode only when asked."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import unittest

import code_drafts
import vryxcode
from tests.test_app_server import Base
from tests.test_code_sessions import open_to_everyone, wait_for

FINISH = '<|tool_call|>{"name": "finish", "args": {"summary": "done"}}<|end_tool_call|>'
FILES = [{"path": "index.html", "content": "<h1>Tips</h1>\n<script src=\"app.js\"></script>\n"}, {"path": "./js/app.js", "content": "console.log(1)\n"}]


class Files(unittest.TestCase):
    def test_only_names_inside_the_project(self):
        self.assertEqual([f["path"] for f in code_drafts.clean_files(FILES)], ["index.html", "js/app.js"])
        for bad in ("../x.py", "/etc/passwd", "a/../../b", ".git/config", "C:\\\\x", ""):
            with self.assertRaises(ValueError, msg=bad):
                code_drafts.clean_files([{"path": bad, "content": "x"}])
        with self.assertRaises(ValueError):
            code_drafts.clean_files([])
        with self.assertRaises(ValueError):
            code_drafts.clean_files([{"path": f"f{i}.py", "content": "x"} for i in range(code_drafts.MAX_FILES + 1)])

    def test_the_task_asks_to_write_run_and_fix(self):
        t = code_drafts.task_for({"request": "a tip calculator", "note": "open index.html", "files": code_drafts.clean_files(FILES)})
        self.assertIn("a tip calculator", t)
        self.assertIn("FILE: js/app.js", t)
        self.assertIn("run and test", t)
        self.assertIn("open index.html", t)

    def test_a_retried_sync_is_kept_once(self):
        d = code_drafts.Drafts(None)
        body = {"sync_id": "p1", "project": "tips", "request": "a tip calculator", "files": FILES}
        first = d.add("sam", body, lambda p: p)
        self.assertEqual(d.add("sam", body, lambda p: p), first)
        self.assertEqual(len(d.list("sam")), 1)


class Api(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        self.chat = vryxcode.ScriptedChat([FINISH])
        self.state.code_generate = lambda model: self.chat

    def send(self, **kw):
        return self.owner.call("POST", "/api/code/drafts", dict({"sync_id": "p1", "project": "tips", "request": "a tip calculator", "files": FILES,
                                                                "note": "open index.html", "model": "flare-3"}, **kw))

    def test_off_by_default(self):
        self.assertNotEqual(self.send()[0], 200)
        self.assertNotEqual(self.owner.call("GET", "/api/code/drafts")[0], 200)

    def test_kept_without_touching_the_project_then_run_in_vryxcode(self):
        self.state.flags.data["audiences"]["android_offline_model"] = "everyone"
        s, j = self.send()
        self.assertEqual(s, 200, j)
        did = j["id"]
        drafts = self.owner.call("GET", "/api/code/drafts")[1]["drafts"]
        self.assertEqual([d["id"] for d in drafts], [did])
        self.assertEqual(drafts[0]["files"][1]["path"], "js/app.js")
        s, j = self.owner.call("POST", f"/api/code/drafts/{did}/run", {"model": "solstice-2"})
        self.assertEqual(s, 200, j)
        sess = self.state.code.sessions[j["id"]]
        wait_for(lambda: sess.state not in ("starting", "working"))
        sent = " ".join(m["content"] for m in self.chat.seen[0] if m["role"] == "user")
        self.assertIn("I wrote a draft on my phone", sent)                                # the model gets the files and what to do with them
        self.assertIn("FILE: index.html", sent)
        self.assertTrue(sess.task.startswith("Phone draft: a tip calculator"))             # the person sees a short title, not the files

    def test_run_with_no_model_uses_vryxcodes_own_choice(self):
        # the page's and the phone's Run button send no model: it failed with "Pick a model for VryxCode."
        self.state.flags.data["audiences"]["android_offline_model"] = "everyone"
        did = self.send()[1]["id"]
        s, j = self.owner.call("POST", f"/api/code/drafts/{did}/run", {})
        self.assertEqual(s, 200, j)
        self.assertTrue(self.state.code.sessions[j["id"]].model_id)

    def test_bad_drafts_and_delete(self):
        self.state.flags.data["audiences"]["android_offline_model"] = "everyone"
        self.assertEqual(self.send(files=[{"path": "../evil", "content": "x"}])[1]["code"], "bad_draft")
        self.assertEqual(self.send(sync_id="", )[0], 400)
        did = self.send()[1]["id"]
        self.assertEqual(self.sam.call("POST", f"/api/code/drafts/{did}/delete")[0], 404)      # someone else's draft
        self.assertEqual(self.owner.call("POST", f"/api/code/drafts/{did}/delete")[1]["drafts"], [])
        self.assertEqual(self.owner.call("POST", f"/api/code/drafts/{did}/run", {})[0], 404)


if __name__ == "__main__":
    unittest.main()
