"""
Sale Profitability dialog - internal Revenue / COGS / Gross Profit / Margin
view for one Sale.

This is strictly internal information: customer-facing documents (Devis,
Bon de Livraison, reports) are never modified. Authorization is enforced at
the authoritative layer - ``Database.get_sale_profitability`` raises
PermissionError for remote callers without Sales read + Imports read, and the
LAN server denies the RPC call before it even reaches the backend.
"""
import shiboken6
import logging

from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QHeaderView, QMessageBox, QFrame,
)

from core import diagnostics

logger = logging.getLogger(__name__)

_GREEN = "#4CAF50"
_RED = "#f44336"


class _ProfitabilityWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, database, sale_id):
        super().__init__()
        self.database = database
        self.sale_id = sale_id

    def _ensure_local_connection(self):
        if self.database.__class__.__name__ == "RemoteDatabase":
            return None
        from core.database import Database
        worker_db = Database(self.database.profile_manager)
        worker_db.language = getattr(self.database, "language", "en")
        worker_db.registered_classes = self.database.registered_classes
        if not worker_db.connect():
            raise RuntimeError(
                getattr(worker_db, "last_error", None)
                or "Could not connect to the database"
            )
        return worker_db

    def run(self):
        worker_db = None
        try:
            worker_db = self._ensure_local_connection()
            db = worker_db or self.database
            result = db.get_sale_profitability(self.sale_id)
            self.finished.emit(result)
        except Exception as error:
            logger.exception(
                "Sale profitability load failed sale_id=%s", self.sale_id
            )
            self.failed.emit(str(error) or "Unknown error")
        finally:
            if worker_db is not None:
                try:
                    worker_db.close()
                except Exception:
                    logger.exception("Could not close profitability worker DB")


