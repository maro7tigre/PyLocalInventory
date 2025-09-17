"""
Suppliers tab - supplier management and procurement tracking
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

class SuppliersTab(QWidget):
    def __init__(self, database=None):
        super().__init__()
        self.database = database
        self.setup_ui()
    
    def setup_ui(self):
        """Setup suppliers tab interface"""
        layout = QVBoxLayout()
        
        # Placeholder content
        label = QLabel("Suppliers Tab - Coming Soon")
        label.setStyleSheet("color: #ffffff; font-size: 16px;")
        layout.addWidget(label)
        
        if self.database:
            db_label = QLabel(f"Database connected: {self.database is not None}")
            db_label.setStyleSheet("color: #00ff00; font-size: 12px;")
            layout.addWidget(db_label)
        
        self.setLayout(layout)