"""One bank account. Money is always a whole number of cents (never a float) so there are no rounding errors."""
from bank.errors import InsufficientFunds


def check_amount(amount):
    """Raise ValueError unless `amount` is a positive whole number of cents.

    Used by deposits, withdrawals and transfers so every path has the same rule.
    """
    # `bool` is a kind of int in Python (True == 1), so it is rejected on purpose.
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise ValueError("amount must be a positive whole number of cents")


class Account:
    """A single person's account: an owner name and a balance in cents."""

    def __init__(self, owner):
        """Start an empty account (balance 0) for `owner`."""
        self.owner, self.balance = owner, 0

    def deposit(self, amount):
        """Add `amount` cents. Raises ValueError if the amount is not valid."""
        check_amount(amount)
        self.balance += amount

    def withdraw(self, amount):
        """Take out `amount` cents. Raises ValueError for a bad amount, InsufficientFunds if it is more than the balance."""
        check_amount(amount)
        if amount > self.balance:
            raise InsufficientFunds(f"balance {self.balance} is less than {amount}")
        self.balance -= amount
