"""
Encryption settings dialog - manage profile password and encryption options
"""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel

class EncryptionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Encryption Password")
        self.setModal(True)
        self.setMinimumSize(400, 300)
        
        # Apply dark theme
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
        """)
        
        layout = QVBoxLayout()
        
        # Placeholder content
        label = QLabel("Encryption Dialog - Coming Soon")
        label.setStyleSheet("color: #ffffff; font-size: 16px;")
        layout.addWidget(label)
        
        self.setLayout(layout)