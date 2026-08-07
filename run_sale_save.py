import sys
import time
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow
from ui.dialogs.edit_dialogs.base_operation_dialog import BaseOperationDialog
from classes.sales_class import SalesClass
from classes.sales_item_class import SalesItemClass
from core.database import Database

def run_test():
    app = QApplication.instance() or QApplication(sys.argv)
    
    # Needs a real DB connection according to the config
    db = Database()
    if not db.connect():
        print("Could not connect to DB")
        return
        
    print("DB Connected. Creating Dialog...")
    dialog = BaseOperationDialog(SalesClass, SalesItemClass, database=db)
    
    # Mock validation and confirmation to force it to go to SaveWorker
    dialog.validate_data = lambda: []
    dialog._confirm_sale_summary = lambda: True
    
    # Provide a minimal valid item
    class MockTable:
        def get_current_table_data(self):
            return [{"quantity": 1, "unit_price": 100, "product_id": 1, "item_type": "product"}]
        def get_items_data(self):
            return []
    dialog.items_table = MockTable()
    
    print("Calling save_changes()...")
    dialog.save_changes()
    
    print("save_changes() returned. Spinning event loop...")
    
    # Spin the event loop for 4 seconds to let the DiagnosticDumper run
    end = time.time() + 4.0
    while time.time() < end:
        QApplication.processEvents()
        time.sleep(0.01)
        
    print("Test complete.")

if __name__ == "__main__":
    run_test()
