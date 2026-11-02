"""Reading and writing the transactions CSV file. All money is stored as whole cents to avoid float rounding errors."""
import csv
import datetime
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class Transaction:
    """One row of the CSV. (`@dataclass` makes Python write __init__ and == for us.)

    amount_cents is negative for money spent and positive for money received.
    """

    date: datetime.date
    description: str
    category: str
    amount_cents: int


def to_cents(text):
    """Turn dollar text like "-42.50" into whole cents (-4250).

    Decimal does exact decimal maths, unlike float (0.1 + 0.2 is not 0.3 in floats).
    """
    return int((Decimal(text.strip()) * 100).to_integral_value())


def load_csv(path):
    """Read the CSV at `path` and return a list of Transaction objects."""
    # newline="" is what the csv module asks for so it can handle line endings itself.
    with open(path, newline="", encoding="utf-8") as f:
        # DictReader gives each row as a dict keyed by the header line (date, description, ...).
        return [Transaction(datetime.date.fromisoformat(r["date"].strip()), r["description"], r["category"], to_cents(r["amount"]))
                for r in csv.DictReader(f)]


def save_csv(path, transactions):
    """Write the transactions to `path` in the same format `load_csv` reads."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "description", "category", "amount"])
        for t in transactions:
            # Split sign and size so the dollars/cents text is built from non-negative numbers:
            # -4250 -> "-" + 42 dollars + 50 cents. `:02d` pads cents to two digits (5 -> "05").
            sign = "-" if t.amount_cents < 0 else ""
            cents = abs(t.amount_cents)
            w.writerow([t.date.isoformat(), t.description, t.category, f"{sign}{cents // 100}.{cents % 100:02d}"])
