import json
import os
import tempfile
import unittest

from adventure.engine import Game
from adventure.world import load_world

WORLD = {"start": "hall", "rooms": {
    "hall": {"description": "A dusty hall.", "exits": {"north": "vault", "east": "kitchen"}, "items": ["key", "lamp"], "locked": {"north": "key"}},
    "kitchen": {"description": "A small kitchen.", "exits": {"west": "hall"}},
    "vault": {"description": "Gold everywhere.", "exits": {}}}}


def save(world):
    path = os.path.join(tempfile.mkdtemp(), "w.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(world, f)
    return path


class Adventure(unittest.TestCase):
    def game(self):
        return Game(load_world(save(WORLD)))

    def test_look(self):
        g = self.game()
        self.assertEqual(g.command("look"), "A dusty hall.\nExits: east, north\nItems: key, lamp")
        self.assertEqual(g.command("go east"), "A small kitchen.\nExits: west")
        self.assertEqual(g.room, "kitchen")

    def test_locked_and_items(self):
        g = self.game()
        self.assertEqual(g.command("go north"), "The way north is locked.")
        self.assertEqual(g.command("  TAKE   key "), "Taken: key")
        self.assertEqual(g.command("take key"), "There is no key here.")
        self.assertEqual(g.command("look"), "A dusty hall.\nExits: east, north\nItems: lamp")
        self.assertEqual(g.command("go north"), "Gold everywhere.\nExits: none")
        self.assertEqual(g.command("go south"), "You can't go that way.")

    def test_inventory_and_drop(self):
        g = self.game()
        self.assertEqual(g.command("inventory"), "You carry nothing.")
        g.command("take lamp")
        g.command("take key")
        self.assertEqual(g.command("inventory"), "You carry: lamp, key")
        self.assertEqual(g.command("drop lamp"), "Dropped: lamp")
        self.assertEqual(g.command("drop lamp"), "You don't have lamp.")
        self.assertEqual(g.command("dance"), "I don't understand.")

    def test_bad_worlds(self):
        with self.assertRaises(ValueError):
            load_world(save({"start": "nowhere", "rooms": {"a": {"description": "x", "exits": {}}}}))
        with self.assertRaises(ValueError):
            load_world(save({"start": "a", "rooms": {"a": {"description": "x", "exits": {"up": "b"}}}}))


if __name__ == "__main__":
    unittest.main()
