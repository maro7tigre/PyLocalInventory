"""
Supplier Dialog - Clean version updated to work with new SupplierClass
"""

from ui.dialogs.edit_dialogs.base_dialog import BaseEditDialog
from classes.supplier_class import SupplierClass
from PySide6.QtWidgets import QDialog, QMessageBox
import re


class SupplierEditDialog(BaseEditDialog):
    """Supplier-specific edit dialog with custom validation and UI config"""
    
    def __init__(self, supplier_id=None, database=None, parent=None):
        """
        Initialize supplier dialog
        
        Args:
            supplier_id: ID of existing supplier (None for new supplier)
            database: Database instance
            parent: Parent widget
        """
        self.supplier_id = supplier_id
        self.database = database
        
        # Create or load supplier object
        if supplier_id:
            self.supplier = SupplierClass(supplier_id, database)
            self.supplier.load_database_data()
            window_title = f"Edit Supplier - {self.supplier.get_value('name') or 'Unnamed'}"
        else:
            self.supplier = SupplierClass(0, database)
            window_title = "New Supplier"
        
        # Define supplier-specific UI configuration
        ui_config = {
            'preview_image': {
                'size': (110, 110),  # Medium size for supplier logos
                'browsing_enabled': True
            },
            'notes': {
                'height': 100  # Extra tall for supplier notes (contracts, terms, etc.)
            },
            'name': {
                'required': True  # Name is always required for suppliers
            }
        }
        
        # Initialize base dialog
        super().__init__(self.supplier, ui_config, parent)
        
        # Set specific window title
        self.setWindowTitle(window_title)
    
    def validate_data(self):
        """Supplier-specific validation (extends base validation)"""
        errors = super().validate_data()  # Get base validation errors
        
        # Get current values from widgets
        email = None
        phone = None
        name = None
        username = None
        
        for param_key, widget in self.parameter_widgets.items():
            if param_key == 'email':
                email = self.get_widget_value(widget)
            elif param_key == 'phone':
                phone = self.get_widget_value(widget)
            elif param_key == 'name':
                name = self.get_widget_value(widget)
            elif param_key == 'username':
                username = self.get_widget_value(widget)
        
        # Additional supplier-specific validation
        if email and not self._validate_email(email):
            errors.append("Please enter a valid email address")
        
        if phone and not self._validate_phone(phone):
            errors.append("Please enter a valid phone number (7-15 digits)")
        
        # Business rule: Suppliers should have at least email OR phone for contact
        if name and not email and not phone:
            errors.append("Please provide at least an email address or phone number for contact")
        
        # Validate username uniqueness
        if username and not self.supplier.validate_username_uniqueness(username):
            errors.append(f"Username '{username}' already exists for another supplier")
        
        return errors
    
    def _validate_email(self, email):
        """Validate email format using regex"""
        if not email:  # Email is optional
            return True
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
    
    def _validate_phone(self, phone):
        """Validate phone format - allows numbers, spaces, hyphens, and parentheses"""
        if not phone:  # Phone is optional
            return True
        # Remove common formatting characters
        cleaned_phone = re.sub(r'[+\s\-()]', '', phone)
        # Check if what remains are only digits and has reasonable length
        return cleaned_phone.isdigit() and len(cleaned_phone) >= 7 and len(cleaned_phone) <= 15
    
    def get_widget_value(self, widget):
        """Helper method to get value from widget"""
        from ui.widgets.parameters_widgets import ParameterWidgetFactory
        return ParameterWidgetFactory.get_widget_value(widget)
    
    def save_changes(self):
        """Save supplier changes without annoying success popup"""
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
            
            # Update supplier object with form data
            from ui.widgets.parameters_widgets import ParameterWidgetFactory
            for param_key, widget in self.parameter_widgets.items():
                value = ParameterWidgetFactory.get_widget_value(widget)
                self.supplier.set_value(param_key, value)
            
            # Save to database
            success = self.supplier.save_to_database()
            
            if success:
                # No success popup - just close dialog
                self.accept()
            else:
                QMessageBox.critical(self, "Error", "Failed to save supplier to database")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save supplier: {str(e)}")
    
    def get_supplier_data(self):
        """Get the supplier object (useful for parent windows)"""
        return self.supplier


# Helper function to easily create supplier dialogs
def show_supplier_dialog(supplier_id=None, database=None, parent=None):
    """
    Convenience function to show supplier dialog
    
    Args:
        supplier_id: ID of existing supplier (None for new supplier)
        database: Database instance
        parent: Parent widget
        
    Returns:
        tuple: (success: bool, supplier_object: SupplierClass or None)
    """
    dialog = SupplierEditDialog(supplier_id, database, parent)
    
    if dialog.exec() == QDialog.Accepted:
        return True, dialog.get_supplier_data()
    else:
        return False, None