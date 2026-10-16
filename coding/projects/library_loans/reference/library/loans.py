import datetime

from library.errors import LoanError

LOAN_DAYS, FINE_PER_DAY, MAX_LOANS, MAX_OWED = 14, 25, 3, 500


class Library:
    def __init__(self, catalog):
        self.catalog = catalog
        self.members = {}

    def add_member(self, member_id, name):
        self.members[member_id] = {"name": name, "loans": {}, "owed": 0}

    def _member(self, member_id):
        if member_id not in self.members:
            raise KeyError(member_id)
        return self.members[member_id]

    def checkout(self, member_id, isbn, day):
        m = self._member(member_id)
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
        m = self._member(member_id)
        if isbn not in m["loans"]:
            raise LoanError("not borrowed")
        due = m["loans"].pop(isbn)
        self.catalog.out[isbn] -= 1
        fine = max(0, (day - due).days) * FINE_PER_DAY
        m["owed"] += fine
        return fine

    def loans(self, member_id):
        return sorted(((i, d) for i, d in self._member(member_id)["loans"].items()), key=lambda p: (p[1], p[0]))

    def owed(self, member_id):
        return self._member(member_id)["owed"]

    def pay(self, member_id, cents):
        m = self._member(member_id)
        m["owed"] = max(0, m["owed"] - cents)
        return m["owed"]

    def overdue(self, day):
        out = []
        for mid in sorted(self.members):
            for isbn, due in sorted(self.members[mid]["loans"].items()):
                if day > due:
                    out.append((mid, isbn, (day - due).days))
        return out
