"""
Clients Tab - Updated to use BaseTab
"""
from ui.tabs.base_tab import BaseTab
from classes.client_class import ClientClass
from ui.dialogs.edit_dialogs.client_dialog import ClientEditDialog
from ui.dialogs.client_details_dialog import ClientDetailsDialog
from ui.widgets.themed_widgets import BlueButton
from PySide6.QtWidgets import QMessageBox, QDialog, QVBoxLayout
from time import monotonic


class ClientsTab(BaseTab):
    """Clients tab with editable table"""
    
    def __init__(self, database=None, parent=None):
        super().__init__(ClientClass, ClientEditDialog, database, parent)

    def add_additional_toolbar_buttons(self, layout):
        """Add the client account view command."""
        self.view_client_btn = BlueButton("View Client")
        self.view_client_btn.setToolTip("View purchases, payments, and remaining balance")
        self.view_client_btn.setMinimumHeight(20)
        self.view_client_btn.setEnabled(
            bool(self.database and self.database.has_permission("Clients", "read"))
        )
        self.view_client_btn.setStyleSheet(
            self.view_client_btn.styleSheet()
            + "\nQPushButton { font-size: 14px; padding: 5px 10px; }"
        )
        self.view_client_btn.clicked.connect(self.view_client)
        layout.insertWidget(layout.count() - 1, self.view_client_btn)

        self.attachments_btn = BlueButton("Attachments")
        self.attachments_btn.setToolTip("Manage permanent files for the selected client")
        self.attachments_btn.setMinimumHeight(20)
        self.attachments_btn.clicked.connect(self.show_attachments)
        layout.insertWidget(layout.count() - 1, self.attachments_btn)

    def show_attachments(self):
        client_id = self.get_selected_id()
        if client_id is None:
            QMessageBox.information(self, "Attachments", "Select a client first.")
            return
        from ui.widgets.attachments_widget import AttachmentPanel
        dialog = QDialog(self)
        dialog.setWindowTitle("Client Sales")
        dialog.resize(1100, 820)
        layout = QVBoxLayout(dialog)
        layout.addWidget(AttachmentPanel(self.database, 'client', client_id, dialog))
        dialog.exec()

    def view_client(self):
        """Open the account view for the selected client."""
        if not self.database or not self.database.has_permission("Clients", "read"):
            QMessageBox.information(
                self, "Access Denied", "You don't have permission to view clients."
            )
            return
        try:
            client_id = self.get_selected_id()
            if client_id is None:
                QMessageBox.information(self, "No Selection", "Please select a client first.")
                return

            # Always load fresh from the database instead of reusing the cached
            # row object, so changes made by other users show up immediately.
            client = ClientClass(client_id, self.database)
            if not client.load_database_data():
                QMessageBox.warning(self, "Client Error", "Could not load the selected client.")
                return

            dialog = ClientDetailsDialog(client, self.database, self)
            dialog.showMaximized()
            dialog.exec()
        except Exception as error:
            QMessageBox.critical(self, "Client Error", f"Could not open the selected client:\n{error}")

    def details_callback(self, obj_id):
        """Open client details from any future details cell."""
        client = ClientClass(obj_id, self.database)
        if client.load_database_data():
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
                ice = obj.get_value('ice')
                if username:
                    options.add(str(username))
                if name:
                    options.add(str(name))
                if ice:
                    options.add(str(ice))
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
        return ['username', 'name', 'ice']
    
    def matches_search(self, obj, search_text):
        """Check if client matches search criteria"""
        if not search_text:
            return True
        
        search_lower = search_text.lower()
        
        # Check username and client name
        try:
            username = obj.get_value('username') or ""
            name = obj.get_value('name') or ""
            ice = obj.get_value('ice') or ""
            
            if (search_lower in username.lower() or 
                search_lower in name.lower() or
                search_lower in ice.lower()):
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
