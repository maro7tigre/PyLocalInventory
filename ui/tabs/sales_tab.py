"""
Sales tab - Updated to use unified BaseTab approach
Now consistent with Products/Clients/Suppliers experience
"""
from ui.tabs.base_tab import BaseTab
from PySide6.QtCore import Qt, QPoint, QDate
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QSpinBox, QDoubleSpinBox, QLineEdit, QDateEdit,
    QWidget, QProgressBar, QSizePolicy, QFrame, QTextBrowser, QPushButton)
from PySide6.QtGui import QPixmap, QColor
from classes.sales_class import SalesClass
from classes.sales_item_class import SalesItemClass
from ui.dialogs.edit_dialogs.base_operation_dialog import BaseOperationDialog
from datetime import datetime
import os
import re


def _ensure_payments_table(database):
    try:
        if database and database.cursor:
            database.cursor.execute("""
                CREATE TABLE IF NOT EXISTS Payments (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    sale_id INTEGER,
                    sales_item_id INTEGER,
                    amount REAL,
                    date TEXT,
                    FOREIGN KEY (sale_id) REFERENCES Sales(ID) ON DELETE CASCADE,
                    FOREIGN KEY (sales_item_id) REFERENCES Sales_Items(ID) ON DELETE CASCADE
                )
            """)
            database.cursor.execute("PRAGMA table_info('Payments')")
            columns = {row[1] for row in database.cursor.fetchall()}
            if "sales_item_id" not in columns:
                database.cursor.execute(
                    "ALTER TABLE Payments ADD COLUMN sales_item_id INTEGER"
                )
            database.conn.commit()
    except Exception as e:
        print(f"Error creating Payments table: {e}")


def _query_total_paid(database, sale_id):
    try:
        if database and database.cursor:
            database.cursor.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM Payments WHERE sale_id = ?",
                (sale_id,)
            )
            result = database.cursor.fetchone()
            return float(result[0]) if result else 0.0
    except Exception:
        pass
    return 0.0


