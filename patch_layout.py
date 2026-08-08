import sys

with open("ui/dialogs/client_details_dialog.py", "r", encoding="utf-8") as f:
    content = f.read()

# Replace the layout logic
old_layout = """        self.purchases_table = self._create_table(
            [
                "Sale",
                "Date",
                "Product / Service",
                "Quantity",
                "Unit Price",
                "State",
                "Total",
                "Paid",
                "Remaining",
            ]
        )
        self.purchases_table.currentCellChanged.connect(self._purchase_selected)
        self.purchases_table.setMinimumHeight(220)
        self.purchases_table.verticalHeader().setDefaultSectionSize(38)
        root.addWidget(self.purchases_table, 3)

        payments_title = QLabel("Payment History")
        payments_title.setStyleSheet("font-size:16px; font-weight:bold;")
        root.addWidget(payments_title)

        self.payments_table = self._create_table(
            ["Payment", "Sale", "Date", "Amount", "Purchase"]
        )
        root.addWidget(self.payments_table, 2)"""

new_layout = """        from PySide6.QtWidgets import QSplitter, QWidget, QHeaderView
        from PySide6.QtCore import Qt

        # Purchases Section
        purchases_widget = QWidget()
        purchases_layout = QVBoxLayout(purchases_widget)
        purchases_layout.setContentsMargins(0, 0, 0, 0)
        
        self.purchases_table = self._create_table(
            [
                "Sale",
                "Date",
                "Product / Service",
                "Quantity",
                "Unit Price",
                "State",
                "Total",
                "Paid",
                "Remaining",
            ]
        )
        p_header = self.purchases_table.horizontalHeader()
        p_header.setSectionResizeMode(2, QHeaderView.Stretch)
        for col in [0, 1, 3, 4, 5, 6, 7, 8]:
            p_header.setSectionResizeMode(col, QHeaderView.ResizeToContents)

        self.purchases_table.currentCellChanged.connect(self._purchase_selected)
        self.purchases_table.setMinimumHeight(150)
        self.purchases_table.verticalHeader().setDefaultSectionSize(38)
        purchases_layout.addWidget(self.purchases_table, 1)

        # Payments Section
        payments_widget = QWidget()
        payments_layout = QVBoxLayout(payments_widget)
        payments_layout.setContentsMargins(0, 0, 0, 0)

        payments_title = QLabel("Payment History")
        payments_title.setStyleSheet("font-size:16px; font-weight:bold;")
        payments_layout.addWidget(payments_title)

        self.payments_table = self._create_table(
            ["Payment", "Sale", "Date", "Amount", "Purchase"]
        )
        pay_header = self.payments_table.horizontalHeader()
        pay_header.setSectionResizeMode(4, QHeaderView.Stretch)
        for col in [0, 1, 2, 3]:
            pay_header.setSectionResizeMode(col, QHeaderView.ResizeToContents)

        self.payments_table.setMinimumHeight(120)
        self.payments_table.verticalHeader().setDefaultSectionSize(38)
        payments_layout.addWidget(self.payments_table, 1)

        # Splitter
        table_splitter = QSplitter(Qt.Vertical)
        table_splitter.addWidget(purchases_widget)
        table_splitter.addWidget(payments_widget)
        table_splitter.setStretchFactor(0, 2)
        table_splitter.setStretchFactor(1, 1)
        root.addWidget(table_splitter, 1)"""

content = content.replace(old_layout, new_layout)
with open("ui/dialogs/client_details_dialog.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Updated successfully")
