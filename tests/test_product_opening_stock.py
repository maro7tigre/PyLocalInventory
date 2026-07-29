import unittest
import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from classes.product_class import ProductClass
from core.database import Database
from ui.dialogs.edit_dialogs.product_dialog import ProductEditDialog


class _Connection:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _Cursor:
    def __init__(self, imported=Decimal("100"), sold=Decimal("0")):
        self.calls = []
        self._row = None
        self.rowcount = 1
        self.imported = imported
        self.sold = sold

    def execute(self, sql, params=()):
        normalized = " ".join(sql.lower().split())
        self.calls.append((normalized, params))
        if normalized.startswith("select 1 from products"):
            self._row = None
        elif normalized.startswith("select id from products") and normalized.endswith("for update"):
            self._row = (int(params[0]),)
        elif normalized.startswith("select coalesce(sum(quantity), 0) from import_items"):
            self._row = (self.imported,)
        elif normalized.startswith("select coalesce(sum(si.quantity), 0)"):
            self._row = (self.sold,)
        elif normalized.startswith("insert into products"):
            self._row = (41,)
        elif normalized.startswith("insert into imports"):
            self._row = (73,)
        else:
            self._row = None

    def fetchone(self):
        return self._row


class ProductOpeningStockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

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

    def test_product_edit_records_only_the_stock_difference(self):
        database = Database.__new__(Database)
        database.registered_classes = {"Products": ProductClass}
        database.cursor = _Cursor(imported=Decimal("100"), sold=Decimal("20"))
        database.conn = _Connection()

        result = database.update_product_with_stock(
            41,
            {
                "name": "Real Product",
                "username": "RP-1",
                "unit_price": 7.5,
                "sale_price": 10,
                "stock_alert": 10,
            },
            76,
        )

        self.assertEqual(result["previous_quantity"], "80")
        self.assertEqual(result["quantity"], "76")
        self.assertEqual(result["adjustment"], "-4")
        adjustment = next(
            params for sql, params in database.cursor.calls
            if sql.startswith("insert into import_items")
        )
        self.assertEqual(adjustment[3], Decimal("-4"))
        self.assertEqual(database.conn.commits, 1)
        self.assertEqual(database.conn.rollbacks, 0)

    def test_unchanged_quantity_does_not_duplicate_stock_records(self):
        database = Database.__new__(Database)
        database.registered_classes = {"Products": ProductClass}
        database.cursor = _Cursor(imported=Decimal("100"), sold=Decimal("20"))
        database.conn = _Connection()

        result = database.update_product_with_stock(
            41,
            {"name": "Real Product", "username": "RP-1"},
            80,
        )

        self.assertEqual(result["adjustment"], "0")
        self.assertFalse(any(
            sql.startswith("insert into import_items")
            for sql, _params in database.cursor.calls
        ))

    def test_create_and_edit_forms_put_quantity_before_stock_alert(self):
        new_dialog = ProductEditDialog(None, None)
        new_keys = list(new_dialog.parameter_widgets)
        self.assertEqual(
            new_keys[new_keys.index("quantity") + 1], "stock_alert"
        )
        self.assertEqual(
            new_dialog.product.get_display_name("quantity"), "Initial Quantity"
        )
        self.assertEqual(new_dialog.parameter_widgets["quantity"].value(), 0)
        quantity_widget = new_dialog.parameter_widgets["quantity"]
        quantity_widget.setValue(6)
        self.assertEqual(quantity_widget.spinbox.text(), "6")
        quantity_widget.setValue(6.25)
        self.assertEqual(quantity_widget.spinbox.text(), "6.25")
        new_dialog.close()


if __name__ == "__main__":
    unittest.main()
