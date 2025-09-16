"""
Profile management dialog - create, delete, and switch between user profiles
"""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel
from PySide6.QtWidgets import QSplitter, QWidget, QHBoxLayout, QPushButton
from PySide6.QtCore import Qt

from ui.widgets.themed_widgets import RedButton, GreenButton
from ui.widgets.cards_list import GridCardsList

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
        
        # Main vertical layout
        layout = QVBoxLayout()

        # Header
        header_label = QLabel("Profiles Dialog")
        header_label.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: bold;")
        layout.addWidget(header_label, alignment=Qt.AlignLeft)

        # Splitter for left and right layouts
        splitter = QSplitter(Qt.Horizontal)

        # Create left and right widgets and set their layouts
        left_widget = QWidget()
        right_widget = QWidget()
        left_widget.setLayout(self.create_left_layout())
        right_widget.setLayout(self.create_right_layout())

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([250, 250])  # Initial sizes

        layout.addWidget(splitter, stretch=1)

        # Confirm and Cancel buttons centered
        button_layout = QHBoxLayout()
        confirm_btn = GreenButton("Confirm")
        cancel_btn = RedButton("Cancel")
        button_layout.addStretch()
        button_layout.addWidget(confirm_btn)
        button_layout.addWidget(cancel_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        self.setLayout(layout)

    def create_left_layout(self):
        # Replace with your actual left layout setup
        left_layout = QVBoxLayout()
        left_layout.addWidget(GridCardsList(category="profiles"))
        return left_layout

    def create_right_layout(self):
        # Replace with your actual right layout setup
        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("Right Content"))
        return right_layout
        
        