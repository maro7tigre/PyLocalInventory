"""
Clients tab - client management and relationship tracking
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QMessageBox
from ui.widgets.table_widgets import TableWidget
from ui.dialogs.edit_dialogs.client_dialog import ClientEditDialog


class ClientsTableWidget(TableWidget):
    """Specialized table widget for clients"""
    
    def __init__(self, database=None, parent=None):
        columns = ["ID", "preview image", "name", "display name", "client type"]
        super().__init__("Clients", database, columns, parent)
    
    def add_item(self):
        """Open client creation dialog"""
        dialog = ClientEditDialog(database=self.database, parent=self)
        if dialog.exec():
            self.refresh_table()
    
    def edit_item(self):
        """Open client edit dialog"""
        client_id = self.get_selected_id()
        if client_id is None:
            QMessageBox.warning(self, "Error", "Please select a client to edit")
            return
        
        dialog = ClientEditDialog(client_id=client_id, database=self.database, parent=self)
        if dialog.exec():
            self.refresh_table()


class ClientsTab(QWidget):
    def __init__(self, database=None):
        super().__init__()
        self.database = database
        self.setup_ui()
    
    def setup_ui(self):
        """Setup clients tab interface"""
        layout = QVBoxLayout(self)
        
        # Use table widget
        self.clients_table = ClientsTableWidget(self.database, self)
        layout.addWidget(self.clients_table)