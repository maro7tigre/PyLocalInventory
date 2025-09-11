"""
Clients tab - client management and relationship tracking
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

class ClientsTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setup_ui()
    
    def setup_ui(self):
        """Setup clients tab interface"""
        layout = QVBoxLayout()
        
        # Placeholder content
        label = QLabel("Clients Tab - Coming Soon")
        label.setStyleSheet("color: #ffffff; font-size: 16px;")
        layout.addWidget(label)
        
        self.setLayout(layout)