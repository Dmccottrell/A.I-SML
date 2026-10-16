import math

from calc.errors import CalcError
from calc.parser import parse
from calc.tokens import tokenize


def _sqrt(x):
    if x < 0:
        raise CalcError("sqrt of a negative number")
    return math.sqrt(x)


FUNCS = {"sqrt": (_sqrt, 1), "abs": (abs, 1), "min": (min, None), "max": (max, None)}


class Calculator:
    def __init__(self):
        self.vars = {}

    def evaluate(self, text):
        tokens = tokenize(text)
        if len(tokens) >= 2 and tokens[0][0] == "name" and tokens[1] == ("sym", "="):
            value = self.run(parse(tokens[2:]))
            self.vars[tokens[0][1]] = value
        else:
            value = self.run(parse(tokens))
        return int(value) if float(value).is_integer() else value

    def run(self, node):
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
            args = [self.run(a) for a in node[2]]
            if (n is not None and len(args) != n) or not args:
                raise CalcError(f"wrong number of arguments for {node[1]}")
            return fn(*args) if n == 1 else fn(args)
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
        try:
            return a ** b
        except (OverflowError, ZeroDivisionError) as e:
            raise CalcError(str(e))
