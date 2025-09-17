"""
Home tab - dashboard and overview of key metrics and recent activity
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

class HomeTab(QWidget):
    def __init__(self, database=None):
        super().__init__()
        self.database = database
        self.setup_ui()
    
    def setup_ui(self):
        """Setup home tab interface"""
        layout = QVBoxLayout()
        
        # Placeholder content
        label = QLabel("Home Tab - Coming Soon")
        label.setStyleSheet("color: #ffffff; font-size: 16px;")
        layout.addWidget(label)
        
        if self.database:
            db_label = QLabel(f"Database connected: {self.database is not None}")
            db_label.setStyleSheet("color: #00ff00; font-size: 12px;")
            layout.addWidget(db_label)
        
        self.setLayout(layout)