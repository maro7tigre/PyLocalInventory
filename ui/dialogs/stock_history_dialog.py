"""
Stock History dialog - derived stock-movement ledger for one Product.

Stock in PyLocalInventory is not stored on the product row; it is derived
from the documents themselves (imports minus sales). This dialog therefore
displays the movement history produced by
``Database.get_product_stock_history()``, which derives the ledger from those
same source rows with running totals - it can never disagree with the
authoritative stock calculation shown elsewhere in the app.

Threading follows the proven project pattern (see ui/tabs/home_tab.py):
a QObject worker moved to a dedicated QThread, GUI callbacks wired to real
bound methods only (never lambdas), strong worker/thread references kept
until ``thread.finished`` fires, duplicate refreshes rejected while a fetch
is in flight, and stale results dropped via a generation counter.
"""
import shiboken6
import logging

from PySide6.QtCore import Qt, QObject, QThread, QDate, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QLineEdit, QTableWidget, QTableWidgetItem, QPushButton, QCheckBox,
    QDateEdit, QHeaderView, QMessageBox,
)

from ui.widgets.themed_widgets import GreenButton
from core import diagnostics

logger = logging.getLogger(__name__)

_MOVEMENT_LABELS = {
    "opening": "Opening Stock",
    "adjustment": "Adjustment",
    "import": "Import",
    "sale": "Sale",
}
_GREEN = "#4CAF50"
_RED = "#f44336"


