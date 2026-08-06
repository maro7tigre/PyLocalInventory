with open("ui/dialogs/edit_dialogs/base_operation_dialog.py", "r", encoding="utf-8") as f:
    content = f.read()

insert_index = content.find("def _confirm_sale_summary(self):")

new_methods = """    def _on_save_finished(self, result, action):
        if hasattr(self, 'save_worker') and self.save_worker:
            self.save_worker.deleteLater()
            self.save_worker = None
        if hasattr(self, 'save_thread') and self.save_thread:
            self.save_thread.deleteLater()
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
            self.accept()
            self._refresh_related_tabs("Sales", "Products", "Clients")
            
        elif getattr(self.operation_obj, 'section', '') == 'Imports':
            self.operation_id = result["import_id"]
            self.operation_obj.id = result["import_id"]
            self.operation_obj.set_value("id", result["import_id"])
            QMessageBox.information(
                self,
                "Success",
                f"Import {action} successfully. {result.get('saved', 0)} items saved.\\n"
                f"Products created: {result.get('created_products', 0)}.",
            )
            self.accept()
            self._refresh_related_tabs("Imports", "Products")

    def _on_save_error(self, err_msg):
        if hasattr(self, 'save_worker') and self.save_worker:
            self.save_worker.deleteLater()
            self.save_worker = None
        if hasattr(self, 'save_thread') and self.save_thread:
            self.save_thread.deleteLater()
            self.save_thread = None

        self._saving = False
        if hasattr(self, 'save_btn') and self.save_btn:
            self.save_btn.setEnabled(True)
            self.save_btn.setText("Save")
        
        QMessageBox.critical(self, "Error", f"Failed to save operation: {err_msg}")

    """

content = content[:insert_index] + new_methods + content[insert_index:]

with open("ui/dialogs/edit_dialogs/base_operation_dialog.py", "w", encoding="utf-8") as f:
    f.write(content)
