import sys

with open('ui/dialogs/client_details_dialog.py', 'a', encoding='utf-8') as f:
    f.write("""
    def _print_selected_sale(self):
        row = self.purchases_table.currentRow()
        if row < 0 or row >= len(self.purchases):
            QMessageBox.information(self, "Select Sale", "Please select a sale to print.")
            return
            
        purchase = self.purchases[row]
        sale_id = purchase["sale_id"]
        
        self.print_selected_btn.setEnabled(False)
        self.print_selected_btn.setText("Generating...")
        self._start_report_worker('selected_sale', sale_id)
        
    def _print_full_statement(self):
        self.print_statement_btn.setEnabled(False)
        self.print_statement_btn.setText("Generating...")
        self._start_report_worker('full_statement')
        
    def _start_report_worker(self, report_type, sale_id=None):
        thread = QThread()
        client_data = {
            'id': self.client_obj.get_value('id'),
            'name': self.client_obj.get_value('name'),
            'username': self.client_obj.get_value('username'),
            'ice': self.client_obj.get_value('ice'),
            'phone': self.client_obj.get_value('phone')
        }
        
        worker = _ClientReportWorker(report_type, client_data, list(self.purchases), list(self.account_data.get('payments', [])), sale_id)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(thread.quit)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        
        worker.finished.connect(self._on_report_finished)
        worker.failed.connect(self._on_report_failed)
        
        self._report_thread = thread
        self._report_worker = worker
        thread.start()
        
    @Slot(str)
    def _on_report_finished(self, pdf_path):
        self._report_thread = None
        self._report_worker = None
        self.print_selected_btn.setText("Print Selected Sale")
        self.print_statement_btn.setText("Print Full Client Statement")
        self.print_statement_btn.setEnabled(True)
        if self.purchases_table.currentRow() >= 0:
            self.print_selected_btn.setEnabled(True)
            
        QMessageBox.information(self, "Success", f"Report generated successfully!\\n\\nSaved to: {pdf_path}")
        
        try:
            import os
            import sys
            import subprocess
            if os.name == 'nt':
                os.startfile(pdf_path)
            elif os.name == 'posix':
                subprocess.call(['open' if sys.platform == 'darwin' else 'xdg-open', pdf_path])
        except Exception as error:
            logger.exception("Generated report could not be opened path=%s", pdf_path)
            QMessageBox.warning(self, "Warning", f"Report generated but failed to open:\\n{error}")

    @Slot(str)
    def _on_report_failed(self, error):
        self._report_thread = None
        self._report_worker = None
        self.print_selected_btn.setText("Print Selected Sale")
        self.print_statement_btn.setText("Print Full Client Statement")
        self.print_statement_btn.setEnabled(True)
        if self.purchases_table.currentRow() >= 0:
            self.print_selected_btn.setEnabled(True)
            
        QMessageBox.critical(self, "Error", f"Failed to generate report:\\n{error}")
""")
