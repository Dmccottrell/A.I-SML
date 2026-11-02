# Lending rules of the library reference solution: members borrow and return books, late returns create fines.
# Money is counted in whole cents (so no rounding problems). It reads copy counts from library/catalog.py.
import datetime

from library.errors import LoanError

# The rules in one place: a loan lasts 14 days, a late book costs 25 cents per day, a member may hold 3 books at once,
# and a member who owes more than 500 cents may not borrow.
LOAN_DAYS, FINE_PER_DAY, MAX_LOANS, MAX_OWED = 14, 25, 3, 500


class Library:
    """Members, their current loans and the fines they owe. Dates are passed in (never read from the clock) so tests are repeatable."""

    def __init__(self, catalog):
        self.catalog = catalog
        # members: {id: {"name", "loans": {isbn: due_date}, "owed": cents}}
        self.members = {}

    def add_member(self, member_id, name):
        """Register a member with no loans and no fines."""
        self.members[member_id] = {"name": name, "loans": {}, "owed": 0}

    def _member(self, member_id):
        """Find a member's record; an unknown id raises KeyError."""
        if member_id not in self.members:
            raise KeyError(member_id)
        return self.members[member_id]

    def checkout(self, member_id, isbn, day):
        """Lend a book on date `day` and return its due date.

        Raises LoanError if no copy is free, the member already holds 3 books, already has this book, or owes more than 500 cents.
        Unknown member or ISBN raises KeyError.
        """
        m = self._member(member_id)
        # Check every rule BEFORE changing anything, so a refused checkout leaves no half-done state.
        if self.catalog.available(isbn) <= 0:
            raise LoanError("no copy available")
        if len(m["loans"]) >= MAX_LOANS:
            raise LoanError("too many books")
        if isbn in m["loans"]:
            raise LoanError("already borrowed")
        if m["owed"] > MAX_OWED:
            raise LoanError("fines owed")
        due = day + datetime.timedelta(days=LOAN_DAYS)
        m["loans"][isbn] = due
        self.catalog.out[isbn] += 1
        return due

    def return_book(self, member_id, isbn, day):
        """Take a book back on date `day`. Returns the fine in cents (0 if on time) and adds it to what the member owes."""
        m = self._member(member_id)
        if isbn not in m["loans"]:
            raise LoanError("not borrowed")
        due = m["loans"].pop(isbn)
        self.catalog.out[isbn] -= 1
        # Late days = day minus due date; max(0, ...) means an early or on-time return costs nothing.
        fine = max(0, (day - due).days) * FINE_PER_DAY
        m["owed"] += fine
        return fine

    def loans(self, member_id):
        """The member's current loans as (isbn, due_date) pairs, earliest due date first, ISBN as tie-break."""
        return sorted(((i, d) for i, d in self._member(member_id)["loans"].items()), key=lambda p: (p[1], p[0]))

    def owed(self, member_id):
        """Cents the member currently owes in fines."""
        return self._member(member_id)["owed"]

    def pay(self, member_id, cents):
        """Pay some of the fines. Overpaying just brings the debt to 0 (never negative). Returns what is still owed."""
        m = self._member(member_id)
        m["owed"] = max(0, m["owed"] - cents)
        return m["owed"]

    def overdue(self, day):
        """Everything late on date `day`, as (member_id, isbn, days_late) tuples ordered by member then ISBN."""
        out = []
        for mid in sorted(self.members):
            for isbn, due in sorted(self.members[mid]["loans"].items()):
                # Late only if today is strictly after the due date.
                if day > due:
                    out.append((mid, isbn, (day - due).days))
        return out
