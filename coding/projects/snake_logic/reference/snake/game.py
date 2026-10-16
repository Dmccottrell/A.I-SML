import random

MOVES = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}


class Game:
    def __init__(self, width, height, seed=0):
        self.width, self.height = width, height
        self.rng = random.Random(seed)
        self.snake = [(width // 2, height // 2)]
        self.direction, self.score, self.over = "right", 0, False
        self.food = None
        self.place_food()

    def place_food(self):
        free = sorted((x, y) for x in range(self.width) for y in range(self.height) if (x, y) not in self.snake)
        self.food = self.rng.choice(free) if free else None

    def step(self, direction=None):
        if self.over:
            return False
        if direction in MOVES and not (len(self.snake) > 1 and direction == OPPOSITE[self.direction]):
            self.direction = direction
        dx, dy = MOVES[self.direction]
        hx, hy = self.snake[0]
        head = (hx + dx, hy + dy)
        eating = head == self.food
        body = self.snake if eating else self.snake[:-1]
        if not (0 <= head[0] < self.width and 0 <= head[1] < self.height) or head in body:
            self.over = True
            return False
        self.snake.insert(0, head)
        if eating:
            self.score += 1
            self.place_food()
        else:
            self.snake.pop()
        return True
