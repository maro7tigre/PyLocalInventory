"""
PreviewWidget: A customizable widget to display images or fallback text/emoji.
how to use it:
preview = PreviewWidget(size=100, category="individual")
preview.set_image_path("path/to/image.png")  # Optional: set image path
preview.set_text("👤")  # Optional: set fallback text/emoji
preview.update_size(150)  # Optional: update size later
"""
    
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QFont
import os


class PreviewWidget(QWidget):
    def __init__(self, size=64, category="individual", parent=None):
        super().__init__(parent)
        self.category = category
        self._image_path = None
        
        self._set_size(size)
        self.setup_ui()
        self.setup_style()
        self._set_default_content()
    
    def _set_size(self, size):
        """Handle size as int (square) or list [height, width]"""
        if isinstance(size, (list, tuple)):
            self.height = size[0]
            self.width = size[1]
        else:
            self.height = size
            self.width = size
        
        self.setFixedSize(self.width, self.height)
    
    def update_size(self, size):
        """Update widget size and refresh content"""
        self._set_size(size)
        self._refresh_content()
    
    def setup_ui(self):
        """Setup the layout and label"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        
        self.content_label = QLabel()
        self.content_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.content_label)
    
    def setup_style(self):
        """Set transparent background with grey border"""
        self.setStyleSheet("""
            PreviewWidget {
                background-color: transparent;
                border: 1px solid #c0c0c0;
                border-radius: 4px;
            }
        """)
    
    def set_image_path(self, path):
        """Set image path and display image or fallback to text"""
        self._image_path = path
        self._refresh_content()
    
    def _refresh_content(self):
        """Refresh the displayed content based on current state"""
        if self._image_path and os.path.exists(self._image_path):
            self._display_image(self._image_path)
        else:
            self._display_fallback()
    
    def _display_image(self, path):
        """Display scaled image"""
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            # Scale to fit widget size minus border padding
            scaled_width = self.width - 6
            scaled_height = self.height - 6
            scaled_pixmap = pixmap.scaled(scaled_width, scaled_height, 
                                        Qt.KeepAspectRatio, 
                                        Qt.SmoothTransformation)
            self.content_label.setPixmap(scaled_pixmap)
            self.content_label.setText("")
    
    def _display_fallback(self):
        """Display text/emoji when no valid image"""
        self.content_label.setPixmap(QPixmap())  # Clear any existing pixmap
        
        # Get default text for category
        text = self._get_category_text()
        self.content_label.setText(text)
        
        # Calculate font size based on smallest dimension
        min_size = min(self.width, self.height)
        font_size = max(8, min_size // 4)
        font = QFont()
        font.setPointSize(font_size)
        self.content_label.setFont(font)
    
    def _get_category_text(self):
        """Get default text/emoji for each category"""
        category_map = {
            "individual": "👤",
            "company": "🏢", 
            "product": "📦",
            "add": "+"
        }
        return category_map.get(self.category, "?")
    
    def _set_default_content(self):
        """Set initial content"""
        self._display_fallback()
    
    def set_text(self, text):
        """Manually set text content (ignores image path)"""
        self.content_label.setPixmap(QPixmap())
        self.content_label.setText(text)
        
        # Calculate font size based on smallest dimension
        min_size = min(self.width, self.height)
        font_size = max(8, min_size // 4)
        font = QFont()
        font.setPointSize(font_size)
        self.content_label.setFont(font)