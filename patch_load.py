with open("ui/dialogs/edit_dialogs/base_operation_dialog.py", "r", encoding="utf-8") as f:
    code = f.read()

old_load_finished = """    def _on_load_finished(self):
        # Thread cleanup is handled safely by QThread.finished -> deleteLater
        self.load_worker = None
        self.load_thread = None

        self.setWindowTitle(self.windowTitle().replace(" (Loading...)", ""))
        
        # Now populate widgets on GUI thread
        self.load_data()
        self.items_table.refresh_table()
        
        self.setEnabled(True)"""

new_load_finished = """    def _on_load_finished(self):
        # Thread cleanup is handled safely by QThread.finished -> deleteLater
        self.load_worker = None
        self.load_thread = None

        try:
            self.setWindowTitle(self.windowTitle().replace(" (Loading...)", ""))
            
            # Now populate widgets on GUI thread
            self.load_data()
            self.items_table.refresh_table()
            
            self.setEnabled(True)
        except RuntimeError:
            pass"""

old_load_error = """    def _on_load_error(self, err_msg):
        self.load_worker = None
        self.load_thread = None

        QMessageBox.critical(self, "Error", f"Failed to load database: {err_msg}")
        self.reject()"""

new_load_error = """    def _on_load_error(self, err_msg):
        self.load_worker = None
        self.load_thread = None

        try:
            QMessageBox.critical(self, "Error", f"Failed to load database: {err_msg}")
            self.reject()
        except RuntimeError:
            pass"""

if old_load_finished in code:
    code = code.replace(old_load_finished, new_load_finished)
    print("Replaced _on_load_finished block!")
else:
    print("Failed to replace _on_load_finished block")
    
if old_load_error in code:
    code = code.replace(old_load_error, new_load_error)
    print("Replaced _on_load_error block!")
else:
    print("Failed to replace _on_load_error block")

with open("ui/dialogs/edit_dialogs/base_operation_dialog.py", "w", encoding="utf-8") as f:
    f.write(code)
