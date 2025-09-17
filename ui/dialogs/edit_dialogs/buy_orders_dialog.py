import sys
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, 
    QLabel, QLineEdit, QPushButton, QMessageBox, 
    QComboBox, QDateEdit, QFormLayout
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QFont

class PurchaseOrderEditDialog(QDialog):
    def __init__(self, order_data, parent=None):
        super().__init__(parent)
        self.order_data = order_data
        self.setWindowTitle("Edit Purchase Order")
        self.setup_ui()
        self.load_order_data()
        
    def setup_ui(self):
        # Create layouts
        main_layout = QVBoxLayout()
        form_layout = QFormLayout()
        button_layout = QHBoxLayout()
        
        # Create form fields
        self.id_label = QLabel("Purchase Order ID:")
        self.id_value = QLabel()
        self.id_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.id_value.setFont(QFont("Arial", 10, QFont.Bold))
        
        self.supplier_label = QLabel("Supplier Name:")
        self.supplier_edit = QLineEdit()
        
        self.date_label = QLabel("Order Date:")
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        
        self.status_label = QLabel("Status:")
        self.status_combo = QComboBox()
        # Add status options
        self.status_combo.addItems([
            "Pending",
            "Ordered",
            "Received",
            "Partially Received",
            "Cancelled",
            "Completed"
        ])
        
        # Add fields to form layout
        form_layout.addRow(self.id_label, self.id_value)
        form_layout.addRow(self.supplier_label, self.supplier_edit)
        form_layout.addRow(self.date_label, self.date_edit)
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
        self.resize(500, 250)
        
    def load_order_data(self):
        """Load order data into the form fields"""
        if self.order_data:
            self.id_value.setText(str(self.order_data.get('id', '')))
            self.supplier_edit.setText(self.order_data.get('supplier', ''))
            
            # Set order date
            order_date = self.order_data.get('order_date')
            if order_date:
                if isinstance(order_date, str):
                    # Parse string date (assuming YYYY-MM-DD format)
                    date_parts = list(map(int, order_date.split('-')))
                    if len(date_parts) == 3:
                        self.date_edit.setDate(QDate(date_parts[0], date_parts[1], date_parts[2]))
                elif isinstance(order_date, QDate):
                    self.date_edit.setDate(order_date)
            else:
                self.date_edit.setDate(QDate.currentDate())
            
            # Set status
            status = self.order_data.get('status', 'Pending')
            index = self.status_combo.findText(status)
            if index >= 0:
                self.status_combo.setCurrentIndex(index)
            else:
                self.status_combo.setCurrentText('Pending')
    
    def save_changes(self):
        """Validate and save the changes"""
        # Get values from form fields
        supplier = self.supplier_edit.text().strip()
        order_date = self.date_edit.date()
        status = self.status_combo.currentText()
        
        # Validate required fields
        if not supplier:
            QMessageBox.warning(self, "Validation Error", "Supplier name is required.")
            return
            
        # Update order data with new values
        self.order_data['supplier'] = supplier
        self.order_data['order_date'] = order_date.toString(Qt.ISODate)  # Save as ISO format string
        self.order_data['status'] = status
        
        # For demonstration, show what would be saved
        print(f"Saved purchase order changes: {self.order_data}")
        
        # Accept the dialog (close with success)
        self.accept()


# Example usage and demonstration
if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Sample purchase order data (this would come from your database)
    sample_order = {
        'id': 4001,
        'supplier': 'ABC Supplies Inc.',
        'order_date': '2024-01-15',  # ISO format string
        'status': 'Ordered'
    }
    
    # Create and show the dialog
    dialog = PurchaseOrderEditDialog(sample_order)
    
    if dialog.exec() == QDialog.Accepted:
        print("Purchase order changes were saved")
        # Here you would typically update the database with the changes
        print(f"Updated order data: {sample_order}")
    else:
        print("Purchase order edit was cancelled")
    
    sys.exit(app.exec())