class ReceiptDialog(QDialog):
    """Printable payment receipt."""

    def __init__(self, sale_id, client, order_date, payment_date,
                 total, amount_this, total_paid, remaining, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Payment Receipt")
        self.setMinimumWidth(500)
        self.setMinimumHeight(480)
        self._html = self._build_html(
            sale_id, client, order_date, payment_date,
            total, amount_this, total_paid, remaining
        )
        self._setup_ui()

    def _build_html(self, sale_id, client, order_date, payment_date,
                    total, amount_this, total_paid, remaining):
        rem_color = '#27ae60' if remaining <= 0 else '#e67e22'
        status_text = 'FULLY PAID ✓' if remaining <= 0 else f'{remaining:.2f} MAD REMAINING'
        return f"""
<html><body style="font-family:Arial,sans-serif;background:#fff;margin:0;padding:0;">
<div style="border:2px solid #222;padding:28px 32px;max-width:440px;margin:20px auto;">
  <h2 style="text-align:center;color:#1a1a1a;margin:0 0 4px 0;letter-spacing:2px;">PAYMENT RECEIPT</h2>
  <p style="text-align:center;color:#888;font-size:12px;margin:0 0 16px 0;">Thank you for your payment</p>
  <hr style="border:none;border-top:1px solid #ccc;margin:0 0 14px 0;"/>
  <table width="100%" cellspacing="0" cellpadding="4">
    <tr><td style="color:#555;font-size:13px;">Sale #:</td><td align="right"><b style="font-size:13px;">{sale_id}</b></td></tr>
    <tr><td style="color:#555;font-size:13px;">Client:</td><td align="right"><b style="font-size:13px;">{client}</b></td></tr>
    <tr><td style="color:#555;font-size:13px;">Order Date:</td><td align="right" style="font-size:13px;">{order_date}</td></tr>
    <tr><td style="color:#555;font-size:13px;">Payment Date:</td><td align="right" style="font-size:13px;">{payment_date}</td></tr>
  </table>
  <hr style="border:none;border-top:1px solid #ccc;margin:14px 0;"/>
  <table width="100%" cellspacing="0" cellpadding="5">
    <tr><td style="color:#555;font-size:13px;">Total Order:</td><td align="right"><b style="font-size:13px;">{total:.2f} MAD</b></td></tr>
    <tr><td style="color:#1565C0;font-size:14px;font-weight:bold;">Amount Paid (this):</td><td align="right"><b style="color:#1565C0;font-size:14px;">{amount_this:.2f} MAD</b></td></tr>
    <tr><td style="color:#555;font-size:13px;">Total Paid:</td><td align="right"><b style="color:#27ae60;font-size:13px;">{total_paid:.2f} MAD</b></td></tr>
    <tr><td style="color:#555;font-size:13px;">Remaining:</td><td align="right"><b style="color:{rem_color};font-size:13px;">{remaining:.2f} MAD</b></td></tr>
  </table>
  <hr style="border:none;border-top:1px solid #ccc;margin:14px 0;"/>
  <p style="text-align:center;color:{rem_color};font-size:15px;font-weight:bold;margin:0;">{status_text}</p>
</div>
</body></html>"""

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self._browser = QTextBrowser()
        self._browser.setHtml(self._html)
        layout.addWidget(self._browser)

        btn_lay = QHBoxLayout()
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(
            "QPushButton { background:#555; color:#fff; border:none; border-radius:6px; padding:8px 16px; }"
            "QPushButton:hover { background:#666; }"
        )
        close_btn.clicked.connect(self.accept)

        print_btn = QPushButton("🖨️  Print")
        print_btn.setStyleSheet(
            "QPushButton { background:#1565C0; color:#fff; border:none; border-radius:6px; padding:8px 16px; font-weight:bold; }"
            "QPushButton:hover { background:#1976D2; }"
        )
        print_btn.clicked.connect(self._print_receipt)

        btn_lay.addWidget(close_btn)
        btn_lay.addWidget(print_btn)
        layout.addLayout(btn_lay)

    def _print_receipt(self):
        try:
            from PySide6.QtPrintSupport import QPrinter, QPrintDialog
            from PySide6.QtGui import QTextDocument
            printer = QPrinter(QPrinter.HighResolution)
            dlg = QPrintDialog(printer, self)
            if dlg.exec() == QPrintDialog.Accepted:
                doc = QTextDocument()
                doc.setHtml(self._html)
                doc.print_(printer)
        except Exception as e:
            print(f"Print error: {e}")


class PaymentDialog(QDialog):
    """Record a payment installment for a sale and show a printable receipt."""

    def __init__(self, sale_obj, database, parent=None):
        super().__init__(parent)
        self.sale_obj = sale_obj
        self.database = database
        self.setWindowTitle(f"Payment — Sale #{sale_obj.id}")
        self.setMinimumWidth(440)
        self.setFixedWidth(440)
        self.setStyleSheet("background:#2a2a2a; color:#eee;")
        _ensure_payments_table(database)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        client = (self.sale_obj.get_value('client_name') or
                  self.sale_obj.get_value('client_username') or 'Unknown')
        order_date = self.sale_obj.get_value('date') or ''
        header = QLabel(f"Sale #{self.sale_obj.id}  |  Client: {client}  |  Date: {order_date}")
        header.setStyleSheet("font-size:13px; font-weight:bold; color:#ddd;")
        layout.addWidget(header)

        self._total = self.sale_obj.calculate_total_price()
        self._total_paid_before = _query_total_paid(self.database, self.sale_obj.id)
        self._remaining_before = self._total - self._total_paid_before

        # Summary frame
        summary = QFrame()
        summary.setStyleSheet("QFrame { background:#252525; border:1px solid #444; border-radius:6px; }")
        s_lay = QVBoxLayout(summary)
        s_lay.setContentsMargins(14, 10, 14, 10)
        s_lay.setSpacing(6)

        def _row(lbl_text, val_text, color='#eee'):
            h = QHBoxLayout()
            l = QLabel(lbl_text)
            l.setStyleSheet("color:#aaa; font-size:13px;")
            v = QLabel(val_text)
            v.setStyleSheet(f"color:{color}; font-size:13px; font-weight:bold;")
            v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            h.addWidget(l)
            h.addStretch()
            h.addWidget(v)
            return h

        s_lay.addLayout(_row("Total Order:", f"{self._total:.2f} MAD"))
        paid_color = '#4CAF50' if self._total_paid_before > 0 else '#888'
        s_lay.addLayout(_row("Already Paid:", f"{self._total_paid_before:.2f} MAD", paid_color))
        rem_color = '#FF9800' if self._remaining_before > 0 else '#4CAF50'
        s_lay.addLayout(_row("Remaining:", f"{self._remaining_before:.2f} MAD", rem_color))
        layout.addWidget(summary)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#444;")
        layout.addWidget(sep)

        # Amount input
        amount_lbl = QLabel("Amount Paying Now:")
        amount_lbl.setStyleSheet("color:#ccc; font-size:13px;")
        layout.addWidget(amount_lbl)

        self._amount_spin = QDoubleSpinBox()
        self._amount_spin.setRange(0.01, 9_999_999.99)
        self._amount_spin.setDecimals(2)
        self._amount_spin.setValue(max(self._remaining_before, 0.0))
        self._amount_spin.setSuffix(" MAD")
        self._amount_spin.setMinimumHeight(36)
        self._amount_spin.setStyleSheet(
            "QDoubleSpinBox { background:#333; color:#eee; border:1px solid #555; padding:4px; font-size:14px; }"
            "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { background:#444; }"
        )
        self._amount_spin.valueChanged.connect(self._on_amount_changed)
        layout.addWidget(self._amount_spin)

        # Date input
        date_lbl = QLabel("Payment Date:")
        date_lbl.setStyleSheet("color:#ccc; font-size:13px;")
        layout.addWidget(date_lbl)

        self._date_edit = QDateEdit()
        self._date_edit.setDate(QDate.currentDate())
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDisplayFormat("dd-MM-yyyy")
        self._date_edit.setMinimumHeight(36)
        self._date_edit.setStyleSheet(
            "QDateEdit { background:#333; color:#eee; border:1px solid #555; padding:4px; font-size:14px; }"
            "QDateEdit::drop-down { background:#444; }"
        )
        layout.addWidget(self._date_edit)

        # Live remaining preview
        init_remaining_after = self._remaining_before - self._amount_spin.value()
        after_color = '#4CAF50' if init_remaining_after <= 0 else '#FF9800'
        self._after_lbl = QLabel(f"Remaining after this payment:  {init_remaining_after:.2f} MAD")
        self._after_lbl.setStyleSheet(f"color:{after_color}; font-size:13px; font-weight:bold; padding-top:4px;")
        layout.addWidget(self._after_lbl)

        # Buttons
        btn_lay = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            "QPushButton { background:#555; color:#fff; border:none; border-radius:6px; padding:8px 16px; font-size:13px; }"
            "QPushButton:hover { background:#666; }"
        )
        cancel_btn.clicked.connect(self.reject)

        save_btn = QPushButton("💾  Save & Print Receipt")
        save_btn.setStyleSheet(
            "QPushButton { background:#1565C0; color:#fff; border:none; border-radius:6px; padding:8px 16px; font-size:13px; font-weight:bold; }"
            "QPushButton:hover { background:#1976D2; }"
        )
        save_btn.clicked.connect(self._save_payment)

        btn_lay.addWidget(cancel_btn)
        btn_lay.addWidget(save_btn)
        layout.addLayout(btn_lay)

    def _on_amount_changed(self, value):
        remaining_after = self._remaining_before - value
        color = '#4CAF50' if remaining_after <= 0 else '#FF9800'
        self._after_lbl.setText(f"Remaining after this payment:  {remaining_after:.2f} MAD")
        self._after_lbl.setStyleSheet(f"color:{color}; font-size:13px; font-weight:bold; padding-top:4px;")

    def _save_payment(self):
        from PySide6.QtWidgets import QMessageBox
        amount = self._amount_spin.value()
        if amount <= 0:
            QMessageBox.warning(self, "Invalid Amount", "Please enter an amount greater than 0.")
            return

        date_str = self._date_edit.date().toString("dd-MM-yyyy")
        try:
            self.database.cursor.execute(
                "INSERT INTO Payments (sale_id, amount, date) VALUES (?, ?, ?)",
                (self.sale_obj.id, amount, date_str)
            )
            self.database.conn.commit()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save payment:\n{e}")
            return

        client = (self.sale_obj.get_value('client_name') or
                  self.sale_obj.get_value('client_username') or 'Unknown')
        remaining_after = self._remaining_before - amount

        ReceiptDialog(
            sale_id=self.sale_obj.id,
            client=client,
            order_date=self.sale_obj.get_value('date') or '',
            payment_date=date_str,
            total=self._total,
            amount_this=amount,
            total_paid=self._total_paid_before + amount,
            remaining=remaining_after,
            parent=self
        ).exec()
        self.accept()


