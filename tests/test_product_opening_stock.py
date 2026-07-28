import unittest
from decimal import Decimal

from classes.product_class import ProductClass
from core.database import Database


class _Connection:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _Cursor:
    def __init__(self):
        self.calls = []
        self._row = None

    def execute(self, sql, params=()):
        normalized = " ".join(sql.lower().split())
        self.calls.append((normalized, params))
        if normalized.startswith("select 1 from products"):
            self._row = None
        elif normalized.startswith("insert into products"):
            self._row = (41,)
        elif normalized.startswith("insert into imports"):
            self._row = (73,)
        else:
            self._row = None

    def fetchone(self):
        return self._row


class ProductOpeningStockTests(unittest.TestCase):
    def test_product_and_opening_stock_are_committed_together(self):
        database = Database.__new__(Database)
        database.registered_classes = {"Products": ProductClass}
        database.cursor = _Cursor()
        database.conn = _Connection()

        result = database.save_product_with_opening_stock(
            {
                "name": "Real Product",
                "username": "RP-1",
                "unit_price": 7.5,
                "sale_price": 10,
                "category": "Tools",
                "description": "",
            },
            12,
        )

        self.assertEqual(result["product_id"], 41)
        self.assertEqual(result["opening_quantity"], "12")
        self.assertEqual(database.conn.commits, 1)
        self.assertEqual(database.conn.rollbacks, 0)

        import_item = next(
            params
            for sql, params in database.cursor.calls
            if sql.startswith("insert into import_items")
        )
        self.assertEqual(import_item[:4], (73, 41, "Real Product", Decimal("12")))
        self.assertEqual(import_item[4], Decimal("7.5"))


if __name__ == "__main__":
    unittest.main()
