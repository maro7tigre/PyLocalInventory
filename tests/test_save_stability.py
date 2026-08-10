import unittest
from unittest.mock import MagicMock, patch
import time
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from PySide6.QtCore import QTimer

# Ensure QApplication exists
if not QApplication.instance():
    _app = QApplication([])

from ui.dialogs.edit_dialogs.base_operation_dialog import BaseOperationDialog, SaveWorker, LoadWorker

class MockDatabase:
    def __init__(self, *args, **kwargs):
        self.profile_manager = MagicMock()
        self.conn = MagicMock()
        self.language = 'en'
        self.registered_classes = {}
        self.last_error = None
        self.save_count = 0

    def connect(self):
        return True
        
    def close(self):
        pass

    def save_sale_with_items(self, **kwargs):
        self.save_count += 1
        time.sleep(0.05) # Simulate DB latency
        return {'transaction': 'committed', 'sale_id': 999, 'expected': len(kwargs.get('items', [])), 'saved': len(kwargs.get('items', []))}
        
    def save_import_with_items(self, **kwargs):
        self.save_count += 1
        time.sleep(0.05)
        return {'transaction': 'committed', 'import_id': 888, 'expected': len(kwargs.get('items', [])), 'saved': len(kwargs.get('items', []))}

class TestSaveStability(unittest.TestCase):
    def setUp(self):
        self.db = MockDatabase()
        # Patch Database so worker local connections return our mock
        self.patcher = patch('core.database.Database', return_value=self.db)
        self.mock_db_class = self.patcher.start()
        # The save worker's success path opens a MODAL QMessageBox.information
        # that would block forever in a headless test (no user to click OK).
        # Auto-dismiss every modal box so the thread-lifecycle logic - not the
        # dialog UX - is what this stress test exercises.
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
        self.patcher.stop()

    def test_duplicate_save_protection(self):
        """D. Duplicate Save - simulate 10 rapid Save calls"""
        dialog = BaseOperationDialog(MagicMock(), MagicMock(), None, self.db)
        dialog.operation_obj = MagicMock()
        dialog.operation_obj.section = "Sales"
        dialog.operation_obj.get_value.return_value = "Test"
        dialog.operation_obj.get_visible_parameters.return_value = ["state"]
        dialog.operation_obj.is_parameter_calculated.return_value = False
        
        dialog._handle_missing_references = MagicMock(return_value=(True, False))
        dialog.validate_data = MagicMock(return_value=[])
        dialog._validate_stock = MagicMock(return_value=[])
        dialog._confirm_sale_summary = MagicMock(return_value=True)
        dialog.items_table = MagicMock()
        dialog.items_table.get_current_table_data.return_value = [{'product_id': 1, 'quantity': 1, 'unit_price': 100}]
        
        # Simulate 10 rapid clicks
        for _ in range(10):
            dialog.save_changes()
            
        # Verify exactly one thread was started
        self.assertTrue(getattr(dialog, '_saving', False))
        self.assertIsNotNone(dialog.save_thread)
        
        # Wait for thread to finish
        while dialog.save_thread and dialog.save_thread.isRunning():
            QApplication.processEvents()
            time.sleep(0.01)
            
        # Exactly one call should be made to the mock DB (recorded on the local db instance)
        self.assertEqual(self.db.save_count, 1)

    def test_close_during_save(self):
        """F. Dialog close while saving - no use-after-delete"""
        dialog = BaseOperationDialog(MagicMock(), MagicMock(), None, self.db)
        dialog.operation_obj = MagicMock()
        dialog.operation_obj.section = "Sales"
        dialog.operation_obj.get_value.return_value = "Test"
        dialog.operation_obj.get_visible_parameters.return_value = ["state"]
        dialog.operation_obj.is_parameter_calculated.return_value = False
        
        dialog._handle_missing_references = MagicMock(return_value=(True, False))
        dialog.validate_data = MagicMock(return_value=[])
        dialog._validate_stock = MagicMock(return_value=[])
        dialog._confirm_sale_summary = MagicMock(return_value=True)
        dialog.items_table = MagicMock()
        dialog.items_table.get_current_table_data.return_value = [{'product_id': 1, 'quantity': 1, 'unit_price': 100}]
        
        # Start save
        dialog.save_changes()
        
        # Destroy dialog immediately
        dialog.deleteLater()
        QApplication.processEvents() # Let deletion happen
        
        # Wait for thread to finish - the try/except RuntimeError in callbacks should catch the destroyed widget access
        # We need to manually poll active threads or just wait a bit because dialog is dead and we lost its reference
        time.sleep(0.2)
        QApplication.processEvents()
        
        self.assertEqual(self.db.save_count, 1)

    def test_100_cycle_stress(self):
        """13. Stress Test the Save Lifecycle"""
        for i in range(100):
            dialog = BaseOperationDialog(MagicMock(), MagicMock(), None, self.db)
            dialog.operation_obj = MagicMock()
            dialog.operation_obj.section = "Sales"
            dialog.operation_obj.get_value.return_value = "Test"
            dialog.operation_obj.get_visible_parameters.return_value = ["state"]
            dialog.operation_obj.is_parameter_calculated.return_value = False
            
            dialog._handle_missing_references = MagicMock(return_value=(True, False))
            dialog.validate_data = MagicMock(return_value=[])
            dialog._validate_stock = MagicMock(return_value=[])
            dialog._confirm_sale_summary = MagicMock(return_value=True)
            dialog.items_table = MagicMock()
            dialog.items_table.get_current_table_data.return_value = [{'product_id': 1, 'quantity': 1, 'unit_price': 100}]
            
            # Start save
            dialog.save_changes()
            
            # Wait for thread to finish
            while dialog.save_thread and dialog.save_thread.isRunning():
                QApplication.processEvents()
                time.sleep(0.005)
                
            QApplication.processEvents()
            
        self.assertEqual(self.db.save_count, 100)
        print("100 cycles completed successfully without crashes!")

if __name__ == '__main__':
    unittest.main()
