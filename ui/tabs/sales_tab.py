"""
Sales tab - sales operations and client transactions
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout
from ui.widgets.table_widgets import ParameterTableWidget
from classes.sales_class import SalesClass
from ui.dialogs.edit_dialogs.sale_dialog import SaleEditDialog


class SalesTableWidget(ParameterTableWidget):
    """Specialized table widget for sales"""
    
    def __init__(self, database=None, parent=None):
        super().__init__(SalesClass, database, SaleEditDialog, parent)


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