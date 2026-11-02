"""Command-line entry point: `python -m budget report FILE.csv YYYY-MM` prints spending per category."""
import sys

from budget.io import load_csv
from budget.report import spending_by_category

# sys.argv is the list of words typed on the command line: [program, "report", file, month].
# Anything other than exactly that shape prints a usage hint and exits with an error.
if len(sys.argv) != 4 or sys.argv[1] != "report":
    sys.exit("usage: python -m budget report FILE.csv YYYY-MM")
spent = spending_by_category(load_csv(sys.argv[2]), sys.argv[3])
# One line per category in alphabetical order; cents are divided by 100 to show dollars.
for cat in sorted(spent):
    print(f"{cat}: {spent[cat] / 100:.2f}")
print(f"total: {sum(spent.values()) / 100:.2f}")
