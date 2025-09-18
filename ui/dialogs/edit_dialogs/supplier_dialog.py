"""
Supplier Edit Dialog - Inherits from BaseEditDialog
Replaces the old repetitive supplier_dialog.py with a clean, customized version
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
            self.supplier = SupplierClass(supplier_id, database, "Existing Supplier")
            self.supplier.load_database_data()
        else:
            self.supplier = SupplierClass(0, database, "New Supplier")
        
        # Define supplier-specific UI configuration
        ui_config = {
            'preview image': {
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
        if supplier_id:
            self.setWindowTitle(f"Edit Supplier - {self.supplier.get_value('name') or 'Unnamed'}")
        else:
            self.setWindowTitle("New Supplier")
    
    def validate_data(self):
        """Supplier-specific validation (extends base validation)"""
        errors = super().validate_data()  # Get base validation errors
        
        # Additional supplier-specific validation
        email = self.get_widget_value(self.parameter_widgets.get('email'))
        phone = self.get_widget_value(self.parameter_widgets.get('phone'))
        name = self.get_widget_value(self.parameter_widgets.get('name'))
        
        # Validate email format if provided
        if email and not self._validate_email(email):
            errors.append("Please enter a valid email address")
        
        # Validate phone format if provided  
        if phone and not self._validate_phone(phone):
            errors.append("Please enter a valid phone number (7-15 digits)")
        
        # Business rule: Suppliers should have at least email OR phone for contact
        if name and not email and not phone:
            errors.append("Please provide at least an email address or phone number for contact")
        
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
    
    def save_changes(self):
        """Save supplier changes to database"""
        # Validate data first
        errors = self.validate_data()
        if errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(errors))
            return
        
        try:
            # Update supplier object with form data
            for param_key, widget in self.parameter_widgets.items():
                value = self.get_widget_value(widget)
                self.supplier.set_value(param_key, value)
            
            # Save to database
            supplier_data = self.supplier.get_value(destination="database")
            
            if self.supplier_id:
                # Update existing supplier
                success = self.database.update_item(self.supplier_id, supplier_data, "Suppliers")
                action = "updated"
            else:
                # Add new supplier
                success = self.database.add_item(supplier_data, "Suppliers")
                action = "created"
            
            if success:
                QMessageBox.information(self, "Success", f"Supplier {action} successfully!")
                self.accept()  # Close dialog
            else:
                QMessageBox.critical(self, "Error", f"Failed to save supplier to database")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save supplier: {str(e)}")
    
    def get_supplier_data(self):
        """Get the supplier object (useful for parent windows)"""
        return self.supplier