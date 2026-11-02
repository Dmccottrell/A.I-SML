"""Evaluates a parsed expression. Pipeline: text -> tokenize() -> parse() (a tree) -> Calculator.run() (a number)."""
import math

from calc.errors import CalcError
from calc.parser import parse
from calc.tokens import tokenize


def _sqrt(x):
    """Square root that raises CalcError (not a raw Python error) for negative input."""
    if x < 0:
        raise CalcError("sqrt of a negative number")
    return math.sqrt(x)


# Built-in functions: name -> (python function, number of arguments).
# An argument count of None means "any number, but at least one" (min and max).
FUNCS = {"sqrt": (_sqrt, 1), "abs": (abs, 1), "min": (min, None), "max": (max, None)}


class Calculator:
    """A calculator that remembers variables between calls to `evaluate`."""

    def __init__(self):
        """Start with no variables defined."""
        self.vars = {}

    def evaluate(self, text):
        """Compute the value of `text`, e.g. "1 + 2 * 3" -> 7. Raises CalcError on any bad input.

        "name = expression" also stores the result in the variable `name`.
        """
        tokens = tokenize(text)
        # A token is (kind, value). An assignment looks like: name, "=", then the expression.
        if len(tokens) >= 2 and tokens[0][0] == "name" and tokens[1] == ("sym", "="):
            # Skip the first two tokens (name and "=") and compute the rest.
            value = self.run(parse(tokens[2:]))
            self.vars[tokens[0][1]] = value
        else:
            value = self.run(parse(tokens))
        # Show whole-number results as ints (6.0 -> 6), keep real fractions as floats (3.5).
        return int(value) if float(value).is_integer() else value

    def run(self, node):
        """Compute one node of the parse tree (a tuple whose first item says what kind of node it is).

        Kinds: ("num", n), ("var", name), ("neg", node), ("call", name, [args]), ("bin", op, left, right).
        """
        kind = node[0]
        if kind == "num":
            return node[1]
        if kind == "var":
            if node[1] not in self.vars:
                raise CalcError(f"unknown variable {node[1]}")
            return self.vars[node[1]]
        if kind == "neg":
            return -self.run(node[1])
        if kind == "call":
            if node[1] not in FUNCS:
                raise CalcError(f"unknown function {node[1]}")
            fn, n = FUNCS[node[1]]
            # Work out every argument first (they can be whole expressions).
            args = [self.run(a) for a in node[2]]
            # Wrong count: a fixed-size function got a different number, or min/max got none.
            if (n is not None and len(args) != n) or not args:
                raise CalcError(f"wrong number of arguments for {node[1]}")
            # sqrt/abs take one plain value; min/max take the whole list.
            return fn(*args) if n == 1 else fn(args)
        # Anything left is a binary operation: ("bin", op, left, right).
        _, op, a, b = node
        a, b = self.run(a), self.run(b)
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            if b == 0:
                raise CalcError("division by zero")
            return a / b
        # The only operator left is "^" (power). Huge results or 0 to a negative power
        # would crash with Python errors, so turn them into CalcError.
        try:
            return a ** b
        except (OverflowError, ZeroDivisionError) as e:
            raise CalcError(str(e))
