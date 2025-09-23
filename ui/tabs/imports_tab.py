"""
Imports tab - import operations and supplier transactions
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout
from ui.widgets.table_widgets import ParameterTableWidget
from classes.import_class import ImportClass
from ui.dialogs.edit_dialogs.import_dialog import ImportEditDialog


class ImportsTableWidget(ParameterTableWidget):
    """Specialized table widget for imports"""
    
    def __init__(self, database=None, parent=None):
        super().__init__(ImportClass, database, ImportEditDialog, parent)


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