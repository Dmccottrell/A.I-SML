"""The editor's Save (CodeManager.save_file and POST /api/code/file): safe paths, quotas, and no saving while VryxCode works in the same project."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import time
import unittest

import vryxcode
from tests.test_code_sessions import wait_for, open_to_everyone
from tests.test_app_server import Base


class Editor(Base):
    def setUp(self):
        super().setUp()
        open_to_everyone(self.state)
        self.state.code_generate = lambda model: vryxcode.ScriptedChat(list(vryxcode.DEMO))
        self.state.code.quotas.q["code_project_mb"] = 1

    def save(self, path, text, project="demo", who=None):
        return (who or self.owner).call("POST", "/api/code/file", {"project": project, "path": path, "text": text})

    def read(self, path, project="demo"):
        return self.owner.call("GET", f"/api/code/file?project={project}&path={path}")

    def test_new_file_then_edit_it_and_read_it_back(self):
        st, j = self.save("hello.py", "print('hi')\n")
        self.assertEqual((st, j["created"], j["path"]), (200, True, "hello.py"))
        st, j = self.save("hello.py", "print('hello')\r\nprint('bye')\r\n")
        self.assertEqual((st, j["created"]), (200, False))
        self.assertEqual(self.read("hello.py")[1]["text"], "print('hello')\nprint('bye')\n")          # Windows line endings are stored as plain ones
        self.assertIn("hello.py", self.owner.call("GET", "/api/code/files?project=demo")[1]["files"])

    def test_folders_are_made_and_unsafe_names_are_refused(self):
        self.assertEqual(self.save("pages/about/index.html", "<p>hi</p>")[0], 200)
        st, j = self.save("/etc/notes.txt", "x")                                            # a leading slash is just a path inside the project, never the real /etc
        self.assertEqual((st, j["path"]), (200, "etc/notes.txt"))
        self.assertFalse(os.path.exists("/etc/notes.txt"))
        for bad in ("../escape.py", ".git/config", ".emvryx/x.txt", "a/../../b.py", "C:/Windows/x.txt", ""):
            self.assertEqual(self.save(bad, "x")[0], 400, bad)
        self.assertFalse(os.path.exists(os.path.join(self.state.code.base("owner"), "escape.py")))

    def test_size_binary_and_folder_rules(self):
        self.assertEqual(self.save("big.txt", "x" * 250_000)[0], 400)
        self.assertEqual(self.save("ok.txt", "x" * 150_000)[0], 200)
        self.assertEqual(self.save("pages/a.html", "x")[0], 200)
        self.assertEqual(self.save("pages", "x")[0], 400)                                   # a folder
        path = os.path.join(self.state.code.project_path("owner", "demo"), "pic.png")
        with open(path, "wb") as f:
            f.write(b"\x89PNG\x00\x00\x00")
        st, j = self.save("pic.png", "text")
        self.assertEqual(st, 400)
        self.assertIn("binary", j["message"])

    def test_the_project_quota_is_respected(self):
        for i in range(7):
            self.save(f"f{i}.txt", "x" * 150_000)
        st, j = self.save("one_more.txt", "x" * 150_000)
        self.assertEqual(st, 400)
        self.assertIn("size limit", j["message"])

    def test_no_saving_while_vryxcode_is_working_in_the_same_project(self):
        st, a = self.owner.call("POST", "/api/code/start", {"project": "demo", "task": "write slugify", "model": "solstice-2"})
        wait_for(lambda: self.owner.call("GET", f"/api/code/sessions/{a['id']}")[1]["state"] == "asking")      # waiting for permission: still working
        st, j = self.save("mine.txt", "x")
        self.assertEqual(st, 400)
        self.assertIn("working in this project", j["message"])
        self.assertEqual(self.save("mine.txt", "x", project="other")[0], 200)                # another project is fine
        self.owner.call("POST", f"/api/code/sessions/{a['id']}/stop", {})
        wait_for(lambda: self.owner.call("GET", f"/api/code/sessions/{a['id']}")[1]["state"] in ("stopped", "done", "failed"))
        self.assertEqual(self.save("mine.txt", "x")[0], 200)

    def test_one_person_cannot_save_into_anothers_project(self):
        self.assertEqual(self.save("a.txt", "mine")[0], 200)
        self.save("a.txt", "theirs", who=self.sam)                                           # sam's own "demo" is a different folder
        self.assertEqual(self.read("a.txt")[1]["text"], "mine")


if __name__ == "__main__":
    unittest.main()
