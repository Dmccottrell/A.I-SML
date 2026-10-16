import json
import os


def load(path):
    if not os.path.exists(path):
        return {"next_id": 1, "tasks": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
