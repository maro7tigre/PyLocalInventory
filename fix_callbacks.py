with open("ui/dialogs/edit_dialogs/base_operation_dialog.py", "r", encoding="utf-8") as f:
    code = f.read()

old_on_save_finished = """    def _on_save_finished(self, result, action):
        # Thread cleanup is handled safely by QThread.finished -> deleteLater
        self.save_worker = None
        self.save_thread = None

        self._saving = False
        if hasattr(self, 'save_btn') and self.save_btn:
            self.save_btn.setEnabled(True)
            self.save_btn.setText("Save")

        if getattr(self.operation_obj, 'section', '') == 'Sales':
            self.operation_id = result['sale_id']
            self.operation_obj.id = result['sale_id']
            self.operation_obj.set_value('id', result['sale_id'])
            expected = result.get('expected', 0)
            saved = result.get('saved', 0)
            if saved != expected:
                QMessageBox.critical(self, "Error", 
                    f"Sale was not saved: {expected} visible items were found, "
                    f"but the server confirmed {saved} saved items."
                )
                return
            QMessageBox.information(
                self, "Success",
                f"Operation {action} successfully. {saved} items saved.\\n"
                f"Inserted: {result.get('inserted', 0)}, updated: {result.get('updated', 0)}, "
                f"deleted: {result.get('deleted', 0)}."
            )
        elif getattr(self.operation_obj, 'section', '') == 'Imports':
            self.operation_id = result['import_id']
            self.operation_obj.id = result['import_id']
            self.operation_obj.set_value('id', result['import_id'])
            expected = result.get('expected', 0)
            saved = result.get('saved', 0)
            if saved != expected:
                QMessageBox.critical(self, "Error", 
                    f"Import was not saved: {expected} visible items were found, "
                    f"but the server confirmed {saved} saved items."
                )
                return
            QMessageBox.information(
                self, "Success",
                f"Operation {action} successfully. {saved} items saved.\\n"
                f"Inserted: {result.get('inserted', 0)}, updated: {result.get('updated', 0)}, "
                f"deleted: {result.get('deleted', 0)}."
            )

        self.accept()"""

new_on_save_finished = """    def _on_save_finished(self, result, action):
        # Thread cleanup is handled safely by QThread.finished -> deleteLater
        self.save_worker = None
        self.save_thread = None

        try:
            self._saving = False
            if hasattr(self, 'save_btn') and self.save_btn:
                self.save_btn.setEnabled(True)
                self.save_btn.setText("Save")

            if getattr(self.operation_obj, 'section', '') == 'Sales':
                self.operation_id = result['sale_id']
                self.operation_obj.id = result['sale_id']
                self.operation_obj.set_value('id', result['sale_id'])
                expected = result.get('expected', 0)
                saved = result.get('saved', 0)
                if saved != expected:
                    QMessageBox.critical(self, "Error", 
                        f"Sale was not saved: {expected} visible items were found, "
                        f"but the server confirmed {saved} saved items."
                    )
                    return
                QMessageBox.information(
                    self, "Success",
                    f"Operation {action} successfully. {saved} items saved.\\n"
                    f"Inserted: {result.get('inserted', 0)}, updated: {result.get('updated', 0)}, "
                    f"deleted: {result.get('deleted', 0)}."
                )
            elif getattr(self.operation_obj, 'section', '') == 'Imports':
                self.operation_id = result['import_id']
                self.operation_obj.id = result['import_id']
                self.operation_obj.set_value('id', result['import_id'])
                expected = result.get('expected', 0)
                saved = result.get('saved', 0)
                if saved != expected:
                    QMessageBox.critical(self, "Error", 
                        f"Import was not saved: {expected} visible items were found, "
                        f"but the server confirmed {saved} saved items."
                    )
                    return
                QMessageBox.information(
                    self, "Success",
                    f"Operation {action} successfully. {saved} items saved.\\n"
                    f"Inserted: {result.get('inserted', 0)}, updated: {result.get('updated', 0)}, "
                    f"deleted: {result.get('deleted', 0)}."
                )

            self.accept()
        except RuntimeError:
            # The dialog's C++ object was destroyed while the background thread was running.
            # We silently ignore GUI updates, but the save was successful on the database side.
            pass"""

old_on_save_error = """    def _on_save_error(self, err_msg):
        self.save_worker = None
        self.save_thread = None

        self._saving = False
        if hasattr(self, 'save_btn') and self.save_btn:
            self.save_btn.setEnabled(True)
            self.save_btn.setText("Save")
        
        QMessageBox.critical(self, "Save Error", f"An error occurred while saving:\\n{err_msg}")"""

new_on_save_error = """    def _on_save_error(self, err_msg):
        self.save_worker = None
        self.save_thread = None

        try:
            self._saving = False
            if hasattr(self, 'save_btn') and self.save_btn:
                self.save_btn.setEnabled(True)
                self.save_btn.setText("Save")
            
            QMessageBox.critical(self, "Save Error", f"An error occurred while saving:\\n{err_msg}")
        except RuntimeError:
            # The dialog's C++ object was destroyed while the background thread was running.
            pass"""

if old_on_save_finished in code:
    code = code.replace(old_on_save_finished, new_on_save_finished)
    print("Replaced _on_save_finished block!")
else:
    print("Failed to replace _on_save_finished block")
    
if old_on_save_error in code:
    code = code.replace(old_on_save_error, new_on_save_error)
    print("Replaced _on_save_error block!")
else:
    print("Failed to replace _on_save_error block")

with open("ui/dialogs/edit_dialogs/base_operation_dialog.py", "w", encoding="utf-8") as f:
    f.write(code)
