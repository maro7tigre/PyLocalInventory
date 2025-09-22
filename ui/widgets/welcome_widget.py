"""
Welcome Widget - Displays welcome screen when no profile is selected
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from ui.widgets.themed_widgets import GreenButton


class WelcomeWidget(QWidget):
    """Welcome screen widget with professional styling and responsive design"""
    
    profile_requested = Signal()  # Emitted when user wants to open profile manager
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.apply_styles()
    
    def setup_ui(self):
        """Setup the welcome interface with responsive design"""
        # Main layout with margins for better spacing
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(40)
        
        # Add stretch at top to center content vertically
        main_layout.addStretch(1)
        
        # Content container - responsive design
        content_container = QWidget()
        content_container.setObjectName("content_container")
        container_layout = QVBoxLayout(content_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(35)
        
        # Header section
        header_wrapper = QHBoxLayout()
        header_wrapper.addStretch()
        
        header_content = QWidget()
        header_content.setMaximumWidth(600)
        header_content.setMinimumWidth(300)
        header_layout = QVBoxLayout(header_content)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(15)
        
        # App title
        title_label = QLabel("PyLocalInventory")
        title_label.setObjectName("app_title")
        title_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(title_label)
        
        # Subtitle
        subtitle_label = QLabel("Professional Inventory Management System")
        subtitle_label.setObjectName("welcome_subtitle")
        subtitle_label.setAlignment(Qt.AlignCenter)
        subtitle_label.setWordWrap(True)
        header_layout.addWidget(subtitle_label)
        
        header_wrapper.addWidget(header_content)
        header_wrapper.addStretch()
        container_layout.addLayout(header_wrapper)
        
        # Welcome message section - responsive
        message_wrapper = QHBoxLayout()
        message_wrapper.addStretch()
        
        message_container = QWidget()
        message_container.setObjectName("welcome_message")
        message_container.setMaximumWidth(700)  # Increased from 500
        message_container.setMinimumWidth(300)   # Minimum for mobile
        message_layout = QVBoxLayout(message_container)
        message_layout.setContentsMargins(35, 35, 35, 35)
        message_layout.setSpacing(20)
        
        # Welcome text - improved wrapping
        welcome_text = QLabel(
            "Welcome to your comprehensive inventory management solution. "
            "Get started by selecting or creating a business profile to manage "
            "your products, clients, suppliers, and transactions."
        )
        welcome_text.setObjectName("welcome_text")
        welcome_text.setWordWrap(True)
        welcome_text.setAlignment(Qt.AlignCenter)
        message_layout.addWidget(welcome_text)
        
        message_wrapper.addWidget(message_container)
        message_wrapper.addStretch()
        container_layout.addLayout(message_wrapper)
        
        # Button section - responsive
        button_wrapper = QHBoxLayout()
        button_wrapper.addStretch()
        
        button_container = QWidget()
        button_container.setMaximumWidth(400)
        button_container.setMinimumWidth(250)
        button_layout = QVBoxLayout(button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)
        
        # Open profile button - full width within container
        self.open_profile_btn = GreenButton("Open Profile Manager")
        self.open_profile_btn.setObjectName("open_profile_btn")
        self.open_profile_btn.setMinimumHeight(50)  # Make button taller
        self.open_profile_btn.clicked.connect(self.profile_requested.emit)
        button_layout.addWidget(self.open_profile_btn)
        
        button_wrapper.addWidget(button_container)
        button_wrapper.addStretch()
        container_layout.addLayout(button_wrapper)
        
        main_layout.addWidget(content_container)
        
        # Add stretch at bottom to center content vertically
        main_layout.addStretch(1)
    
    def apply_styles(self):
        """Apply custom styling to the welcome widget"""
        self.setStyleSheet("""
            WelcomeWidget {
                background-color: #2b2b2b;
                min-height: 600px;
            }
            
            QWidget#content_container {
                background-color: transparent;
            }
            
            QLabel#app_title {
                font-size: 48px;
                font-weight: bold;
                color: #4CAF50;
                margin-bottom: 5px;
                text-align: center;
            }
            
            QLabel#welcome_subtitle {
                font-size: 20px;
                color: #cccccc;
                font-weight: 300;
                margin-bottom: 10px;
                line-height: 1.3;
            }
            
            QWidget#welcome_message {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #3c3c3c, stop:1 #2d2d2d);
                border: 2px solid #555555;
                border-radius: 15px;
            }
            
            QLabel#welcome_text {
                font-size: 18px;
                line-height: 1.6;
                color: #e0e0e0;
                text-align: center;
            }
            
            QPushButton#open_profile_btn {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4CAF50, stop:1 #45a049);
                color: white;
                border: none;
                padding: 18px 35px;
                font-size: 20px;
                font-weight: bold;
                border-radius: 12px;
                min-height: 50px;
            }
            
            QPushButton#open_profile_btn:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #5CBAE6, stop:1 #4CAF50);
            }
            
            QPushButton#open_profile_btn:pressed {
                background: #45a049;
            }
        """)
    
    def resizeEvent(self, event):
        """Handle resize events for responsive behavior"""
        super().resizeEvent(event)
        # Additional responsive logic could go here if needed