"""Hidden grading test for the "bank ledger" practice project.

The coding agent (VryxCode) is asked to write a small `bank` package. It never
sees this file. After it finishes, the harness runs this test against the
agent's code to decide whether the job really works. The correct answer
(the `reference/bank` folder next to this one) must pass it.
"""
import unittest

from bank.accounts import Account
from bank.errors import InsufficientFunds
from bank.ledger import Ledger
from bank.report import statement


class Bank(unittest.TestCase):
    """Checks accounts, the multi-account ledger, transfers and the printed statement."""

    def test_account(self):
        """Proves one Account can deposit, withdraw, and refuses bad or too-large amounts."""
        a = Account("Ann")
        # A new account has the given owner and starts with zero cents.
        self.assertEqual((a.owner, a.balance), ("Ann", 0))
        a.deposit(500)
        a.withdraw(200)
        self.assertEqual(a.balance, 300)
        # Taking out more than the balance must raise, and must not change the balance.
        with self.assertRaises(InsufficientFunds):
            a.withdraw(301)
        self.assertEqual(a.balance, 300)
        # Money must be a positive whole number of cents: zero, negatives, floats and strings are rejected.
        for bad in (0, -5, 2.5, "10"):
            with self.assertRaises(ValueError):
                a.deposit(bad)

    def test_ids_and_unknown(self):
        """Proves account ids are handed out as A1, A2, ... and unknown ids raise KeyError."""
        led = Ledger()
        self.assertEqual([led.open_account("x"), led.open_account("y")], ["A1", "A2"])
        # "A9" was never opened, so looking it up (or paying into it) must fail with KeyError.
        with self.assertRaises(KeyError):
            led.balance("A9")
        with self.assertRaises(KeyError):
            led.deposit("A9", 5)

    def test_transfer_all_or_nothing(self):
        """Proves a transfer either fully happens or changes nothing, and history records it."""
        led = Ledger()
        a, b = led.open_account("Ann"), led.open_account("Bo")
        led.deposit(a, 1000)
        led.transfer(a, b, 400)
        self.assertEqual((led.balance(a), led.balance(b)), (600, 400))
        # Two failing transfers (not enough money, unknown target account)...
        with self.assertRaises(InsufficientFunds):
            led.transfer(a, b, 601)
        with self.assertRaises(KeyError):
            led.transfer(a, "A7", 10)
        # ...must leave both balances exactly as they were ("all or nothing").
        self.assertEqual((led.balance(a), led.balance(b)), (600, 400))
        # Each history row is (kind, amount, balance after). Failed attempts must not appear.
        self.assertEqual(led.history(a), [("deposit", 1000, 1000), ("transfer_out", 400, 600)])
        self.assertEqual(led.history(b), [("transfer_in", 400, 400)])

    def test_failed_ops_leave_no_history(self):
        """Proves operations that raise an error are not written to the history."""
        led = Ledger()
        a = led.open_account("Ann")
        with self.assertRaises(InsufficientFunds):
            led.withdraw(a, 1)
        with self.assertRaises(ValueError):
            led.deposit(a, -1)
        self.assertEqual(led.history(a), [])

    def test_statement(self):
        """Proves the text statement shows cents as dollars with two decimals, line by line."""
        led = Ledger()
        a = led.open_account("Ann")
        led.deposit(a, 1250)
        led.withdraw(a, 250)
        # 1250 cents -> 12.50, then 250 cents out -> balance 1000 cents -> 10.00.
        self.assertEqual(statement(led, a), "Statement for Ann (A1)\ndeposit 12.50 -> 12.50\nwithdraw 2.50 -> 10.00\nBalance: 10.00")


if __name__ == "__main__":
    unittest.main()
