"""
Clients Tab - Updated to use BaseTab
"""
from ui.tabs.base_tab import BaseTab
from classes.client_class import ClientClass
from ui.dialogs.edit_dialogs.client_dialog import ClientEditDialog
from ui.dialogs.client_details_dialog import ClientDetailsDialog
from ui.widgets.themed_widgets import BlueButton
from PySide6.QtWidgets import QMessageBox


class ClientsTab(BaseTab):
    """Clients tab with editable table"""
    
    def __init__(self, database=None, parent=None):
        super().__init__(ClientClass, ClientEditDialog, database, parent)

    def add_additional_toolbar_buttons(self, layout):
        """Add the client account view command."""
        self.view_client_btn = BlueButton("View Client")
        self.view_client_btn.setToolTip("View purchases, payments, and remaining balance")
        self.view_client_btn.setMinimumHeight(20)
        self.view_client_btn.setStyleSheet(
            self.view_client_btn.styleSheet()
            + "\nQPushButton { font-size: 14px; padding: 5px 10px; }"
        )
        self.view_client_btn.clicked.connect(self.view_client)
        layout.insertWidget(layout.count() - 1, self.view_client_btn)

    def view_client(self):
        """Open the account view for the selected client."""
        client_id = self.get_selected_id()
        if client_id is None:
            QMessageBox.information(self, "No Selection", "Please select a client first.")
            return

        client = next((item for item in self.all_items if item.id == client_id), None)
        if client is None:
            client = ClientClass(client_id, self.database)
            if not client.load_database_data():
                QMessageBox.warning(self, "Client Error", "Could not load the selected client.")
                return

        dialog = ClientDetailsDialog(client, self.database, self)
        dialog.showMaximized()
        dialog.exec()

    def details_callback(self, obj_id):
        """Open client details from any future details cell."""
        client = next((item for item in self.all_items if item.id == obj_id), None)
        if client:
            dialog = ClientDetailsDialog(client, self.database, self)
            dialog.showMaximized()
            dialog.exec()
    
    def get_preview_category(self):
        """Override to specify preview category for clients"""
        # Check client type to determine preview category
        # For now, default to individual - could be enhanced to check client type
        return "individual"
    
    def get_search_options(self):
        """Get autocomplete options for client search"""
        if not self.all_items:
            return []
        
        options = set()
        for obj in self.all_items:
            try:
                # Add usernames and client names
                username = obj.get_value('username')
                name = obj.get_value('name')
                if username:
                    options.add(str(username))
                if name:
                    options.add(str(name))
            except:
                pass
        
        return sorted(list(options))
    
    def setup_order_options(self):
        """Setup order dropdown options for clients"""
        self.order_combo.clear()
        self.order_combo.addItems([
            "Default",
            "Username ↑",
            "Username ↓", 
            "Client Name ↑",
            "Client Name ↓"
        ])
    
    def get_searchable_fields(self):
        """Get fields that can be searched for clients"""
        return ['username', 'name']
    
    def matches_search(self, obj, search_text):
        """Check if client matches search criteria"""
        if not search_text:
            return True
        
        search_lower = search_text.lower()
        
        # Check username and client name
        try:
            username = obj.get_value('username') or ""
            name = obj.get_value('name') or ""
            
            if (search_lower in username.lower() or 
                search_lower in name.lower()):
                return True
        except:
            pass
        
        return False
    
    def sort_items(self, items, order_option):
        """Sort clients based on order option"""
        if not order_option or order_option == "Default":
            return items
        
        try:
            if order_option == "Username ↑":
                items.sort(key=lambda x: str(x.get_value('username') or "").lower())
            elif order_option == "Username ↓":
                items.sort(key=lambda x: str(x.get_value('username') or "").lower(), reverse=True)
            elif order_option == "Client Name ↑":
                items.sort(key=lambda x: str(x.get_value('name') or "").lower())
            elif order_option == "Client Name ↓":
                items.sort(key=lambda x: str(x.get_value('name') or "").lower(), reverse=True)
        except Exception as e:
            print(f"Error sorting clients: {e}")
        
        return items
