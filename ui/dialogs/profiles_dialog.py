"""
Profile management dialog - create, delete, and switch between user profiles
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QFileDialog, QScrollArea,
                               QSplitter, QWidget, QHBoxLayout, QLineEdit, QPushButton)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
import os

from ui.widgets.themed_widgets import RedButton, GreenButton, BlueButton
from ui.widgets.cards_list import GridCardsList
from core.profiles import ProfileClass, ProfileManager

class ProfilesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Profiles Manager")
        self.setModal(True)
        self.setMinimumSize(800, 500)
        self.load_config()
        
        self.right_enabled = False
        # Initialize right panel components
        self.image_path = ""
        self.right_components = []  # Store all editable components
        self.parameter_edits = {}  # Store parameter line edits by key
        
        self.profile_manager = ProfileManager()
        self.empty_profile = self.profile_manager.empty_profile
        self.current_profile = None
        
        # Apply dark theme
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QScrollArea {
                background-color: #2b2b2b;
                border: none;
            }
            QLabel {
                color: #ffffff;
            }
            QLineEdit {
                background-color: #404040;
                border: 1px solid #555555;
                padding: 5px;
                color: #ffffff;
            }
            QLineEdit:disabled {
                background-color: #2a2a2a;
                border: 1px solid #333333;
                color: #666666;
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
        
        # Initialize with empty profile
        self.enable_right_layout(False)
        self.refresh_info()
        
    # MARK: Left Layout
    def create_left_layout(self):
        """Setup the left panel with profiles list"""
        left_layout = QVBoxLayout()
        left_layout.addWidget(GridCardsList(category="profiles"))
        return left_layout

    # MARK: Right Layout
    def create_right_layout(self):
        """Setup the right panel with profile details"""
        right_layout = QVBoxLayout()
        
        # Header with save and cancel buttons
        header_layout = QHBoxLayout()
        header_layout.addStretch()
        
        self.save_btn = GreenButton("Save")
        self.save_btn.setFixedSize(80, 30)
        self.save_btn.clicked.connect(self.save_profile)
        
        self.cancel_edit_btn = RedButton("Cancel")
        self.cancel_edit_btn.setFixedSize(80, 30)
        self.cancel_edit_btn.clicked.connect(self.cancel_edit)
        
        header_layout.addWidget(self.save_btn)
        header_layout.addWidget(self.cancel_edit_btn)
        
        right_layout.addLayout(header_layout)
        
        # Scrollable area
        scroll_area = QScrollArea()
        self.scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout()
        
        # Image preview
        self.image_label = QLabel("Click to select image")
        self.image_label.setFixedHeight(150)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("""
            QLabel {
                border: 2px dashed #555555;
                background-color: #404040;
                color: #aaaaaa;
            }
        """)
        self.image_label.mousePressEvent = self.select_image
        self.scroll_layout.addWidget(self.image_label)
        
        # Name field
        self.scroll_layout.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit()
        self.scroll_layout.addWidget(self.name_edit)
        
        # Create parameter fields dynamically
        self.parameter_edits = {}
        for param_key in self.empty_profile.available_parameters["dialog"]:
            display_name = self.empty_profile.get_display_name(param_key, self.language)
            self.scroll_layout.addWidget(QLabel(f"{display_name}:"))
            edit = QLineEdit()
            self.parameter_edits[param_key] = edit
            self.scroll_layout.addWidget(edit)
        
        # Password fields
        self.scroll_layout.addWidget(QLabel("Password:"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.scroll_layout.addWidget(self.password_edit)
        
        self.scroll_layout.addWidget(QLabel("Confirm Password:"))
        self.confirm_password_edit = QLineEdit()
        self.confirm_password_edit.setEchoMode(QLineEdit.Password)
        self.scroll_layout.addWidget(self.confirm_password_edit)
        
        self.scroll_layout.addStretch()
        
        self.scroll_widget.setLayout(self.scroll_layout)
        scroll_area.setWidget(self.scroll_widget)
        scroll_area.setWidgetResizable(True)
        
        right_layout.addWidget(scroll_area)
        
        # Store components for enable/disable functionality
        self.right_components = [
            self.save_btn,
            self.cancel_edit_btn,
            self.name_edit,
            self.password_edit,
            self.confirm_password_edit
        ]
        self.right_components.extend(self.parameter_edits.values())
        
        return right_layout
    
    # MARK: Profile Management
    def refresh_info(self, profile=None):
        """Update right panel with profile information"""
        if profile is None:
            profile = self.empty_profile
        
        self.current_profile = profile
        
        # Update name
        self.name_edit.setText(profile.name)
        
        # Update image preview
        if profile.preview_path and os.path.exists(profile.preview_path):
            pixmap = QPixmap(profile.preview_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(
                    self.image_label.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                self.image_label.setPixmap(scaled_pixmap)
                self.image_label.setText("")
            self.image_path = profile.preview_path
        else:
            self.image_label.clear()
            self.image_label.setText("Click to select image")
            self.image_path = ""
        
        # Update parameter fields
        for param_key, edit in self.parameter_edits.items():
            current_value = profile.get_value(param_key)
            if current_value is None:
                default_value = profile.get_parameter_info(param_key, "default")
                edit.setText(default_value if default_value else "")
            else:
                edit.setText(current_value)
        
        # Enable/disable password fields based on encrypted_phrase
        password_enabled = profile.encrypted_phrase is None and self.right_enabled
        self.password_edit.setEnabled(password_enabled)
        self.confirm_password_edit.setEnabled(password_enabled)
        
        # Clear password fields
        self.password_edit.setText("")
        self.confirm_password_edit.setText("")
    
    # MARK: UI Interactions
    def select_image(self, event):
        """Open file dialog to select profile image"""
        dialog = QFileDialog()
        image_path, _ = dialog.getOpenFileName(
            self,
            "Select Profile Image",
            "",
            "Image Files (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        
        if image_path:
            self.image_path = image_path
            # Load and display the image
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(
                    self.image_label.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                self.image_label.setPixmap(scaled_pixmap)
                self.image_label.setText("")
    
    def enable_right_layout(self, enabled):
        """Enable or disable all editable components in right layout"""
        for component in self.right_components:
            if hasattr(component, 'set_enable'):  # Themed buttons
                component.set_enable(enabled)
            elif hasattr(component, 'setEnabled'):  # Line edits and other widgets
                component.setEnabled(enabled)
        
        # Override password fields regardless of encrypted_phrase state
        self.password_edit.setEnabled(enabled)
        self.confirm_password_edit.setEnabled(enabled)
        
        # Handle image selection separately
        if enabled:
            self.image_label.mousePressEvent = self.select_image
        else:
            self.image_label.mousePressEvent = lambda event: None
        self.right_enabled = enabled
    
    # MARK: Profile Actions
    def save_profile(self):
        """Save current profile data"""
        # TODO: Implement profile saving logic
        pass
    
    def cancel_edit(self):
        """Cancel current profile editing"""
        # TODO: Implement cancel edit logic
        pass
        
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
        self.language = "en"
        
    def save_config(self):
        """Save current configuration to file"""
        pass #TODO: implement saving config