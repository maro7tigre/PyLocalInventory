import sys
import os
import faulthandler

faulthandler.enable(open("crash.log", "w"))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from ui.main_window import MainWindow

app = QApplication(sys.argv)
window = MainWindow()
window.show()

def auto_click():
    try:
        window.tab_widget.setCurrentIndex(2)
        clients_tab = window.tabs['Clients']
        if clients_tab.table.rowCount() == 0:
            print("No clients found!")
            app.quit()
            return
        clients_tab.table.selectRow(0)
        
        # Override the exec of the dialog so it doesn't block the timer thread
        from ui.dialogs.client_details_dialog import ClientDetailsDialog
        original_exec = ClientDetailsDialog.exec
        def fake_exec(self):
            print("Dialog opened!")
            self.show()
            self.purchases_table.selectRow(0)
            self._print_selected_sale()
        ClientDetailsDialog.exec = fake_exec
        
        clients_tab._view_client()
    except Exception as e:
        print("Error in auto_click:", e)
        app.quit()

QTimer.singleShot(1000, auto_click)

def close_app():
    app.quit()
    
QTimer.singleShot(10000, close_app)

sys.exit(app.exec())
