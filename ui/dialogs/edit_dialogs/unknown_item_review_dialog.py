"""
Unknown Item Review Dialog - single review screen for sale lines that are not
linked to a Product or Service yet. The user decides for every line whether to
Add to Products, Add to Services, Keep only in this Sale, keep it as a Section,
or Cancel and edit.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QComboBox, QHeaderView,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from ui.widgets.themed_widgets import GreenButton, RedButton


class UnknownItemReviewDialog(QDialog):
    """Review dialog for unknown Product/Service names in a sale."""

    ACTION_LABELS = {
        "product": "Add to Products",
        "service": "Add to Services",
        "manual": "Keep only in this Sale",
        "section": "Section",
        "cancel": "Cancel and edit",
    }

    COLUMNS = ["Name", "Type", "Quantity", "Unit Price", "Action"]

    def __init__(self, unknown_items, parent=None):
        super().__init__(parent)
        self.unknown_items = unknown_items
        self.setWindowTitle("Review Unknown Items")
        self.resize(760, 380)
        self.setup_ui()
        self.apply_theme()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        intro = QLabel(
            "These lines are not linked to a Product or Service. "
            "Choose what to do with each one."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.table = QTableWidget(len(self.unknown_items), len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(self.COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        for row_index, item in enumerate(self.unknown_items):
            name_item = QTableWidgetItem(str(item.get("name") or ""))
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row_index, 0, name_item)

            entered_type = str(item.get("item_type") or "").casefold()
            type_label = {
                "product": "Product", "service": "Service", "manual": "Manual",
                "section": "Section",
            }.get(entered_type, "Not set")
            type_item = QTableWidgetItem(type_label)
            type_item.setFlags(type_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row_index, 1, type_item)

            quantity_item = QTableWidgetItem(str(item.get("quantity") or ""))
            quantity_item.setFlags(quantity_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row_index, 2, quantity_item)

            price_item = QTableWidgetItem(str(item.get("unit_price") or ""))
            price_item.setFlags(price_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row_index, 3, price_item)

            action = QComboBox()
            for value, label in self.ACTION_LABELS.items():
                action.addItem(label, value)
            default = entered_type if entered_type in self.ACTION_LABELS else "product"
            action.setCurrentIndex(action.findData(default))
            self.table.setCellWidget(row_index, 4, action)

        bulk_row = QHBoxLayout()
        bulk_label = QLabel("Apply to all:")
        self.bulk_selector = QComboBox()
        for value, label in self.ACTION_LABELS.items():
            self.bulk_selector.addItem(label, value)
        self.bulk_selector.setCurrentIndex(self.bulk_selector.findData("product"))
        bulk_btn = QPushButton("Apply")
        bulk_btn.clicked.connect(self._apply_to_all)
        bulk_row.addWidget(bulk_label)
        bulk_row.addWidget(self.bulk_selector)
        bulk_row.addWidget(bulk_btn)
        bulk_row.addStretch()
        layout.addLayout(bulk_row)

        button_row = QHBoxLayout()
        button_row.addStretch()
        self.save_btn = GreenButton("Continue")
        self.save_btn.clicked.connect(self._on_continue)
        button_row.addWidget(self.save_btn)
        self.cancel_btn = RedButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(self.cancel_btn)
        layout.addLayout(button_row)

    def _apply_to_all(self):
        value = self.bulk_selector.currentData()
        for row_index in range(self.table.rowCount()):
            combo = self.table.cellWidget(row_index, 4)
            if combo:
                combo.setCurrentIndex(combo.findData(value))

    def _on_continue(self):
        self.accept()

    def _decisions(self):
        decisions = {}
        for index in range(self.table.rowCount()):
            combo = self.table.cellWidget(index, 4)
            action = combo.currentData() if combo else "cancel"
            decisions[index] = str(action or "cancel")
        return decisions

    def get_decisions(self):
        """Return a list parallel to unknown_items with the chosen action."""
        return [
            {
                "name": str(self.unknown_items[index].get("name") or ""),
                "action": self._decisions()[index],
            }
            for index in range(self.table.rowCount())
        ]

    def apply_theme(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
            }
            QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QTableWidget {
                background-color: #3c3c3c;
                gridline-color: #555555;
            }
            QHeaderView::section {
                background-color: #4c4c4c;
                color: #ffffff;
            }
        """)
