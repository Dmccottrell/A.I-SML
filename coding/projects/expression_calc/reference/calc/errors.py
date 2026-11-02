"""The one error type the calculator raises for any bad input."""


class CalcError(Exception):
    """Raised for any problem with an expression (bad syntax, unknown name, divide by zero, ...)."""

    pass
