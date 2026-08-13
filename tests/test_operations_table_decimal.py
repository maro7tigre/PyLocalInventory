import os
import unittest
from unittest.mock import MagicMock
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem

from ui.widgets.operations_table import TableEventHandler
from core.calculations import InputState

class DummyDataManager:
    def __init__(self):
        self.table_columns = ['quantity', 'unit_price', 'subtotal', 'product_name']

class DummyTableEventHandler(TableEventHandler):
    def __init__(self, table):
        self.table = table
        self.data_manager = DummyDataManager()
        self._updating = False
        self.items_changed_callback = MagicMock()
        
    def _validate_stock(self, row):
        pass

class TestOperationsTableDecimal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.table = QTableWidget(1, 4)
        self.handler = DummyTableEventHandler(self.table)
        
        # Populate table cells
        for col in range(4):
            self.table.setItem(0, col, QTableWidgetItem(""))

    def test_update_row_subtotal_valid(self):
        self.table.item(0, 0).setText("2")
        self.table.item(0, 1).setText("12.50")
        
        self.handler._update_row_subtotal(0)
        self.assertEqual(self.table.item(0, 2).text(), "25.00")

    def test_update_row_subtotal_intermediate_preserves_subtotal(self):
        # Set a valid subtotal first
        self.table.item(0, 0).setText("2")
        self.table.item(0, 1).setText("12.50")
        self.handler._update_row_subtotal(0)
        self.assertEqual(self.table.item(0, 2).text(), "25.00")

        # Now type something intermediate in quantity
        self.table.item(0, 0).setText("2.")
        self.handler._update_row_subtotal(0)
        
        # Subtotal should NOT be overwritten (it should remain 25.00)
        self.assertEqual(self.table.item(0, 2).text(), "25.00")

    def test_update_row_subtotal_invalid_preserves_subtotal(self):
        self.table.item(0, 0).setText("2")
        self.table.item(0, 1).setText("12.50")
        self.handler._update_row_subtotal(0)
        self.assertEqual(self.table.item(0, 2).text(), "25.00")

        # Now type something malformed
        self.table.item(0, 0).setText("abc")
        self.handler._update_row_subtotal(0)
        self.assertEqual(self.table.item(0, 2).text(), "25.00")

    def test_update_row_subtotal_empty_preserves_subtotal(self):
        self.table.item(0, 0).setText("2")
        self.table.item(0, 1).setText("12.50")
        self.handler._update_row_subtotal(0)
        self.assertEqual(self.table.item(0, 2).text(), "25.00")

        # Clear quantity
        self.table.item(0, 0).setText("")
        self.handler._update_row_subtotal(0)
        self.assertEqual(self.table.item(0, 2).text(), "25.00")

    def test_apply_subtotal_override_valid(self):
        self.table.item(0, 0).setText("2")
        self.table.item(0, 1).setText("")
        self.table.item(0, 2).setText("25.00")
        
        self.handler._apply_subtotal_override(0)
        self.assertEqual(
            Decimal(self.table.item(0, 1).text()),
            Decimal("12.5")
        )
        self.assertEqual(self.table.item(0, 2).text(), "25.00")

    def test_apply_subtotal_override_intermediate(self):
        self.table.item(0, 0).setText("2")
        self.table.item(0, 1).setText("10.00")
        
        # Type something intermediate in subtotal
        self.table.item(0, 2).setText("25.")
        self.handler._apply_subtotal_override(0)
        
        # Unit price should NOT be overwritten
        self.assertEqual(self.table.item(0, 1).text(), "10.00")

    def test_apply_subtotal_override_empty(self):
        self.table.item(0, 0).setText("2")
        self.table.item(0, 1).setText("10.00")
        self.table.item(0, 2).setText("")
        self.handler._apply_subtotal_override(0)
        self.assertEqual(self.table.item(0, 1).text(), "10.00")

    def test_item_changed_defers_empty_row_removal(self):
        empty_row_manager = MagicMock()
        empty_row_manager._is_row_empty.return_value = False
        callback = MagicMock()
        handler = TableEventHandler(
            self.table, DummyDataManager(), empty_row_manager, callback
        )
        handler._update_row_subtotal = MagicMock()
        handler._validate_stock = MagicMock()

        handler._on_item_changed(self.table.item(0, 0))

        empty_row_manager.ensure_single_empty_row.assert_not_called()
        self.app.processEvents()
        empty_row_manager.ensure_single_empty_row.assert_called_once_with()

if __name__ == "__main__":
    unittest.main()
