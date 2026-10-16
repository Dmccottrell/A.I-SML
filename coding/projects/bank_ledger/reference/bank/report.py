def money(cents):
    return f"{cents / 100:.2f}"


def statement(ledger, aid):
    acc = ledger.accounts[aid]
    lines = [f"Statement for {acc.owner} ({aid})"]
    for kind, amount, after in ledger.history(aid):
        lines.append(f"{kind} {money(amount)} -> {money(after)}")
    lines.append(f"Balance: {money(ledger.balance(aid))}")
    return "\n".join(lines)
