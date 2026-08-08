import faulthandler
faulthandler.enable()

import sys
from PySide6.QtWidgets import QApplication
from ui.dialogs.client_details_dialog import ClientDetailsDialog

# Dummy Database
class DummyDB:
    def get_client_account(self, client_id):
        return {
            "purchases": [[1, "01-01-2026", "completed", 1, "Prod A", 2, 10.0, 0.0, 0.0, "Info", 1, "Sale Info", "", "User"]],
            "payments": []
        }
    def has_permission(self, *args): return True

class DummyClient:
    id = 1
    def get_value(self, key): return "Test"

app = QApplication(sys.argv)
dialog = ClientDetailsDialog(DummyClient(), DummyDB())
# mock the table so we can click
dialog.purchases_table.setRowCount(1)
dialog.purchases_table.selectRow(0)
# Trigger print
dialog.purchases = dialog._compute_purchases(DummyDB().get_client_account(1))
dialog._print_selected_sale()

# We don't want to run the full event loop forever, but we need it to process the thread
import time
def wait_for_thread():
    if dialog._report_thread and dialog._report_thread.isRunning():
        return
    app.quit()

timer = app.startTimer(100)
app.exec()
