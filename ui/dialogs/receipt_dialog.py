"""
Payment receipt dialog - printable receipt display.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTextBrowser, QMessageBox
)
from PySide6.QtGui import QTextDocument
import os


class ReceiptDialog(QDialog):
    """Printable payment receipt."""

    def __init__(self, sale_id, client, order_date, payment_date,
                 total, amount_this, total_paid, remaining, parent=None, currency='MAD'):
        super().__init__(parent)
        self.setWindowTitle("Payment Receipt")
        self.setMinimumWidth(500)
        self.setMinimumHeight(480)
        self.currency = currency
        self._html = self._build_html(
            sale_id, client, order_date, payment_date,
            total, amount_this, total_paid, remaining
        )
        self._setup_ui()

    def _build_html(self, sale_id, client, order_date, payment_date,
                    total, amount_this, total_paid, remaining):
        rem_color = '#27ae60' if remaining <= 0 else '#e67e22'
        status_text = 'FULLY PAID ✓' if remaining <= 0 else f'{remaining:.2f} {self.currency} REMAINING'

        template_path = os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..', '..', 'report', 'Receipt_templat.html'
        ))
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                template = f.read()
            html = template.format(
                sale_id=sale_id, client=client,
                order_date=order_date, payment_date=payment_date,
                total=f"{total:.2f}", amount_this=f"{amount_this:.2f}",
                total_paid=f"{total_paid:.2f}", remaining=f"{remaining:.2f}",
                status_text=status_text,
                currency=self.currency,
            )
            return html.replace('REM_COLOR', rem_color)
        except Exception as e:
            print(f"Error loading receipt template: {e}")
            return (f"<html><body><p>Receipt for Sale #{sale_id} — "
                    f"{amount_this:.2f} {self.currency} paid by {client}. "
                    f"Remaining: {remaining:.2f} {self.currency}</p></body></html>")

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
            from PySide6.QtPrintSupport import QPrinter, QPrinterInfo, QPrintDialog
            if not QPrinterInfo.availablePrinterNames():
                QMessageBox.warning(
                    self, "No Printer",
                    "No printer is installed or available on this computer.",
                )
                return
            printer = QPrinter(QPrinter.HighResolution)
            default_printer = QPrinterInfo.defaultPrinter()
            if not default_printer.isNull():
                printer.setPrinterName(default_printer.printerName())
            dlg = QPrintDialog(printer, self)
            if dlg.exec() == QPrintDialog.Accepted:
                doc = QTextDocument()
                doc.setHtml(self._html)
                doc.print_(printer)
        except Exception as e:
            print(f"Print error: {e}")
            QMessageBox.critical(
                self, "Print Error", f"Could not print this receipt:\n{e}"
            )