class OrderProgressDialog(QDialog):
    """Popup showing per-product production progress for a sale."""

    def __init__(self, sale_obj, database, parent=None):
        super().__init__(parent)
        self.sale_obj = sale_obj
        self.database = database
        self.setWindowTitle(f"Order Progress — Sale #{sale_obj.id}")
        self.setMinimumWidth(700)
        self.setMinimumHeight(520)
        _ensure_payments_table(database)
        self._setup_ui()

    def _setup_ui(self):
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(16, 16, 16, 16)
        self._root_layout.setSpacing(10)
        try:
            self._build_ui(self._root_layout)
        except Exception as e:
            import traceback
            traceback.print_exc()
            err = QLabel(f"Error loading progress dialog:\n{e}")
            err.setStyleSheet("color:#ff6b6b; font-size:13px; padding:8px;")
            self._root_layout.addWidget(err)

    def _build_ui(self, layout):
        client = (self.sale_obj.get_value('client_name') or
                  self.sale_obj.get_value('client_username') or 'Unknown')
        date = self.sale_obj.get_value('date') or ''
        header_lbl = QLabel(f"Sale #{self.sale_obj.id}   |   Client: {client}   |   Date: {date}")
        header_lbl.setStyleSheet("font-size:14px; font-weight:bold; color:#ddd; padding-bottom:4px;")
        layout.addWidget(header_lbl)

        self.items = self.sale_obj.get_sales_items()

        self.table = QTableWidget(len(self.items), 5)
        self.table.setHorizontalHeaderLabels(["Preview", "Product", "Target", "Production", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 68)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(68)
        self.table.verticalHeader().hide()
        self.table.setStyleSheet(
            "QTableWidget { background:#2a2a2a; color:#eee; gridline-color:#444; border:1px solid #555; }"
            "QHeaderView::section { background:#333; color:#fff; border:1px solid #555; padding:4px; font-weight:bold; }"
            "QTableWidget::item:alternate { background:#252525; }"
        )

        for row, item in enumerate(self.items):
            self._set_preview_cell(row, item.get_product_preview())

            name_cell = QTableWidgetItem(str(item.get_value('product_name') or ''))
            name_cell.setFlags(name_cell.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 1, name_cell)

            qty = int(item.get_value('quantity') or 0)
            qty_cell = QTableWidgetItem(str(qty))
            qty_cell.setFlags(qty_cell.flags() & ~Qt.ItemIsEditable)
            qty_cell.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, qty_cell)

            prod = int(item.get_value('production') or 0)
            spinbox = QSpinBox()
            spinbox.setRange(0, 999999)
            spinbox.setValue(prod)
            spinbox.setStyleSheet(
                "QSpinBox { background:#333; color:#eee; border:1px solid #555; padding:2px; }"
            )
            spinbox.valueChanged.connect(
                lambda val, i=item, r=row, t=qty: self._on_production_changed(val, i, r, t)
            )
            self.table.setCellWidget(row, 3, spinbox)

            self._refresh_status_cell(row, qty, prod)

        self.table.setMaximumHeight(300)
        layout.addWidget(self.table)
        self._build_payment_section(layout)

    def _build_payment_section(self, layout):
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#444;")
        layout.addWidget(sep)

        lbl = QLabel("Payment & Notes")
        lbl.setStyleSheet("font-size:13px; font-weight:bold; color:#aaa; padding-top:2px;")
        layout.addWidget(lbl)

        self._pay_table = QTableWidget(1, 4)
        self._pay_table.setHorizontalHeaderLabels(["Total Price", "Total Paid", "Remaining", "Note"])
        self._pay_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._pay_table.verticalHeader().hide()
        self._pay_table.setRowHeight(0, 42)
        self._pay_table.setFixedHeight(74)
        self._pay_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._pay_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._pay_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._pay_table.setStyleSheet(
            "QTableWidget { background:#2a2a2a; color:#eee; gridline-color:#444; border:1px solid #555; }"
            "QHeaderView::section { background:#333; color:#fff; border:1px solid #555; padding:4px; font-weight:bold; }"
        )

        total = self.sale_obj.calculate_total_price()
        total_paid = _query_total_paid(self.database, self.sale_obj.id)
        remaining = total - total_paid

        # Col 0 — total price (read-only)
        total_item = QTableWidgetItem(f"{total:.2f}")
        total_item.setTextAlignment(Qt.AlignCenter)
        total_item.setFlags(total_item.flags() & ~Qt.ItemIsEditable)
        self._pay_table.setItem(0, 0, total_item)

        # Col 1 — total paid so far (read-only, sum from Payments table)
        paid_item = QTableWidgetItem(f"{total_paid:.2f}")
        paid_item.setTextAlignment(Qt.AlignCenter)
        paid_item.setFlags(paid_item.flags() & ~Qt.ItemIsEditable)
        paid_item.setForeground(QColor('#4CAF50') if total_paid > 0 else QColor('#888'))
        self._pay_table.setItem(0, 1, paid_item)

        # Col 2 — remaining (read-only, colour-coded)
        self._remaining_item = QTableWidgetItem(f"{remaining:.2f}")
        self._remaining_item.setTextAlignment(Qt.AlignCenter)
        self._remaining_item.setFlags(self._remaining_item.flags() & ~Qt.ItemIsEditable)
        self._refresh_remaining_color(remaining)
        self._pay_table.setItem(0, 2, self._remaining_item)

        # Col 3 — note (editable line edit, saves to Sales.notes)
        note_edit = QLineEdit()
        note_edit.setPlaceholderText("Add a note…")
        note_edit.setText(self.sale_obj.get_value('notes') or '')
        note_edit.setStyleSheet(
            "QLineEdit { background:#333; color:#eee; border:1px solid #555; padding:2px 4px; }"
        )
        note_edit.editingFinished.connect(lambda: self._on_note_changed(note_edit.text()))
        self._pay_table.setCellWidget(0, 3, note_edit)

        layout.addWidget(self._pay_table)

    def _on_note_changed(self, text):
        try:
            if self.database and self.sale_obj.id:
                self.database.update_item(self.sale_obj.id, {'notes': text}, 'Sales')
                if 'notes' in self.sale_obj.parameters:
                    self.sale_obj.parameters['notes']['value'] = text
        except Exception as e:
            print(f"Error saving notes: {e}")

    def _refresh_remaining_color(self, remaining):
        if remaining <= 0:
            color = QColor('#4CAF50')
        elif remaining > 0:
            color = QColor('#FF9800')
        else:
            color = QColor('#eee')
        self._remaining_item.setForeground(color)

    def _set_preview_cell(self, row, image_path):
        container = QWidget()
        lay = QHBoxLayout(container)
        lay.setContentsMargins(4, 4, 4, 4)
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setFixedSize(58, 58)
        if image_path and os.path.exists(image_path):
            pix = QPixmap(image_path).scaled(58, 58, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            lbl.setPixmap(pix)
        else:
            lbl.setText("📦")
            lbl.setStyleSheet("font-size:22px; background:#333; border-radius:4px;")
        lay.addWidget(lbl)
        self.table.setCellWidget(row, 0, container)

    def _on_production_changed(self, value, item, row, target):
        try:
            if self.database and item.id:
                self.database.update_item(item.id, {'production': value}, 'Sales_Items')
                if 'production' in item.parameters:
                    item.parameters['production']['value'] = value
        except Exception as e:
            print(f"Error saving production value: {e}")
        self._refresh_status_cell(row, target, value)

    def _refresh_status_cell(self, row, target, production):
        if target > 0 and production >= target:
            text, color = "Complete", QColor('#4CAF50')
        elif production > 0:
            text, color = "In Progress", QColor('#FF9800')
        else:
            text, color = "Pending", QColor('#757575')

        cell = QTableWidgetItem(text)
        cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
        cell.setForeground(color)
        cell.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 4, cell)


