import sys
from PySide6.QtWidgets import (QApplication, QTableWidget, 
                               QTableWidgetItem, QHeaderView, QVBoxLayout, 
                               QWidget, QLabel, QPushButton, QHBoxLayout,
                               QDialog, QComboBox, QMessageBox)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt
from core.database import Database
from ui.widgets.themed_widgets import RedButton, BlueButton




class InventoryApp(QWidget):
    def __init__(self, parent=None, section="Inventory", columns=None):
        super().__init__(parent)
        
        # Initialize database
        self.db = Database()
        self.section : str = section
        self.columns : list[str] = columns if columns else ["ID", "Company", "Role", "Product", "Price HT", "Price TTC", "Quantity", "Icon"]
        
        # Setup UI
        self.setup_ui()
        self.refresh_table()
        
        #MARK: theme
        self.setStyleSheet("""
            QMainWindow, QDialog { background-color: #2D2D30; color: #E0E0E0; }
            QLabel { color: #E0E0E0; }
            QTableWidget { 
                background-color: #2D2D30; gridline-color: #3E3E42; color: #E0E0E0;
                border: 1px solid #3E3E42; alternate-background-color: #252526;
            }
            QTableWidget::item:selected { background-color: #3E3E42; }
            QHeaderView::section { background-color: #252526; color: #CCCCCC; padding: 5px; border: none; }
        """)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Header
        header = QHBoxLayout()
        title = QLabel(self.section)
        title.setFont(QFont("Arial", 16, QFont.Bold))
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        
        # Buttons
        buttons = QHBoxLayout()
        
        Add_button = BlueButton("Add")
        Add_button.clicked.connect(self.add_item)
        buttons.addWidget(Add_button)
        Edit_button = BlueButton("Edit")
        Edit_button.clicked.connect(self.edit_item)
        buttons.addWidget(Edit_button)
        Delete_button = RedButton("Delete")
        Delete_button.clicked.connect(self.delete_item)
        buttons.addWidget(Delete_button)
        
        layout.addLayout(buttons)
        
        self.setup_table()
        layout.addWidget(self.table)

    #MARK: table (overwrite)
    def setup_table(self):
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(["ID", "Company", "Role", "Product", "Price HT", "Price TTC", "Quantity", "Icon"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setColumnHidden(0, True)
        self.table.verticalHeader().setVisible(False)


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
            
            
    def add_item(self):
        """overwrite the method in subclass"""
        pass
    
    def edit_item(self):
        """overwrite the method in subclass"""
        pass
    
    def delete_item(self):
        """overwrite the method in subclass"""
        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = InventoryApp()
    window.show()
    sys.exit(app.exec())