"""
Imports tab - import operations and supplier transactions
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QMessageBox, QTableWidgetItem
from ui.widgets.table_widgets import TableWidget
from ui.widgets.preview_widget import PreviewWidget
from ui.dialogs.edit_dialogs.import_dialog import ImportEditDialog


class ImportsTableWidget(TableWidget):
    """Specialized table widget for imports"""
    
    def __init__(self, database=None, parent=None):
        columns = ["ID", "supplier_preview", "supplier_name", "product", "quantity", "unit price", "tva", "total price", "date"]
        super().__init__("Imports", database, columns, parent)
    
    def refresh_table(self):
        """Refresh table with joined supplier and product data"""
        if not self.database:
            return
        
        # Get imports with supplier and product info
        query = """
        SELECT i.ID, s.preview_image, s.name as supplier_name, p.name as product_name,
               i.quantity, i.unit_price, i.tva, i.total_price, i.date
        FROM Imports i
        JOIN Suppliers s ON i.supplier_id = s.ID
        JOIN Products p ON i.product_id = p.ID
        ORDER BY i.date DESC
        """
        
        try:
            self.database.cursor.execute(query)
            items = self.database.cursor.fetchall()
            
            self.table.setRowCount(len(items))
            
            for row, item in enumerate(items):
                for col, value in enumerate(item):
                    if col == 1:  # supplier_preview column
                        preview_widget = PreviewWidget(50, "company")
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
            print(f"Error refreshing imports table: {e}")
    
    def add_item(self):
        """Open import creation dialog"""
        
        dialog = ImportEditDialog(database=self.database, parent=self)
        if dialog.exec():
            self.refresh_table()
    
    def edit_item(self):
        """Open import edit dialog"""
        import_id = self.get_selected_id()
        if import_id is None:
            QMessageBox.warning(self, "Error", "Please select an import to edit")
            return

        dialog = ImportEditDialog(import_id=import_id, database=self.database, parent=self)
        if dialog.exec():
            self.refresh_table()
    
    def show_report(self):
        """Show import report (override to disable for imports)"""
        QMessageBox.information(self, "Info", "Import reports not available")


class ImportsTab(QWidget):
    def __init__(self, database=None):
        super().__init__()
        self.database = database
        self.setup_ui()
    
    def setup_ui(self):
        """Setup imports tab interface"""
        layout = QVBoxLayout(self)
        
        # Use table widget
        self.imports_table = ImportsTableWidget(self.database, self)
        layout.addWidget(self.imports_table)