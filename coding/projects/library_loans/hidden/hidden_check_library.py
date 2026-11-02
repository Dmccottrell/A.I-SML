# Hidden checks for the "library_loans" coding exercise. The agent never sees this file; it is run afterwards to decide
# whether the agent's library/ package really works (catalog, checkout rules, fines).
import datetime
import unittest

from library.catalog import Catalog
from library.errors import LoanError
from library.loans import Library

# Day zero for all tests; day(n) is n days later. Fixed dates keep the tests repeatable.
D = datetime.date(2026, 1, 1)


def day(n):
    """The date n days after D."""
    return D + datetime.timedelta(days=n)


class Loans(unittest.TestCase):
    """Checks for the Catalog and the Library lending rules."""

    def setUp(self):
        """Before each test: a catalog of 4 books ("Dune" has 2 copies, the rest 1) and a library with members m1 and m2."""
        self.cat = Catalog()
        self.cat.add_book("111", "Dune", copies=2)
        self.cat.add_book("222", "Emma")
        self.cat.add_book("333", "Ulysses")
        self.cat.add_book("444", "Beloved")
        self.lib = Library(self.cat)
        self.lib.add_member("m1", "Ann")
        self.lib.add_member("m2", "Bo")

    def test_catalog(self):
        """Proves adding an existing ISBN adds copies (1 + 2 = 3) and keeps the title; an unknown ISBN raises KeyError."""
        self.cat.add_book("222", "Emma", copies=2)
        self.assertEqual((self.cat.title("222"), self.cat.available("222")), ("Emma", 3))
        with self.assertRaises(KeyError):
            self.cat.available("999")

    def test_checkout_rules(self):
        """Proves due date is 14 days out and each refusal rule fires: duplicate, no copies left, 3-book limit, unknown member."""
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
        # Loans are listed by due date: borrowed on day 0, 1 and 2 means due on 14, 15 and 16.
        self.assertEqual(self.lib.loans("m1"), [("111", day(14)), ("222", day(15)), ("333", day(16))])

    def test_fines(self):
        """Proves overdue list, fine amounts (25 cents a day), the 500-cent borrowing block, paying, and double returns."""
        self.lib.checkout("m1", "222", D)
        self.lib.checkout("m1", "333", D)
        # On day 20 both books (due day 14) are 6 days late.
        self.assertEqual(self.lib.overdue(day(20)), [("m1", "222", 6), ("m1", "333", 6)])
        self.assertEqual(self.lib.return_book("m1", "222", day(14)), 0)
        # Returned on day 40, due day 14: 26 days late at 25 cents each.
        self.assertEqual(self.lib.return_book("m1", "333", day(40)), 26 * 25)
        self.assertEqual(self.lib.owed("m1"), 650)
        # Returning the same book again is an error.
        with self.assertRaises(LoanError):
            self.lib.return_book("m1", "333", day(41))
        with self.assertRaises(LoanError):
            self.lib.checkout("m1", "444", day(41))           # owes more than 500
        self.assertEqual(self.lib.pay("m1", 200), 450)
        # Now owing 450 (not more than 500), borrowing works again.
        self.lib.checkout("m1", "444", day(41))
        # Overpaying leaves 0, not a negative amount.
        self.assertEqual(self.lib.pay("m1", 9999), 0)


if __name__ == "__main__":
    unittest.main()
