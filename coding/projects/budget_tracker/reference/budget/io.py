import csv
import datetime
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class Transaction:
    date: datetime.date
    description: str
    category: str
    amount_cents: int


def to_cents(text):
    return int((Decimal(text.strip()) * 100).to_integral_value())


def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return [Transaction(datetime.date.fromisoformat(r["date"].strip()), r["description"], r["category"], to_cents(r["amount"]))
                for r in csv.DictReader(f)]


def save_csv(path, transactions):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "description", "category", "amount"])
        for t in transactions:
            sign = "-" if t.amount_cents < 0 else ""
            cents = abs(t.amount_cents)
            w.writerow([t.date.isoformat(), t.description, t.category, f"{sign}{cents // 100}.{cents % 100:02d}"])
