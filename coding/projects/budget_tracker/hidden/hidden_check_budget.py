"""Hidden grading test for the "budget tracker" practice project.

The coding agent (VryxCode) writes a small `budget` package that reads a CSV of
transactions and reports spending. It never sees this file; the harness runs it
afterwards to judge the agent's work. The `reference/budget` folder passes it.
"""
import datetime
import os
import subprocess
import sys
import tempfile
import unittest

from budget.io import Transaction, load_csv, save_csv
from budget.report import monthly_net, over_budget, spending_by_category

# The folder this test file lives in; the command-line test runs `python -m budget` from here.
HERE = os.path.dirname(os.path.abspath(__file__))
# Sample data: negative amounts are money spent, positive is money received. Amounts are in dollars.
CSV = """date,description,category,amount
2026-03-01,Pay,salary,1500
2026-03-02,Shop,food,-42.50
2026-03-09,Cafe,food,-7.25
2026-03-10,Bus,travel,-3.00
2026-04-01,Shop,food,-10.00
"""


def write(text):
    """Save `text` to a new file called t.csv in a fresh temp folder and return its path."""
    path = os.path.join(tempfile.mkdtemp(), "t.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class Budget(unittest.TestCase):
    """Checks loading/saving the CSV, the monthly reports and the command-line tool."""

    def setUp(self):
        """Before each test: write the sample CSV to disk and load it into `self.tx`."""
        self.path = write(CSV)
        self.tx = load_csv(self.path)

    def test_load(self):
        """Proves rows are parsed: 5 of them, dates become date objects, dollars become whole cents."""
        self.assertEqual(len(self.tx), 5)
        # -42.50 dollars must become exactly -4250 cents (no float rounding).
        self.assertEqual(self.tx[1], Transaction(datetime.date(2026, 3, 2), "Shop", "food", -4250))
        self.assertEqual(self.tx[0].amount_cents, 150000)

    def test_round_trip(self):
        """Proves saving then loading gives back exactly the same transactions."""
        out = os.path.join(tempfile.mkdtemp(), "o.csv")
        save_csv(out, self.tx)
        self.assertEqual(load_csv(out), self.tx)

    def test_reports(self):
        """Proves the three report functions add up the right cents."""
        # March spending only: food 42.50 + 7.25 = 4975 cents, travel 300. Income is ignored, April is ignored.
        self.assertEqual(spending_by_category(self.tx, "2026-03"), {"food": 4975, "travel": 300})
        # Only categories whose spending is above their limit are listed: (category, spent, limit).
        # travel (300 <= 500) and fun (0 <= 0) are fine, food (4975 > 4000) is over.
        self.assertEqual(over_budget(self.tx, {"food": 4000, "travel": 500, "fun": 0}, "2026-03"), [("food", 4975, 4000)])
        # Net = income minus spending per month, so March is 1500.00 - 49.75 - 3.00, April is -10.00.
        self.assertEqual(monthly_net(self.tx), {"2026-03": 150000 - 4975 - 300, "2026-04": -1000})

    def test_cli(self):
        """Proves `python -m budget report FILE MONTH` runs and prints the right lines."""
        # Run it as a separate process, like a real user would. PYTHONPATH lets Python find the `budget` package.
        r = subprocess.run([sys.executable, "-m", "budget", "report", self.path, "2026-03"], cwd=HERE, capture_output=True, text=True, timeout=30,
                           env={**os.environ, "PYTHONPATH": HERE})
        # Exit code 0 means success; stderr is shown as the failure message if it is not 0.
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip().splitlines(), ["food: 49.75", "travel: 3.00", "total: 52.75"])


if __name__ == "__main__":
    unittest.main()
