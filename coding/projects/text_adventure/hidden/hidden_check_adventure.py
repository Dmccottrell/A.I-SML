# Hidden checks for the "text_adventure" coding exercise. The agent never sees this file; it is run afterwards to decide
# whether the agent's adventure/ package works (looking, moving, locked doors, items, bad worlds).
import json
import os
import tempfile
import unittest

from adventure.engine import Game
from adventure.world import load_world

# A tiny world: a hall (start) with a key and a lamp whose north door is locked by the key, a kitchen to the east, and a vault beyond the door.
WORLD = {"start": "hall", "rooms": {
    "hall": {"description": "A dusty hall.", "exits": {"north": "vault", "east": "kitchen"}, "items": ["key", "lamp"], "locked": {"north": "key"}},
    "kitchen": {"description": "A small kitchen.", "exits": {"west": "hall"}},
    "vault": {"description": "Gold everywhere.", "exits": {}}}}


def save(world):
    """Write a world dict to a JSON file in a fresh temporary folder and return its path."""
    path = os.path.join(tempfile.mkdtemp(), "w.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(world, f)
    return path


class Adventure(unittest.TestCase):
    """Checks for the Game engine and load_world."""

    def game(self):
        """Helper (not a test): a new Game on the sample world, loaded from a file so load_world is used too."""
        return Game(load_world(save(WORLD)))

    def test_look(self):
        """Proves "look" lists description, sorted exits and items; moving to the kitchen shows no Items line (it has none)."""
        g = self.game()
        self.assertEqual(g.command("look"), "A dusty hall.\nExits: east, north\nItems: key, lamp")
        self.assertEqual(g.command("go east"), "A small kitchen.\nExits: west")
        self.assertEqual(g.room, "kitchen")

    def test_locked_and_items(self):
        """Proves a locked door blocks until the key is taken, take is case/space tolerant, and bad moves give the right message."""
        g = self.game()
        self.assertEqual(g.command("go north"), "The way north is locked.")
        # Odd capitals and extra spaces must be tolerated.
        self.assertEqual(g.command("  TAKE   key "), "Taken: key")
        self.assertEqual(g.command("take key"), "There is no key here.")
        self.assertEqual(g.command("look"), "A dusty hall.\nExits: east, north\nItems: lamp")
        self.assertEqual(g.command("go north"), "Gold everywhere.\nExits: none")
        self.assertEqual(g.command("go south"), "You can't go that way.")

    def test_inventory_and_drop(self):
        """Proves inventory text (empty and with items, in pick-up order), dropping, dropping twice, and unknown commands."""
        g = self.game()
        self.assertEqual(g.command("inventory"), "You carry nothing.")
        g.command("take lamp")
        g.command("take key")
        self.assertEqual(g.command("inventory"), "You carry: lamp, key")
        self.assertEqual(g.command("drop lamp"), "Dropped: lamp")
        self.assertEqual(g.command("drop lamp"), "You don't have lamp.")
        self.assertEqual(g.command("dance"), "I don't understand.")

    def test_bad_worlds(self):
        """Proves load_world rejects a start room that does not exist and an exit that leads to a missing room."""
        with self.assertRaises(ValueError):
            load_world(save({"start": "nowhere", "rooms": {"a": {"description": "x", "exits": {}}}}))
        with self.assertRaises(ValueError):
            load_world(save({"start": "a", "rooms": {"a": {"description": "x", "exits": {"up": "b"}}}}))


if __name__ == "__main__":
    unittest.main()