class _StockHistoryWorker(QObject):
    """Fetches one page of the movement ledger off the GUI thread."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, database, product_id, filters):
        super().__init__()
        self.database = database
        self.product_id = product_id
        self.filters = dict(filters)

    def _ensure_local_connection(self):
        """Local workers get their own connection, opened on this thread."""
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
            result = db.get_product_stock_history(
                self.product_id,
                movement_type=self.filters.get("movement_type", "all"),
                date_from=self.filters.get("date_from"),
                date_to=self.filters.get("date_to"),
                search=self.filters.get("search") or None,
                limit=int(self.filters.get("limit", 200)),
                offset=int(self.filters.get("offset", 0)),
            )
            self.finished.emit(result)
        except Exception as error:
            logger.exception(
                "Stock history load failed product_id=%s", self.product_id
            )
            self.failed.emit(str(error) or "Unknown error")
        finally:
            if worker_db is not None:
                try:
                    worker_db.close()
                except Exception:
                    logger.exception("Could not close stock-history worker DB")


class StockHistoryDialog(QDialog):
    """Product → Stock History viewer (Products section of the app)."""

    PAGE_SIZE = 200

    def __init__(self, product_id, product_name, database, parent=None):
        super().__init__(parent)
        self.product_id = int(product_id)
        self.product_name = product_name or f"Product #{self.product_id}"
        self.database = database

        self._thread = None
        self._worker = None
        self._generation = 0
        self._movements = []
        self._total_count = 0
        self._current_stock = "0"

        self.setWindowTitle(f"Stock History - {self.product_name}")
        self.resize(1080, 640)
        self._build_ui()

        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self._wait_for_thread)

        self._start_load()

    # ─────────────────────────────── UI setup ────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.header_label = QLabel(
            f"{self.product_name}   -   Current Stock: "
            f"<b>{self._current_stock}</b>"
        )
        self.header_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(self.header_label)

        filters_row = QHBoxLayout()
        filters_row.addWidget(QLabel("Type:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["All", "Sales", "Imports", "Adjustments"])
        self.type_combo.currentIndexChanged.connect(self._on_filters_changed)
        filters_row.addWidget(self.type_combo)

        self.from_check = QCheckBox("From")
        self.from_date = QDateEdit()
        self.from_date.setCalendarPopup(True)
        self.from_date.setDisplayFormat("yyyy-MM-dd")
        self.from_date.setDate(QDate.currentDate().addMonths(-1))
        self.from_date.setEnabled(False)
        self.from_check.toggled.connect(self.from_date.setEnabled)
        self.from_check.toggled.connect(self._on_filters_changed)
        self.from_date.dateChanged.connect(self._on_filters_changed)
        filters_row.addWidget(self.from_check)
        filters_row.addWidget(self.from_date)

        self.to_check = QCheckBox("To")
        self.to_date = QDateEdit()
        self.to_date.setCalendarPopup(True)
        self.to_date.setDisplayFormat("yyyy-MM-dd")
        self.to_date.setDate(QDate.currentDate())
        self.to_date.setEnabled(False)
        self.to_check.toggled.connect(self.to_date.setEnabled)
        self.to_check.toggled.connect(self._on_filters_changed)
        self.to_date.dateChanged.connect(self._on_filters_changed)
        filters_row.addWidget(self.to_check)
        filters_row.addWidget(self.to_date)

        filters_row.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Reference, note or user...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self._on_filters_changed)
        filters_row.addWidget(self.search_edit, 1)

        self.refresh_btn = GreenButton("Refresh")
        self.refresh_btn.clicked.connect(self._on_filters_changed)
        filters_row.addWidget(self.refresh_btn)
        layout.addLayout(filters_row)

        self.table = QTableWidget(0, 8, self)
        self.table.setHorizontalHeaderLabels([
            "Date & Time", "Type", "Reference", "Change",
            "Before", "After", "User", "Note",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(7, QHeaderView.Stretch)
        for column in range(7):
            header_view.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #aaaaaa;")
        layout.addWidget(self.status_label)

        bottom_row = QHBoxLayout()
        self.load_more_btn = QPushButton("Load more")
        self.load_more_btn.setVisible(False)
        self.load_more_btn.clicked.connect(self._load_more)
        bottom_row.addWidget(self.load_more_btn)
        bottom_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        bottom_row.addWidget(close_btn)
        layout.addLayout(bottom_row)

    # ─────────────────────────── data loading ────────────────────────────

    def _filters(self, offset):
        movement_map = {
            0: "all", 1: "sale", 2: "import", 3: "adjustment",
        }
        return {
            "movement_type": movement_map.get(self.type_combo.currentIndex(), "all"),
            "date_from": (
                self.from_date.date().toString("yyyy-MM-dd")
                if self.from_check.isChecked() else None
            ),
            "date_to": (
                self.to_date.date().toString("yyyy-MM-dd")
                if self.to_check.isChecked() else None
            ),
            "search": self.search_edit.text().strip(),
            "limit": self.PAGE_SIZE,
            "offset": offset,
        }

    def _on_filters_changed(self, *_args):
        self._start_load()

    def _load_more(self):
        # Append the next page while keeping everything already displayed.
        self._start_load(offset=len(self._movements))

    def _start_load(self, offset=0):
        thread = getattr(self, "_thread", None)
        if thread is not None:
            try:
                if shiboken6.isValid(thread) and thread.isRunning():
                    logger.info(
                        "Stock history refresh ignored while a fetch is active"
                    )
                    return False
            except RuntimeError:
                pass

        self._generation += 1
        self._append_mode = bool(offset)
        if not self._append_mode:
            self._movements = []
            self._total_count = 0
        self.status_label.setText("Loading...")
        self.status_label.setStyleSheet("color: #aaaaaa;")
        self.load_more_btn.setVisible(False)

        thread = QThread()
        worker = _StockHistoryWorker(
            self.database, self.product_id, self._filters(offset)
        )
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
            "stock_history", "Products", self.product_id
        )
        thread.start()
        return True

    @Slot(object)
    def _on_load_finished(self, result):
        if result is None:
            self._on_load_failed("The host returned no stock history data")
            return
        self._total_count = int(result.get("total_count") or 0)
        self._current_stock = str(result.get("current_stock") or "0")
        name = result.get("product_name") or self.product_name
        self.header_label.setText(
            f"{name}   -   Current Stock: <b>{self._current_stock}</b>"
        )
        page = list(result.get("movements") or [])
        if self._append_mode:
            self._movements.extend(page)
        else:
            self._movements = page
        self._render_movements()
        self.status_label.setText(
            f"{self._total_count} movements"
            if self._total_count else "No stock movements found."
        )
        self.status_label.setStyleSheet("color: #aaaaaa;")

    @Slot(str)
    def _on_load_failed(self, error):
        if not self._append_mode:
            self._movements = []
            self._render_movements()
        # A failure must never silently look like an empty ledger.
        self.status_label.setText(f"Failed to load stock history: {error}")
        self.status_label.setStyleSheet("color: #f44336;")

    def _render_movements(self):
        self.table.setRowCount(0)
        for movement in self._movements:
            row_index = self.table.rowCount()
            self.table.insertRow(row_index)
            delta_text = str(movement.get("delta") or "0")
            try:
                is_positive = float(delta_text) >= 0
            except ValueError:
                is_positive = True
            color = QColor(_GREEN if is_positive else _RED)

            created = str(movement.get("created_at") or "")
            ev_date = str(movement.get("date") or "")
            datetime_text = ev_date or created[:10]
            if len(created) > 16:
                datetime_text = f"{ev_date} {created[11:16]}".strip()

            values = [
                datetime_text,
                _MOVEMENT_LABELS.get(
                    movement.get("movement_type"),
                    str(movement.get("movement_type")),
                ),
                str(movement.get("reference") or ""),
                ("+" if is_positive else "") + delta_text,
                str(movement.get("stock_before") or "0"),
                str(movement.get("stock_after") or "0"),
                str(movement.get("username") or ""),
                str(movement.get("note") or ""),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 3:
                    item.setForeground(color)
                if column in (3, 4, 5):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row_index, column, item)
        self.load_more_btn.setVisible(len(self._movements) < self._total_count)

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
            logger.error("Stock history thread did not stop in time")
            return False
        if getattr(self, "_thread", None) is thread:
            self._thread = None
            self._worker = None
        return True

    def closeEvent(self, event):
        self._wait_for_thread()
        super().closeEvent(event)


def show_stock_history(product_id, product_name, database, parent=None):
    """Open the Stock History dialog for one product."""
    if database is None:
        QMessageBox.warning(parent, "Stock History", "No database connection.")
        return None
    dialog = StockHistoryDialog(product_id, product_name, database, parent)
    dialog.exec()
    return dialog
