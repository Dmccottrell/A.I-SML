# The storage layer of the inventory reference solution (used by the "inventory_api" coding exercise).
# It keeps items (name, quantity, price) in a SQLite database: a small database that lives in memory or in one file.
# inventory/api.py calls these methods and turns the results into HTTP-style answers.
import sqlite3


class Store:
    """A table of stock items. Each item is a dict: {"id", "name", "qty", "price_cents"}. Names must be unique."""

    def __init__(self, path=":memory:"):
        """Open the database at path. The special name ":memory:" means a temporary database that vanishes at exit.

        A real file path keeps the data between runs. The table is created only if it is not there yet.
        """
        self.db = sqlite3.connect(path)
        # id counts up by itself (AUTOINCREMENT); UNIQUE on name is what makes a duplicate name fail later.
        self.db.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, qty INTEGER NOT NULL, price_cents INTEGER NOT NULL)")

    @staticmethod
    def _row(r):
        """Turn a database row (a tuple in column order) into a dict; None (no row found) stays None."""
        return None if r is None else {"id": r[0], "name": r[1], "qty": r[2], "price_cents": r[3]}

    def add_item(self, name, qty, price_cents):
        """Insert a new item and return its new id. A name that already exists raises ValueError."""
        try:
            # "with self.db" is a transaction: it saves (commits) on success and undoes the change if an error happens.
            # The ? marks are placeholders: values are passed separately so they can never be mistaken for SQL code.
            with self.db:
                cur = self.db.execute("INSERT INTO items (name, qty, price_cents) VALUES (?, ?, ?)", (name, qty, price_cents))
        except sqlite3.IntegrityError:
            # IntegrityError is SQLite saying "this breaks a rule" (here the UNIQUE name rule); we turn it into a friendlier error.
            raise ValueError(f"{name} already exists")
        return cur.lastrowid

    def get(self, item_id):
        """Return the item with this id as a dict, or None if there is no such item."""
        return self._row(self.db.execute("SELECT id, name, qty, price_cents FROM items WHERE id = ?", (item_id,)).fetchone())

    def update_qty(self, item_id, delta):
        """Add delta to the stock (use a negative number to take stock out) and return the updated item.

        Raises KeyError if the item does not exist, ValueError if the stock would go below zero (nothing is changed then).
        """
        item = self.get(item_id)
        if item is None:
            raise KeyError(item_id)
        if item["qty"] + delta < 0:
            raise ValueError("not enough stock")
        with self.db:
            self.db.execute("UPDATE items SET qty = qty + ? WHERE id = ?", (delta, item_id))
        return self.get(item_id)

    def list_items(self, low=None):
        """All items ordered by id. If low is given, only items whose quantity is below it (a "running low" report)."""
        if low is None:
            rows = self.db.execute("SELECT id, name, qty, price_cents FROM items ORDER BY id").fetchall()
        else:
            rows = self.db.execute("SELECT id, name, qty, price_cents FROM items WHERE qty < ? ORDER BY id", (low,)).fetchall()
        return [self._row(r) for r in rows]

    def delete(self, item_id):
        """Remove an item. Returns True if something was deleted, False if the id did not exist."""
        with self.db:
            # rowcount is how many rows the DELETE touched: 1 means it existed, 0 means it did not.
            return self.db.execute("DELETE FROM items WHERE id = ?", (item_id,)).rowcount > 0
