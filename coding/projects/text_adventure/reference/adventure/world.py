import json


def check_world(world):
    rooms = world.get("rooms", {})
    if world.get("start") not in rooms:
        raise ValueError("the start room does not exist")
    for name, room in rooms.items():
        room.setdefault("items", [])
        room.setdefault("locked", {})
        room.setdefault("exits", {})
        for d, target in room["exits"].items():
            if target not in rooms:
                raise ValueError(f"{name} {d} leads to a room that does not exist: {target}")
    return world


def load_world(path):
    with open(path, encoding="utf-8") as f:
        return check_world(json.load(f))
