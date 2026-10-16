import sqlite3


class Store:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, qty INTEGER NOT NULL, price_cents INTEGER NOT NULL)")

    @staticmethod
    def _row(r):
        return None if r is None else {"id": r[0], "name": r[1], "qty": r[2], "price_cents": r[3]}

    def add_item(self, name, qty, price_cents):
        try:
            with self.db:
                cur = self.db.execute("INSERT INTO items (name, qty, price_cents) VALUES (?, ?, ?)", (name, qty, price_cents))
        except sqlite3.IntegrityError:
            raise ValueError(f"{name} already exists")
        return cur.lastrowid

    def get(self, item_id):
        return self._row(self.db.execute("SELECT id, name, qty, price_cents FROM items WHERE id = ?", (item_id,)).fetchone())

    def update_qty(self, item_id, delta):
        item = self.get(item_id)
        if item is None:
            raise KeyError(item_id)
        if item["qty"] + delta < 0:
            raise ValueError("not enough stock")
        with self.db:
            self.db.execute("UPDATE items SET qty = qty + ? WHERE id = ?", (delta, item_id))
        return self.get(item_id)

    def list_items(self, low=None):
        if low is None:
            rows = self.db.execute("SELECT id, name, qty, price_cents FROM items ORDER BY id").fetchall()
        else:
            rows = self.db.execute("SELECT id, name, qty, price_cents FROM items WHERE qty < ? ORDER BY id", (low,)).fetchall()
        return [self._row(r) for r in rows]

    def delete(self, item_id):
        with self.db:
            return self.db.execute("DELETE FROM items WHERE id = ?", (item_id,)).rowcount > 0
