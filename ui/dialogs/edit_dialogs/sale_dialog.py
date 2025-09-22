"""
Sale Edit Dialog - Inherits from BaseEditDialog
For managing sale transactions
"""

from ui.dialogs.edit_dialogs.base_dialog import BaseEditDialog
from classes.sales_class import SaleClass
from PySide6.QtWidgets import QDialog, QMessageBox
from datetime import datetime


class SaleEditDialog(BaseEditDialog):
    """Sale-specific edit dialog with client and product selection"""
    
    def __init__(self, sale_id=None, database=None, parent=None):
        """
        Initialize sale dialog
        
        Args:
            sale_id: ID of existing sale (None for new sale)
            database: Database instance
            parent: Parent widget
        """
        self.sale_id = sale_id
        self.database = database
        
        # Create or load sale object
        if sale_id:
            self.sale_obj = SaleClass(sale_id, database, 0, 0)
            self.sale_obj.load_database_data()
        else:
            self.sale_obj = SaleClass(0, database, 0, 0)
            # Set default date to today
            self.sale_obj.set_value("date", datetime.now().strftime("%Y-%m-%d"))
        
        # Define sale-specific UI configuration
        ui_config = {
            'client_id': {
                'options': self._get_client_options()
            },
            'product_id': {
                'options': self._get_product_options()
            },
            'unit_price': {
                'minimum': 0.0,
                'maximum': 999999.99,
                'unit': '€'
            },
            'tva': {
                'minimum': 0.0,
                'maximum': 100.0,
                'unit': '%'
            },
            'total_price': {
                'minimum': 0.0,
                'maximum': 999999.99,
                'unit': '€'
            }
        }
        
        # Initialize base dialog
        super().__init__(self.sale_obj, ui_config, parent)
        
        # Set specific window title
        if sale_id:
            self.setWindowTitle(f"Edit Sale - ID {sale_id}")
        else:
            self.setWindowTitle("New Sale")
        
        # Connect quantity, price, and tva changes to auto-calculate total
        self._connect_calculation_updates()
    
    def _get_client_options(self):
        """Get list of clients for dropdown"""
        if not self.database:
            return []
        
        try:
            clients = self.database.get_items("Clients")
            return [f"{c['ID']} - {c['name']}" for c in clients]
        except:
            return []
    
    def _get_product_options(self):
        """Get list of products for dropdown"""
        if not self.database:
            return []
        
        try:
            products = self.database.get_items("Products")
            return [f"{p['ID']} - {p['name']}" for p in products]
        except:
            return []
    
    def _connect_calculation_updates(self):
        """Connect value changes to auto-calculate total price"""
        # TODO: Connect signals to auto-calculate total when quantity, unit_price, or tva changes
        pass
    
    def validate_data(self):
        """Sale-specific validation (extends base validation)"""
        errors = super().validate_data()  # Get base validation errors
        
        # Additional sale-specific validation
        client_text = self.get_widget_value(self.parameter_widgets.get('client_id', ''))
        product_text = self.get_widget_value(self.parameter_widgets.get('product_id', ''))
        quantity = self.get_widget_value(self.parameter_widgets.get('quantity', 0))
        unit_price = self.get_widget_value(self.parameter_widgets.get('unit_price', 0))
        
        # Extract client ID from selection
        try:
            client_id = int(client_text.split(' - ')[0]) if client_text else 0
        except (ValueError, IndexError):
            errors.append("Please select a valid client")
            client_id = 0
        
        # Extract product ID from selection
        try:
            product_id = int(product_text.split(' - ')[0]) if product_text else 0
        except (ValueError, IndexError):
            errors.append("Please select a valid product")
            product_id = 0
        
        # Business rules validation
        if quantity <= 0:
            errors.append("Quantity must be greater than 0")
        
        if unit_price <= 0:
            errors.append("Unit price must be greater than 0")
        
        # Store extracted IDs for saving
        self._extracted_client_id = client_id
        self._extracted_product_id = product_id
        
        return errors
    
    def save_changes(self):
        """Save sale changes to database"""
        # Validate data first
        errors = self.validate_data()
        if errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(errors))
            return
        
        try:
            # Update sale object with form data
            for param_key, widget in self.parameter_widgets.items():
                if param_key in ['client_id', 'product_id']:
                    # Use extracted IDs
                    if param_key == 'client_id':
                        self.sale_obj.set_value(param_key, self._extracted_client_id)
                    else:
                        self.sale_obj.set_value(param_key, self._extracted_product_id)
                else:
                    value = self.get_widget_value(widget)
                    self.sale_obj.set_value(param_key, value)
            
            # Calculate total price
            self.sale_obj.calculate_total_price()
            
            # Save to database
            sale_data = self.sale_obj.get_value(destination="database")
            
            if self.sale_id:
                # Update existing sale
                success = self.database.update_item(self.sale_id, sale_data, "Sales")
                action = "updated"
            else:
                # Add new sale
                success = self.database.add_item(sale_data, "Sales")
                action = "created"
            
            if success:
                QMessageBox.information(self, "Success", f"Sale {action} successfully!")
                self.accept()  # Close dialog
            else:
                QMessageBox.critical(self, "Error", f"Failed to save sale to database")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save sale: {str(e)}")
    
    def get_sale_data(self):
        """Get the sale object (useful for parent windows)"""
        return self.sale_obj