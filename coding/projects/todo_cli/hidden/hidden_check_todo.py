# Hidden checks for the "todo_cli" coding exercise. The agent never sees this file; it is run afterwards to decide
# whether the agent's todo/ package works as a command-line program. Each test runs `python -m todo ...` as a real
# separate program and looks at its exit code and printed text.
import json
import os
import subprocess
import sys
import tempfile
import unittest

# The folder this check file lives in; programs are started from here so `python -m todo` finds the todo package.
HERE = os.path.dirname(os.path.abspath(__file__))


class TodoApp(unittest.TestCase):
    """End-to-end checks for the todo command-line app."""

    def setUp(self):
        """Before each test: a fresh temporary folder, and the path of the (not yet created) tasks file inside it."""
        self.dir = tempfile.mkdtemp()
        self.file = os.path.join(self.dir, "tasks.json")

    def todo(self, *args):
        """Helper (not a test): run `python -m todo <args>` and return (exit code, stdout text, stderr text), outputs stripped."""
        # TODO_FILE points the program at the temporary tasks file; PYTHONPATH lets it import the todo package.
        env = {**os.environ, "TODO_FILE": self.file, "PYTHONPATH": HERE}
        r = subprocess.run([sys.executable, "-m", "todo", *args], cwd=HERE, env=env, capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout.strip(), r.stderr.strip()

    def test_empty_list(self):
        """Proves listing with no tasks exits 0 and prints "No tasks" (first two parts of the result: code and stdout)."""
        self.assertEqual(self.todo("list")[:2], (0, "No tasks"))

    def test_add_and_list(self):
        """Proves add prints the new id and text, ids count 1, 2, ..., and list shows them with empty [ ] boxes."""
        self.assertEqual(self.todo("add", "Buy milk")[1], "Added 1: Buy milk")
        self.assertEqual(self.todo("add", "Walk the dog")[1], "Added 2: Walk the dog")
        self.assertEqual(self.todo("list")[1], "1 [ ] Buy milk\n2 [ ] Walk the dog")

    def test_done_and_pending(self):
        """Proves done ticks a task ([x]) and `list --pending` hides finished ones."""
        self.todo("add", "a")
        self.todo("add", "b")
        self.assertEqual(self.todo("done", "1")[1], "Done 1: a")
        self.assertEqual(self.todo("list")[1], "1 [x] a\n2 [ ] b")
        self.assertEqual(self.todo("list", "--pending")[1], "2 [ ] b")

    def test_remove_never_reuses_ids(self):
        """Proves removing the last task does not free its id: the next added task gets 3, not 2."""
        self.todo("add", "a")
        self.todo("add", "b")
        self.assertEqual(self.todo("remove", "2")[1], "Removed 2: b")
        self.assertEqual(self.todo("add", "c")[1], "Added 3: c")

    def test_missing_id(self):
        """Proves done/remove on an id that does not exist exit with code 1 and print "No task <id>" to the error stream."""
        code, out, err = self.todo("done", "7")
        self.assertEqual(code, 1)
        self.assertIn("No task 7", err)
        self.assertEqual(self.todo("remove", "9")[0], 1)

    def test_file_format_and_storage(self):
        """Proves the JSON file layout ({"next_id", "tasks"}) and that storage.load/save work directly, including a missing file."""
        self.todo("add", "x")
        with open(self.file, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["next_id"], 2)
        self.assertEqual(data["tasks"], [{"id": 1, "text": "x", "done": False}])
        # Make the todo package importable inside this test process, then test the storage module directly.
        sys.path.insert(0, HERE)
        from todo import storage
        # A file that does not exist loads as an empty list starting at id 1.
        self.assertEqual(storage.load(os.path.join(self.dir, "nope.json")), {"next_id": 1, "tasks": []})
        storage.save(self.file, {"next_id": 5, "tasks": []})
        self.assertEqual(storage.load(self.file)["next_id"], 5)


if __name__ == "__main__":
    unittest.main()
