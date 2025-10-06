from PySide6.QtWidgets import QMainWindow, QPushButton, QLineEdit, QLabel, QWidget, QHBoxLayout
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

# MARK: Main Window
class ThemedMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QMenuBar {
                background-color: #3c3c3c;
                color: #ffffff;
                border: 1px solid #555555;
            }
            QMenuBar::item {
                background-color: transparent;
                padding: 4px 8px;
            }
            QMenuBar::item:selected {
                background-color: #555555;
            }
            QMenu {
                background-color: #3c3c3c;
                color: #ffffff;
                border: 1px solid #555555;
            }
            QMenu::item:selected {
                background-color: #555555;
            }
            QTabWidget {
                background-color: #2b2b2b;
            }
            QTabWidget::pane {
                border: 1px solid #555555;
                background-color: #2b2b2b;
            }
            QTabBar::tab {
                background-color: #3c3c3c;
                color: #ffffff;
                padding: 8px 16px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #555555;
            }
            QLabel {
                color: #ffffff;
            }
        """)

# MARK: Buttons
class GreenButton(QPushButton):
    def __init__(self, text=""):
        super().__init__(text)
        self.enabled_style = """
            QPushButton {
                background-color: #2b2b2b;
                color: #4CAF50;
                border: 2px solid #4CAF50;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4CAF50;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: #45a049;
            }
        """
        self.disabled_style = """
            QPushButton {
                background-color: #1a1a1a;
                color: #888888;
                border: 2px solid #444444;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
        """
        self.setStyleSheet(self.enabled_style)

    def set_enable(self, enabled: bool):
        self.setEnabled(enabled)
        if enabled:
            self.setStyleSheet(self.enabled_style)
        else:
            self.setStyleSheet(self.disabled_style)

class RedButton(QPushButton):
    def __init__(self, text=""):
        super().__init__(text)
        self.enabled_style = """
            QPushButton {
                background-color: #2b2b2b;
                color: #f44336;
                border: 2px solid #f44336;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #f44336;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: #da190b;
            }
        """
        self.disabled_style = """
            QPushButton {
                background-color: #1a1a1a;
                color: #888888;
                border: 2px solid #444444;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
        """
        self.setStyleSheet(self.enabled_style)

    def set_enable(self, enabled: bool):
        self.setEnabled(enabled)
        if enabled:
            self.setStyleSheet(self.enabled_style)
        else:
            self.setStyleSheet(self.disabled_style)

class OrangeButton(QPushButton):
    def __init__(self, text=""):
        super().__init__(text)
        self.enabled_style = """
            QPushButton {
                background-color: #2b2b2b;
                color: #ff9800;
                border: 2px solid #ff9800;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ff9800;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: #e68900;
            }
        """
        self.disabled_style = """
            QPushButton {
                background-color: #1a1a1a;
                color: #888888;
                border: 2px solid #444444;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
        """
        self.setStyleSheet(self.enabled_style)

    def set_enable(self, enabled: bool):
        self.setEnabled(enabled)
        if enabled:
            self.setStyleSheet(self.enabled_style)
        else:
            self.setStyleSheet(self.disabled_style)

class BlueButton(QPushButton):
    def __init__(self, text=""):
        super().__init__(text)
        self.enabled_style = """
            QPushButton {
                background-color: #2b2b2b;
                color: #2196F3;
                border: 2px solid #2196F3;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2196F3;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: #0b7dda;
            }
        """
        self.disabled_style = """
            QPushButton {
                background-color: #1a1a1a;
                color: #888888;
                border: 2px solid #444444;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
        """
        self.setStyleSheet(self.enabled_style)

    def set_enable(self, enabled: bool):
        self.setEnabled(enabled)
        if enabled:
            self.setStyleSheet(self.enabled_style)
        else:
            self.setStyleSheet(self.disabled_style)

# MARK: Line Edits
class ColoredLineEdit(QLineEdit):
    def __init__(self, border_color="#ffffff"):
        super().__init__()
        self.default_color = border_color
        self.setStyleSheet(f"""
            QLineEdit {{
                background-color: #3c3c3c;
                color: #ffffff;
                border: 2px solid {border_color};
                padding: 8px;
                border-radius: 4px;
                font-size: 14px;
            }}
            QLineEdit:focus {{
                border-color: #2196F3;
            }}
        """)
    
    def set_border_color(self, color):
        """Change border color of the line edit"""
        self.setStyleSheet(f"""
            QLineEdit {{
                background-color: #3c3c3c;
                color: #ffffff;
                border: 2px solid {color};
                padding: 8px;
                border-radius: 4px;
                font-size: 14px;
            }}
            QLineEdit:focus {{
                border-color: #2196F3;
            }}
        """)
    
    def reset_border_color(self):
        """Reset border to default color"""
        self.set_border_color(self.default_color)
        
# MARK: Labels
class ThemedLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setStyleSheet("""
            QLabel {
                color: #ffffff;
                background-color: transparent;
            }
        """)

# MARK: Password Input with Toggle
class PasswordInputWidget(QWidget):
    def __init__(self, border_color="#ffffff", parent=None):
        super().__init__(parent)
        self.default_color = border_color
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the password input with toggle button"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Password input
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        
        # Toggle button
        self.toggle_button = QPushButton("🔒")
        self.toggle_button.setFixedSize(45, 45)  # Square button
        self.toggle_button.clicked.connect(self.toggle_visibility)
        
        layout.addWidget(self.password_input)
        layout.addWidget(self.toggle_button)
        
        self.apply_styles()
    
    def toggle_visibility(self):
        """Toggle password visibility"""
        if self.password_input.echoMode() == QLineEdit.Password:
            self.password_input.setEchoMode(QLineEdit.Normal)
            self.toggle_button.setText("👀")
        else:
            self.password_input.setEchoMode(QLineEdit.Password)
            self.toggle_button.setText("🔒")
    
    def apply_styles(self):
        """Apply styles to make input and button look like one widget"""
        self.password_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: #3c3c3c;
                color: #ffffff;
                border: 2px solid {self.default_color};
                border-right: none;
                padding: 8px;
                border-radius: 4px;
                border-top-right-radius: 0px;
                border-bottom-right-radius: 0px;
                font-size: 14px;
                min-height: 29px;
            }}
            QLineEdit:focus {{
                border-color: #2196F3;
                border-right: none;
            }}
        """)
        
        self.toggle_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #3c3c3c;
                color: #cccccc;
                border: 2px solid {self.default_color};
                border-left: none;
                border-radius: 4px;
                border-top-left-radius: 0px;
                border-bottom-left-radius: 0px;
                font-size: 16px;
                min-height: 29px;
                max-height: 45px;
            }}
            QPushButton:hover {{
                background-color: #4a4a4a;
            }}
            QPushButton:pressed {{
                background-color: #555555;
            }}
        """)
    
    def set_border_color(self, color):
        """Change border color of the input widget"""
        self.password_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: #3c3c3c;
                color: #ffffff;
                border: 2px solid {color};
                border-right: none;
                padding: 8px;
                border-radius: 4px;
                border-top-right-radius: 0px;
                border-bottom-right-radius: 0px;
                font-size: 14px;
                min-height: 29px;
            }}
            QLineEdit:focus {{
                border-color: #2196F3;
                border-right: none;
            }}
        """)
        
        self.toggle_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #3c3c3c;
                color: #cccccc;
                border: 2px solid {color};
                border-left: none;
                border-radius: 4px;
                border-top-left-radius: 0px;
                border-bottom-left-radius: 0px;
                font-size: 16px;
                min-height: 29px;
                max-height: 45px;
            }}
            QPushButton:hover {{
                background-color: #4a4a4a;
            }}
            QPushButton:pressed {{
                background-color: #555555;
            }}
        """)
    
    def reset_border_color(self):
        """Reset border to default color"""
        self.set_border_color(self.default_color)
    
    # Proxy methods to make it work like a QLineEdit
    def text(self):
        return self.password_input.text()
    
    def setText(self, text):
        self.password_input.setText(text)
    
    def setPlaceholderText(self, text):
        self.password_input.setPlaceholderText(text)
    
    def setFocus(self):
        self.password_input.setFocus()
    
    def selectAll(self):
        self.password_input.selectAll()
    
    def textChanged(self):
        return self.password_input.textChanged
    
    def returnPressed(self):
        return self.password_input.returnPressed
    
    def setEnabled(self, enabled):
        self.password_input.setEnabled(enabled)
        self.toggle_button.setEnabled(enabled)