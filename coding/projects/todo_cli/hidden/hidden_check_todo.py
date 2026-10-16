import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


class TodoApp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.file = os.path.join(self.dir, "tasks.json")

    def todo(self, *args):
        env = {**os.environ, "TODO_FILE": self.file, "PYTHONPATH": HERE}
        r = subprocess.run([sys.executable, "-m", "todo", *args], cwd=HERE, env=env, capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout.strip(), r.stderr.strip()

    def test_empty_list(self):
        self.assertEqual(self.todo("list")[:2], (0, "No tasks"))

    def test_add_and_list(self):
        self.assertEqual(self.todo("add", "Buy milk")[1], "Added 1: Buy milk")
        self.assertEqual(self.todo("add", "Walk the dog")[1], "Added 2: Walk the dog")
        self.assertEqual(self.todo("list")[1], "1 [ ] Buy milk\n2 [ ] Walk the dog")

    def test_done_and_pending(self):
        self.todo("add", "a")
        self.todo("add", "b")
        self.assertEqual(self.todo("done", "1")[1], "Done 1: a")
        self.assertEqual(self.todo("list")[1], "1 [x] a\n2 [ ] b")
        self.assertEqual(self.todo("list", "--pending")[1], "2 [ ] b")

    def test_remove_never_reuses_ids(self):
        self.todo("add", "a")
        self.todo("add", "b")
        self.assertEqual(self.todo("remove", "2")[1], "Removed 2: b")
        self.assertEqual(self.todo("add", "c")[1], "Added 3: c")

    def test_missing_id(self):
        code, out, err = self.todo("done", "7")
        self.assertEqual(code, 1)
        self.assertIn("No task 7", err)
        self.assertEqual(self.todo("remove", "9")[0], 1)

    def test_file_format_and_storage(self):
        self.todo("add", "x")
        with open(self.file, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["next_id"], 2)
        self.assertEqual(data["tasks"], [{"id": 1, "text": "x", "done": False}])
        sys.path.insert(0, HERE)
        from todo import storage
        self.assertEqual(storage.load(os.path.join(self.dir, "nope.json")), {"next_id": 1, "tasks": []})
        storage.save(self.file, {"next_id": 5, "tasks": []})
        self.assertEqual(storage.load(self.file)["next_id"], 5)


if __name__ == "__main__":
    unittest.main()
