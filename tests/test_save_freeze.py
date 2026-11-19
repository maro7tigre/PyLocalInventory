import sys
import os
sys.path.insert(0, os.path.abspath('.'))

import time
import unittest
from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtCore import QTimer

# Ensure QApplication exists
if not QApplication.instance():
    _app = QApplication([])

from ui.dialogs.edit_dialogs.base_operation_dialog import BaseOperationDialog
from classes.sales_class import SalesClass
from classes.sales_item_class import SalesItemClass
from unittest.mock import MagicMock, patch

class TestSaveFreeze(unittest.TestCase):
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.QMessageBox')
    def test_save_is_async(self, mock_msgbox):
        """Simulate a slow persistence call and verify GUI is responsive."""
        db_mock = MagicMock()
        db_mock.language = 'en'
        db_mock.registered_classes = []
        db_mock.sale_catalog = {"products": []}
        del db_mock.profile_manager
        
        # We will mock the database save to take 2 seconds
        def fake_save(*args, **kwargs):
            time.sleep(2)
            return {"transaction": "committed", "sale_id": 999, "expected": 1, "saved": 1}
            
        db_mock.save_sale_with_items.side_effect = fake_save
        # Make it remote so it uses standard save pattern
        db_mock.__class__.__name__ = 'RemoteDatabase'
        
        dialog = BaseOperationDialog(SalesClass, SalesItemClass, database=db_mock)
        dialog.items_table = MagicMock()
        dialog.items_table.get_current_table_data.return_value = [{"quantity": 1, "unit_price": 100}]
        dialog.items_table.get_items_data.return_value = []
        dialog.validate_data = MagicMock(return_value=[])
        dialog._confirm_sale_summary = MagicMock(return_value=True)
        dialog._handle_missing_references = MagicMock(return_value=(True, True))
        dialog.save_btn = QPushButton()
        
        # Timer to prove event loop runs
        self.timer_ticks = 0
        def on_tick():
            self.timer_ticks += 1
            
        timer = QTimer()
        timer.timeout.connect(on_tick)
        timer.start(50)
        
        # Start save
        start_time = time.time()
        dialog.save_changes()
        
        # If save_changes() blocked, time.time() - start_time would be >= 2
        # If it's truly async, it should return instantly.
        duration = time.time() - start_time
        self.assertLess(duration, 0.5, "save_changes() took too long; it blocked the GUI thread!")
        
        self.assertTrue(dialog._saving, "Dialog should be marked as saving")
        self.assertFalse(dialog.save_btn.isEnabled(), "Save button should be disabled")
        self.assertEqual(dialog.save_btn.text(), "Saving...", "Save button text should update")
        self.assertIsNotNone(dialog.save_thread, "SaveWorker thread should exist")
        
        # Spin event loop for 0.5 second to let worker start and run
        end = time.time() + 0.5
        while time.time() < end:
            QApplication.processEvents()
            time.sleep(0.01)
            
        # Has the timer ticked? If event loop blocked, ticks would be 0
        self.assertGreater(self.timer_ticks, 0, "GUI Event loop froze during save! Timer didn't tick.")
        print(f"Success! Event loop is running. Timer ticks after 0.5 sec: {self.timer_ticks}")
        
        # Wait for completion (up to 3 seconds)
        end = time.time() + 3.0
        while time.time() < end and dialog._saving:
            QApplication.processEvents()
            time.sleep(0.01)
            
        self.assertFalse(dialog._saving, "Dialog should finish saving")
        print("Save completed asynchronously successfully.")

if __name__ == '__main__':
    unittest.main()
