"""Client account view with purchases, payments, and balance tracking."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from ui.widgets.preview_widget import PreviewWidget


def _format_money(value):
    return f"{float(value or 0):,.2f}".replace(",", " ")


class ClientDetailsDialog(QDialog):
    """Show a client's purchases, payment history, and account balance."""

    def __init__(self, client_obj, database, parent=None):
        super().__init__(parent)
        self.client_obj = client_obj
        self.database = database
        self.purchases = []
        self.setWindowTitle(
            f"Client Account - {client_obj.get_value('name') or client_obj.get_value('username')}"
        )
        self.setMinimumSize(1250, 800)
        self._ensure_payments_table()
        self._setup_ui()
        self.refresh_data()

    def _ensure_payments_table(self):
        self.database.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS Payments (
                ID INTEGER PRIMARY KEY AUTOINCREMENT,
                sale_id INTEGER,
                sales_item_id INTEGER,
                amount REAL,
                date TEXT,
                FOREIGN KEY (sale_id) REFERENCES Sales(ID) ON DELETE CASCADE,
                FOREIGN KEY (sales_item_id) REFERENCES Sales_Items(ID) ON DELETE CASCADE
            )
            """
        )
        self.database.cursor.execute("PRAGMA table_info('Payments')")
        columns = {row[1] for row in self.database.cursor.fetchall()}
        if "sales_item_id" not in columns:
            self.database.cursor.execute(
                "ALTER TABLE Payments ADD COLUMN sales_item_id INTEGER"
            )
        self.database.conn.commit()

    def _setup_ui(self):
        window_layout = QVBoxLayout(self)
        window_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        content.setMinimumWidth(1180)
        root = QVBoxLayout(content)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel(self.client_obj.get_value("name") or "Client")
        title.setStyleSheet("font-size:22px; font-weight:bold; color:#fff;")
        root.addWidget(title)

        info = QFrame()
        info.setObjectName("clientInfo")
        info_container = QHBoxLayout(info)
        info_container.setContentsMargins(12, 10, 12, 10)
        info_container.setSpacing(16)

        preview = PreviewWidget(120, "individual")
        image_path = self.client_obj.get_value("preview_image")
        if image_path:
            preview.set_image_path(image_path)
        info_container.addWidget(preview, 0, Qt.AlignTop)

        info_fields = QWidget()
        info_layout = QFormLayout(info_fields)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setHorizontalSpacing(20)
        for label, key in (
            ("Client ID", "id"),
            ("Username", "username"),
            ("Client Type", "client_type"),
            ("Phone", "phone"),
            ("Email", "email"),
            ("Address", "address"),
            ("Notes", "notes"),
        ):
            value = QLabel(str(self.client_obj.get_value(key) or "-"))
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value.setWordWrap(True)
            info_layout.addRow(f"{label}:", value)
        info_container.addWidget(info_fields, 1)
        root.addWidget(info)

        totals = QHBoxLayout()
        self.total_bought_label = self._summary_value(totals, "Total Bought")
        self.total_paid_label = self._summary_value(totals, "Total Paid")
        self.remaining_label = self._summary_value(totals, "Remaining")
        root.addLayout(totals)

        purchases_title = QLabel("Purchases")
        purchases_title.setStyleSheet("font-size:16px; font-weight:bold;")
        root.addWidget(purchases_title)

        self.purchases_table = self._create_table(
            [
                "Sale",
                "Date",
                "Product / Service",
                "Quantity",
                "Unit Price",
                "State",
                "Total",
            ]
        )
        self.purchases_table.setMinimumHeight(320)
        self.purchases_table.verticalHeader().setDefaultSectionSize(44)
        root.addWidget(self.purchases_table, 3)

        payments_title = QLabel("Payment History")
        payments_title.setStyleSheet("font-size:16px; font-weight:bold;")
        root.addWidget(payments_title)

        self.payments_table = self._create_table(
            ["Payment", "Sale", "Date", "Amount"]
        )
        self.payments_table.setMinimumHeight(260)
        self.payments_table.verticalHeader().setDefaultSectionSize(44)
        root.addWidget(self.payments_table, 2)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)

        controls = QHBoxLayout()
        controls.addStretch()
        controls.addWidget(close_button)
        root.addLayout(controls)

        scroll_area.setWidget(content)
        window_layout.addWidget(scroll_area)

        self.setStyleSheet(
            """
            QDialog { background:#252525; color:#eee; }
            #clientInfo { background:#2d2d2d; border:1px solid #444; border-radius:6px; }
            QLabel { color:#eee; }
            QTableWidget {
                background:#2a2a2a; color:#eee; gridline-color:#444;
                border:1px solid #444; selection-background-color:#1565C0;
            }
            QHeaderView::section {
                background:#333; color:#fff; border:1px solid #444;
                padding:6px; font-weight:bold;
            }
            QLineEdit, QDateEdit {
                background:#333; color:#fff; border:1px solid #555;
                padding:6px; min-height:24px;
            }
            QLineEdit:focus, QDateEdit:focus { border:2px solid #2196F3; }
            QPushButton {
                background:#1565C0; color:#fff; border:none;
                border-radius:5px; padding:8px 14px;
            }
            QPushButton:hover { background:#1976D2; }
            """
        )

    def _summary_value(self, layout, title):
        block = QFrame()
        block.setObjectName("clientInfo")
        block_layout = QVBoxLayout(block)
        block_layout.setContentsMargins(12, 8, 12, 8)
        caption = QLabel(title)
        caption.setStyleSheet("color:#aaa; font-size:12px;")
        value = QLabel("0.00 MAD")
        value.setStyleSheet("font-size:18px; font-weight:bold;")
        block_layout.addWidget(caption)
        block_layout.addWidget(value)
        layout.addWidget(block)
        return value

    def _create_table(self, headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().hide()
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.horizontalHeader().setMinimumSectionSize(110)
        table.horizontalHeader().setDefaultSectionSize(150)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        if len(headers) > 2:
            table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        return table

    def _load_purchases(self):
        username = self.client_obj.get_value("username") or ""
        name = self.client_obj.get_value("name") or ""
        self.database.cursor.execute(
            """
            SELECT
                s.ID,
                COALESCE(s.date, ''),
                COALESCE(s.state, 'pending'),
                si.ID,
                COALESCE(si.product_name, ''),
                COALESCE(si.quantity, 0),
                COALESCE(si.unit_price, 0),
                COALESCE(s.tva, 0)
            FROM Sales s
            JOIN Sales_Items si ON si.sales_id = s.ID
            WHERE s.client_username = ?
               OR (COALESCE(s.client_username, '') = '' AND s.client_name = ?)
            ORDER BY s.ID, si.ID
            """,
            (username, name),
        )
        rows = self.database.cursor.fetchall()
        purchases = []
        sale_ids = set()
        for sale_id, date, state, item_id, product, quantity, unit_price, vat in rows:
            total = float(quantity or 0) * float(unit_price or 0)
            total *= 1 + float(vat or 0) / 100
            sale_ids.add(sale_id)
            purchases.append(
                {
                    "sale_id": sale_id,
                    "item_id": item_id,
                    "date": date,
                    "state": state,
                    "product": product,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "total": total,
                    "paid": 0.0,
                    "remaining": total,
                }
            )

        if not sale_ids:
            return purchases

        placeholders = ",".join("?" for _ in sale_ids)
        self.database.cursor.execute(
            f"""
            SELECT sale_id, sales_item_id, COALESCE(SUM(amount), 0)
            FROM Payments
            WHERE sale_id IN ({placeholders})
            GROUP BY sale_id, sales_item_id
            """,
            list(sale_ids),
        )
        targeted = {}
        legacy_by_sale = {}
        for sale_id, item_id, amount in self.database.cursor.fetchall():
            if item_id is None:
                legacy_by_sale[sale_id] = float(amount or 0)
            else:
                targeted[item_id] = float(amount or 0)

        for purchase in purchases:
            purchase["paid"] = min(targeted.get(purchase["item_id"], 0.0), purchase["total"])
            purchase["remaining"] = max(purchase["total"] - purchase["paid"], 0)

        # Payments created before item-level tracking are applied in item order.
        for sale_id, legacy_amount in legacy_by_sale.items():
            amount_left = legacy_amount
            for purchase in purchases:
                if purchase["sale_id"] != sale_id or amount_left <= 0:
                    continue
                allocation = min(purchase["remaining"], amount_left)
                purchase["paid"] += allocation
                purchase["remaining"] -= allocation
                amount_left -= allocation

        return purchases

    def refresh_data(self):
        self.purchases = self._load_purchases()
        self._populate_purchases()
        self._populate_payments()

        total_bought = sum(purchase["total"] for purchase in self.purchases)
        total_paid = sum(purchase["paid"] for purchase in self.purchases)
        remaining = max(total_bought - total_paid, 0)

        self.total_bought_label.setText(f"{_format_money(total_bought)} MAD")
        self.total_paid_label.setText(f"{_format_money(total_paid)} MAD")
        self.total_paid_label.setStyleSheet("font-size:18px; font-weight:bold; color:#4CAF50;")
        self.remaining_label.setText(f"{_format_money(remaining)} MAD")
        color = "#4CAF50" if remaining <= 0 else "#FF9800"
        self.remaining_label.setStyleSheet(f"font-size:18px; font-weight:bold; color:{color};")

    def _populate_purchases(self):
        self.purchases_table.setRowCount(len(self.purchases))
        for row, purchase in enumerate(self.purchases):
            values = [
                f"#{purchase['sale_id']}",
                purchase["date"],
                purchase["product"] or "-",
                str(purchase["quantity"]),
                _format_money(purchase["unit_price"]),
                str(purchase["state"]).replace("_", " ").title(),
                _format_money(purchase["total"]),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, purchase["item_id"])
                item.setData(Qt.UserRole + 1, purchase["sale_id"])
                if col >= 4 and col != 5:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.purchases_table.setItem(row, col, item)

    def _populate_payments(self):
        sale_ids = sorted({purchase["sale_id"] for purchase in self.purchases})
        if not sale_ids:
            self.payments_table.setRowCount(0)
            return

        placeholders = ",".join("?" for _ in sale_ids)
        self.database.cursor.execute(
            f"""
            SELECT p.ID, p.sale_id, p.date, p.amount
            FROM Payments p
            WHERE p.sale_id IN ({placeholders})
            ORDER BY p.ID DESC
            """,
            sale_ids,
        )
        rows = self.database.cursor.fetchall()
        self.payments_table.setRowCount(len(rows))
        for row_index, (payment_id, sale_id, date, amount) in enumerate(rows):
            values = [f"#{payment_id}", f"#{sale_id}", date, _format_money(amount)]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 3:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    item.setForeground(QColor("#4CAF50"))
                self.payments_table.setItem(row_index, col, item)
