# Loading and checking the game world for the text adventure reference solution ("text_adventure" exercise).
# A world is a dict read from a JSON file: {"start": room_name, "rooms": {name: {description, exits, items, locked}}}.
# adventure/engine.py plays the game on a world that passed these checks.
import json


def check_world(world):
    """Validate a world dict and fill in missing parts. Returns the same dict, or raises ValueError.

    Checks: the start room exists, and every exit leads to a room that exists. Rooms with no "items", "locked"
    or "exits" get empty ones, so the game code can use them without checking first.
    """
    rooms = world.get("rooms", {})
    if world.get("start") not in rooms:
        raise ValueError("the start room does not exist")
    for name, room in rooms.items():
        # setdefault only adds the key when it is missing; the world dict is changed in place.
        room.setdefault("items", [])
        room.setdefault("locked", {})
        room.setdefault("exits", {})
        # d is a direction like "north", target is the room it leads to.
        for d, target in room["exits"].items():
            if target not in rooms:
                raise ValueError(f"{name} {d} leads to a room that does not exist: {target}")
    return world


def load_world(path):
    """Read a JSON world file from path and return the checked world."""
    with open(path, encoding="utf-8") as f:
        return check_world(json.load(f))
