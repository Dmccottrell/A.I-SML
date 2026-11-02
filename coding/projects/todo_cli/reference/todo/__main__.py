# The command-line program of the todo reference solution: `python -m todo add TEXT | list [--pending] | done ID | remove ID`.
# Python runs this file when the package is started with -m. Tasks are kept in a JSON file via todo/storage.py.
import os
import sys

from todo import storage


def main(argv):
    """Run one command. argv is the list of words after `python -m todo`. Returns the exit code (0 ok, 1 no such task, 2 bad usage)."""
    # The file location can be set with the TODO_FILE environment variable (tests use this); default is todo.json here.
    path = os.environ.get("TODO_FILE", "todo.json")
    data = storage.load(path)
    if not argv:
        print("usage: python -m todo add TEXT | list [--pending] | done ID | remove ID", file=sys.stderr)
        return 2
    # cmd is the first word (the command); rest is everything after it.
    cmd, rest = argv[0], argv[1:]
    if cmd == "add":
        text = " ".join(rest)
        # Ids come from a counter that only goes up, so a removed task's id is never given to a new task.
        task = {"id": data["next_id"], "text": text, "done": False}
        data["next_id"] += 1
        data["tasks"].append(task)
        storage.save(path, data)
        print(f"Added {task['id']}: {text}")
        return 0
    if cmd == "list":
        # With --pending, hide finished tasks.
        tasks = [t for t in data["tasks"] if not ("--pending" in rest and t["done"])]
        if not tasks:
            print("No tasks")
        for t in tasks:
            print(f"{t['id']} [{'x' if t['done'] else ' '}] {t['text']}")
        return 0
    if cmd in ("done", "remove"):
        # Both commands need a task number; a missing or non-numeric one is a usage error.
        try:
            tid = int(rest[0])
        except (IndexError, ValueError):
            print("give a task id", file=sys.stderr)
            return 2
        # next(..., None) gives the first matching task, or None when there is none.
        task = next((t for t in data["tasks"] if t["id"] == tid), None)
        if task is None:
            print(f"No task {tid}", file=sys.stderr)
            return 1
        if cmd == "done":
            task["done"] = True
            print(f"Done {tid}: {task['text']}")
        else:
            data["tasks"].remove(task)
            print(f"Removed {tid}: {task['text']}")
        storage.save(path, data)
        return 0
    print(f"unknown command {cmd}", file=sys.stderr)
    return 2


# Run main() and pass its return value to the operating system as the program's exit code.
sys.exit(main(sys.argv[1:]))
