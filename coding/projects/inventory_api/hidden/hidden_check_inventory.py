import os
import tempfile
import unittest

from inventory.api import handle
from inventory.store import Store


class StoreTests(unittest.TestCase):
    def test_store(self):
        s = Store()
        self.assertEqual(s.add_item("pen", 10, 150), 1)
        self.assertEqual(s.add_item("cup", 2, 900), 2)
        with self.assertRaises(ValueError):
            s.add_item("pen", 1, 1)
        self.assertEqual(s.get(1), {"id": 1, "name": "pen", "qty": 10, "price_cents": 150})
        self.assertIsNone(s.get(99))
        self.assertEqual(s.update_qty(1, -4)["qty"], 6)
        with self.assertRaises(ValueError):
            s.update_qty(2, -3)
        self.assertEqual(s.get(2)["qty"], 2)
        with self.assertRaises(KeyError):
            s.update_qty(42, 1)
        self.assertEqual([i["name"] for i in s.list_items(low=5)], ["cup"])
        self.assertTrue(s.delete(2))
        self.assertFalse(s.delete(2))

    def test_file_persists(self):
        path = os.path.join(tempfile.mkdtemp(), "inv.db")
        Store(path).add_item("bolt", 3, 5)
        self.assertEqual(Store(path).get(1)["name"], "bolt")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.s = Store()

    def test_create_and_read(self):
        status, item = handle(self.s, "POST", "/items", {"name": "pen", "qty": 3, "price_cents": 120})
        self.assertEqual((status, item["id"], item["qty"]), (201, 1, 3))
        self.assertEqual(handle(self.s, "GET", "/items/1"), (200, item))
        self.assertEqual(handle(self.s, "GET", "/items")[1], [item])
        self.assertEqual(handle(self.s, "GET", "/items/5")[0], 404)

    def test_errors(self):
        self.assertEqual(handle(self.s, "POST", "/items", {"name": "x"})[0], 400)
        handle(self.s, "POST", "/items", {"name": "x", "qty": 1, "price_cents": 1})
        status, data = handle(self.s, "POST", "/items", {"name": "x", "qty": 1, "price_cents": 1})
        self.assertEqual(status, 409)
        self.assertIn("error", data)
        self.assertEqual(handle(self.s, "GET", "/nothing")[0], 404)

    def test_patch_low_delete(self):
        handle(self.s, "POST", "/items", {"name": "a", "qty": 10, "price_cents": 1})
        handle(self.s, "POST", "/items", {"name": "b", "qty": 1, "price_cents": 1})
        self.assertEqual(handle(self.s, "PATCH", "/items/1", {"delta": -7})[1]["qty"], 3)
        self.assertEqual(handle(self.s, "PATCH", "/items/2", {"delta": -2})[0], 400)
        self.assertEqual(handle(self.s, "PATCH", "/items/9", {"delta": 1})[0], 404)
        self.assertEqual([i["name"] for i in handle(self.s, "GET", "/items?low=5")[1]], ["a", "b"])
        self.assertEqual(handle(self.s, "DELETE", "/items/1"), (204, None))
        self.assertEqual(handle(self.s, "DELETE", "/items/1")[0], 404)


if __name__ == "__main__":
    unittest.main()
