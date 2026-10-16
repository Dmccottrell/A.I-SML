import random
import unittest

from snake import Game, render


class Snake(unittest.TestCase):
    def test_start(self):
        g = Game(10, 8, seed=3)
        self.assertEqual((g.snake, g.score, g.over), ([(5, 4)], 0, False))
        free = sorted((x, y) for x in range(10) for y in range(8) if (x, y) != (5, 4))
        self.assertEqual(g.food, random.Random(3).choice(free))

    def test_move_and_turn(self):
        g = Game(10, 10)
        g.food = (0, 0)
        self.assertTrue(g.step())
        self.assertEqual(g.snake, [(6, 5)])
        g.step("down")
        self.assertEqual(g.snake, [(6, 6)])
        g.step("up")                     # length 1: turning back is allowed
        self.assertEqual(g.snake, [(6, 5)])

    def test_eat_and_grow(self):
        g = Game(10, 10)
        g.food = (6, 5)
        g.step()
        self.assertEqual((g.snake, g.score), ([(6, 5), (5, 5)], 1))
        self.assertNotIn(g.food, g.snake)
        g.food = (0, 0)
        g.step("left")                   # straight back is ignored now
        self.assertEqual(g.snake, [(7, 5), (6, 5)])

    def test_wall(self):
        g = Game(4, 4)
        g.food = (0, 0)
        self.assertTrue(g.step())
        self.assertFalse(g.step())
        self.assertTrue(g.over)
        self.assertEqual(g.snake, [(3, 2)])
        self.assertFalse(g.step("up"))
        self.assertEqual(g.snake, [(3, 2)])

    def test_hit_self(self):
        g = Game(10, 10)
        g.snake = [(5, 5), (4, 5), (4, 4), (5, 4), (6, 4)]
        g.direction = "right"
        g.food = (0, 9)
        self.assertTrue(g.step("up") is False)
        self.assertTrue(g.over)

    def test_render(self):
        g = Game(4, 3)
        g.snake = [(1, 1), (0, 1)]
        g.food = (3, 0)
        self.assertEqual(render(g), "...*\no@..\n....")


if __name__ == "__main__":
    unittest.main()
