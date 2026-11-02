# Parser for the expression calculator (a reference solution that VryxCode's coding exercises are judged against).
# It takes the token list made by calc/tokens.py and builds a small "tree" (nested tuples) describing the maths,
# which calc/evaluator.py then walks to get the answer. This is a "recursive descent" parser: one method per
# level of operator strength, each calling the next stronger one.
from calc.errors import CalcError


class Parser:
    """Turns a list of tokens into a tree of tuples.

    Input: tokens like [("num", 2.0), ("sym", "+"), ("num", 3.0)] (a token is a (kind, value) pair).
    Output of parse(): a nested tuple such as ("bin", "+", ("num", 2.0), ("num", 3.0)).
    Node shapes: ("num", x), ("var", name), ("neg", node), ("bin", op, left, right), ("call", name, [args]).
    Weakest operators (+ -) are handled first, then * /, then unary minus, then ^, then single values;
    that order is what makes 2+3*4 mean 2+(3*4).
    """

    def __init__(self, tokens):
        # self.t is the token list and self.i is our position in it (the next token to look at).
        self.t, self.i = tokens, 0

    def peek(self):
        """Look at the next token without using it. Past the end it gives (None, None) so callers need no length check."""
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self, sym=None):
        """Use up the next token and return it.

        If sym is given (for example ")"), the next token must be exactly that symbol, else we raise CalcError.
        Running out of tokens is also an error, because take() is only called when something is still expected.
        """
        tok = self.peek()
        if tok[0] is None or (sym and tok != ("sym", sym)):
            raise CalcError(f"expected {sym or 'more input'}")
        self.i += 1
        return tok

    def parse(self):
        """Parse the whole input as one expression; leftover tokens (like a stray ")") are an error."""
        node = self.expr()
        if self.i != len(self.t):
            raise CalcError(f"unexpected {self.peek()[1]!r}")
        return node

    def expr(self):
        """Addition and subtraction, the weakest level. Loops so 1-2-3 groups left to right as (1-2)-3."""
        node = self.term()
        while self.peek() in (("sym", "+"), ("sym", "-")):
            op = self.take()[1]
            node = ("bin", op, node, self.term())
        return node

    def term(self):
        """Multiplication and division, one level stronger than + and -. Also grouped left to right."""
        node = self.unary()
        while self.peek() in (("sym", "*"), ("sym", "/")):
            op = self.take()[1]
            node = ("bin", op, node, self.unary())
        return node

    def unary(self):
        """A leading minus (negate) or plus (ignored) in front of a value; it can repeat, like --5."""
        if self.peek() == ("sym", "-"):
            self.take()
            return ("neg", self.unary())
        if self.peek() == ("sym", "+"):
            self.take()
            return self.unary()
        return self.power()

    def power(self):
        """The ^ operator. The right side goes through unary(), so 2^3^2 is 2^(3^2) and 2^-1 works (^ groups right to left)."""
        base = self.atom()
        if self.peek() == ("sym", "^"):
            self.take()
            return ("bin", "^", base, self.unary())
        return base

    def atom(self):
        """The smallest piece: a number, a variable, a function call like max(1, 2), or something in ( ) brackets."""
        kind, val = self.take()
        if kind == "num":
            return ("num", val)
        if kind == "name":
            # A name followed by "(" is a function call; otherwise it is a variable.
            if self.peek() == ("sym", "("):
                self.take()
                args = []
                # An empty argument list "()" is allowed here; the evaluator decides if that is valid for the function.
                if self.peek() != ("sym", ")"):
                    args.append(self.expr())
                    while self.peek() == ("sym", ","):
                        self.take()
                        args.append(self.expr())
                self.take(")")
                return ("call", val, args)
            return ("var", val)
        if (kind, val) == ("sym", "("):
            # Brackets: parse a whole new expression inside, then insist on the closing bracket.
            node = self.expr()
            self.take(")")
            return node
        raise CalcError(f"unexpected {val!r}")


def parse(tokens):
    """Public entry point: tokens in, tree out. An empty token list is rejected with a clear message."""
    if not tokens:
        raise CalcError("empty expression")
    return Parser(tokens).parse()
