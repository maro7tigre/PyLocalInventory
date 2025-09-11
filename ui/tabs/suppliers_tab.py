"""
Suppliers tab - supplier management and procurement tracking
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

class SuppliersTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setup_ui()
    
    def setup_ui(self):
        """Setup suppliers tab interface"""
        layout = QVBoxLayout()
        
        # Placeholder content
        label = QLabel("Suppliers Tab - Coming Soon")
        label.setStyleSheet("color: #ffffff; font-size: 16px;")
        layout.addWidget(label)
        
        self.setLayout(layout)