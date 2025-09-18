"""
Products tab - product management interface and inventory overview
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QMessageBox, QTableWidgetItem
from ui.widgets.table_widgets import TableWidget
from ui.dialogs.edit_dialogs.product_dialog import ProductEditDialog
from classes.product_class import ProductClass


class ProductsTableWidget(TableWidget):
    """Specialized table widget for products with quantity calculation"""
    
    def __init__(self, database=None, parent=None):
        columns = ["ID", "name", "unit price", "sale price", "quantity"]
        super().__init__("Products", database, columns, parent)
    
    def refresh_table(self):
        """Refresh table data with calculated quantities"""
        if not self.database:
            return
        
        items = self.database.get_items(self.section)
        self.table.setRowCount(len(items))
        
        for row, item in enumerate(items):
            for col, column_name in enumerate(self.columns):
                if column_name == "quantity":
                    # Calculate quantity using ProductClass
                    product = ProductClass(item["ID"], self.database, item["name"])
                    quantity = product.get_quantity()
                    self.table.setItem(row, col, QTableWidgetItem(str(quantity)))
                elif column_name in ["unit price", "sale price"]:
                    # Format prices with currency
                    value = item.get(column_name, 0)
                    formatted_value = f"€{float(value):.2f}" if value else "€0.00"
                    self.table.setItem(row, col, QTableWidgetItem(formatted_value))
                else:
                    value = item.get(column_name, "")
                    self.table.setItem(row, col, QTableWidgetItem(str(value)))
    
    def add_item(self):
        """Open product creation dialog"""
        dialog = ProductEditDialog(database=self.database, parent=self)
        if dialog.exec():
            self.refresh_table()
    
    def edit_item(self):
        """Open product edit dialog"""
        product_id = self.get_selected_id()
        if product_id is None:
            QMessageBox.warning(self, "Error", "Please select a product to edit")
            return
        
        dialog = ProductEditDialog(product_id=product_id, database=self.database, parent=self)
        if dialog.exec():
            self.refresh_table()


class ProductsTab(QWidget):
    def __init__(self, database=None):
        super().__init__()
        self.database = database
        self.setup_ui()
    
    def setup_ui(self):
        """Setup products tab interface"""
        layout = QVBoxLayout(self)
        
        # Use  table widget
        self.products_table = ProductsTableWidget(self.database, self)
        layout.addWidget(self.products_table)