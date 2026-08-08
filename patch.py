import sys

with open("ui/dialogs/client_details_dialog.py", "r", encoding="utf-8") as f:
    content = f.read()

# Fix 1: QThread lifetime crash fix
thread_cleanup = """        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(thread.quit)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        
        # FIX: Ensure thread is only cleared when finished
        thread.finished.connect(lambda t=thread: self._on_report_thread_finished(t))
        
        worker.finished.connect(self._on_report_finished)
        worker.failed.connect(self._on_report_failed)
        
        self._report_thread = thread
        self._report_worker = worker
        thread.start()
        
    def _on_report_thread_finished(self, thread):
        if getattr(self, "_report_thread", None) is thread:
            self._report_thread = None
            self._report_worker = None
"""

content = content.replace("""        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(thread.quit)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        
        worker.finished.connect(self._on_report_finished)
        worker.failed.connect(self._on_report_failed)
        
        self._report_thread = thread
        self._report_worker = worker
        thread.start()""", thread_cleanup)

# Remove thread cleanup from _on_report_finished
finished_method_old = """    @Slot(str)
    def _on_report_finished(self, pdf_path):
        self._report_thread = None
        self._report_worker = None
        self.print_selected_btn.setText("Print Selected Sale")"""
finished_method_new = """    @Slot(str)
    def _on_report_finished(self, pdf_path):
        self.print_selected_btn.setText("Print Selected Sale")"""
content = content.replace(finished_method_old, finished_method_new)

# Remove thread cleanup from _on_report_failed
failed_method_old = """    @Slot(str)
    def _on_report_failed(self, error):
        self._report_thread = None
        self._report_worker = None
        self.print_selected_btn.setText("Print Selected Sale")"""
failed_method_new = """    @Slot(str)
    def _on_report_failed(self, error):
        self.print_selected_btn.setText("Print Selected Sale")"""
content = content.replace(failed_method_old, failed_method_new)

# Fix 2: Template variables space fix
temp_fix_old = """        for k, v in data.items():
            template = template.replace(f"{{{{{k}}}}}", str(v))"""
temp_fix_new = """        for k, v in data.items():
            template = template.replace(f"{{{{ {k} }}}}", str(v))"""
content = content.replace(temp_fix_old, temp_fix_new)

# Fix 3: qty -> quantity and item_info
qty_old = """            sale_subtotal = 0.0
            for item in sale_data['items']:
                st = float(item['total'])
                sale_subtotal += st
                items_html += f"<tr><td>{item['item_type'].title()}</td><td>{html.escape(item['product'])}</td><td>{item['qty']}</td><td>{self._fmt_money(item['unit_price'])}</td><td>{self._fmt_money(st)}</td></tr>"
"""
qty_new = """            sale_subtotal = 0.0
            for item in sale_data['items']:
                st = float(item['total'])
                sale_subtotal += st
                product_desc = html.escape(item['product'] or '')
                if item.get('item_info'):
                    product_desc += f"<br><small>{html.escape(item['item_info'])}</small>"
                items_html += f"<tr><td>{item['item_type'].title()}</td><td>{product_desc}</td><td>{item['quantity']}</td><td>{self._fmt_money(item['unit_price'])}</td><td>{self._fmt_money(st)}</td></tr>"
"""
content = content.replace(qty_old, qty_new)

# Fix 4: Table layouts
purchases_table_old = """        self.purchases_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.purchases_table.setColumnWidth(0, 80)
        self.purchases_table.setColumnWidth(1, 100)
        self.purchases_table.setColumnWidth(3, 80)
        self.purchases_table.setColumnWidth(4, 100)
        self.purchases_table.setColumnWidth(5, 100)
        self.purchases_table.setColumnWidth(6, 100)
        self.purchases_table.setColumnWidth(7, 100)
        self.purchases_table.setColumnWidth(8, 100)"""

purchases_table_new = """        p_header = self.purchases_table.horizontalHeader()
        p_header.setSectionResizeMode(2, QHeaderView.Stretch)
        for col in [0, 1, 3, 4, 5, 6, 7, 8]:
            p_header.setSectionResizeMode(col, QHeaderView.ResizeToContents)"""
content = content.replace(purchases_table_old, purchases_table_new)

payments_table_old = """        self.payments_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.payments_table.setColumnWidth(0, 80)
        self.payments_table.setColumnWidth(1, 80)
        self.payments_table.setColumnWidth(2, 120)
        self.payments_table.setColumnWidth(3, 120)"""
payments_table_new = """        pay_header = self.payments_table.horizontalHeader()
        pay_header.setSectionResizeMode(4, QHeaderView.Stretch)
        for col in [0, 1, 2, 3]:
            pay_header.setSectionResizeMode(col, QHeaderView.ResizeToContents)"""
content = content.replace(payments_table_old, payments_table_new)

# Fix alignments in purchases
purchases_align_old = """            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, purchase["item_id"])
                item.setData(Qt.UserRole + 1, purchase["sale_id"])
                if col >= 4 and col != 5:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if col == 7:
                    item.setForeground(QColor("#4CAF50"))
                elif col == 8:
                    item.setForeground(
                        QColor("#4CAF50" if purchase["remaining"] <= 0 else "#FF9800")
                    )"""
purchases_align_new = """            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, purchase["item_id"])
                item.setData(Qt.UserRole + 1, purchase["sale_id"])
                
                if col in [0, 1, 3, 5]:
                    item.setTextAlignment(Qt.AlignCenter)
                elif col in [4, 6, 7, 8]:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    
                if col == 7:
                    item.setForeground(QColor("#4CAF50"))
                elif col == 8:
                    item.setForeground(
                        QColor("#4CAF50" if purchase["remaining"] <= 0 else "#FF9800")
                    )"""
content = content.replace(purchases_align_old, purchases_align_new)

# Fix alignments in payments
payments_align_old = """            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 3:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    item.setForeground(QColor("#4CAF50"))"""
payments_align_new = """            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                
                if col in [0, 1, 2]:
                    item.setTextAlignment(Qt.AlignCenter)
                elif col == 3:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    item.setForeground(QColor("#4CAF50"))"""
content = content.replace(payments_align_old, payments_align_new)


with open("ui/dialogs/client_details_dialog.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Updated successfully")
