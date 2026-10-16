from bank.accounts import Account, check_amount
from bank.errors import InsufficientFunds


class Ledger:
    def __init__(self):
        self.accounts, self.histories = {}, {}

    def open_account(self, owner):
        aid = f"A{len(self.accounts) + 1}"
        self.accounts[aid], self.histories[aid] = Account(owner), []
        return aid

    def _get(self, aid):
        if aid not in self.accounts:
            raise KeyError(aid)
        return self.accounts[aid]

    def deposit(self, aid, amount):
        acc = self._get(aid)
        acc.deposit(amount)
        self.histories[aid].append(("deposit", amount, acc.balance))

    def withdraw(self, aid, amount):
        acc = self._get(aid)
        acc.withdraw(amount)
        self.histories[aid].append(("withdraw", amount, acc.balance))

    def transfer(self, from_id, to_id, amount):
        src, dst = self._get(from_id), self._get(to_id)
        check_amount(amount)
        if amount > src.balance:
            raise InsufficientFunds("not enough money")
        src.withdraw(amount)
        dst.deposit(amount)
        self.histories[from_id].append(("transfer_out", amount, src.balance))
        self.histories[to_id].append(("transfer_in", amount, dst.balance))

    def balance(self, aid):
        return self._get(aid).balance

    def history(self, aid):
        self._get(aid)
        return list(self.histories[aid])
