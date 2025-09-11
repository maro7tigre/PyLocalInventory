"""
Simple Widgets

Basic utility widgets for the PyLocalInventory application.
"""

from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont


class ClickableLabel(QLabel):
    """Label that acts like a button with click events"""
    clicked = Signal()
    
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("""
            QLabel {
                color: #BB86FC;
                text-decoration: underline;
                background-color: transparent;
            }
            QLabel:hover {
                color: #9965DA;
            }
        """)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class PlaceholderPixmap:
    """Utility class for creating placeholder pixmaps with text/icons"""
    
    @staticmethod
    def create(size, text="", background_color="#44475c", text_color="#ffffff"):
        """Create a placeholder pixmap with text"""
        pixmap = QPixmap(*size)
        pixmap.fill(QColor(background_color))
        
        if text:
            painter = QPainter(pixmap)
            painter.setPen(QColor(text_color))
            painter.setFont(QFont("Arial", 12, QFont.Bold))
            painter.drawText(pixmap.rect(), Qt.AlignCenter, text)
            painter.end()
        
        return pixmap
    
    @staticmethod
    def create_add_button(size=(80, 80)):
        """Create add button placeholder with + symbol"""
        pixmap = QPixmap(*size)
        pixmap.fill(QColor("#44475c"))
        
        painter = QPainter(pixmap)
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Arial", 24, QFont.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "+")
        painter.end()
        
        return pixmap
    
    @staticmethod
    def create_file_icon(size=(60, 60), icon="📄"):
        """Create file icon placeholder"""
        return PlaceholderPixmap.create(size, icon, "#44475c", "#ffffff")
    
    @staticmethod
    def create_profile_placeholder(size=(150, 150)):
        """Create profile image placeholder"""
        return PlaceholderPixmap.create(size, "Profile\nImage", "#44475c", "#ffffff")