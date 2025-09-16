"""
Product dialog - add, edit, and view product information
"""
import sys
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox, QDialogButtonBox)

class ProductDialog(QDialog):
    def __init__(self, parent=None, product=None):
        super().__init__(parent)
        self.setWindowTitle("Add Product" if not product else "Edit Product")
        self.setMinimumWidth(300)
        
        layout = QVBoxLayout(self)
        self.fields = {}
        
        # Create form fields
        for label in ["Company", "Product"]:
            self.fields[label.lower()] = QLineEdit()
            layout.addWidget(QLabel(f"{label}:"))
            layout.addWidget(self.fields[label.lower()])
        
        self.fields["role"] = QComboBox()
        self.fields["role"].addItems(["Buyer", "Seller"])
        layout.addWidget(QLabel("Role:"))
        layout.addWidget(self.fields["role"])
        
        for label in ["Price HT", "Price TTC"]:
            self.fields[label.lower().replace(" ", "_")] = QDoubleSpinBox()
            self.fields[label.lower().replace(" ", "_")].setMaximum(10000)
            layout.addWidget(QLabel(f"{label}:"))
            layout.addWidget(self.fields[label.lower().replace(" ", "_")])
        
        self.fields["quantity"] = QSpinBox()
        self.fields["quantity"].setMaximum(1000)
        layout.addWidget(QLabel("Quantity:"))
        layout.addWidget(self.fields["quantity"])
        
        self.fields["currency"] = QComboBox()
        self.fields["currency"].addItems(["USD", "MAD", "EUR"])
        layout.addWidget(QLabel("Currency:"))
        layout.addWidget(self.fields["currency"])
        
        # Set values if editing
        if product:
            for key, value in product.items():
                if key in self.fields:
                    if isinstance(self.fields[key], QComboBox):
                        self.fields[key].setCurrentText(str(value))
                    else:
                        self.fields[key].setValue(value) if hasattr(self.fields[key], 'setValue') else self.fields[key].setText(str(value))
        
        # Dialog buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self):
        return {
            "company": self.fields["company"].text(),
            "role": self.fields["role"].currentText(),
            "product": self.fields["product"].text(),
            "price_ht": self.fields["price_ht"].value(),
            "price_ttc": self.fields["price_ttc"].value(),
            "quantity": self.fields["quantity"].value(),
            "currency": self.fields["currency"].currentText()
        }