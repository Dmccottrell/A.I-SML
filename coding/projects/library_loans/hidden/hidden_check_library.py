import datetime
import unittest

from library.catalog import Catalog
from library.errors import LoanError
from library.loans import Library

D = datetime.date(2026, 1, 1)


def day(n):
    return D + datetime.timedelta(days=n)


class Loans(unittest.TestCase):
    def setUp(self):
        self.cat = Catalog()
        self.cat.add_book("111", "Dune", copies=2)
        self.cat.add_book("222", "Emma")
        self.cat.add_book("333", "Ulysses")
        self.cat.add_book("444", "Beloved")
        self.lib = Library(self.cat)
        self.lib.add_member("m1", "Ann")
        self.lib.add_member("m2", "Bo")

    def test_catalog(self):
        self.cat.add_book("222", "Emma", copies=2)
        self.assertEqual((self.cat.title("222"), self.cat.available("222")), ("Emma", 3))
        with self.assertRaises(KeyError):
            self.cat.available("999")

    def test_checkout_rules(self):
        self.assertEqual(self.lib.checkout("m1", "111", D), day(14))
        self.assertEqual(self.cat.available("111"), 1)
        with self.assertRaises(LoanError):
            self.lib.checkout("m1", "111", D)                 # already has it
        self.lib.checkout("m2", "111", D)
        with self.assertRaises(LoanError):
            self.lib.checkout("m2", "111", D)                 # none left
        self.lib.checkout("m1", "222", day(1))
        self.lib.checkout("m1", "333", day(2))
        with self.assertRaises(LoanError):
            self.lib.checkout("m1", "444", D)                 # three already
        with self.assertRaises(KeyError):
            self.lib.checkout("nobody", "444", D)
        self.assertEqual(self.lib.loans("m1"), [("111", day(14)), ("222", day(15)), ("333", day(16))])

    def test_fines(self):
        self.lib.checkout("m1", "222", D)
        self.lib.checkout("m1", "333", D)
        self.assertEqual(self.lib.overdue(day(20)), [("m1", "222", 6), ("m1", "333", 6)])
        self.assertEqual(self.lib.return_book("m1", "222", day(14)), 0)
        self.assertEqual(self.lib.return_book("m1", "333", day(40)), 26 * 25)
        self.assertEqual(self.lib.owed("m1"), 650)
        with self.assertRaises(LoanError):
            self.lib.return_book("m1", "333", day(41))
        with self.assertRaises(LoanError):
            self.lib.checkout("m1", "444", day(41))           # owes more than 500
        self.assertEqual(self.lib.pay("m1", 200), 450)
        self.lib.checkout("m1", "444", day(41))
        self.assertEqual(self.lib.pay("m1", 9999), 0)


if __name__ == "__main__":
    unittest.main()
