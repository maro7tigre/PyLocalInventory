"""
Updated Product Dialog - Uses new base dialog system
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
            self.product = ProductClass(product_id, database)
            self.product.load_database_data()
            window_title = f"Edit Product - {self.product.get_value('name') or 'Unnamed'}"
        else:
            self.product = ProductClass(0, database)
            window_title = "New Product"
        
        # Define product-specific UI configuration
        ui_config = {
            'preview_image': {
                'size': (100, 100),
                'browsing_enabled': True
            },
            'description': {
                'multiline': True  # Could be extended for text areas
            }
        }
        
        # Initialize base dialog
        super().__init__(self.product, ui_config, parent)
        
        # Set specific window title
        self.setWindowTitle(window_title)
    
    def validate_data(self):
        """Product-specific validation (extends base validation)"""
        errors = super().validate_data()  # Get base validation errors
        
        # Get current values from widgets
        unit_price = None
        sale_price = None
        
        for param_key, widget in self.parameter_widgets.items():
            if param_key == 'unit_price':
                unit_price = self.get_widget_value(widget)
            elif param_key == 'sale_price':
                sale_price = self.get_widget_value(widget)
        
        # Additional product-specific validation
        if unit_price is not None and sale_price is not None:
            if sale_price < unit_price:
                errors.append("Warning: Sale price is lower than unit price. This may result in losses.")
        
        # Business rule: Both prices should be non-negative
        if unit_price is not None and unit_price < 0:
            errors.append("Unit price cannot be negative")
        
        if sale_price is not None and sale_price < 0:
            errors.append("Sale price cannot be negative")
        
        return errors
    
    def get_widget_value(self, widget):
        """Helper method to get value from widget"""
        from ui.widgets.parameters_widgets import ParameterWidgetFactory
        return ParameterWidgetFactory.get_widget_value(widget)
    
    def save_changes(self):
        """Save product changes with custom success message"""
        # Call parent save method
        try:
            # Validate data first
            errors = self.validate_data()
            
            # Separate warnings from critical errors
            critical_errors = [e for e in errors if not e.lower().startswith('warning')]
            warnings = [e for e in errors if e.lower().startswith('warning')]
            
            # Handle critical errors
            if critical_errors:
                QMessageBox.warning(self, "Validation Error", "\n".join(critical_errors))
                return
            
            # Handle warnings
            if warnings:
                reply = QMessageBox.question(
                    self, "Warning", 
                    "\n".join(warnings) + "\n\nDo you want to continue anyway?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return
            
            # Update product object with form data
            from ui.widgets.parameters_widgets import ParameterWidgetFactory
            for param_key, widget in self.parameter_widgets.items():
                value = ParameterWidgetFactory.get_widget_value(widget)
                self.product.set_value(param_key, value)
            
            # Save to database
            success = self.product.save_to_database()
            
            if success:
                action = "updated" if self.product_id else "created"
                product_name = self.product.get_value('name') or 'Unnamed Product'
                QMessageBox.information(self, "Success", f"Product '{product_name}' {action} successfully!")
                self.accept()  # Close dialog
            else:
                QMessageBox.critical(self, "Error", "Failed to save product to database")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save product: {str(e)}")
    
    def get_product_data(self):
        """Get the product object (useful for parent windows)"""
        return self.product


# Helper function to easily create product dialogs
def show_product_dialog(product_id=None, database=None, parent=None):
    """
    Convenience function to show product dialog
    
    Args:
        product_id: ID of existing product (None for new product)
        database: Database instance
        parent: Parent widget
        
    Returns:
        tuple: (success: bool, product_object: ProductClass or None)
    """
    dialog = ProductEditDialog(product_id, database, parent)
    
    if dialog.exec() == QDialog.Accepted:
        return True, dialog.get_product_data()
    else:
        return False, None