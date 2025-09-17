import sys
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, 
    QLabel, QLineEdit, QPushButton, QMessageBox, 
    QComboBox, QFormLayout
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

class SalesOrderEditDialog(QDialog):
    def __init__(self, order_data, parent=None):
        super().__init__(parent)
        self.order_data = order_data
        self.setWindowTitle("Edit Sales Order")
        self.setup_ui()
        self.load_order_data()
        
    def setup_ui(self):
        # Create layouts
        main_layout = QVBoxLayout()
        form_layout = QFormLayout()
        button_layout = QHBoxLayout()
        
        # Create form fields
        self.id_label = QLabel("Invoice Number / Sale Order ID:")
        self.id_value = QLabel()
        self.id_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.id_value.setFont(QFont("Arial", 10, QFont.Bold))
        
        self.client_label = QLabel("Client Name:")
        self.client_edit = QLineEdit()
        
        self.status_label = QLabel("Status:")
        self.status_combo = QComboBox()
        # Add status options for sales orders
        self.status_combo.addItems([
            "Quotation",
            "Confirmed",
            "In Progress",
            "Ready for Shipping",
            "Shipped",
            "Delivered",
            "Partially Shipped",
            "Cancelled",
            "Completed",
            "On Hold"
        ])
        
        # Add fields to form layout
        form_layout.addRow(self.id_label, self.id_value)
        form_layout.addRow(self.client_label, self.client_edit)
        form_layout.addRow(self.status_label, self.status_combo)
        
        # Create buttons
        self.save_button = QPushButton("Save")
        self.save_button.setMinimumWidth(100)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setMinimumWidth(100)
        
        # Connect buttons to functions
        self.save_button.clicked.connect(self.save_changes)
        self.cancel_button.clicked.connect(self.reject)
        
        # Add buttons to button layout
        button_layout.addStretch()
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)
        
        # Combine layouts
        main_layout.addLayout(form_layout)
        main_layout.addSpacing(20)
        main_layout.addLayout(button_layout)
        
        self.setLayout(main_layout)
        self.resize(500, 200)
        
    def load_order_data(self):
        """Load order data into the form fields"""
        if self.order_data:
            self.id_value.setText(str(self.order_data.get('id', '')))
            self.client_edit.setText(self.order_data.get('client', ''))
            
            # Set status
            status = self.order_data.get('status', 'Quotation')
            index = self.status_combo.findText(status)
            if index >= 0:
                self.status_combo.setCurrentIndex(index)
            else:
                self.status_combo.setCurrentText('Quotation')
    
    def save_changes(self):
        """Validate and save the changes"""
        # Get values from form fields
        client = self.client_edit.text().strip()
        status = self.status_combo.currentText()
        
        # Validate required fields
        if not client:
            QMessageBox.warning(self, "Validation Error", "Client name is required.")
            return
            
        # Update order data with new values
        self.order_data['client'] = client
        self.order_data['status'] = status
        
        # For demonstration, show what would be saved
        print(f"Saved sales order changes: {self.order_data}")
        
        # Accept the dialog (close with success)
        self.accept()


# Example usage and demonstration
if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Sample sales order data (this would come from your database)
    sample_order = {
        'id': 'SO-2024-001',
        'client': 'John Smith Enterprises',
        'status': 'Confirmed'
    }
    
    # Create and show the dialog
    dialog = SalesOrderEditDialog(sample_order)
    
    if dialog.exec() == QDialog.Accepted:
        print("Sales order changes were saved")
        # Here you would typically update the database with the changes
        print(f"Updated order data: {sample_order}")
    else:
        print("Sales order edit was cancelled")
    
    sys.exit(app.exec())