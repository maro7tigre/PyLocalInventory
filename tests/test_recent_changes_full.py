import sys
import os
import unittest
from unittest.mock import MagicMock, patch, call
from decimal import Decimal

# Add root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ui.dialogs.edit_dialogs.base_operation_dialog import BaseOperationDialog, SaveWorker, LoadWorker
from ui.widgets.operations_table import OperationsTableWidget
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from PySide6.QtCore import QTimer

app = QApplication.instance() or QApplication(sys.argv)

class DummyItem:
    def __init__(self, id, db):
        self.id = id
        self.section = "Sales_Items"
        self.db = db
        self.data = {}
    
    def get_value(self, key):
        return self.data.get(key)
        
    def set_value(self, key, val):
        self.data[key] = val

class DummyOperation:
    def __init__(self, id, db):
        self.id = id
        self.section = "Sales"
        self.database = db
        self.parameters = ["date", "state", "is_historical"]
        self.data = {"state": "pending", "is_historical": False}
        self.items = []

    def get_value(self, key):
        return self.data.get(key)
        
    def set_value(self, key, val):
        self.data[key] = val

    def get_visible_parameters(self, scope=None):
        return self.parameters
        
    def is_parameter_calculated(self, key):
        return False

    def load_database_data(self):
        self.data['loaded'] = True

class TestBaseOperationDialogAsync(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.db.sale_catalog = {
            "products": [{"id": 1, "name": "Prod A", "stock": 10}],
            "services": []
        }
        # Save/load error paths open MODAL QMessageBox dialogs that would
        # block forever in a headless test (no user to click). Auto-dismiss
        # every modal box so the async lifecycle - not the dialog UX - is
        # what these tests exercise.
        self.qmsg_patchers = [
            patch.object(QMessageBox, 'information', return_value=QMessageBox.Ok),
            patch.object(QMessageBox, 'critical', return_value=QMessageBox.Ok),
            patch.object(QMessageBox, 'warning', return_value=QMessageBox.Ok),
            patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes),
        ]
        for patcher in self.qmsg_patchers:
            patcher.start()

    def tearDown(self):
        for patcher in self.qmsg_patchers:
            patcher.stop()
        self.db.get_sale_catalog.return_value = self.db.sale_catalog

    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.QThread.start')
    @patch('core.database.Database')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog.setup_ui')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog.load_data')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog.apply_theme')
    def test_load_worker_success(self, mock_theme, mock_load, mock_setup, mock_db_class, mock_thread_start):
        mock_db_class.return_value.connect.return_value = True
        mock_db_class.return_value.get_sale_catalog.return_value = self.db.sale_catalog
        dialog = BaseOperationDialog(DummyOperation, DummyItem, operation_id=1, database=self.db)
        
        # Test worker (QThread.start is mocked so the worker only runs via the
        # explicit process() call below; the real thread would otherwise delete
        # the worker before we get here, racing this test).
        self.assertTrue(dialog.load_thread.isRunning() or not dialog.load_thread.isFinished())
        
        if dialog.load_worker:
            dialog.load_worker.process()
        
        lt = dialog.load_thread
        dialog._on_load_finished()
        if lt:
            lt.quit()
            lt.wait()
        
        self.assertTrue(dialog.operation_obj.data.get('loaded'))
        self.assertEqual(dialog.database.sale_catalog["products"][0]["name"], "Prod A")

    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.QThread.start')
    @patch('core.database.Database')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog.setup_ui')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog.load_data')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog.apply_theme')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.QMessageBox.warning')
    def test_load_worker_failure(self, mock_warn, mock_theme, mock_load, mock_setup, mock_db_class, mock_thread_start):
        mock_db_class.return_value.connect.return_value = True
        dialog = BaseOperationDialog(DummyOperation, DummyItem, operation_id=1, database=self.db)
        
        # Mock load_database_data to raise exception
        dialog.operation_obj.load_database_data = MagicMock(side_effect=Exception("Load error!"))
        
        # Force worker
        dialog.load_worker.process()
        
        # We manually call the connected slot because Qt signal dispatching in unittests across threads is tricky
        lt = dialog.load_thread
        dialog._on_load_error("Load error!")
        mock_warn.assert_called()
        if lt:
            lt.quit()
            lt.wait()

    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog.setup_ui')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog.load_data')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog.apply_theme')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog.validate_data', return_value=[])
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.QThread.start')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog._handle_missing_references', return_value=(True, False))
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog._confirm_sale_summary', return_value=True)
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.QMessageBox.information')
    def test_save_worker_success(self, mock_info, mock_confirm, mock_missing, mock_thread_start, mock_val, mock_theme, mock_load, mock_setup):
        dialog = BaseOperationDialog(DummyOperation, DummyItem, operation_id=1, database=self.db)
        dialog.items_table = MagicMock()
        dialog.items_table.get_items_data.return_value = []
        dialog.items_table.get_current_table_data.return_value = []
        dialog.parameter_widgets = {}
        dialog.save_btn = MagicMock()
        
        # Set up mock save
        dialog.database.save_sale_with_items = MagicMock(return_value={"sale_id": 1, "expected": 1, "saved": 1, "transaction": "committed"})
        
        # Trigger save
        dialog.save_changes()
        
        self.assertTrue(dialog._saving)
        dialog.save_btn.setEnabled.assert_called_with(False)
        
        # Process worker
        dialog.save_worker.process()
        
        st = dialog.save_thread
        dialog._on_save_finished({"sale_id": 1, "expected": 1, "saved": 1}, "updated")
        if st:
            st.quit()
            st.wait()
        
        self.assertFalse(dialog._saving)
        dialog.save_btn.setEnabled.assert_called_with(True)
        # Refs are cleared by _on_save_thread_finished (queued after the thread
        # stops), so simulate that delivery before asserting the cleanup.
        dialog._on_save_thread_finished()
        self.assertIsNone(dialog.save_worker)

