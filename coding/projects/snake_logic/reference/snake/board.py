def render(game):
    rows = []
    for y in range(game.height):
        row = ""
        for x in range(game.width):
            cell = (x, y)
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
