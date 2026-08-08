import faulthandler
faulthandler.enable()
import sys
import time
from PySide6.QtWidgets import QApplication
from ui.dialogs.client_details_dialog import ClientDetailsDialog

class DummyDB:
    def get_client_account(self, client_id):
        return {"purchases": [[1, "2026-08-01", "completed", 1, "Prod A", 2, 10.0, 0.0, 0.0, "Info", 1, "Sale Info", "", "User"]], "payments": []}
    def has_permission(self, *args): return True

class DummyClient:
    id = 1
    def get_value(self, key): return "Test"

app = QApplication(sys.argv)
# mock the database connection if needed, but DummyDB doesn't have cursor
# Oh wait, ClientDetailsDialog._ensure_payments_table uses self.database.cursor
class DummyCursor:
    def execute(self, *args): pass
    def fetchall(self): return []
    def commit(self): pass
class DummyDBWithCursor(DummyDB):
    def __init__(self):
        self.cursor = DummyCursor()

dialog = ClientDetailsDialog(DummyClient(), DummyDBWithCursor())
dialog.purchases = dialog._compute_purchases(DummyDB().get_client_account(1))
dialog.account_data = {"purchases": [], "payments": []}
dialog.purchases_table.setRowCount(1)
dialog.purchases_table.selectRow(0)

print("Triggering report...")
dialog._print_selected_sale()

def check_thread():
    if not dialog._report_thread or not dialog._report_thread.isRunning():
        print("Thread finished.")
        app.quit()
        
timer = app.startTimer(500)
dialog.timerEvent = lambda e: check_thread()
app.exec()