class TestOperationsTableCatalog(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.db.sale_catalog = {
            "products": [
                {"id": 1, "name": "Apple", "stock": 50},
                {"id": 2, "name": "Banana", "stock": 10}
            ],
            "services": [
                {"id": 3, "name": "Delivery"}
            ]
        }
        
        self.table_widget = OperationsTableWidget(DummyItem, database=self.db)
        # Mock items_table inside dialog
        self.dialog = MagicMock()
        self.dialog.database = self.db
        self.dialog.operation_id = 1
        from ui.dialogs.edit_dialogs.base_operation_dialog import BaseOperationDialog
        self.dialog._normalize_name = BaseOperationDialog._normalize_name
        self.validate_stock = BaseOperationDialog._validate_stock.__get__(self.dialog, BaseOperationDialog)
        self.catalog_entity_exists = BaseOperationDialog._catalog_entity_exists.__get__(self.dialog, BaseOperationDialog)

    def test_catalog_entity_exists(self):
        # Uses in-memory catalog, no SQL calls!
        self.db.cursor.execute = MagicMock()
        
        self.assertTrue(self.catalog_entity_exists("product", "Apple"))
        self.assertTrue(self.catalog_entity_exists("service", "Delivery"))
        self.assertFalse(self.catalog_entity_exists("product", "Orange"))
        
        # Assert NO SQL calls were made
        self.db.cursor.execute.assert_not_called()
        
    def test_validate_stock(self):
        item1 = MagicMock()
        item1.get_value.side_effect = lambda k: 1 if k == 'product_id' else ("Apple" if k == 'product_name' else 60)
        
        item2 = MagicMock()
        item2.get_value.side_effect = lambda k: 2 if k == 'product_id' else ("Banana" if k == 'product_name' else 5)
        
        self.db.cursor.execute = MagicMock()
        
        errors = self.validate_stock([item1, item2])
        self.assertEqual(len(errors), 1)
        self.assertIn("Apple", errors[0])
        
        # Assert NO SQL calls were made (uses catalog)
        self.db.cursor.execute.assert_not_called()
        
    def test_table_widget_stock_state_no_db(self):
        from ui.widgets.operations_table import TableEventHandler
        self.table_widget.event_handler.get_row_stock_state = TableEventHandler.get_row_stock_state.__get__(self.table_widget.event_handler, TableEventHandler)
        
        self.db.cursor.execute = MagicMock()
        
        self.table_widget.data_manager.table_columns = ['product_name', 'quantity']
        self.table_widget.table.setColumnCount(2)
        from PySide6.QtWidgets import QLineEdit
        prod_edit = QLineEdit("Apple")
        prod_edit.setProperty("product_id", 1)
        
        qty_edit = QLineEdit("60")
        
        # Mock cellWidget to return these
        self.table_widget.table.cellWidget = MagicMock(side_effect=lambda r, c: prod_edit if c == 0 else (qty_edit if c == 1 else None))
        
        self.table_widget.table.setRowCount(1)
        from PySide6.QtWidgets import QTableWidgetItem
        self.table_widget.table.setItem(0, 1, QTableWidgetItem("60"))
        
        state = self.table_widget.event_handler.get_row_stock_state(0)
        self.assertIsNotNone(state)
        req, stock, exceeded, name = state
        self.assertEqual(req, Decimal("60"))
        self.assertEqual(stock, Decimal("50"))
        self.assertTrue(exceeded)
        
        self.db.cursor.execute.assert_not_called()

if __name__ == '__main__':
    unittest.main()
