import datetime
import os
import subprocess
import sys
import tempfile
import unittest

from budget.io import Transaction, load_csv, save_csv
from budget.report import monthly_net, over_budget, spending_by_category

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = """date,description,category,amount
2026-03-01,Pay,salary,1500
2026-03-02,Shop,food,-42.50
2026-03-09,Cafe,food,-7.25
2026-03-10,Bus,travel,-3.00
2026-04-01,Shop,food,-10.00
"""


def write(text):
    path = os.path.join(tempfile.mkdtemp(), "t.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class Budget(unittest.TestCase):
    def setUp(self):
        self.path = write(CSV)
        self.tx = load_csv(self.path)

    def test_load(self):
        self.assertEqual(len(self.tx), 5)
        self.assertEqual(self.tx[1], Transaction(datetime.date(2026, 3, 2), "Shop", "food", -4250))
        self.assertEqual(self.tx[0].amount_cents, 150000)

    def test_round_trip(self):
        out = os.path.join(tempfile.mkdtemp(), "o.csv")
        save_csv(out, self.tx)
        self.assertEqual(load_csv(out), self.tx)

    def test_reports(self):
        self.assertEqual(spending_by_category(self.tx, "2026-03"), {"food": 4975, "travel": 300})
        self.assertEqual(over_budget(self.tx, {"food": 4000, "travel": 500, "fun": 0}, "2026-03"), [("food", 4975, 4000)])
        self.assertEqual(monthly_net(self.tx), {"2026-03": 150000 - 4975 - 300, "2026-04": -1000})

    def test_cli(self):
        r = subprocess.run([sys.executable, "-m", "budget", "report", self.path, "2026-03"], cwd=HERE, capture_output=True, text=True, timeout=30,
                           env={**os.environ, "PYTHONPATH": HERE})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip().splitlines(), ["food: 49.75", "travel: 3.00", "total: 52.75"])


if __name__ == "__main__":
    unittest.main()
