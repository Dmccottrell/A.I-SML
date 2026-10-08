"""VryxCode workflow features: plan first, the to-do list, @file mentions and the project instructions file."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401  (the code folders become importable)
import unittest

import harness
import vryxcode
from vryxcode import harness_call
from tests.test_app_server import Base
from tests.test_code_sessions import open_to_everyone, wait_for


class Workflow(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)

    def run_with(self, replies, **kw):
        chat = vryxcode.ScriptedChat(replies)
        self.state.code_generate = lambda model: chat
        st, j = self.owner.call("POST", "/api/code/start", {"project": "demo", "task": kw.pop("task", "make slugify"), "model": "solstice-2", "auto_edits": True, **kw})
        self.assertEqual(st, 200, j)
        sid = j["id"]
        wait_for(lambda: self.state.code.sessions[sid].state in ("done", "stopped", "failed"))
        return sid, chat, self.owner.call("GET", f"/api/code/sessions/{sid}")[1]

    def files(self):
        return self.owner.call("GET", "/api/code/files?project=demo")[1]["files"]

    # ---- plan first
    def test_plan_mode_looks_but_changes_nothing_and_answers_with_a_plan(self):
        sid, chat, j = self.run_with([harness_call("write_file", path="a.py", content="x = 1\n"),
                                      "1. Write slug.py with a slugify function.\n2. Add a test.\nShall I go ahead?"], plan=True)
        self.assertEqual(self.files(), [])                                   # the write was refused
        end = j["events"][-1]
        self.assertTrue(end["plan"] and end["said"])
        self.assertEqual(j["events"][0]["plan"], True)
        self.assertIn("PLAN MODE", chat.seen[0][0]["content"])

    def test_a_later_message_can_build_after_the_plan(self):
        sid, chat, j = self.run_with(["1. Write a.py.\nShall I go ahead?"], plan=True)
        chat.replies += [harness_call("write_file", path="a.py", content="x = 1\n"), harness_call("finish", summary="done")]
        st, _ = self.owner.call("POST", f"/api/code/sessions/{sid}/message", {"text": "Go ahead and build it as planned."})
        self.assertEqual(st, 200)
        wait_for(lambda: self.state.code.sessions[sid].state == "done")
        self.assertEqual(self.files(), ["a.py"])
        ends = [e for e in self.owner.call("GET", f"/api/code/sessions/{sid}")[1]["events"] if e["kind"] == "end"]
        self.assertEqual([e["plan"] for e in ends], [True, False])           # the plan, then the build

    # ---- to-do list
    def test_todo_tool_records_a_checklist(self):
        items = [{"text": "Write slug.py", "done": False}, {"text": "Run the tests", "done": False}]
        sid, chat, j = self.run_with([harness_call("todo", items=items), harness_call("todo", items=[dict(items[0], done=True), items[1]]), harness_call("finish", summary="ok")])
        todos = [e for e in j["events"] if e["kind"] == "step" and e["tool"] == "todo"]
        self.assertEqual(len(todos), 2)
        self.assertIn("Write slug.py", todos[1]["preview"])
        results = [e["text"] for e in j["events"] if e["kind"] == "result"]
        self.assertIn("todo list saved: 1 of 2 done", results[1])
        self.assertIn("todo", chat.seen[0][0]["content"])

    def test_todo_with_nothing_in_it_is_an_error_the_model_can_fix(self):
        sid, chat, j = self.run_with([harness_call("todo", items=[]), harness_call("finish", summary="ok")])
        self.assertIn("todo needs items", [e["text"] for e in j["events"] if e["kind"] == "result"][0])

    # ---- @file mentions
    def test_at_file_adds_its_contents_for_the_model_but_not_to_the_shown_message(self):
        self.owner.call("POST", "/api/code/import", {"project": "demo", "files": [{"path": "notes.txt", "b64": "bWFnaWMgd29yZDogcGx1Z2h5"}]})   # "magic word: plughy"
        sid, chat, j = self.run_with([harness_call("finish", summary="ok")], task="explain @notes.txt please")
        first_user = chat.seen[0][1]["content"]
        self.assertIn("plughy", first_user)
        self.assertEqual(j["events"][0]["task"], "explain @notes.txt please")

    def test_at_something_that_is_not_a_file_is_left_alone(self):
        sid, chat, j = self.run_with([harness_call("finish", summary="ok")], task="email me@example.com about @nothing.txt")
        self.assertNotIn("Contents of", chat.seen[0][1]["content"])

    def test_no_escaping_the_project_with_a_mention(self):
        sid, chat, j = self.run_with([harness_call("finish", summary="ok")], task="read @../../etc/passwd")
        self.assertNotIn("Contents of", chat.seen[0][1]["content"])

    # ---- project instructions
    def test_init_creates_instructions_once_and_the_model_reads_them(self):
        st, j = self.owner.call("POST", "/api/code/init", {"project": "demo"})
        self.assertEqual((st, j["created"], j["path"]), (200, True, "VRYX.md"))
        self.assertEqual(self.owner.call("POST", "/api/code/init", {"project": "demo"})[1]["created"], False)
        sid, chat, _ = self.run_with([harness_call("finish", summary="ok")])
        self.assertIn("Project notes", chat.seen[0][1]["content"])
        self.assertIn("VryxCode reads this file", chat.seen[0][1]["content"])


if __name__ == "__main__":
    unittest.main()
