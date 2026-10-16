from adventure.world import check_world


class Game:
    def __init__(self, world):
        self.world = check_world(world)
        self.room = world["start"]
        self.inventory = []

    def here(self):
        return self.world["rooms"][self.room]

    def look(self):
        r = self.here()
        lines = [r["description"], "Exits: " + (", ".join(sorted(r["exits"])) or "none")]
        if r["items"]:
            lines.append("Items: " + ", ".join(r["items"]))
        return "\n".join(lines)

    def command(self, text):
        words = text.lower().split()
        if words == ["look"]:
            return self.look()
        if words == ["inventory"]:
            return "You carry: " + ", ".join(self.inventory) if self.inventory else "You carry nothing."
        if len(words) == 2:
            verb, what = words
            r = self.here()
            if verb == "go":
                if what not in r["exits"]:
                    return "You can't go that way."
                need = r["locked"].get(what)
                if need and need not in self.inventory:
                    return f"The way {what} is locked."
                self.room = r["exits"][what]
                return self.look()
            if verb == "take":
                if what not in r["items"]:
                    return f"There is no {what} here."
                r["items"].remove(what)
                self.inventory.append(what)
                return f"Taken: {what}"
            if verb == "drop":
                if what not in self.inventory:
                    return f"You don't have {what}."
                self.inventory.remove(what)
                r["items"].append(what)
                return f"Dropped: {what}"
        return "I don't understand."
