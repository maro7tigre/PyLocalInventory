"""
Profile management dialog - create, delete, and switch between user profiles
"""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel

class ProfilesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Profiles Manager")
        self.setModal(True)
        self.setMinimumSize(500, 400)
        
        # Apply dark theme
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
        """)
        
        layout = QVBoxLayout()
        
        # Placeholder content
        label = QLabel("Profiles Dialog - Coming Soon")
        label.setStyleSheet("color: #ffffff; font-size: 16px;")
        layout.addWidget(label)
        
        self.setLayout(layout)