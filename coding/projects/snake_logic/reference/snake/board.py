# Draws the snake board as plain text (for the "snake_logic" reference solution). Used by tests and for debugging.


def render(game):
    """Return the board as text, one line per row: "@" snake head, "o" body, "*" food, "." empty.

    game: a Game (see snake/game.py). Coordinates are (x, y) with (0, 0) at the top left, y growing downwards.
    """
    rows = []
    for y in range(game.height):
        row = ""
        for x in range(game.width):
            cell = (x, y)
            # Order matters: check head first, then the rest of the body, then food, else empty ground.
            if game.snake and cell == game.snake[0]:
                row += "@"
            elif cell in game.snake:
                row += "o"
            elif cell == game.food:
                row += "*"
            else:
                row += "."
        rows.append(row)
    return "\n".join(rows)
