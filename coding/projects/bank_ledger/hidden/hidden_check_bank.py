import unittest

from bank.accounts import Account
from bank.errors import InsufficientFunds
from bank.ledger import Ledger
from bank.report import statement


class Bank(unittest.TestCase):
    def test_account(self):
        a = Account("Ann")
        self.assertEqual((a.owner, a.balance), ("Ann", 0))
        a.deposit(500)
        a.withdraw(200)
        self.assertEqual(a.balance, 300)
        with self.assertRaises(InsufficientFunds):
            a.withdraw(301)
        self.assertEqual(a.balance, 300)
        for bad in (0, -5, 2.5, "10"):
            with self.assertRaises(ValueError):
                a.deposit(bad)

    def test_ids_and_unknown(self):
        led = Ledger()
        self.assertEqual([led.open_account("x"), led.open_account("y")], ["A1", "A2"])
        with self.assertRaises(KeyError):
            led.balance("A9")
        with self.assertRaises(KeyError):
            led.deposit("A9", 5)

    def test_transfer_all_or_nothing(self):
        led = Ledger()
        a, b = led.open_account("Ann"), led.open_account("Bo")
        led.deposit(a, 1000)
        led.transfer(a, b, 400)
        self.assertEqual((led.balance(a), led.balance(b)), (600, 400))
        with self.assertRaises(InsufficientFunds):
            led.transfer(a, b, 601)
        with self.assertRaises(KeyError):
            led.transfer(a, "A7", 10)
        self.assertEqual((led.balance(a), led.balance(b)), (600, 400))
        self.assertEqual(led.history(a), [("deposit", 1000, 1000), ("transfer_out", 400, 600)])
        self.assertEqual(led.history(b), [("transfer_in", 400, 400)])

    def test_failed_ops_leave_no_history(self):
        led = Ledger()
        a = led.open_account("Ann")
        with self.assertRaises(InsufficientFunds):
            led.withdraw(a, 1)
        with self.assertRaises(ValueError):
            led.deposit(a, -1)
        self.assertEqual(led.history(a), [])

    def test_statement(self):
        led = Ledger()
        a = led.open_account("Ann")
        led.deposit(a, 1250)
        led.withdraw(a, 250)
        self.assertEqual(statement(led, a), "Statement for Ann (A1)\ndeposit 12.50 -> 12.50\nwithdraw 2.50 -> 10.00\nBalance: 10.00")


if __name__ == "__main__":
    unittest.main()
