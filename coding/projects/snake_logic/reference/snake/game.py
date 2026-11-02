# The rules of the snake game, with no screen or keyboard (reference solution for "snake_logic").
# A Game holds the snake, the food and the score; step() moves the snake one square. snake/board.py can draw it.
import random

# How each direction changes (x, y) in one step. y grows downwards, so "up" is -1.
MOVES = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
# The direction that would turn the snake straight back on itself.
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}


class Game:
    """State of one snake game on a width x height grid."""

    def __init__(self, width, height, seed=0):
        """Start with a one-square snake in the middle heading right. seed makes the food positions repeatable."""
        self.width, self.height = width, height
        self.rng = random.Random(seed)
        # snake is a list of (x, y) squares; index 0 is the head.
        self.snake = [(width // 2, height // 2)]
        self.direction, self.score, self.over = "right", 0, False
        self.food = None
        self.place_food()

    def place_food(self):
        """Put the food on a random empty square. If the snake fills the whole board there is none left (food = None)."""
        # The list is sorted so that, for a given seed, the same square is picked every time.
        free = sorted((x, y) for x in range(self.width) for y in range(self.height) if (x, y) not in self.snake)
        self.food = self.rng.choice(free) if free else None

    def step(self, direction=None):
        """Move the snake one square. Optional direction ("up", "down", "left", "right") turns it first.

        A turn straight back is ignored once the snake is longer than 1 (it would hit its own neck).
        Returns True if the snake moved, False if the game was already over or this move ended it
        (hitting a wall or itself). Eating the food grows the snake by one and adds 1 to the score.
        """
        if self.over:
            return False
        # Apply the turn only if it is a known direction and not a U-turn for a snake that has a body.
        if direction in MOVES and not (len(self.snake) > 1 and direction == OPPOSITE[self.direction]):
            self.direction = direction
        dx, dy = MOVES[self.direction]
        hx, hy = self.snake[0]
        head = (hx + dx, hy + dy)
        eating = head == self.food
        # When not eating, the tail square moves away this step, so the head may safely enter it; when eating, the tail stays.
        body = self.snake if eating else self.snake[:-1]
        if not (0 <= head[0] < self.width and 0 <= head[1] < self.height) or head in body:
            self.over = True
            return False
        self.snake.insert(0, head)
        if eating:
            # Keep the tail (the snake grows) and put new food somewhere.
            self.score += 1
            self.place_food()
        else:
            # Drop the tail so the snake keeps the same length.
            self.snake.pop()
        return True
