"""
Log tab - activity log and system events display
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

class LogTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setup_ui()
    
    def setup_ui(self):
        """Setup log tab interface"""
        layout = QVBoxLayout()
        
        # Placeholder content
        label = QLabel("Log Tab - Coming Soon")
        label.setStyleSheet("color: #ffffff; font-size: 16px;")
        layout.addWidget(label)
        
        self.setLayout(layout)