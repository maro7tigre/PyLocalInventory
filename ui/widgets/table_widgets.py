import sys
import sqlite3
from PySide6.QtWidgets import (QApplication, QMainWindow, QTableWidget, 
                               QTableWidgetItem, QHeaderView, QVBoxLayout, 
                               QWidget, QLabel, QPushButton, QHBoxLayout,
                               QDialog, QLineEdit, QComboBox, QSpinBox,
                               QDoubleSpinBox, QDialogButtonBox, QMessageBox)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt

# Currency settings
CURRENCY_RATES = {"USD": 1.0, "MAD": 9.8, "EUR": 0.92}
CURRENCY_SYMBOLS = {"USD": "$", "MAD": "MAD", "EUR": "€"}

class Database:
    def __init__(self, db_name="inventory.db"):
        self.conn = sqlite3.connect(db_name)
        self.cursor = self.conn.cursor()
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT, role TEXT, product TEXT,
                price_ht REAL, price_ttc REAL, quantity INTEGER,
                currency TEXT DEFAULT 'USD'
            )
        ''')
        self.conn.commit()

    def get_products(self):
        self.cursor.execute("SELECT * FROM products")
        columns = [col[0] for col in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def add_product(self, data):
        self.cursor.execute('''
            INSERT INTO products (company, role, product, price_ht, price_ttc, quantity, currency)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (data["company"], data["role"], data["product"], data["price_ht"], 
              data["price_ttc"], data["quantity"], data["currency"]))
        self.conn.commit()
        return self.cursor.lastrowid

    def update_product(self, product_id, data):
        self.cursor.execute('''
            UPDATE products SET company=?, role=?, product=?, price_ht=?, price_ttc=?, quantity=?, currency=?
            WHERE id=?
        ''', (data["company"], data["role"], data["product"], data["price_ht"], 
              data["price_ttc"], data["quantity"], data["currency"], product_id))
        self.conn.commit()

    def delete_product(self, product_id):
        self.cursor.execute("DELETE FROM products WHERE id=?", (product_id,))
        self.conn.commit()

class ProductDialog(QDialog):
    def __init__(self, parent=None, product=None):
        super().__init__(parent)
        self.setWindowTitle("Add Product" if not product else "Edit Product")
        self.setMinimumWidth(300)
        
        layout = QVBoxLayout(self)
        self.fields = {}
        
        # Create form fields
        for label in ["Company", "Product"]:
            self.fields[label.lower()] = QLineEdit()
            layout.addWidget(QLabel(f"{label}:"))
            layout.addWidget(self.fields[label.lower()])
        
        self.fields["role"] = QComboBox()
        self.fields["role"].addItems(["Buyer", "Seller"])
        layout.addWidget(QLabel("Role:"))
        layout.addWidget(self.fields["role"])
        
        for label in ["Price HT", "Price TTC"]:
            self.fields[label.lower().replace(" ", "_")] = QDoubleSpinBox()
            self.fields[label.lower().replace(" ", "_")].setMaximum(10000)
            layout.addWidget(QLabel(f"{label}:"))
            layout.addWidget(self.fields[label.lower().replace(" ", "_")])
        
        self.fields["quantity"] = QSpinBox()
        self.fields["quantity"].setMaximum(1000)
        layout.addWidget(QLabel("Quantity:"))
        layout.addWidget(self.fields["quantity"])
        
        self.fields["currency"] = QComboBox()
        self.fields["currency"].addItems(["USD", "MAD", "EUR"])
        layout.addWidget(QLabel("Currency:"))
        layout.addWidget(self.fields["currency"])
        
        # Set values if editing
        if product:
            for key, value in product.items():
                if key in self.fields:
                    if isinstance(self.fields[key], QComboBox):
                        self.fields[key].setCurrentText(str(value))
                    else:
                        self.fields[key].setValue(value) if hasattr(self.fields[key], 'setValue') else self.fields[key].setText(str(value))
        
        # Dialog buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self):
        return {
            "company": self.fields["company"].text(),
            "role": self.fields["role"].currentText(),
            "product": self.fields["product"].text(),
            "price_ht": self.fields["price_ht"].value(),
            "price_ttc": self.fields["price_ttc"].value(),
            "quantity": self.fields["quantity"].value(),
            "currency": self.fields["currency"].currentText()
        }

class InventoryApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Inventory Management")
        self.setGeometry(100, 100, 1000, 500)
        
        # Initialize database
        self.db = Database()
        self.display_currency = "USD"
        
        # Setup UI
        self.setup_ui()
        self.refresh_table()
        
        # Apply dark theme
        self.setStyleSheet("""
            QMainWindow, QDialog { background-color: #2D2D30; color: #E0E0E0; }
            QLabel { color: #E0E0E0; }
            QTableWidget { 
                background-color: #2D2D30; gridline-color: #3E3E42; color: #E0E0E0;
                border: 1px solid #3E3E42; alternate-background-color: #252526;
            }
            QTableWidget::item:selected { background-color: #3E3E42; }
            QHeaderView::section { background-color: #252526; color: #CCCCCC; padding: 5px; border: none; }
            QPushButton { 
                background-color: #0E639C; color: white; border: none; 
                padding: 8px 16px; border-radius: 4px; 
            }
            QPushButton:hover { background-color: #1177BB; }
            QPushButton#delete { background-color: #C42B1C; }
            QPushButton#delete:hover { background-color: #E02F1E; }
        """)

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # Header
        header = QHBoxLayout()
        title = QLabel("Inventory Overview")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        header.addWidget(title)
        
        header.addStretch()
        header.addWidget(QLabel("Currency:"))
        self.currency_combo = QComboBox()
        self.currency_combo.addItems(["USD", "MAD", "EUR"])
        self.currency_combo.currentTextChanged.connect(self.change_currency)
        header.addWidget(self.currency_combo)
        layout.addLayout(header)
        
        # Buttons
        buttons = QHBoxLayout()
        for text, slot in [("Add", self.add_product), ("Edit", self.edit_product), ("Delete", self.delete_product)]:
            btn = QPushButton(text)
            if text == "Delete": btn.setObjectName("delete")
            btn.clicked.connect(slot)
            buttons.addWidget(btn)
        layout.addLayout(buttons)
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(["ID", "Company", "Role", "Product", "Price HT", "Price TTC", "Quantity", "Icon"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setColumnHidden(0, True)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

    def convert_currency(self, amount, from_currency, to_currency):
        return amount if from_currency == to_currency else (amount / CURRENCY_RATES[from_currency]) * CURRENCY_RATES[to_currency]

    def refresh_table(self):
        products = self.db.get_products()
        self.table.setRowCount(len(products))
        
        for row, product in enumerate(products):
            self.table.setItem(row, 0, QTableWidgetItem(str(product["id"])))
            self.table.setItem(row, 1, QTableWidgetItem(product["company"]))
            self.table.setItem(row, 2, QTableWidgetItem(product["role"]))
            self.table.setItem(row, 3, QTableWidgetItem(product["product"]))
            
            # Convert and display prices
            product_currency = product.get("currency", "USD")
            price_ht = self.convert_currency(product["price_ht"], product_currency, self.display_currency)
            price_ttc = self.convert_currency(product["price_ttc"], product_currency, self.display_currency)
            
            symbol = CURRENCY_SYMBOLS[self.display_currency]
            self.table.setItem(row, 4, QTableWidgetItem(f"{symbol} {price_ht:.2f}"))
            self.table.setItem(row, 5, QTableWidgetItem(f"{symbol} {price_ttc:.2f}"))
            self.table.setItem(row, 6, QTableWidgetItem(str(product["quantity"])))
            
            # Icon column with package emoji
            icon_item = QTableWidgetItem("📦")
            icon_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 7, icon_item)

    def change_currency(self, currency):
        self.display_currency = currency
        self.refresh_table()

    def add_product(self):
        dialog = ProductDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.db.add_product(dialog.get_data())
            self.refresh_table()

    def get_selected_id(self):
        row = self.table.currentRow()
        return int(self.table.item(row, 0).text()) if row != -1 else None

    def edit_product(self):
        if (product_id := self.get_selected_id()) is None:
            QMessageBox.warning(self, "Error", "Please select a product")
            return
            
        products = self.db.get_products()
        product = next((p for p in products if p["id"] == product_id), None)
        if product:
            dialog = ProductDialog(self, product)
            if dialog.exec() == QDialog.Accepted:
                self.db.update_product(product_id, dialog.get_data())
                self.refresh_table()

    def delete_product(self):
        if (product_id := self.get_selected_id()) is None:
            QMessageBox.warning(self, "Error", "Please select a product")
            return
            
        if QMessageBox.question(self, "Confirm", "Delete this product?") == QMessageBox.Yes:
            self.db.delete_product(product_id)
            self.refresh_table()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = InventoryApp()
    window.show()
    sys.exit(app.exec())