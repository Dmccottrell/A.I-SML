# Hidden checks for the "inventory_api" coding exercise. The agent never sees this file; it is run afterwards to decide
# whether the agent's inventory/ package really works. Two groups: the database layer (Store) and the request layer (handle).
import os
import tempfile
import unittest

from inventory.api import handle
from inventory.store import Store


class StoreTests(unittest.TestCase):
    """Checks for the Store class on its own (no web layer)."""

    def test_store(self):
        """Proves add/get/update/list/delete work, including duplicate names, missing items and stock never going below zero."""
        s = Store()
        # Ids count up from 1.
        self.assertEqual(s.add_item("pen", 10, 150), 1)
        self.assertEqual(s.add_item("cup", 2, 900), 2)
        # Same name again is refused.
        with self.assertRaises(ValueError):
            s.add_item("pen", 1, 1)
        self.assertEqual(s.get(1), {"id": 1, "name": "pen", "qty": 10, "price_cents": 150})
        self.assertIsNone(s.get(99))
        self.assertEqual(s.update_qty(1, -4)["qty"], 6)
        # Taking 3 from a stock of 2 fails and must leave the stock at 2 (checked on the next line).
        with self.assertRaises(ValueError):
            s.update_qty(2, -3)
        self.assertEqual(s.get(2)["qty"], 2)
        with self.assertRaises(KeyError):
            s.update_qty(42, 1)
        # Only "cup" (2) is below 5; "pen" has 6.
        self.assertEqual([i["name"] for i in s.list_items(low=5)], ["cup"])
        self.assertTrue(s.delete(2))
        self.assertFalse(s.delete(2))

    def test_file_persists(self):
        """Proves data written to a file database is still there when a new Store opens the same file."""
        path = os.path.join(tempfile.mkdtemp(), "inv.db")
        Store(path).add_item("bolt", 3, 5)
        self.assertEqual(Store(path).get(1)["name"], "bolt")


class ApiTests(unittest.TestCase):
    """Checks for handle(): status codes and data for each kind of request."""

    def setUp(self):
        """Runs before every test: gives each test a fresh empty in-memory Store."""
        self.s = Store()

    def test_create_and_read(self):
        """Proves POST creates (201), then GET by id, GET list and a missing id (404) behave."""
        status, item = handle(self.s, "POST", "/items", {"name": "pen", "qty": 3, "price_cents": 120})
        self.assertEqual((status, item["id"], item["qty"]), (201, 1, 3))
        self.assertEqual(handle(self.s, "GET", "/items/1"), (200, item))
        self.assertEqual(handle(self.s, "GET", "/items")[1], [item])
        self.assertEqual(handle(self.s, "GET", "/items/5")[0], 404)

    def test_errors(self):
        """Proves missing fields give 400, a duplicate name gives 409 with an error message, an unknown path gives 404."""
        self.assertEqual(handle(self.s, "POST", "/items", {"name": "x"})[0], 400)
        handle(self.s, "POST", "/items", {"name": "x", "qty": 1, "price_cents": 1})
        status, data = handle(self.s, "POST", "/items", {"name": "x", "qty": 1, "price_cents": 1})
        self.assertEqual(status, 409)
        self.assertIn("error", data)
        self.assertEqual(handle(self.s, "GET", "/nothing")[0], 404)

    def test_patch_low_delete(self):
        """Proves PATCH changes stock (and refuses too much or an unknown id), ?low= filters, and DELETE gives 204 then 404."""
        handle(self.s, "POST", "/items", {"name": "a", "qty": 10, "price_cents": 1})
        handle(self.s, "POST", "/items", {"name": "b", "qty": 1, "price_cents": 1})
        self.assertEqual(handle(self.s, "PATCH", "/items/1", {"delta": -7})[1]["qty"], 3)
        self.assertEqual(handle(self.s, "PATCH", "/items/2", {"delta": -2})[0], 400)
        self.assertEqual(handle(self.s, "PATCH", "/items/9", {"delta": 1})[0], 404)
        # After the patch, a has 3 and b has 1, so both are below 5.
        self.assertEqual([i["name"] for i in handle(self.s, "GET", "/items?low=5")[1]], ["a", "b"])
        self.assertEqual(handle(self.s, "DELETE", "/items/1"), (204, None))
        self.assertEqual(handle(self.s, "DELETE", "/items/1")[0], 404)


if __name__ == "__main__":
    unittest.main()
