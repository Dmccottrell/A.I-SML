"""Simple reports over a list of Transaction objects (see io.py). All sums are in cents."""


def month_of(t):
    """Return the month of transaction `t` as text like "2026-03"."""
    return t.date.strftime("%Y-%m")


def spending_by_category(transactions, month):
    """Return {category: cents spent} for one month ("YYYY-MM"). Only money going out counts (negative amounts)."""
    out = {}
    for t in transactions:
        if month_of(t) == month and t.amount_cents < 0:
            # Subtracting a negative number adds its size, so spending shows as a positive total.
            out[t.category] = out.get(t.category, 0) - t.amount_cents
    return out


def over_budget(transactions, limits, month):
    """Return [(category, spent, limit), ...] for categories whose spending in `month` is above their limit.

    `limits` maps category -> allowed cents. The result is sorted by category name.
    """
    spent = spending_by_category(transactions, month)
    return [(c, spent.get(c, 0), limit) for c, limit in sorted(limits.items()) if spent.get(c, 0) > limit]


def monthly_net(transactions):
    """Return {month: cents} with income minus spending for every month that has any transaction."""
    out = {}
    for t in transactions:
        out[month_of(t)] = out.get(month_of(t), 0) + t.amount_cents
    return out
