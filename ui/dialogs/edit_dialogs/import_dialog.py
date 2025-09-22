"""
Import Edit Dialog - Inherits from BaseEditDialog
For managing import transactions
"""

from ui.dialogs.edit_dialogs.base_dialog import BaseEditDialog
from classes.import_class import ImportClass
from PySide6.QtWidgets import QDialog, QMessageBox
from datetime import datetime


class ImportEditDialog(BaseEditDialog):
    """Import-specific edit dialog with supplier and product selection"""
    
    def __init__(self, import_id=None, database=None, parent=None):
        """
        Initialize import dialog
        
        Args:
            import_id: ID of existing import (None for new import)
            database: Database instance
            parent: Parent widget
        """
        self.import_id = import_id
        self.database = database
        
        # Create or load import object
        if import_id:
            self.import_obj = ImportClass(import_id, database, 0, 0)
            self.import_obj.load_database_data()
        else:
            self.import_obj = ImportClass(0, database, 0, 0)
            # Set default date to today
            self.import_obj.set_value("date", datetime.now().strftime("%Y-%m-%d"))
        
        # Define import-specific UI configuration
        ui_config = {
            'supplier_id': {
                'options': self._get_supplier_options()
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
        super().__init__(self.import_obj, ui_config, parent)
        
        # Set specific window title
        if import_id:
            self.setWindowTitle(f"Edit Import - ID {import_id}")
        else:
            self.setWindowTitle("New Import")
        
        # Connect quantity, price, and tva changes to auto-calculate total
        self._connect_calculation_updates()
    
    def _get_supplier_options(self):
        """Get list of suppliers for dropdown"""
        if not self.database:
            return []
        
        try:
            suppliers = self.database.get_items("Suppliers")
            return [f"{s['ID']} - {s['name']}" for s in suppliers]
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
        """Import-specific validation (extends base validation)"""
        errors = super().validate_data()  # Get base validation errors
        
        # Additional import-specific validation
        supplier_text = self.get_widget_value(self.parameter_widgets.get('supplier_id', ''))
        product_text = self.get_widget_value(self.parameter_widgets.get('product_id', ''))
        quantity = self.get_widget_value(self.parameter_widgets.get('quantity', 0))
        unit_price = self.get_widget_value(self.parameter_widgets.get('unit_price', 0))
        
        # Extract supplier ID from selection
        try:
            supplier_id = int(supplier_text.split(' - ')[0]) if supplier_text else 0
        except (ValueError, IndexError):
            errors.append("Please select a valid supplier")
            supplier_id = 0
        
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
        self._extracted_supplier_id = supplier_id
        self._extracted_product_id = product_id
        
        return errors
    
    def save_changes(self):
        """Save import changes to database"""
        # Validate data first
        errors = self.validate_data()
        if errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(errors))
            return
        
        try:
            # Update import object with form data
            for param_key, widget in self.parameter_widgets.items():
                if param_key in ['supplier_id', 'product_id']:
                    # Use extracted IDs
                    if param_key == 'supplier_id':
                        self.import_obj.set_value(param_key, self._extracted_supplier_id)
                    else:
                        self.import_obj.set_value(param_key, self._extracted_product_id)
                else:
                    value = self.get_widget_value(widget)
                    self.import_obj.set_value(param_key, value)
            
            # Calculate total price
            self.import_obj.calculate_total_price()
            
            # Save to database
            import_data = self.import_obj.get_value(destination="database")
            
            if self.import_id:
                # Update existing import
                success = self.database.update_item(self.import_id, import_data, "Imports")
                action = "updated"
            else:
                # Add new import
                success = self.database.add_item(import_data, "Imports")
                action = "created"
            
            if success:
                QMessageBox.information(self, "Success", f"Import {action} successfully!")
                self.accept()  # Close dialog
            else:
                QMessageBox.critical(self, "Error", f"Failed to save import to database")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save import: {str(e)}")
    
    def get_import_data(self):
        """Get the import object (useful for parent windows)"""
        return self.import_obj