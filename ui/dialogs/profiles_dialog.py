"""
Profile management dialog - create, delete, and switch between user profiles
"""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QFileDialog
from PySide6.QtWidgets import QSplitter, QWidget, QHBoxLayout, QLineEdit
from PySide6.QtCore import Qt
import os

from ui.widgets.themed_widgets import RedButton, GreenButton, BlueButton
from ui.widgets.cards_list import GridCardsList

class ProfilesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Profiles Manager")
        self.setModal(True)
        self.setMinimumSize(800, 500)
        self.load_config()
        
        # Apply dark theme
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
        """)
        
        # Main vertical layout
        layout = QVBoxLayout()

        # Header row with label, stretch, line edit, and browse button
        header_layout = QHBoxLayout()
        header_label = QLabel("Profiles Dialog")
        header_label.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: bold;")
        header_layout.addWidget(header_label)

        header_layout.addStretch()

        self.profiles_path_edit = QLineEdit()
        self.profiles_path_edit.setReadOnly(True)
        self.profiles_path_edit.setFixedWidth(350)
        # Set initial path from config
        self.profiles_path_edit.setText(self.profiles_path)
        header_layout.addWidget(self.profiles_path_edit)

        browse_btn = BlueButton("Browse")
        browse_btn.setFixedSize(100, 30)
        browse_btn.clicked.connect(self.browse_profiles_path)
        header_layout.addWidget(browse_btn)

        layout.addLayout(header_layout)

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
        confirm_btn.clicked.connect(self.confirm)
        confirm_btn.setFixedSize(150, 30)
        cancel_btn = RedButton("Cancel")
        cancel_btn.clicked.connect(self.cancel)
        cancel_btn.setFixedSize(150, 30)
        button_layout.addStretch()
        button_layout.addWidget(confirm_btn)
        button_layout.addWidget(cancel_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        self.setLayout(layout)

    def create_left_layout(self):
        """Setup the left panel with profiles list"""
        left_layout = QVBoxLayout()
        left_layout.addWidget(GridCardsList(category="profiles"))
        return left_layout

    def create_right_layout(self):
        """Setup the right panel with profile details"""
        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("Right Content"))
        return right_layout
        
    def browse_profiles_path(self):
        """Open directory dialog to select profiles folder"""
        dialog = QFileDialog()
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        
        # Start from current profiles path or home directory
        start_dir = self.profiles_path if os.path.exists(self.profiles_path) else os.path.expanduser("~")
        
        selected_dir = dialog.getExistingDirectory(
            self, 
            "Select Profiles Directory", 
            start_dir
        )
        
        # Update path if user selected a directory (not cancelled)
        if selected_dir:
            self.profiles_path = selected_dir
            self.profiles_path_edit.setText(selected_dir)

    def confirm(self):
        """Save changes and close dialog"""
        self.accept()
        
    def cancel(self):
        """Close dialog without saving changes"""
        self.reject()
    
    # MARK: Config
    def load_config(self):
        """Load configuration from file or set defaults"""
        self.profiles_path = "./profiles"
        
    def save_config(self):
        """Save current configuration to file"""
        pass #TODO: implement saving config