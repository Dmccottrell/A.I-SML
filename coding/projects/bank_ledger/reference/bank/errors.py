"""Custom error types for the bank package."""


class InsufficientFunds(Exception):
    """Raised when someone tries to take out more money than the account holds."""

    pass
