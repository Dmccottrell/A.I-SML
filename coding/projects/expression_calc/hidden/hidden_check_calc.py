"""Hidden grading test for the "expression calculator" practice project.

The coding agent (VryxCode) writes a `calc` package that evaluates maths text
like "1 + 2 * 3". It never sees this file; the harness runs it afterwards to
judge the work. The `reference/calc` folder passes it.
"""
import unittest

from calc import CalcError, Calculator
from calc.tokens import tokenize


class Calc(unittest.TestCase):
    """Checks operator order, variables, built-in functions, error handling and the tokenizer."""

    def setUp(self):
        """Before each test: make a fresh Calculator (so variables from one test do not leak into another)."""
        self.c = Calculator()

    def ev(self, text):
        """Shortcut: evaluate `text` with this test's calculator."""
        return self.c.evaluate(text)

    def test_precedence(self):
        """Proves the usual maths rules: order of operations, brackets, and left/right grouping."""
        self.assertEqual(self.ev("1 + 2 * 3"), 7)
        self.assertEqual(self.ev("(1 + 2) * 3"), 9)
        # ^ (power) groups to the right: 2 ^ (3 ^ 2) = 2 ^ 9 = 512, not (2 ^ 3) ^ 2 = 64.
        self.assertEqual(self.ev("2 ^ 3 ^ 2"), 512)
        # Power binds tighter than the minus sign: -(2 ^ 2) = -4, not (-2) ^ 2 = 4.
        self.assertEqual(self.ev("-2 ^ 2"), -4)
        # - and / group to the left: (10 - 4) - 3 = 3 and (8 / 4) / 2 = 1.
        self.assertEqual(self.ev("10 - 4 - 3"), 3)
        self.assertEqual(self.ev("8 / 4 / 2"), 1)
        self.assertEqual(self.ev("7 / 2"), 3.5)
        # Numbers may start with a dot.
        self.assertEqual(self.ev(".5 + 2.5"), 3)
        # A whole-number answer comes back as an int (2), not a float (2.0).
        self.assertIsInstance(self.ev("6 / 3"), int)

    def test_variables_and_functions(self):
        """Proves "name = value" stores a variable and the built-ins sqrt, abs, min, max work."""
        self.assertEqual(self.ev("x = 3 * 2"), 6)
        # x was stored by the line above (same calculator), so it can be used now: 6 * 2 + 1.
        self.assertEqual(self.ev("x * 2 + 1"), 13)
        self.assertEqual(self.ev("sqrt(16) + abs(-3)"), 7)
        # max(1, 6, 4) = 6 and min(5, 2, 9) = 2, so 6 - 2 = 4.
        self.assertEqual(self.ev("max(1, x, 4) - min(5, 2, 9)"), 4)
        self.assertEqual(self.ev("-(2 + 3)"), -5)

    def test_errors(self):
        """Proves every kind of bad input raises CalcError instead of crashing some other way."""
        # In order: unknown variable, divide by zero, sqrt of a negative, unknown function, wrong argument count,
        # missing operand, missing closing bracket, two numbers in a row, unknown symbol, empty text.
        for bad in ("y + 1", "1 / 0", "sqrt(-1)", "foo(2)", "sqrt(1, 2)", "2 +", "(1 + 2", "1 2", "3 $ 4", ""):
            # msg=bad prints which input failed if the check does not raise.
            with self.assertRaises(CalcError, msg=bad):
                self.ev(bad)

    def test_tokenize(self):
        """Proves the tokenizer (which splits text into pieces) counts pieces right and rejects unknown characters."""
        # Pieces: a_1, =, 2.5, *, (, b, +, 3, ) -> 9 tokens.
        self.assertEqual(len(tokenize("a_1 = 2.5*(b+3)")), 9)
        with self.assertRaises(CalcError):
            tokenize("2 # 3")


if __name__ == "__main__":
    unittest.main()