class SalesEditDialog(BaseOperationDialog):
    """Sales-specific dialog using unified base operation dialog"""
    
    def __init__(self, sales_id=None, database=None, parent=None):
        super().__init__(
            operation_class=SalesClass,
            item_class=SalesItemClass, 
            operation_id=sales_id,
            database=database,
            parent=parent
        )
    
    def get_item_columns(self):
        """Override to specify sales item columns"""
        return ['product_preview', 'product_name', 'information', 'quantity', 'unit_price', 'subtotal', 'delete_action']
    
    def validate_data(self):
        """Sales-specific validation"""
        # Keep only base validation; existence check handled in auto-create workflow
        return super().validate_data()
    
    def _validate_client_exists(self, username):
        """Check if client username exists in database"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return False
        
        try:
            self.database.cursor.execute("SELECT COUNT(*) FROM Clients WHERE username = ?", (username,))
            result = self.database.cursor.fetchone()
            return result[0] > 0 if result else False
        except Exception as e:
            print(f"Error validating client: {e}")
            return False


class SalesTab(BaseTab):
    """Sales tab with unified table experience - consistent with other entity tabs"""
    
    def __init__(self, database=None, parent=None):
        super().__init__(SalesClass, SalesEditDialog, database, parent)
        self._ensure_new_columns_order()
    
    def setup_ui(self):
        """Override setup_ui to add reports button"""
        # Call parent setup first
        super().setup_ui()
        
        # Find the controls layout and add reports button
        controls_layout = None
        for i in range(self.layout().count()):
            item = self.layout().itemAt(i)
            if item and hasattr(item, 'layout') and item.layout():
                # Check if this is the controls layout by looking for buttons
                for j in range(item.layout().count()):
                    widget = item.layout().itemAt(j).widget() if item.layout().itemAt(j) else None
                    if widget and hasattr(widget, 'text') and 'Add' in widget.text():
                        controls_layout = item.layout()
                        break
                if controls_layout:
                    break
        
        if controls_layout:
            from ui.widgets.themed_widgets import OrangeButton

            self.reports_btn = OrangeButton("📊 Reports")
            self.reports_btn.clicked.connect(self.show_reports)
            self.reports_btn.setStyleSheet(self.reports_btn.styleSheet() + "\nQPushButton { font-size: 14px; padding: 5px 10px; }")
            self.reports_btn.setMinimumHeight(20)
            controls_layout.insertWidget(controls_layout.count() - 1, self.reports_btn)

            self.payment_btn = OrangeButton("💳 Payment")
            self.payment_btn.clicked.connect(self.show_payment_dialog)
            self.payment_btn.setStyleSheet(
                "QPushButton { background:#1565C0; color:#fff; border:none; border-radius:6px; font-size:14px; padding:5px 10px; }"
                "QPushButton:hover { background:#1976D2; }"
            )
            self.payment_btn.setMinimumHeight(20)
            controls_layout.insertWidget(controls_layout.count() - 1, self.payment_btn)

    def get_preview_category(self):
        """Override to specify preview category for sales operations"""
        return "individual"  # Since sales are typically associated with clients
    
    def get_search_options(self):
        """Get autocomplete options for sales search"""
        if not self.all_items:
            return []
        
        options = set()
        for obj in self.all_items:
            try:
                # Add client usernames, client names, and products
                client_username = obj.get_value('client_username')
                client_name = obj.get_value('client_name')
                information = obj.get_value('information')
                date = obj.get_value('date')
                
                if client_username:
                    options.add(str(client_username))
                if client_name:
                    options.add(str(client_name))
                if information:
                    options.add(str(information))
                if date:
                    # Add formatted date
                    options.add(str(date))
                
                # Add products from sales items if available
                if hasattr(obj, 'items') and obj.items:
                    for item in obj.items:
                        try:
                            product_name = item.get_value('product_name')
                            if product_name:
                                options.add(str(product_name))
                        except:
                            pass
            except:
                pass
        
        return sorted(list(options))
    
    def setup_order_options(self):
        """Setup order dropdown options for sales"""
        self.order_combo.clear()
        self.order_combo.addItems([
            "Default",
            "Client Username ↑",
            "Client Username ↓", 
            "Client Name ↑",
            "Client Name ↓",
            "Recent ↑",
            "Recent ↓",
            "Total ↑",
            "Total ↓"
        ])
    
    def get_searchable_fields(self):
        """Get fields that can be searched for sales"""
        return ['client_username', 'client_name', 'information', 'date']
    
    def matches_search(self, obj, search_text):
        """Check if sales matches search criteria"""
        if not search_text:
            return True
        
        search_lower = search_text.lower()
        
        # Check for date search patterns first
        date_search = self.parse_date_search(search_text)
        if date_search:
            return self._matches_date_search(obj, date_search)
        
        # Check client username, client name, and products
        try:
            client_username = obj.get_value('client_username') or ""
            client_name = obj.get_value('client_name') or ""
            information = obj.get_value('information') or ""
            
            if (search_lower in client_username.lower() or 
                search_lower in client_name.lower() or
                search_lower in information.lower()):
                return True
            
            # Check products in sales items
            if hasattr(obj, 'items') and obj.items:
                for item in obj.items:
                    try:
                        product_name = item.get_value('product_name') or ""
                        if search_lower in product_name.lower():
                            return True
                    except:
                        pass
        except:
            pass
        
        return False
    
    def _matches_date_search(self, obj, date_search):
        """Check if sales matches date search criteria"""
        try:
            sales_date_str = obj.get_value('date')
            if not sales_date_str:
                return False
            
            # Parse sales date (try multiple formats)
            sales_date = None
            date_formats = ['%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y']
            for fmt in date_formats:
                try:
                    sales_date = datetime.strptime(str(sales_date_str), fmt).date()
                    break
                except ValueError:
                    continue
            
            if not sales_date:
                return False
            
            if date_search[0] == 'single':
                return sales_date == date_search[1]
            elif date_search[0] == 'range':
                return date_search[1] <= sales_date <= date_search[2]
        except:
            pass
        
        return False
    
    def sort_items(self, items, order_option):
        """Sort sales based on order option"""
        if not order_option or order_option == "Default":
            return items
        
        try:
            if order_option == "Client Username ↑":
                items.sort(key=lambda x: str(x.get_value('client_username') or "").lower())
            elif order_option == "Client Username ↓":
                items.sort(key=lambda x: str(x.get_value('client_username') or "").lower(), reverse=True)
            elif order_option == "Client Name ↑":
                items.sort(key=lambda x: str(x.get_value('client_name') or "").lower())
            elif order_option == "Client Name ↓":
                items.sort(key=lambda x: str(x.get_value('client_name') or "").lower(), reverse=True)
            elif order_option == "Recent ↑":
                items.sort(key=lambda x: self.parse_date_for_sorting(x.get_value('date')))
            elif order_option == "Recent ↓":
                items.sort(key=lambda x: self.parse_date_for_sorting(x.get_value('date')), reverse=True)
            elif order_option == "Total ↑":
                items.sort(key=lambda x: float(x.get_value('total_price') or 0))
            elif order_option == "Total ↓":
                items.sort(key=lambda x: float(x.get_value('total_price') or 0), reverse=True)
        except Exception as e:
            print(f"Error sorting sales: {e}")
        
        return items

    # ------------- New columns injection and custom cell rendering -------------
    _VIRTUAL_COLUMN_HEADERS = {'check_progress': '', 'progress': 'Progress'}

    def _ensure_new_columns_order(self):
        """Ensure state appears after ID, check_progress button is second, and progress column exists."""
        try:
            if 'state' not in self.table_columns:
                self.table_columns.insert(1, 'state')
            if 'check_progress' not in self.table_columns:
                # Insert right after id (index 0), before state
                self.table_columns.insert(1, 'check_progress')
            if 'progress' not in self.table_columns:
                self.table_columns.append('progress')

            temp_obj = self.object_class(0, self.database)
            headers = []
            for key in self.table_columns:
                if key in self._VIRTUAL_COLUMN_HEADERS:
                    headers.append(self._VIRTUAL_COLUMN_HEADERS[key])
                elif key in temp_obj.parameters:
                    headers.append(temp_obj.get_display_name(key))
                else:
                    headers.append(key.capitalize())
            self.table.setColumnCount(len(self.table_columns))
            self.table.setHorizontalHeaderLabels(headers)
            # Fix the check_progress column to a narrow width
            if 'check_progress' in self.table_columns:
                cp_col = self.table_columns.index('check_progress')
                self.table.setColumnWidth(cp_col, 50)
                self.table.horizontalHeader().setSectionResizeMode(cp_col, QHeaderView.Fixed)
        except Exception as e:
            print(f"Error ensuring sales columns order: {e}")

    def populate_table_with_items(self, items):
        """Populate table with custom state/progress rendering."""
        self.table.setRowCount(len(items))
        for row, obj in enumerate(items):
            try:
                for col, column_key in enumerate(self.table_columns):
                    if column_key == 'check_progress':
                        self._set_check_progress_cell(row, col, obj)
                    elif column_key == 'state':
                        self._set_state_cell(row, col, obj)
                    elif column_key == 'progress':
                        self._set_progress_cell(row, col, obj)
                    else:
                        self.set_table_cell(row, col, column_key, obj)
            except Exception as e:
                print(f"Error processing Sales row {row}: {e}")
        self.table.resizeRowsToContents()

    def _set_check_progress_cell(self, row, col, obj):
        from PySide6.QtWidgets import QPushButton
        btn = QPushButton("📦")
        btn.setToolTip("Check Progress")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton { background:#1565C0; color:#fff; border:none; border-radius:4px; padding:3px 8px; font-size:15px; }"
            "QPushButton:hover { background:#1976D2; }"
        )
        btn.clicked.connect(lambda _=None, o=obj, r=row, c=col: (self.table.setCurrentCell(r, c), self._open_progress_for_sale(o)))

        container = QWidget()
        lay = QHBoxLayout(container)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.addWidget(btn)
        self.table.setCellWidget(row, col, container)

    def _open_progress_for_sale(self, obj):
        try:
            dialog = OrderProgressDialog(obj, self.database, self)
            dialog.exec()
            self.refresh_table()
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Failed to open progress dialog:\n{e}")
            import traceback
            traceback.print_exc()

    def _set_state_cell(self, row, col, obj):
        from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton
        state = obj.get_value('state') or 'pending'
        colors = {
            'on_hold': ('On Hold', '#757575'),
            'pending': ('Pending', '#FF9800'),
            'confirmed': ('Confirmed', '#4CAF50'),
            'finished': ('Finished', '#1976D2')
        }
        label, color = colors.get(state, ('Pending', '#FF9800'))
        btn = QPushButton(label)
        btn.setStyleSheet(f"QPushButton {{ background:{color}; color:#fff; border:none; border-radius:6px; padding:4px 10px; }}")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _=None, o=obj, b=btn, r=row, c=col: (self.table.setCurrentCell(r, c), self._open_state_popup(o, b)))

        container = QWidget()
        lay = QHBoxLayout(container)
        lay.setContentsMargins(0,0,0,0)
        lay.addWidget(btn)
        self.table.setCellWidget(row, col, container)

    def _set_progress_cell(self, row, col, obj):
        items = obj.get_sales_items()
        total_target = sum(int(item.get_value('quantity') or 0) for item in items)
        total_prod = sum(int(item.get_value('production') or 0) for item in items)
        pct = min(int(total_prod / total_target * 100), 100) if total_target > 0 else 0

        if pct >= 100:
            chunk_color = '#4CAF50'
        elif pct > 0:
            chunk_color = '#FF9800'
        else:
            chunk_color = '#555'

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(pct)
        bar.setFormat(f"{pct}%")
        bar.setTextVisible(True)
        bar.setStyleSheet(
            f"QProgressBar {{ border:1px solid #444; border-radius:4px; background:#2a2a2a; text-align:center; color:#fff; }}"
            f"QProgressBar::chunk {{ background:{chunk_color}; border-radius:3px; }}"
        )

        container = QWidget()
        lay = QHBoxLayout(container)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.addWidget(bar)
        # Pass mouse events through so clicking the bar selects the table row
        bar.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        container.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.table.setCellWidget(row, col, container)

    def _open_state_popup(self, obj, anchor):
        """Open a small popup dialog with state choices."""
        from PySide6.QtWidgets import (
            QApplication,
            QDialog,
            QFrame,
            QPushButton,
            QScrollArea,
            QSizePolicy,
            QVBoxLayout,
            QWidget,
        )
        # Close previous
        if hasattr(self, '_state_popup') and self._state_popup:
            try:
                self._state_popup.close()
            except Exception:
                pass
        popup = QDialog(self)
        popup.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        popup.setAttribute(Qt.WA_TranslucentBackground, False)
        popup.setModal(False)
        popup.setObjectName('statePopup')

        layout = QVBoxLayout(popup)
        layout.setContentsMargins(6, 6, 6, 6)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        options_widget = QWidget()
        options_layout = QVBoxLayout(options_widget)
        options_layout.setContentsMargins(6, 6, 6, 6)
        options_layout.setSpacing(8)

        styles = {
            'on_hold': ('On Hold', '#757575'),
            'pending': ('Pending', '#FF9800'),
            'confirmed': ('Confirmed', '#4CAF50'),
            'finished': ('Finished', '#1976D2')
        }
        current = obj.get_value('state') or 'pending'
        for key, (text, color) in styles.items():
            btn = QPushButton(text)
            sel_border = '3px solid #FFFFFF' if key == current else '1px solid #1e1e1e'
            btn.setStyleSheet(
                f"QPushButton {{ background:{color}; color:#fff; border:{sel_border}; border-radius:6px; padding:8px 12px; font-weight:bold; }}"
                f"QPushButton:hover {{ filter: brightness(110%); }}"
            )
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=None, k=key: self._select_state_from_popup(popup, obj, k))
            options_layout.addWidget(btn)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet('color:#555;')
        options_layout.addWidget(line)

        cancel_btn = QPushButton('Cancel')
        cancel_btn.setStyleSheet("QPushButton { background:#E53935; color:#fff; border:none; border-radius:6px; padding:8px 12px; }"
                                "QPushButton:hover { background:#EF5350; }")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(popup.close)
        cancel_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        options_layout.addWidget(cancel_btn)

        scroll_area.setWidget(options_widget)
        layout.addWidget(scroll_area)

        popup.setStyleSheet("#statePopup { background:#2f2f2f; border:2px solid #444; border-radius:10px; }")
        popup.setMinimumWidth(max(anchor.width(), 250))
        popup.setMaximumHeight(320)
        self._state_popup = popup

        popup.adjustSize()
        screen = QApplication.screenAt(anchor.mapToGlobal(anchor.rect().center()))
        available = screen.availableGeometry() if screen else QApplication.primaryScreen().availableGeometry()
        below = anchor.mapToGlobal(anchor.rect().bottomLeft()) + QPoint(0, 6)
        above_y = anchor.mapToGlobal(anchor.rect().topLeft()).y() - popup.height() - 6

        x = min(max(below.x(), available.left()), available.right() - popup.width() + 1)
        if below.y() + popup.height() <= available.bottom() + 1:
            y = below.y()
        else:
            y = max(available.top(), above_y)
        popup.move(x, y)
        popup.show()

    def _select_state_from_popup(self, popup, obj, new_state):
        try:
            popup.close()
        except Exception:
            pass
        self._change_sale_state(obj, new_state)

    def _change_sale_state(self, obj, new_state):
        if not self.database:
            return
        try:
            obj.set_value('state', new_state)
            payload = {'state': new_state}
            self.database.update_item(obj.id, payload, 'Sales')
            # Refresh to reflect button style
            self.refresh_table()
        except Exception as e:
            print(f"Error updating sale state: {e}")
    
    def show_order_progress(self):
        """Show order production progress dialog for the selected sale."""
        from PySide6.QtWidgets import QMessageBox
        obj_id = self.get_selected_id()
        if obj_id is None:
            QMessageBox.warning(self, "No Selection", "Please select a sale to check progress.")
            return
        obj = next((s for s in self.filtered_items if s.id == obj_id), None)
        if obj is None:
            obj = next((s for s in self.all_items if s.id == obj_id), None)
        if obj:
            self._open_progress_for_sale(obj)

    def show_reports(self):
        """Show reports dialog for selected sales record"""
        try:
            # Get selected row
            current_row = self.table.currentRow()
            
            if current_row < 0:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(self, "No Selection", "Please select a sales record to generate a report.")
                return
            
            # Get the sales object from the current row
            if current_row >= len(self.filtered_items):
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Error", f"Selected row is invalid. Row: {current_row}, Filtered items: {len(self.filtered_items)}")
                return
            
            selected_sales = self.filtered_items[current_row]
            
            # Get profile manager from parent (main window)
            profile_manager = None
            if hasattr(self.parent_widget, 'profile_manager'):
                profile_manager = self.parent_widget.profile_manager
            elif hasattr(self.parent_widget, 'parent') and hasattr(self.parent_widget.parent, 'profile_manager'):
                profile_manager = self.parent_widget.parent.profile_manager
            
            if not profile_manager:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Error", "Could not access profile manager.")
                return
            
            # Show reports dialog
            from ui.dialogs.reports_dialog import ReportsDialog
            dialog = ReportsDialog(selected_sales, profile_manager, self)
            dialog.exec()
            
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Failed to show reports dialog:\n{str(e)}")
            print(f"Error in show_reports: {e}")
            import traceback
            traceback.print_exc()

    def show_payment_dialog(self):
        """Open the payment dialog for the selected sale."""
        from PySide6.QtWidgets import QMessageBox
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.information(self, "No Selection", "Please select a sale to record a payment.")
            return
        if current_row >= len(self.filtered_items):
            return
        selected_sale = self.filtered_items[current_row]
        dialog = PaymentDialog(selected_sale, self.database, self)
        if dialog.exec():
            self.refresh_table()
