"""
Client Edit Dialog - Inherits from BaseEditDialog
Replaces the old repetitive client_dialog.py with a clean, customized version
"""

from ui.dialogs.edit_dialogs.base_dialog import BaseEditDialog
from classes.client_class import ClientClass
from PySide6.QtWidgets import QDialog, QMessageBox
import re


class ClientEditDialog(BaseEditDialog):
    """Client-specific edit dialog with custom validation and UI config"""
    
    def __init__(self, client_id=None, database=None, parent=None):
        """
        Initialize client dialog
        
        Args:
            client_id: ID of existing client (None for new client)
            database: Database instance
            parent: Parent widget
        """
        self.client_id = client_id
        self.database = database
        
        # Create or load client object
        if client_id:
            self.client = ClientClass(client_id, database, "Existing Client")
            self.client.load_database_data()
        else:
            self.client = ClientClass(0, database, "New Client")
        
        # Define client-specific UI configuration
        ui_config = {
            'preview image': {
                'size': (120, 120),
                'browsing_enabled': True
            },
            'notes': {
                'height': 80  # Taller text area for notes
            },
            'client type': {
                'read_only': False  # Allow changing client type
            }
        }
        
        # Initialize base dialog
        super().__init__(self.client, ui_config, parent)
        
        # Set specific window title
        if client_id:
            self.setWindowTitle(f"Edit Client - {self.client.get_value('name') or 'Unnamed'}")
        else:
            self.setWindowTitle("New Client")
    
    def validate_data(self):
        """Client-specific validation (extends base validation)"""
        errors = super().validate_data()  # Get base validation errors
        
        # Additional client-specific validation
        email = self.get_widget_value(self.parameter_widgets.get('email'))
        phone = self.get_widget_value(self.parameter_widgets.get('phone'))
        
        # Validate email format if provided
        if email and not self._validate_email(email):
            errors.append("Please enter a valid email address")
        
        # Validate phone format if provided
        if phone and not self._validate_phone(phone):
            errors.append("Please enter a valid phone number (7-15 digits)")
        
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
        """Save client changes to database"""
        # Validate data first
        errors = self.validate_data()
        if errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(errors))
            return
        
        try:
            # Update client object with form data
            for param_key, widget in self.parameter_widgets.items():
                value = self.get_widget_value(widget)
                self.client.set_value(param_key, value)
            
            # Save to database
            client_data = self.client.get_value(destination="database")
            
            if self.client_id:
                # Update existing client
                success = self.database.update_item(self.client_id, client_data, "Clients")
                action = "updated"
            else:
                # Add new client
                success = self.database.add_item(client_data, "Clients")
                action = "created"
            
            if success:
                QMessageBox.information(self, "Success", f"Client {action} successfully!")
                self.accept()  # Close dialog
            else:
                QMessageBox.critical(self, "Error", f"Failed to save client to database")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save client: {str(e)}")
    
    def get_client_data(self):
        """Get the client object (useful for parent windows)"""
        return self.client