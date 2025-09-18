"""
Product Edit Dialog - Inherits from BaseEditDialog
Replaces the old repetitive product_dialog.py with a clean, customized version
"""

from ui.dialogs.edit_dialogs.base_dialog import BaseEditDialog
from classes.product_class import ProductClass
from PySide6.QtWidgets import QDialog, QMessageBox


class ProductEditDialog(BaseEditDialog):
    """Product-specific edit dialog with custom validation and UI config"""
    
    def __init__(self, product_id=None, database=None, parent=None):
        """
        Initialize product dialog
        
        Args:
            product_id: ID of existing product (None for new product)
            database: Database instance
            parent: Parent widget
        """
        self.product_id = product_id
        self.database = database
        
        # Create or load product object
        if product_id:
            self.product = ProductClass(product_id, database, "Existing Product")
            self.product.load_database_data()
        else:
            self.product = ProductClass(0, database, "New Product")
        
        # Define product-specific UI configuration
        ui_config = {
            'preview image': {
                'size': (100, 100),  # Smaller than client images
                'browsing_enabled': True
            },
            'unit price': {
                'minimum': 0.0,
                'maximum': 999999.99,
                'unit': '€'
            },
            'sale price': {
                'minimum': 0.0,
                'maximum': 999999.99,
                'unit': '€'
            }
        }
        
        # Initialize base dialog
        super().__init__(self.product, ui_config, parent)
        
        # Set specific window title
        if product_id:
            self.setWindowTitle(f"Edit Product - {self.product.get_value('name') or 'Unnamed'}")
        else:
            self.setWindowTitle("New Product")
    
    def validate_data(self):
        """Product-specific validation (extends base validation)"""
        errors = super().validate_data()  # Get base validation errors
        
        # Additional product-specific validation
        unit_price = self.get_widget_value(self.parameter_widgets.get('unit price', 0))
        sale_price = self.get_widget_value(self.parameter_widgets.get('sale price', 0))
        
        # Business rule: Sale price should typically be higher than unit price
        if unit_price and sale_price and sale_price < unit_price:
            errors.append("Warning: Sale price is lower than unit price. This may result in losses.")
        
        # Business rule: Both prices should be positive
        if unit_price and unit_price < 0:
            errors.append("Unit price cannot be negative")
        
        if sale_price and sale_price < 0:
            errors.append("Sale price cannot be negative")
        
        return errors
    
    def save_changes(self):
        """Save product changes to database"""
        # Validate data first
        errors = self.validate_data()
        if errors:
            # Check if errors are just warnings (like sale price < unit price)
            warning_errors = [e for e in errors if e.startswith("Warning:")]
            critical_errors = [e for e in errors if not e.startswith("Warning:")]
            
            if critical_errors:
                QMessageBox.warning(self, "Validation Error", "\n".join(critical_errors))
                return
            elif warning_errors:
                # Show warning but allow user to continue
                reply = QMessageBox.question(
                    self, "Warning", 
                    "\n".join(warning_errors) + "\n\nDo you want to continue anyway?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return
        
        try:
            # Update product object with form data
            for param_key, widget in self.parameter_widgets.items():
                value = self.get_widget_value(widget)
                self.product.set_value(param_key, value)
            
            # Save to database
            product_data = self.product.get_value(destination="database")
            
            if self.product_id:
                # Update existing product
                success = self.database.update_item(self.product_id, product_data, "Products")
                action = "updated"
            else:
                # Add new product
                success = self.database.add_item(product_data, "Products")
                action = "created"
            
            if success:
                QMessageBox.information(self, "Success", f"Product {action} successfully!")
                self.accept()  # Close dialog
            else:
                QMessageBox.critical(self, "Error", f"Failed to save product to database")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save product: {str(e)}")
    
    def get_product_data(self):
        """Get the product object (useful for parent windows)"""
        return self.product