class SaleProfitabilityDialog(QDialog):
    """Internal per-sale profitability viewer."""

    def __init__(self, sale_id, database, parent=None):
        super().__init__(parent)
        self.sale_id = int(sale_id)
        self.database = database
        self._thread = None
        self._worker = None

        self.setWindowTitle(f"Sale Profitability - #{self.sale_id}")
        self.resize(760, 560)
        self._build_ui()

        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self._wait_for_thread)

        self._start_load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.header_label = QLabel(f"Sale #{self.sale_id}")
        self.header_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(self.header_label)

        summary_frame = QFrame()
        summary_layout = QHBoxLayout(summary_frame)
        summary_layout.setContentsMargins(8, 8, 8, 8)
        self.summary_labels = {}
        for key, title in (
            ("revenue_ht", "Revenue (HT)"),
            ("cogs", "COGS"),
            ("gross_profit", "Gross Profit"),
            ("gross_margin_pct", "Gross Margin"),
        ):
            box = QVBoxLayout()
            caption = QLabel(title)
            caption.setStyleSheet("color: #aaaaaa; font-size: 11px;")
            value = QLabel("-")
            value.setStyleSheet("font-size: 18px; font-weight: bold;")
            box.addWidget(caption)
            box.addWidget(value)
            summary_layout.addLayout(box)
            self.summary_labels[key] = value
        layout.addWidget(summary_frame)

        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels([
            "Type", "Item", "Qty", "Net Revenue", "Avg Cost", "Profit",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(1, QHeaderView.Stretch)
        for column in (0, 2, 3, 4, 5):
            header_view.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.status_label = QLabel("Loading...")
        self.status_label.setStyleSheet("color: #aaaaaa;")
        layout.addWidget(self.status_label)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        bottom_row.addWidget(close_btn)
        layout.addLayout(bottom_row)

    # ─────────────────────────── data loading ────────────────────────────

    def _start_load(self):
        thread = getattr(self, "_thread", None)
        if thread is not None:
            try:
                if shiboken6.isValid(thread) and thread.isRunning():
                    return False
            except RuntimeError:
                pass

        thread = QThread()
        worker = _ProfitabilityWorker(self.database, self.sale_id)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        worker.finished.connect(self._on_load_finished)
        worker.failed.connect(self._on_load_failed)

        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)

        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_finished)

        self._thread = thread
        self._worker = worker
        diagnostics.worker_started(
            "sale_profitability", "Sales", self.sale_id
        )
        thread.start()
        return True

    @Slot(object)
    def _on_load_finished(self, result):
        if not result:
            self._on_load_failed("The host returned no profitability data")
            return
        devis = result.get("devis") or ""
        title = f"Sale #{result.get('sale_id')}"
        if devis:
            title += f"   ({devis})"
        client = result.get("client_name") or ""
        if client:
            title += f"   -   {client}"
        self.header_label.setText(title)

        revenue = result.get("revenue_ht") or "0"
        cogs = result.get("cogs")
        profit = result.get("gross_profit")
        margin = result.get("gross_margin_pct")
        self.summary_labels["revenue_ht"].setText(f"{float(revenue):,.2f} MAD")
        self.summary_labels["cogs"].setText(
            f"{float(cogs):,.2f} MAD" if cogs is not None else "-"
        )
        profit_label = self.summary_labels["gross_profit"]
        if profit is None:
            profit_label.setText("-")
        else:
            profit_value = float(profit)
            profit_label.setText(f"{profit_value:,.2f} MAD")
            profit_label.setStyleSheet(
                f"font-size: 18px; font-weight: bold; "
                f"color: {_GREEN if profit_value >= 0 else _RED};"
            )
        self.summary_labels["gross_margin_pct"].setText(
            f"{margin}%" if margin is not None else "-"
        )

        items = result.get("items") or []
        self.table.setRowCount(0)
        for item in items:
            row_index = self.table.rowCount()
            self.table.insertRow(row_index)
            item_type = str(item.get("item_type") or "")
            avg_cost = item.get("avg_cost")
            line_profit = float(item.get("profit") or 0)
            values = [
                item_type.capitalize(),
                str(item.get("name") or ""),
                str(item.get("quantity") or "0"),
                f"{float(item.get('net_revenue') or 0):,.2f}",
                (
                    f"{float(avg_cost):,.2f}"
                    if avg_cost is not None else "n/a"
                ),
                f"{line_profit:,.2f}",
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column in (2, 3, 4, 5):
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if column == 5:
                    cell.setForeground(QColor(
                        _GREEN if line_profit >= 0 else _RED
                    ))
                self.table.setItem(row_index, column, cell)
        note = (
            "Services have no recorded cost in this application; their "
            "revenue counts fully toward profit."
            if any(str(i.get("item_type")) != "product" for i in items)
            else ""
        )
        self.status_label.setText(note or "")

    @Slot(str)
    def _on_load_failed(self, error):
        self.status_label.setText(f"Failed to load profitability: {error}")
        self.status_label.setStyleSheet("color: #f44336;")

    # ───────────────────────── thread lifecycle ──────────────────────────

    @Slot()
    def _on_thread_finished(self):
        self._thread = None
        self._worker = None

    def _wait_for_thread(self, timeout_ms=5000):
        thread = getattr(self, "_thread", None)
        if thread is None:
            return True
        try:
            if not shiboken6.isValid(thread) or not thread.isRunning():
                self._thread = None
                self._worker = None
                return True
        except RuntimeError:
            self._thread = None
            self._worker = None
            return True
        if thread == QThread.currentThread():
            return False
        thread.requestInterruption()
        thread.quit()
        if not thread.wait(timeout_ms):
            logger.error("Profitability thread did not stop in time")
            return False
        if getattr(self, "_thread", None) is thread:
            self._thread = None
            self._worker = None
        return True

    def closeEvent(self, event):
        self._wait_for_thread()
        super().closeEvent(event)


def show_sale_profitability(sale_id, database, parent=None):
    """Open the internal profitability view for one sale."""
    if database is None:
        QMessageBox.warning(parent, "Profitability", "No database connection.")
        return None
    dialog = SaleProfitabilityDialog(sale_id, database, parent)
    dialog.exec()
    return dialog
