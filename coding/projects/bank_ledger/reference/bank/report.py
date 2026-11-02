"""Turns a ledger's data into printable text."""


def money(cents):
    """Format a number of cents as dollars with two decimals, e.g. 1250 -> "12.50"."""
    return f"{cents / 100:.2f}"


def statement(ledger, aid):
    """Return a multi-line text statement for account `aid`: a title, one line per operation, then the balance."""
    acc = ledger.accounts[aid]
    lines = [f"Statement for {acc.owner} ({aid})"]
    # Each history row is (kind, amount, balance after); show both amounts as money.
    for kind, amount, after in ledger.history(aid):
        lines.append(f"{kind} {money(amount)} -> {money(after)}")
    lines.append(f"Balance: {money(ledger.balance(aid))}")
    return "\n".join(lines)
