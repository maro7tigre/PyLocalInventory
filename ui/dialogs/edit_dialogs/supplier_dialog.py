import sys
import re
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, 
    QLabel, QLineEdit, QPushButton, QMessageBox, QTextEdit
)
from PySide6.QtCore import Qt

class SupplierEditDialog(QDialog):
    def __init__(self, supplier_data, parent=None):
        super().__init__(parent)
        self.supplier_data = supplier_data
        self.setWindowTitle("Edit Supplier")
        self.setup_ui()
        self.load_supplier_data()
        
    def setup_ui(self):
        # Create layouts
        main_layout = QVBoxLayout()
        form_layout = QVBoxLayout()
        button_layout = QHBoxLayout()
        
        # Create form fields
        self.id_label = QLabel("Supplier ID:")
        self.id_value = QLabel()
        self.id_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        
        self.name_label = QLabel("Supplier Name:")
        self.name_edit = QLineEdit()
        
        self.phone_label = QLabel("Phone Number:")
        self.phone_edit = QLineEdit()
        
        self.email_label = QLabel("Email Address:")
        self.email_edit = QLineEdit()
        
        self.notes_label = QLabel("Notes:")
        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(100)
        
        # Add fields to form layout
        form_layout.addWidget(self.id_label)
        form_layout.addWidget(self.id_value)
        form_layout.addWidget(self.name_label)
        form_layout.addWidget(self.name_edit)
        form_layout.addWidget(self.phone_label)
        form_layout.addWidget(self.phone_edit)
        form_layout.addWidget(self.email_label)
        form_layout.addWidget(self.email_edit)
        form_layout.addWidget(self.notes_label)
        form_layout.addWidget(self.notes_edit)
        
        # Create buttons
        self.save_button = QPushButton("Save")
        self.cancel_button = QPushButton("Cancel")
        
        # Connect buttons to functions
        self.save_button.clicked.connect(self.save_changes)
        self.cancel_button.clicked.connect(self.reject)
        
        # Add buttons to button layout
        button_layout.addStretch()
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)
        
        # Combine layouts
        main_layout.addLayout(form_layout)
        main_layout.addSpacing(10)
        main_layout.addLayout(button_layout)
        
        self.setLayout(main_layout)
        self.resize(450, 400)
        
    def load_supplier_data(self):
        """Load supplier data into the form fields"""
        if self.supplier_data:
            self.id_value.setText(str(self.supplier_data.get('id', '')))
            self.name_edit.setText(self.supplier_data.get('name', ''))
            self.phone_edit.setText(self.supplier_data.get('phone', ''))
            self.email_edit.setText(self.supplier_data.get('email', ''))
            self.notes_edit.setPlainText(self.supplier_data.get('notes', ''))
    
    def validate_email(self, email):
        """Simple email validation using regex"""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
    
    def validate_phone(self, phone):
        """Simple phone validation - allows numbers, spaces, hyphens, and parentheses"""
        # Remove common formatting characters
        cleaned_phone = re.sub(r'[+\s\-()]', '', phone)
        # Check if what remains are only digits
        return cleaned_phone.isdigit() and len(cleaned_phone) >= 7
    
    def save_changes(self):
        """Validate and save the changes"""
        # Get values from form fields
        name = self.name_edit.text().strip()
        phone = self.phone_edit.text().strip()
        email = self.email_edit.text().strip()
        notes = self.notes_edit.toPlainText().strip()
        
        # Validate required fields
        if not name:
            QMessageBox.warning(self, "Validation Error", "Supplier name is required.")
            return
            
        # Validate phone format
        if phone and not self.validate_phone(phone):
            QMessageBox.warning(self, "Validation Error", 
                               "Please enter a valid phone number (at least 7 digits).")
            return
            
        # Validate email format if provided
        if email and not self.validate_email(email):
            QMessageBox.warning(self, "Validation Error", 
                               "Please enter a valid email address.")
            return
            
        # Update supplier data with new values
        self.supplier_data['name'] = name
        self.supplier_data['phone'] = phone
        self.supplier_data['email'] = email
        self.supplier_data['notes'] = notes
        
        # For demonstration, show what would be saved
        print(f"Saved changes: {self.supplier_data}")
        
        # Accept the dialog (close with success)
        self.accept()


# Example usage and demonstration
if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Sample supplier data (this would come from your database)
    sample_supplier = {
        'id': 2001,
        'name': 'ABC Supplies Inc.',
        'phone': '(555) 123-4567',
        'email': 'contact@abcsupplies.com',
        'notes': 'Primary supplier for electronic components. Contact: John Smith'
    }
    
    # Create and show the dialog
    dialog = SupplierEditDialog(sample_supplier)
    
    if dialog.exec() == QDialog.Accepted:
        print("Supplier changes were saved")
        # Here you would typically update the database with the changes
    else:
        print("Supplier edit was cancelled")
    
    sys.exit(app.exec())