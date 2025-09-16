import sys
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, 
    QLabel, QLineEdit, QPushButton, QMessageBox
)
from PySide6.QtCore import Qt

class ProductEditDialog(QDialog):
    def __init__(self, product_data, parent=None):
        super().__init__(parent)
        self.product_data = product_data
        self.setWindowTitle("Edit Product")
        self.setup_ui()
        self.load_product_data()
        
    def setup_ui(self):
        # Create layouts
        main_layout = QVBoxLayout()
        form_layout = QVBoxLayout()
        button_layout = QHBoxLayout()
        
        # Create form fields
        self.id_label = QLabel("Product ID:")
        self.id_value = QLabel()
        self.id_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        
        self.name_label = QLabel("Product Name:")
        self.name_edit = QLineEdit()
        
        self.unit_price_label = QLabel("Unit Price:")
        self.unit_price_edit = QLineEdit()
        
        self.sale_price_label = QLabel("Sale Price:")
        self.sale_price_edit = QLineEdit()
        
        # Add fields to form layout
        form_layout.addWidget(self.id_label)
        form_layout.addWidget(self.id_value)
        form_layout.addWidget(self.name_label)
        form_layout.addWidget(self.name_edit)
        form_layout.addWidget(self.unit_price_label)
        form_layout.addWidget(self.unit_price_edit)
        form_layout.addWidget(self.sale_price_label)
        form_layout.addWidget(self.sale_price_edit)
        
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
        main_layout.addLayout(button_layout)
        
        self.setLayout(main_layout)
        self.resize(400, 250)
        
    def load_product_data(self):
        """Load product data into the form fields"""
        if self.product_data:
            self.id_value.setText(str(self.product_data.get('id', '')))
            self.name_edit.setText(self.product_data.get('name', ''))
            self.unit_price_edit.setText(str(self.product_data.get('unit_price', '')))
            self.sale_price_edit.setText(str(self.product_data.get('sale_price', '')))
    
    def save_changes(self):
        """Validate and save the changes"""
        # Get values from form fields
        name = self.name_edit.text().strip()
        unit_price = self.unit_price_edit.text().strip()
        sale_price = self.sale_price_edit.text().strip()
        
        # Validate required fields
        if not name:
            QMessageBox.warning(self, "Validation Error", "Product name is required.")
            return
            
        # Validate numeric fields
        try:
            unit_price_float = float(unit_price)
            if unit_price_float < 0:
                raise ValueError("Price cannot be negative")
        except ValueError:
            QMessageBox.warning(self, "Validation Error", "Unit price must be a valid number.")
            return
            
        try:
            sale_price_float = float(sale_price)
            if sale_price_float < 0:
                raise ValueError("Price cannot be negative")
        except ValueError:
            QMessageBox.warning(self, "Validation Error", "Sale price must be a valid number.")
            return
            
        # Update product data with new values
        self.product_data['name'] = name
        self.product_data['unit_price'] = unit_price_float
        self.product_data['sale_price'] = sale_price_float
        
        # For demonstration, show what would be saved
        print(f"Saved changes: {self.product_data}")
        
        # Accept the dialog (close with success)
        self.accept()


# Example usage and demonstration
if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Sample product data (this would come from your database)
    sample_product = {
        'id': 1001,
        'name': 'Sample Product',
        'unit_price': 19.99,
        'sale_price': 15.99
    }
    
    # Create and show the dialog
    dialog = ProductEditDialog(sample_product)
    
    if dialog.exec() == QDialog.Accepted:
        print("Changes were saved")
        # Here you would typically update the database with the changes
    else:
        print("Edit was cancelled")
    
    sys.exit(app.exec())