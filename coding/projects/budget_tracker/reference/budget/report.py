def month_of(t):
    return t.date.strftime("%Y-%m")


def spending_by_category(transactions, month):
    out = {}
    for t in transactions:
        if month_of(t) == month and t.amount_cents < 0:
            out[t.category] = out.get(t.category, 0) - t.amount_cents
    return out


def over_budget(transactions, limits, month):
    spent = spending_by_category(transactions, month)
    return [(c, spent.get(c, 0), limit) for c, limit in sorted(limits.items()) if spent.get(c, 0) > limit]


def monthly_net(transactions):
    out = {}
    for t in transactions:
        out[month_of(t)] = out.get(month_of(t), 0) + t.amount_cents
    return out
