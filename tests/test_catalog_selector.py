import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from classes.sales_item_class import SalesItemClass
from ui.widgets.operations_table import OperationsTableWidget


class _CatalogCursor:
    def __init__(self):
        self.row = None
        self.queries = []

    def execute(self, sql, params=()):
        normalized = " ".join(sql.lower().split())
        self.queries.append((normalized, params))
        if "from products" in normalized:
            self.row = (11, "Shared Name", 18)
        elif "from services" in normalized:
            self.row = (22, "Shared Name", 35)
        else:
            self.row = None

    def fetchone(self):
        return self.row


class _Database:
    def __init__(self):
        self.cursor = _CatalogCursor()


class CatalogSelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_explicit_service_keeps_service_id_and_price_and_skips_stock(self):
        database = _Database()
        widget = OperationsTableWidget(
            SalesItemClass,
            database=database,
            columns=[
                "item_type", "product_name", "quantity", "unit_price",
                "subtotal", "delete_action",
            ],
            highlight_stock_exceed=True,
        )
        type_col = widget.data_manager.table_columns.index("item_type")
        name_col = widget.data_manager.table_columns.index("product_name")
        price_col = widget.data_manager.table_columns.index("unit_price")
        selector = widget.table.cellWidget(0, type_col)
        name = widget.table.cellWidget(0, name_col)
        selector.setCurrentIndex(selector.findData("service"))
        name.setText("Shared Name")

        widget.event_handler._handle_product_selection(0, "Shared Name")
        row = widget.data_manager.extract_row_data(widget.table, 0)

        self.assertEqual(row["item_type"], "service")
        self.assertEqual(row["service_id"], 22)
        self.assertNotIn("product_id", row)
        self.assertEqual(widget.table.item(0, price_col).text(), "35")
        self.assertIsNone(widget.event_handler.get_row_stock_state(0))
        widget.close()


if __name__ == "__main__":
    unittest.main()
