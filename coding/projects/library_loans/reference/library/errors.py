# The one custom error type of the library reference solution.
class LoanError(Exception):
    """Raised when a loan rule is broken (no copy left, too many books, already borrowed, fines owed, not borrowed)."""
    pass
