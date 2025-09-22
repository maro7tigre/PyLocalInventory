"""
Sales tab - sales operations and client transactions
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QMessageBox, QTableWidgetItem
from ui.widgets.table_widgets import TableWidget
from ui.widgets.preview_widget import PreviewWidget
from ui.dialogs.edit_dialogs.sale_dialog import SaleEditDialog


class SalesTableWidget(TableWidget):
    """Specialized table widget for sales"""
    
    def __init__(self, database=None, parent=None):
        columns = ["ID", "client_preview", "client_name", "product", "quantity", "unit price", "tva", "total price", "date"]
        super().__init__("Sales", database, columns, parent)
    
    def refresh_table(self):
        """Refresh table with joined client and product data"""
        if not self.database:
            return
        
        # Get sales with client and product info
        query = """
        SELECT s.ID, c.preview_image, c.name as client_name, p.name as product_name,
               s.quantity, s.unit_price, s.tva, s.total_price, s.date
        FROM Sales s
        JOIN Clients c ON s.client_id = c.ID
        JOIN Products p ON s.product_id = p.ID
        ORDER BY s.date DESC
        """
        
        try:
            self.database.cursor.execute(query)
            items = self.database.cursor.fetchall()
            
            self.table.setRowCount(len(items))
            
            for row, item in enumerate(items):
                for col, value in enumerate(item):
                    if col == 1:  # client_preview column
                        preview_widget = PreviewWidget(50, "individual")
                        if value:  # If there's a preview image path
                            preview_widget.set_image_path(value)
                        self.table.setCellWidget(row, col, preview_widget)
                    elif col in [4, 5, 6, 7]:  # quantity, unit_price, tva, total_price
                        if col == 6:  # tva
                            formatted_value = f"{float(value):.1f}%" if value else "0.0%"
                        elif col in [5, 7]:  # prices
                            formatted_value = f"€{float(value):.2f}" if value else "€0.00"
                        else:  # quantity
                            formatted_value = str(int(value)) if value else "0"
                        self.table.setItem(row, col, QTableWidgetItem(formatted_value))
                    else:
                        self.table.setItem(row, col, QTableWidgetItem(str(value) if value else ""))
                        
        except Exception as e:
            print(f"Error refreshing sales table: {e}")
    
    def add_item(self):
        """Open sale creation dialog"""
        dialog = SaleEditDialog(database=self.database, parent=self)
        if dialog.exec():
            self.refresh_table()
    
    def edit_item(self):
        """Open sale edit dialog"""
        sale_id = self.get_selected_id()
        if sale_id is None:
            QMessageBox.warning(self, "Error", "Please select a sale to edit")
            return
        
        dialog = SaleEditDialog(sale_id=sale_id, database=self.database, parent=self)
        if dialog.exec():
            self.refresh_table()
    
    def show_report(self):
        """Show sale report (override to disable for sales)"""
        QMessageBox.information(self, "Info", "Sale reports not available")


class SalesTab(QWidget):
    def __init__(self, database=None):
        super().__init__()
        self.database = database
        self.setup_ui()
    
    def setup_ui(self):
        """Setup sales tab interface"""
        layout = QVBoxLayout(self)
        
        # Use table widget
        self.sales_table = SalesTableWidget(self.database, self)
        layout.addWidget(self.sales_table)