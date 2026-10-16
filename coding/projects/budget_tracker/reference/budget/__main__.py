import sys

from budget.io import load_csv
from budget.report import spending_by_category

if len(sys.argv) != 4 or sys.argv[1] != "report":
    sys.exit("usage: python -m budget report FILE.csv YYYY-MM")
spent = spending_by_category(load_csv(sys.argv[2]), sys.argv[3])
for cat in sorted(spent):
    print(f"{cat}: {spent[cat] / 100:.2f}")
print(f"total: {sum(spent.values()) / 100:.2f}")
