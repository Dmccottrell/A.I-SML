from bank.errors import InsufficientFunds


def check_amount(amount):
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise ValueError("amount must be a positive whole number of cents")


class Account:
    def __init__(self, owner):
        self.owner, self.balance = owner, 0

    def deposit(self, amount):
        check_amount(amount)
        self.balance += amount

    def withdraw(self, amount):
        check_amount(amount)
        if amount > self.balance:
            raise InsufficientFunds(f"balance {self.balance} is less than {amount}")
        self.balance -= amount
