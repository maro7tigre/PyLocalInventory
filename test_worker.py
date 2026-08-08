import faulthandler
faulthandler.enable()
import sys
from PySide6.QtWidgets import QApplication
from ui.dialogs.client_details_dialog import _ClientReportWorker

app = QApplication(sys.argv)

client_data = {'id': 1, 'name': 'test', 'username': 'test', 'ice': '', 'phone': ''}
purchases = []
payments = []

worker = _ClientReportWorker('selected_sale', client_data, purchases, payments, 1)

def on_finished(path):
    print("Finished:", path)
    app.quit()

def on_failed(err):
    print("Failed:", err)
    app.quit()

worker.finished.connect(on_finished)
worker.failed.connect(on_failed)

print("Running worker...")
worker.run()
