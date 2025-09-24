"""
Sales tab - Updated to use unified BaseTab approach
Now consistent with Products/Clients/Suppliers experience
"""
from ui.tabs.base_tab import BaseTab
from classes.sales_class import SalesClass
from classes.sales_item_class import SalesItemClass
from ui.dialogs.edit_dialogs.base_operation_dialog import BaseOperationDialog


class SalesEditDialog(BaseOperationDialog):
    """Sales-specific dialog using unified base operation dialog"""
    
    def __init__(self, sales_id=None, database=None, parent=None):
        super().__init__(
            operation_class=SalesClass,
            item_class=SalesItemClass, 
            operation_id=sales_id,
            database=database,
            parent=parent
        )
    
    def get_item_columns(self):
        """Override to specify sales item columns"""
        return ['product_preview', 'product_name', 'quantity', 'unit_price', 'subtotal', 'delete_action']
    
    def validate_data(self):
        """Sales-specific validation"""
        errors = super().validate_data()
        
        # Additional sales validation
        client_username = None
        for param_key, widget in self.parameter_widgets.items():
            if param_key == 'client_username':
                from ui.widgets.parameters_widgets import ParameterWidgetFactory
                client_username = ParameterWidgetFactory.get_widget_value(widget)
                break
        
        # Validate client exists
        if client_username and not self._validate_client_exists(client_username):
            errors.append(f"Client username '{client_username}' does not exist")
        
        return errors
    
    def _validate_client_exists(self, username):
        """Check if client username exists in database"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return False
        
        try:
            self.database.cursor.execute("SELECT COUNT(*) FROM Clients WHERE username = ?", (username,))
            result = self.database.cursor.fetchone()
            return result[0] > 0 if result else False
        except Exception as e:
            print(f"Error validating client: {e}")
            return False


class SalesTab(BaseTab):
    """Sales tab with unified table experience - consistent with other entity tabs"""
    
    def __init__(self, database=None, parent=None):
        super().__init__(SalesClass, SalesEditDialog, database, parent)
    
    def get_preview_category(self):
        """Override to specify preview category for sales operations"""
        return "individual"  # Since sales are typically associated with clients