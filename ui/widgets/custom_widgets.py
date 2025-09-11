"""
Custom Widgets

Reusable custom widgets for PyLocalInventory application.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont
from .themed_widgets import ThemedLabel, GreenButton, RedButton, BlueButton


class InfoCard(QFrame):
    """Information card widget for displaying key-value pairs"""
    
    def __init__(self, title="", value="", subtitle="", parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            InfoCard {
                background-color: #3c3c3c;
                border: 1px solid #6f779a;
                border-radius: 6px;
                padding: 10px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        
        # Title
        if title:
            title_label = ThemedLabel(title)
            title_label.setStyleSheet("QLabel { color: #ffffff; font-size: 12px; }")
            layout.addWidget(title_label)
        
        # Value (main content)
        if value:
            value_label = ThemedLabel(str(value))
            value_label.setStyleSheet("QLabel { color: #ffffff; font-size: 18px; font-weight: bold; }")
            layout.addWidget(value_label)
        
        # Subtitle
        if subtitle:
            subtitle_label = ThemedLabel(subtitle)
            subtitle_label.setStyleSheet("QLabel { color: #bdbdc0; font-size: 10px; }")
            layout.addWidget(subtitle_label)


class StatusBadge(QLabel):
    """Colored status badge for showing states"""
    
    def __init__(self, text="", status_type="default", parent=None):
        super().__init__(text, parent)
        self.status_type = status_type
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(self._get_style())
        
        # Set fixed height and auto width
        self.setFixedHeight(24)
        self.setContentsMargins(8, 0, 8, 0)
    
    def _get_style(self):
        """Get styling based on status type"""
        styles = {
            "success": "background-color: #4CAF50; color: #ffffff;",
            "error": "background-color: #f44336; color: #ffffff;", 
            "warning": "background-color: #ff9800; color: #ffffff;",
            "info": "background-color: #2196F3; color: #ffffff;",
            "default": "background-color: #6f779a; color: #ffffff;"
        }
        
        base_style = """
            QLabel {
                border-radius: 12px;
                padding: 4px 8px;
                font-size: 10px;
                font-weight: bold;
        """
        
        return base_style + styles.get(self.status_type, styles["default"]) + "}"
    
    def set_status(self, text, status_type="default"):
        """Update badge text and status"""
        self.setText(text)
        self.status_type = status_type
        self.setStyleSheet(self._get_style())


class ActionToolbar(QWidget):
    """Toolbar with common action buttons"""
    
    add_clicked = Signal()
    edit_clicked = Signal()
    delete_clicked = Signal()
    
    def __init__(self, show_add=True, show_edit=True, show_delete=True, parent=None):
        super().__init__(parent)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        if show_add:
            self.add_btn = GreenButton("Add")
            self.add_btn.clicked.connect(self.add_clicked)
            layout.addWidget(self.add_btn)
        
        if show_edit:
            self.edit_btn = BlueButton("Edit")
            self.edit_btn.clicked.connect(self.edit_clicked)
            layout.addWidget(self.edit_btn)
        
        if show_delete:
            self.delete_btn = RedButton("Delete")
            self.delete_btn.clicked.connect(self.delete_clicked)
            layout.addWidget(self.delete_btn)
        
        layout.addStretch()  # Push buttons to the left


class LabeledInput(QWidget):
    """Input field with label and optional validation"""
    
    def __init__(self, label_text="", placeholder="", parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # Label
        if label_text:
            from .themed_widgets import ThemedLabel
            self.label = ThemedLabel(label_text)
            self.label.setStyleSheet("QLabel { font-weight: bold; }")
            layout.addWidget(self.label)
        
        # Input field
        from .themed_widgets import ThemedLineEdit
        self.input = ThemedLineEdit()
        if placeholder:
            self.input.setPlaceholderText(placeholder)
        layout.addWidget(self.input)
    
    def get_text(self):
        """Get input text"""
        return self.input.text()
    
    def set_text(self, text):
        """Set input text"""
        self.input.setText(text)
    
    def set_error(self, has_error=True):
        """Set error state styling"""
        if has_error:
            self.input.setStyleSheet("""
                QLineEdit {
                    background-color: #1d1f28;
                    color: #ffffff;
                    border: 2px solid #f44336;
                    border-radius: 4px;
                    padding: 4px;
                }
            """)
        else:
            # Reset to default themed style
            self.input.setStyleSheet("""
                QLineEdit {
                    background-color: #1d1f28;
                    color: #ffffff;
                    border: 1px solid #6f779a;
                    border-radius: 4px;
                    padding: 4px;
                }
                QLineEdit:focus {
                    border: 1px solid #BB86FC;
                }
            """)