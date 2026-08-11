"""
Suppliers Tab - Updated to use BaseTab
"""
from ui.tabs.base_tab import BaseTab
from classes.supplier_class import SupplierClass
from ui.dialogs.edit_dialogs.supplier_dialog import SupplierEditDialog
from ui.dialogs.supplier_details_dialog import SupplierDetailsDialog
from ui.widgets.themed_widgets import BlueButton
from PySide6.QtWidgets import QMessageBox


class SuppliersTab(BaseTab):
    """Suppliers tab with editable table"""
    
    def __init__(self, database=None, parent=None):
        super().__init__(SupplierClass, SupplierEditDialog, database, parent)

    def add_additional_toolbar_buttons(self, layout):
        """Add the supplier account view command."""
        self.view_supplier_btn = BlueButton("View Supplier")
        self.view_supplier_btn.setToolTip("View imports, payments, and remaining balance")
        self.view_supplier_btn.setMinimumHeight(20)
        self.view_supplier_btn.setEnabled(
            bool(self.database and self.database.has_permission("Suppliers", "read"))
        )
        self.view_supplier_btn.setStyleSheet(
            self.view_supplier_btn.styleSheet()
            + "\nQPushButton { font-size: 14px; padding: 5px 10px; }"
        )
        self.view_supplier_btn.clicked.connect(self.view_supplier)
        layout.insertWidget(layout.count() - 1, self.view_supplier_btn)

    def view_supplier(self):
        """Open the account view for the selected supplier."""
        if not self.database or not self.database.has_permission("Suppliers", "read"):
            QMessageBox.information(
                self, "Access Denied", "You don't have permission to view suppliers."
            )
            return
        try:
            supplier_id = self.get_selected_id()
            if supplier_id is None:
                QMessageBox.information(self, "No Selection", "Please select a supplier first.")
                return

            # Always load fresh from the database instead of reusing the cached
            # row object, so changes made by other users show up immediately.
            supplier = SupplierClass(supplier_id, self.database)
            if not supplier.load_database_data():
                QMessageBox.warning(self, "Supplier Error", "Could not load the selected supplier.")
                return

            dialog = SupplierDetailsDialog(supplier, self.database, self)
            dialog.showMaximized()
            dialog.exec()
        except Exception as error:
            QMessageBox.critical(self, "Supplier Error", f"Could not open the selected supplier:\n{error}")

    def details_callback(self, obj_id):
        """Open supplier details from any future details cell."""
        supplier = SupplierClass(obj_id, self.database)
        if supplier.load_database_data():
            dialog = SupplierDetailsDialog(supplier, self.database, self)
            dialog.showMaximized()
            dialog.exec()

    def get_preview_category(self):
        """Override to specify preview category for suppliers"""
        return "company"
    
    def get_search_options(self):
        """Get autocomplete options for supplier search"""
        if not self.all_items:
            return []
        
        options = set()
        for obj in self.all_items:
            try:
                # Add usernames and supplier names
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
        """Setup order dropdown options for suppliers"""
        self.order_combo.clear()
        self.order_combo.addItems([
            "Default",
            "Username ↑",
            "Username ↓", 
            "Supplier Name ↑",
            "Supplier Name ↓"
        ])
    
    def get_searchable_fields(self):
        """Get fields that can be searched for suppliers"""
        return ['username', 'name']
    
    def matches_search(self, obj, search_text):
        """Check if supplier matches search criteria"""
        if not search_text:
            return True
        
        search_lower = search_text.lower()
        
        # Check username and supplier name
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
        """Sort suppliers based on order option"""
        if not order_option or order_option == "Default":
            return items
        
        try:
            if order_option == "Username ↑":
                items.sort(key=lambda x: str(x.get_value('username') or "").lower())
            elif order_option == "Username ↓":
                items.sort(key=lambda x: str(x.get_value('username') or "").lower(), reverse=True)
            elif order_option == "Supplier Name ↑":
                items.sort(key=lambda x: str(x.get_value('name') or "").lower())
            elif order_option == "Supplier Name ↓":
                items.sort(key=lambda x: str(x.get_value('name') or "").lower(), reverse=True)
        except Exception as e:
            print(f"Error sorting suppliers: {e}")
        
        return items