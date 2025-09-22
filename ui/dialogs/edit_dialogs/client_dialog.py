"""
Client Dialog - Clean version updated to work with new ClientClass
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
            self.client = ClientClass(client_id, database)
            self.client.load_database_data()
            window_title = f"Edit Client - {self.client.get_value('name') or 'Unnamed'}"
        else:
            self.client = ClientClass(0, database)
            window_title = "New Client"
        
        # Define client-specific UI configuration
        ui_config = {
            'preview_image': {
                'size': (120, 120),
                'browsing_enabled': True
            },
            'notes': {
                'height': 80  # Taller text area for notes
            },
            'client_type': {
                'read_only': False  # Allow changing client type
            }
        }
        
        # Initialize base dialog
        super().__init__(self.client, ui_config, parent)
        
        # Set specific window title
        self.setWindowTitle(window_title)
    
    def validate_data(self):
        """Client-specific validation (extends base validation)"""
        errors = super().validate_data()  # Get base validation errors
        
        # Get current values from widgets
        email = None
        phone = None
        name = None
        
        for param_key, widget in self.parameter_widgets.items():
            if param_key == 'email':
                email = self.get_widget_value(widget)
            elif param_key == 'phone':
                phone = self.get_widget_value(widget)
            elif param_key == 'name':
                name = self.get_widget_value(widget)
        
        # Additional client-specific validation
        if email and not self._validate_email(email):
            errors.append("Please enter a valid email address")
        
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
    
    def get_widget_value(self, widget):
        """Helper method to get value from widget"""
        from ui.widgets.parameters_widgets import ParameterWidgetFactory
        return ParameterWidgetFactory.get_widget_value(widget)
    
    def save_changes(self):
        """Save client changes without annoying success popup"""
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
            
            # Update client object with form data
            from ui.widgets.parameters_widgets import ParameterWidgetFactory
            for param_key, widget in self.parameter_widgets.items():
                value = ParameterWidgetFactory.get_widget_value(widget)
                self.client.set_value(param_key, value)
            
            # Save to database
            success = self.client.save_to_database()
            
            if success:
                # No success popup - just close dialog
                self.accept()
            else:
                QMessageBox.critical(self, "Error", "Failed to save client to database")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save client: {str(e)}")
    
    def get_client_data(self):
        """Get the client object (useful for parent windows)"""
        return self.client


# Helper function to easily create client dialogs
def show_client_dialog(client_id=None, database=None, parent=None):
    """
    Convenience function to show client dialog
    
    Args:
        client_id: ID of existing client (None for new client)
        database: Database instance
        parent: Parent widget
        
    Returns:
        tuple: (success: bool, client_object: ClientClass or None)
    """
    dialog = ClientEditDialog(client_id, database, parent)
    
    if dialog.exec() == QDialog.Accepted:
        return True, dialog.get_client_data()
    else:
        return False, None