import os
import sys

from todo import storage


def main(argv):
    path = os.environ.get("TODO_FILE", "todo.json")
    data = storage.load(path)
    if not argv:
        print("usage: python -m todo add TEXT | list [--pending] | done ID | remove ID", file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "add":
        text = " ".join(rest)
        task = {"id": data["next_id"], "text": text, "done": False}
        data["next_id"] += 1
        data["tasks"].append(task)
        storage.save(path, data)
        print(f"Added {task['id']}: {text}")
        return 0
    if cmd == "list":
        tasks = [t for t in data["tasks"] if not ("--pending" in rest and t["done"])]
        if not tasks:
            print("No tasks")
        for t in tasks:
            print(f"{t['id']} [{'x' if t['done'] else ' '}] {t['text']}")
        return 0
    if cmd in ("done", "remove"):
        try:
            tid = int(rest[0])
        except (IndexError, ValueError):
            print("give a task id", file=sys.stderr)
            return 2
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


sys.exit(main(sys.argv[1:]))
