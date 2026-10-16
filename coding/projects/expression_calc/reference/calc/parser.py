from calc.errors import CalcError


class Parser:
    def __init__(self, tokens):
        self.t, self.i = tokens, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self, sym=None):
        tok = self.peek()
        if tok[0] is None or (sym and tok != ("sym", sym)):
            raise CalcError(f"expected {sym or 'more input'}")
        self.i += 1
        return tok

    def parse(self):
        node = self.expr()
        if self.i != len(self.t):
            raise CalcError(f"unexpected {self.peek()[1]!r}")
        return node

    def expr(self):
        node = self.term()
        while self.peek() in (("sym", "+"), ("sym", "-")):
            op = self.take()[1]
            node = ("bin", op, node, self.term())
        return node

    def term(self):
        node = self.unary()
        while self.peek() in (("sym", "*"), ("sym", "/")):
            op = self.take()[1]
            node = ("bin", op, node, self.unary())
        return node

    def unary(self):
        if self.peek() == ("sym", "-"):
            self.take()
            return ("neg", self.unary())
        if self.peek() == ("sym", "+"):
            self.take()
            return self.unary()
        return self.power()

    def power(self):
        base = self.atom()
        if self.peek() == ("sym", "^"):
            self.take()
            return ("bin", "^", base, self.unary())
        return base

    def atom(self):
        kind, val = self.take()
        if kind == "num":
            return ("num", val)
        if kind == "name":
            if self.peek() == ("sym", "("):
                self.take()
                args = []
                if self.peek() != ("sym", ")"):
                    args.append(self.expr())
                    while self.peek() == ("sym", ","):
                        self.take()
                        args.append(self.expr())
                self.take(")")
                return ("call", val, args)
            return ("var", val)
        if (kind, val) == ("sym", "("):
            node = self.expr()
            self.take(")")
            return node
        raise CalcError(f"unexpected {val!r}")


def parse(tokens):
    if not tokens:
        raise CalcError("empty expression")
    return Parser(tokens).parse()
