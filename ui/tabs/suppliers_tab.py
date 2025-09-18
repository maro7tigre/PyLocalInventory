"""
Suppliers tab - supplier management and procurement tracking
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QMessageBox
from ui.widgets.table_widgets import TableWidget
from ui.dialogs.edit_dialogs.supplier_dialog import SupplierEditDialog


class SuppliersTableWidget(TableWidget):
    """Specialized table widget for suppliers"""
    
    def __init__(self, database=None, parent=None):
        columns = ["ID", "preview image", "name", "display name"]
        super().__init__("Suppliers", database, columns, parent)
    
    def add_item(self):
        """Open supplier creation dialog"""
        dialog = SupplierEditDialog(database=self.database, parent=self)
        if dialog.exec():
            self.refresh_table()
    
    def edit_item(self):
        """Open supplier edit dialog"""
        supplier_id = self.get_selected_id()
        if supplier_id is None:
            QMessageBox.warning(self, "Error", "Please select a supplier to edit")
            return
        
        dialog = SupplierEditDialog(supplier_id=supplier_id, database=self.database, parent=self)
        if dialog.exec():
            self.refresh_table()


class SuppliersTab(QWidget):
    def __init__(self, database=None):
        super().__init__()
        self.database = database
        self.setup_ui()
    
    def setup_ui(self):
        """Setup suppliers tab interface"""
        layout = QVBoxLayout(self)
        
        # Use table widget
        self.suppliers_table = SuppliersTableWidget(self.database, self)
        layout.addWidget(self.suppliers_table)