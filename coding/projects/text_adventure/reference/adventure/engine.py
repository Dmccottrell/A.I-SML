# The game engine of the text adventure reference solution: keeps track of where the player is and what they carry,
# and turns typed commands ("go north", "take key") into replies. The world data comes from adventure/world.py.
from adventure.world import check_world


class Game:
    """One play of the adventure. Call command("go north") etc. and print what comes back."""

    def __init__(self, world):
        """world: a world dict (see world.py). It is checked, and the player starts in its start room with empty hands."""
        self.world = check_world(world)
        self.room = world["start"]
        self.inventory = []

    def here(self):
        """The data dict of the room the player is in."""
        return self.world["rooms"][self.room]

    def look(self):
        """Describe the current room: its description, its exits (sorted, or "none"), and its items if there are any."""
        r = self.here()
        lines = [r["description"], "Exits: " + (", ".join(sorted(r["exits"])) or "none")]
        if r["items"]:
            lines.append("Items: " + ", ".join(r["items"]))
        return "\n".join(lines)

    def command(self, text):
        """Run one typed command and return the reply text.

        Understands: look, inventory, go <direction>, take <item>, drop <item>. Capitals and extra spaces do not matter.
        Anything else gets "I don't understand."
        """
        # lower() ignores capitals; split() with no argument splits on any run of spaces and drops the empty ends.
        words = text.lower().split()
        if words == ["look"]:
            return self.look()
        if words == ["inventory"]:
            # Python reads this as: ("You carry: " + the list) if we carry something, else "You carry nothing."
            return "You carry: " + ", ".join(self.inventory) if self.inventory else "You carry nothing."
        # The remaining commands all have the shape "verb thing".
        if len(words) == 2:
            verb, what = words
            r = self.here()
            if verb == "go":
                if what not in r["exits"]:
                    return "You can't go that way."
                # r["locked"] maps a direction to the item needed to pass; the player just needs to be carrying it.
                need = r["locked"].get(what)
                if need and need not in self.inventory:
                    return f"The way {what} is locked."
                self.room = r["exits"][what]
                return self.look()
            if verb == "take":
                # Move the item from the room to the player's pockets.
                if what not in r["items"]:
                    return f"There is no {what} here."
                r["items"].remove(what)
                self.inventory.append(what)
                return f"Taken: {what}"
            if verb == "drop":
                # Move the item from the player's pockets into the current room.
                if what not in self.inventory:
                    return f"You don't have {what}."
                self.inventory.remove(what)
                r["items"].append(what)
                return f"Dropped: {what}"
        return "I don't understand."
