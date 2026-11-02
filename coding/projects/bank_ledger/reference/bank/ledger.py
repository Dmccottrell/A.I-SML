"""The Ledger: a book that holds many accounts and the history of what happened to each."""
from bank.accounts import Account, check_amount
from bank.errors import InsufficientFunds


class Ledger:
    """Keeps every account (by id like "A1") and a list of its past operations."""

    def __init__(self):
        """Create an empty ledger. `accounts` maps id -> Account, `histories` maps id -> list of rows."""
        self.accounts, self.histories = {}, {}

    def open_account(self, owner):
        """Open a new account for `owner` and return its id ("A1", "A2", ... in order)."""
        aid = f"A{len(self.accounts) + 1}"
        self.accounts[aid], self.histories[aid] = Account(owner), []
        return aid

    def _get(self, aid):
        """Return the Account for `aid`, or raise KeyError if no such account exists."""
        if aid not in self.accounts:
            raise KeyError(aid)
        return self.accounts[aid]

    def deposit(self, aid, amount):
        """Add money to an account and record it. A history row is (kind, amount, balance after)."""
        acc = self._get(aid)
        # If the deposit raises, the line below never runs, so failed attempts leave no history.
        acc.deposit(amount)
        self.histories[aid].append(("deposit", amount, acc.balance))

    def withdraw(self, aid, amount):
        """Take money out of an account and record it (same rules as `deposit`)."""
        acc = self._get(aid)
        acc.withdraw(amount)
        self.histories[aid].append(("withdraw", amount, acc.balance))

    def transfer(self, from_id, to_id, amount):
        """Move money between two accounts, all or nothing.

        Every check happens first; only then is money moved, so a failure
        can never leave one account changed and the other not.
        """
        # Look up both accounts first (KeyError if either is missing), then validate the amount.
        src, dst = self._get(from_id), self._get(to_id)
        check_amount(amount)
        if amount > src.balance:
            raise InsufficientFunds("not enough money")
        # Checks passed, so these two calls cannot fail.
        src.withdraw(amount)
        dst.deposit(amount)
        self.histories[from_id].append(("transfer_out", amount, src.balance))
        self.histories[to_id].append(("transfer_in", amount, dst.balance))

    def balance(self, aid):
        """Return the account's balance in cents."""
        return self._get(aid).balance

    def history(self, aid):
        """Return a copy of the account's history rows (a copy so callers cannot change the real list)."""
        # Called for its side effect too: raises KeyError when the account does not exist.
        self._get(aid)
        return list(self.histories[aid])
