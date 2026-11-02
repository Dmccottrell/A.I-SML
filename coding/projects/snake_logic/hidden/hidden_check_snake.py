# Hidden checks for the "snake_logic" coding exercise. The agent never sees this file; it is run afterwards to decide
# whether the agent's snake/ package follows the rules (start, moving, eating, walls, self-collision, drawing).
import random
import unittest

from snake import Game, render


class Snake(unittest.TestCase):
    """Checks for the Game class and render()."""

    def test_start(self):
        """Proves the start: one-square snake in the middle, score 0, not over, and food picked by Random(seed) from the sorted free squares."""
        g = Game(10, 8, seed=3)
        self.assertEqual((g.snake, g.score, g.over), ([(5, 4)], 0, False))
        # Rebuild the free-square list the same way the game should, then replay the seeded random choice.
        free = sorted((x, y) for x in range(10) for y in range(8) if (x, y) != (5, 4))
        self.assertEqual(g.food, random.Random(3).choice(free))

    def test_move_and_turn(self):
        """Proves the snake moves right by default, can turn down and up, and may reverse when it has length 1."""
        g = Game(10, 10)
        g.food = (0, 0)               # move the food far away so nothing is eaten
        self.assertTrue(g.step())
        self.assertEqual(g.snake, [(6, 5)])
        g.step("down")
        self.assertEqual(g.snake, [(6, 6)])
        g.step("up")                     # length 1: turning back is allowed
        self.assertEqual(g.snake, [(6, 5)])

    def test_eat_and_grow(self):
        """Proves eating: snake grows to 2, score 1, new food is not on the snake, and an instant U-turn is then ignored."""
        g = Game(10, 10)
        g.food = (6, 5)               # food directly in front of the head
        g.step()
        self.assertEqual((g.snake, g.score), ([(6, 5), (5, 5)], 1))
        self.assertNotIn(g.food, g.snake)
        g.food = (0, 0)
        g.step("left")                   # straight back is ignored now
        self.assertEqual(g.snake, [(7, 5), (6, 5)])

    def test_wall(self):
        """Proves hitting a wall ends the game, the snake stays where it was, and later steps do nothing."""
        g = Game(4, 4)
        g.food = (0, 0)
        self.assertTrue(g.step())
        self.assertFalse(g.step())
        self.assertTrue(g.over)
        self.assertEqual(g.snake, [(3, 2)])
        self.assertFalse(g.step("up"))
        self.assertEqual(g.snake, [(3, 2)])

    def test_hit_self(self):
        """Proves turning into the snake's own body ends the game."""
        g = Game(10, 10)
        # A curled snake; going "up" from the head (5, 5) lands on its own body square (5, 4).
        g.snake = [(5, 5), (4, 5), (4, 4), (5, 4), (6, 4)]
        g.direction = "right"
        g.food = (0, 9)
        self.assertTrue(g.step("up") is False)
        self.assertTrue(g.over)

    def test_render(self):
        """Proves the text drawing: head "@", body "o", food "*", empty "." on a 4 x 3 board."""
        g = Game(4, 3)
        g.snake = [(1, 1), (0, 1)]
        g.food = (3, 0)
        self.assertEqual(render(g), "...*\no@..\n....")


if __name__ == "__main__":
    unittest.main()
