"""
Products tab - product management interface and inventory overview
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

class ProductsTab(QWidget):
    def __init__(self, database=None):
        super().__init__()
        self.database = database
        self.setup_ui()
    
    def setup_ui(self):
        """Setup products tab interface"""
        layout = QVBoxLayout()
        
        # Placeholder content
        label = QLabel("Products Tab - Coming Soon")
        label.setStyleSheet("color: #ffffff; font-size: 16px;")
        layout.addWidget(label)
        
        if self.database:
            db_label = QLabel(f"Database connected: {self.database is not None}")
            db_label.setStyleSheet("color: #00ff00; font-size: 12px;")
            layout.addWidget(db_label)
        
        self.setLayout(layout)