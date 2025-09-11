"""
Home tab - dashboard and overview of key metrics and recent activity
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

class HomeTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setup_ui()
    
    def setup_ui(self):
        """Setup home tab interface"""
        layout = QVBoxLayout()
        
        # Placeholder content
        label = QLabel("Home Tab - Coming Soon")
        label.setStyleSheet("color: #ffffff; font-size: 16px;")
        layout.addWidget(label)
        
        self.setLayout(layout)