import unittest

from calc import CalcError, Calculator
from calc.tokens import tokenize


class Calc(unittest.TestCase):
    def setUp(self):
        self.c = Calculator()

    def ev(self, text):
        return self.c.evaluate(text)

    def test_precedence(self):
        self.assertEqual(self.ev("1 + 2 * 3"), 7)
        self.assertEqual(self.ev("(1 + 2) * 3"), 9)
        self.assertEqual(self.ev("2 ^ 3 ^ 2"), 512)
        self.assertEqual(self.ev("-2 ^ 2"), -4)
        self.assertEqual(self.ev("10 - 4 - 3"), 3)
        self.assertEqual(self.ev("8 / 4 / 2"), 1)
        self.assertEqual(self.ev("7 / 2"), 3.5)
        self.assertEqual(self.ev(".5 + 2.5"), 3)
        self.assertIsInstance(self.ev("6 / 3"), int)

    def test_variables_and_functions(self):
        self.assertEqual(self.ev("x = 3 * 2"), 6)
        self.assertEqual(self.ev("x * 2 + 1"), 13)
        self.assertEqual(self.ev("sqrt(16) + abs(-3)"), 7)
        self.assertEqual(self.ev("max(1, x, 4) - min(5, 2, 9)"), 4)
        self.assertEqual(self.ev("-(2 + 3)"), -5)

    def test_errors(self):
        for bad in ("y + 1", "1 / 0", "sqrt(-1)", "foo(2)", "sqrt(1, 2)", "2 +", "(1 + 2", "1 2", "3 $ 4", ""):
            with self.assertRaises(CalcError, msg=bad):
                self.ev(bad)

    def test_tokenize(self):
        self.assertEqual(len(tokenize("a_1 = 2.5*(b+3)")), 9)
        with self.assertRaises(CalcError):
            tokenize("2 # 3")


if __name__ == "__main__":
    unittest.main()
