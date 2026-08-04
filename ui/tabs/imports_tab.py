"""
Imports tab - Updated to use unified BaseTab approach
Now consistent with Products/Clients/Suppliers experience
"""
from ui.tabs.base_tab import BaseTab
from classes.import_class import ImportClass
from classes.import_item_class import ImportItemClass
from ui.dialogs.edit_dialogs.base_operation_dialog import BaseOperationDialog
from datetime import datetime
import re


class ImportEditDialog(BaseOperationDialog):
    """Import-specific dialog using unified base operation dialog"""
    
    def __init__(self, import_id=None, database=None, parent=None):
        super().__init__(
            operation_class=ImportClass,
            item_class=ImportItemClass,
            operation_id=import_id,
            database=database,
            parent=parent
        )
    
    def get_item_columns(self):
        """Override to specify import item columns"""
        return ['product_preview', 'product_name', 'quantity', 'unit_price', 'subtotal', 'delete_action']
    
    def validate_data(self):
        """Import-specific validation"""
        # Only base validation; existence handled in auto-create workflow
        return super().validate_data()
    
    def _validate_supplier_exists(self, username):
        """Check if supplier username exists in database"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return False
        
        try:
            self.database.cursor.execute("SELECT COUNT(*) FROM Suppliers WHERE username = %s", (username,))
            result = self.database.cursor.fetchone()
            return result[0] > 0 if result else False
        except Exception as e:
            print(f"Error validating supplier: {e}")
            return False


class ImportsTab(BaseTab):
    """Imports tab with unified table experience - consistent with other entity tabs"""
    
    def __init__(self, database=None, parent=None):
        super().__init__(ImportClass, ImportEditDialog, database, parent)
    
    def get_preview_category(self):
        """Override to specify preview category for import operations"""
        return "company"  # Since imports are typically associated with suppliers
    
    def get_search_options(self):
        """Get autocomplete options for imports search"""
        if not self.all_items:
            return []
        
        options = set()
        for obj in self.all_items:
            try:
                supplier_username = obj.get_value('supplier_username')
                supplier_name = obj.get_value('supplier_name')
                date = obj.get_value('date')
                
                if supplier_username:
                    options.add(str(supplier_username))
                if supplier_name:
                    options.add(str(supplier_name))
                if date:
                    options.add(str(date))
            except:
                pass
        
        return sorted(list(options))
    
    def setup_order_options(self):
        """Setup order dropdown options for imports"""
        self.order_combo.clear()
        self.order_combo.addItems([
            "Default",
            "Supplier Username ↑",
            "Supplier Username ↓", 
            "Supplier Name ↑",
            "Supplier Name ↓",
            "Recent ↑",
            "Recent ↓",
            "Total ↑",
            "Total ↓"
        ])

    def _order_by_field(self, order_option):
        """Map display labels to allowlisted sort columns."""
        field = super()._order_by_field(order_option)
        if field == 'recent':
            return 'date'
        if field == 'total':
            return 'total_price'
        return field
    
    def get_searchable_fields(self):
        """Get fields that can be searched for imports"""
        return ['supplier_username', 'supplier_name', 'date']
    
    def matches_search(self, obj, search_text):
        """Check if import matches search criteria"""
        if not search_text:
            return True
        
        search_lower = search_text.lower()
        
        date_search = self.parse_date_search(search_text)
        if date_search:
            return self._matches_date_search(obj, date_search)
        
        try:
            supplier_username = obj.get_value('supplier_username') or ""
            supplier_name = obj.get_value('supplier_name') or ""
            return (
                search_lower in supplier_username.lower() or 
                search_lower in supplier_name.lower()
            )
        except:
            return False
    
    def _matches_date_search(self, obj, date_search):
        """Check if import matches date search criteria"""
        try:
            import_date_str = obj.get_value('date')
            if not import_date_str:
                return False
            
            # Parse import date (try multiple formats)
            import_date = None
            date_formats = ['%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y']
            for fmt in date_formats:
                try:
                    import_date = datetime.strptime(str(import_date_str), fmt).date()
                    break
                except ValueError:
                    continue
            
            if not import_date:
                return False
            
            if date_search[0] == 'single':
                return import_date == date_search[1]
            elif date_search[0] == 'range':
                return date_search[1] <= import_date <= date_search[2]
        except:
            pass
        
        return False
    
    def details_callback(self, obj_id):
        """Open the edit dialog for the selected import to view its details."""
        try:
            dialog = self.dialog_class(obj_id, self.database, self.parent_widget)
            if dialog.exec():
                self.refresh_table(force=True)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Failed to open import details: {e}")

    def sort_items(self, items, order_option):
        """Sort imports based on order option"""
        if not order_option or order_option == "Default":
            return items
        
        try:
            if order_option == "Supplier Username ↑":
                items.sort(key=lambda x: str(x.get_value('supplier_username') or "").lower())
            elif order_option == "Supplier Username ↓":
                items.sort(key=lambda x: str(x.get_value('supplier_username') or "").lower(), reverse=True)
            elif order_option == "Supplier Name ↑":
                items.sort(key=lambda x: str(x.get_value('supplier_name') or "").lower())
            elif order_option == "Supplier Name ↓":
                items.sort(key=lambda x: str(x.get_value('supplier_name') or "").lower(), reverse=True)
            elif order_option == "Recent ↑":
                items.sort(key=lambda x: self.parse_date_for_sorting(x.get_value('date')))
            elif order_option == "Recent ↓":
                items.sort(key=lambda x: self.parse_date_for_sorting(x.get_value('date')), reverse=True)
            elif order_option == "Total ↑":
                items.sort(key=lambda x: float(x.get_value('total_price') or 0))
            elif order_option == "Total ↓":
                items.sort(key=lambda x: float(x.get_value('total_price') or 0), reverse=True)
        except Exception as e:
            print(f"Error sorting imports: {e}")
        
        return items