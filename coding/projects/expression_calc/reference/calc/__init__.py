"""The `calc` package: a small maths-expression calculator. Re-exports the two names users need."""
# The # noqa: F401 markers below tell the linter "unused import is on purpose, this is a re-export".
from calc.errors import CalcError  # noqa: F401
from calc.evaluator import Calculator  # noqa: F401
