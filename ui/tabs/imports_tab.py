"""
Imports tab - Updated to use unified BaseTab approach
Now consistent with Products/Clients/Suppliers experience
"""
from ui.tabs.base_tab import BaseTab
from classes.import_class import ImportClass
from classes.import_item_class import ImportItemClass
from ui.dialogs.edit_dialogs.base_operation_dialog import BaseOperationDialog


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
        errors = super().validate_data()
        
        # Additional import validation
        supplier_username = None
        for param_key, widget in self.parameter_widgets.items():
            if param_key == 'supplier_username':
                from ui.widgets.parameters_widgets import ParameterWidgetFactory
                supplier_username = ParameterWidgetFactory.get_widget_value(widget)
                break
        
        # Validate supplier exists
        if supplier_username and not self._validate_supplier_exists(supplier_username):
            errors.append(f"Supplier username '{supplier_username}' does not exist")
        
        return errors
    
    def _validate_supplier_exists(self, username):
        """Check if supplier username exists in database"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return False
        
        try:
            self.database.cursor.execute("SELECT COUNT(*) FROM Suppliers WHERE username = ?", (username,))
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