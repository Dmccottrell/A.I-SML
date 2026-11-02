# Saving and loading the task list for the todo command-line reference solution ("todo_cli" exercise).
# The data is a dict {"next_id": number, "tasks": [{"id", "text", "done"}]} kept as JSON in one file.
import json
import os


def load(path):
    """Read the task data from the file at path. If the file does not exist yet, return a fresh empty list that starts at id 1."""
    if not os.path.exists(path):
        return {"next_id": 1, "tasks": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, data):
    """Write the task data to path as readable JSON (indent=2 puts it on separate indented lines), replacing the old file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
