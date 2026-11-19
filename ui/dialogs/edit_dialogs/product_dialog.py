"""
Product Dialog - Clean version without success popups
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
            current_quantity = self.product.get_value("quantity")
            window_title = f"Edit Product - {self.product.get_value('name') or 'Unnamed'}"
        else:
            self.product = ProductClass(0, database)
            current_quantity = 0
            window_title = "New Product"

        # Stock is ledger-based, so this writable presentation field is saved
        # as one opening/adjustment ledger entry. Keep it directly before the
        # stock-alert threshold in both create and edit forms.
        self.product.parameters["quantity"] = {
            "value": current_quantity,
            "display_name": {
                "en": "Stock Quantity" if product_id else "Initial Quantity",
                "fr": "Quantité en stock" if product_id else "Quantité initiale",
                "es": "Cantidad en stock" if product_id else "Cantidad inicial",
            },
            "required": False,
            "default": 0,
            "options": [],
            "type": "decimal",
            "precision": 3,
            "min": 0,
            "max": 999999999,
        }
        dialog_fields = self.product.available_parameters["dialog"]
        reordered = {}
        for key, permission in dialog_fields.items():
            if key == "stock_alert":
                reordered["quantity"] = "rw"
            reordered[key] = permission
        if "quantity" not in reordered:
            reordered["quantity"] = "rw"
        self.product.available_parameters["dialog"] = reordered
        
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
        self._saving = False
    
    def validate_data(self):
        """Product-specific validation (extends base validation)"""
        errors = super().validate_data()  # Get base validation errors
        
        # Get current values from widgets
        unit_price = None
        sale_price = None
        username = None
        
        for param_key, widget in self.parameter_widgets.items():
            if param_key == 'unit_price':
                unit_price = self.get_widget_value(widget)
            elif param_key == 'sale_price':
                sale_price = self.get_widget_value(widget)
            elif param_key == 'username':
                username = self.get_widget_value(widget)
        
        # Additional product-specific validation
        if unit_price is not None and sale_price is not None:
            if sale_price < unit_price:
                errors.append("Warning: Sale price is lower than unit price. This may result in losses.")
        
        # Business rule: Both prices should be non-negative
        if unit_price is not None and unit_price < 0:
            errors.append("Unit price cannot be negative")
        
        if sale_price is not None and sale_price < 0:
            errors.append("Sale price cannot be negative")
        
        # Validate username uniqueness (skip if empty — will default to product name on save)
        if username and not self.product.validate_username_uniqueness(username):
            errors.append(f"Username '{username}' already exists for another product")
        
        return errors
    
    def get_widget_value(self, widget):
        """Helper method to get value from widget"""
        from ui.widgets.parameters_widgets import ParameterWidgetFactory
        return ParameterWidgetFactory.get_widget_value(widget)
    
    def save_changes(self):
        """Save product changes without annoying success popup"""
        if self._saving:
            return
        self._saving = True
        self.save_btn.setEnabled(False)
        self.save_btn.setText("Saving...")
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
            form_values = {}
            for param_key, widget in self.parameter_widgets.items():
                value = ParameterWidgetFactory.get_widget_value(widget)
                form_values[param_key] = value

            target_quantity = form_values.pop("quantity", 0)

            # Default username to product name if left empty
            if not form_values.get('username'):
                form_values['username'] = form_values.get('name') or self.product.get_value('name') or ''

            for param_key, value in form_values.items():
                self.product.set_value(param_key, value)
            
            # A new product and its opening stock must be one transaction so
            # rapid clicks or a partial failure cannot duplicate stock.
            if not self.product_id:
                product_data = self.product.get_value(destination="database")
                result = self.database.save_product_with_opening_stock(
                    product_data, target_quantity
                )
                success = bool(result and result.get("product_id"))
                if success:
                    self.product.id = int(result["product_id"])
                    self.product.parameters["id"]["value"] = self.product.id
            else:
                product_data = self.product.get_value(destination="database")
                result = self.database.update_product_with_stock(
                    self.product_id, product_data, target_quantity
                )
                success = bool(
                    result and result.get("transaction") == "committed"
                )
            
            if success:
                # No success popup - just close dialog
                self.accept()
            else:
                QMessageBox.critical(self, "Error", "Failed to save product to database")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save product: {str(e)}")
        finally:
            if self.result() != QDialog.Accepted:
                self._saving = False
                self.save_btn.setEnabled(True)
                self.save_btn.setText("Save")
    
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
