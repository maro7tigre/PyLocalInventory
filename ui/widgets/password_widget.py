"""
Password Widget - Displays password entry screen for selected profile
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from ui.widgets.themed_widgets import GreenButton, ColoredLineEdit, PasswordInputWidget
from ui.widgets.preview_widget import PreviewWidget


class PasswordWidget(QWidget):
    """Password entry widget with profile preview - full width responsive design"""
    
    password_submitted = Signal(str)  # Emitted with entered password
    profile_change_requested = Signal()  # Emitted when user wants to change profile
    
    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.setup_ui()
        self.apply_styles()
    
    def setup_ui(self):
        """Setup the password entry interface with full-width responsive design"""
        # Main layout with margins
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(30)
        
        # Add stretch at top to center content vertically
        main_layout.addStretch(1)
        
        # Profile card container - full width with max constraint
        profile_container = QWidget()
        profile_container.setObjectName("profile_container")
        container_layout = QVBoxLayout(profile_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        
        # Profile card - centered but with max width
        profile_card_wrapper = QHBoxLayout()
        profile_card_wrapper.addStretch()
        
        profile_card = QWidget()
        profile_card.setObjectName("profile_card")
        profile_card.setMaximumWidth(500)  # Reasonable max width
        profile_card.setMinimumWidth(350)   # Minimum width for mobile
        profile_layout = QVBoxLayout(profile_card)
        profile_layout.setContentsMargins(30, 30, 30, 30)
        profile_layout.setSpacing(15)
        
        # Profile preview
        preview_container = QHBoxLayout()
        preview_container.addStretch()
        self.profile_preview = PreviewWidget(100, "individual")
        if self.profile and hasattr(self.profile, 'preview_path') and self.profile.preview_path:
            self.profile_preview.set_image_path(self.profile.preview_path)
        preview_container.addWidget(self.profile_preview)
        preview_container.addStretch()
        profile_layout.addLayout(preview_container)
        
        # Profile information
        profile_name = self.profile.name if self.profile else "No Profile"
        self.profile_name_label = QLabel(profile_name)
        self.profile_name_label.setObjectName("profile_name")
        self.profile_name_label.setAlignment(Qt.AlignCenter)
        profile_layout.addWidget(self.profile_name_label)
        
        # Company name (bigger and bold)
        company_name = "Unknown Company"
        if self.profile:
            company_name = self.profile.get_value("company name") or "Unknown Company"
        
        self.company_name_label = QLabel(company_name)
        self.company_name_label.setObjectName("company_name")
        self.company_name_label.setAlignment(Qt.AlignCenter)
        profile_layout.addWidget(self.company_name_label)
        
        # Change profile button - full width within card
        self.change_profile_btn = QPushButton("Change Profile")
        self.change_profile_btn.setObjectName("change_profile_btn")
        self.change_profile_btn.clicked.connect(self.profile_change_requested.emit)
        profile_layout.addWidget(self.change_profile_btn)
        
        profile_card_wrapper.addWidget(profile_card)
        profile_card_wrapper.addStretch()
        container_layout.addLayout(profile_card_wrapper)
        
        main_layout.addWidget(profile_container)
        
        # Password form container
        form_container = QWidget()
        form_container.setObjectName("form_container")
        form_wrapper_layout = QVBoxLayout(form_container)
        form_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        
        # Form content - centered with max width
        form_content_wrapper = QHBoxLayout()
        form_content_wrapper.addStretch()
        
        form_content = QWidget()
        form_content.setMaximumWidth(500)  # Match profile card width
        form_content.setMinimumWidth(350)  # Minimum width
        form_layout = QVBoxLayout(form_content)
        form_layout.setContentsMargins(30, 20, 30, 20)
        form_layout.setSpacing(20)
        
        # Password label
        password_label = QLabel("Enter Password:")
        password_label.setObjectName("password_label")
        form_layout.addWidget(password_label)
        
        # Password input - full width within form
        self.password_input = PasswordInputWidget()
        self.password_input.setObjectName("password_input")
        self.password_input.setPlaceholderText("Enter your password...")
        self.password_input.returnPressed().connect(self._submit_password)
        self.password_input.textChanged().connect(self._reset_password_styling)
        form_layout.addWidget(self.password_input)
        
        # Confirm button - full width within form
        self.confirm_btn = GreenButton("Unlock Profile")
        self.confirm_btn.setObjectName("confirm_btn")
        self.confirm_btn.setMinimumHeight(45)  # Make button taller
        self.confirm_btn.clicked.connect(self._submit_password)
        form_layout.addWidget(self.confirm_btn)
        
        form_content_wrapper.addWidget(form_content)
        form_content_wrapper.addStretch()
        form_wrapper_layout.addLayout(form_content_wrapper)
        
        main_layout.addWidget(form_container)
        
        # Add stretch at bottom to center content vertically
        main_layout.addStretch(1)
        
        # Focus on password input
        self.password_input.setFocus()
    
    def _submit_password(self):
        """Submit password for validation"""
        password = self.password_input.text()
        self.password_submitted.emit(password)
    
    def _reset_password_styling(self):
        """Reset password input styling when text changes"""
        self.password_input.reset_border_color()
    
    def set_password_error(self):
        """Set error styling for incorrect password"""
        self.password_input.set_border_color("#f44336")  # Red border
        self.password_input.selectAll()  # Select all text for easy re-entry
    
    def apply_styles(self):
        """Apply custom styling to the password widget"""
        self.setStyleSheet("""
            PasswordWidget {
                background-color: #2b2b2b;
                min-height: 600px;
            }
            
            QWidget#profile_container {
                background-color: transparent;
            }
            
            QWidget#profile_card {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #3c3c3c, stop:1 #2d2d2d);
                border: 2px solid #4CAF50;
                border-radius: 15px;
                margin-bottom: 10px;
            }
            
            QLabel#profile_name {
                font-size: 16px;
                color: #cccccc;
                margin: 5px 0px;
                font-weight: normal;
            }
            
            QLabel#company_name {
                font-size: 26px;
                font-weight: bold;
                color: #ffffff;
                margin: 5px 0px 10px 0px;
                line-height: 1.2;
            }
            
            QPushButton#change_profile_btn {
                background-color: transparent;
                color: #2196F3;
                border: 2px solid #2196F3;
                padding: 10px 15px;
                font-size: 15px;
                font-weight: 500;
                border-radius: 8px;
                min-height: 35px;
            }
            
            QPushButton#change_profile_btn:hover {
                background-color: #2196F3;
                color: white;
                border-color: #2196F3;
            }
            
            QPushButton#change_profile_btn:pressed {
                background-color: #1976D2;
                border-color: #1976D2;
            }
            
            QWidget#form_container {
                background-color: transparent;
            }
            
            QLabel#password_label {
                font-size: 18px;
                font-weight: 600;
                color: #e0e0e0;
                margin-bottom: 5px;
            }
            
            PasswordInputWidget#password_input {
                min-height: 45px;
            }
            
            QPushButton#confirm_btn {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4CAF50, stop:1 #45a049);
                color: white;
                border: none;
                padding: 15px 25px;
                font-size: 18px;
                font-weight: bold;
                border-radius: 10px;
                min-height: 45px;
            }
            
            QPushButton#confirm_btn:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #5CBAE6, stop:1 #4CAF50);
            }
            
            QPushButton#confirm_btn:pressed {
                background: #45a049;
            }
            
            QPushButton#confirm_btn:disabled {
                background: #666666;
                color: #999999;
            }
        """)
    
    def resizeEvent(self, event):
        """Handle resize events to ensure responsive design"""
        super().resizeEvent(event)
        # Could add dynamic sizing logic here if needed