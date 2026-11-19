"""
PreviewWidget: A customizable widget to display images or fallback text/emoji.
how to use it:
preview = PreviewWidget(size=100, category="individual")
preview.set_image_path("path/to/image.png")  # Optional: set image path
preview.set_text("👤")  # Optional: set fallback text/emoji
preview.update_size(150)  # Optional: update size later

Images are decoded once, scaled to a small thumbnail, and kept in a bounded
cache so large tables never re-decode the same full-size picture on every
refresh (the main source of image-related freezes on big tabs).
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QFont
import os
import logging

logger = logging.getLogger(__name__)

# --- Bounded thumbnail cache ------------------------------------------------
# All access happens on the GUI thread only (cell rendering + deferred preview
# loading both run there), so no locking is required.
_THUMB_MAX_BYTES = 64 * 1024 * 1024   # hard memory cap for cached pixmaps
_THUMB_MAX_ENTRIES = 400              # hard entry cap
_THUMB_MAX_DIMENSION = 128            # thumbnails never exceed this square
_thumb_cache = {}                     # path -> QPixmap
_thumb_order = []                     # LRU order (front = newest)
_thumb_bytes = 0


def clear_thumbnail_cache():
    """Drop all cached thumbnails (used when profiles/connections change)."""
    global _thumb_bytes
    _thumb_cache.clear()
    _thumb_order.clear()
    _thumb_bytes = 0


def _cache_thumb(path, pixmap):
    """Insert into the bounded LRU cache, evicting oldest entries first."""
    global _thumb_bytes
    key = os.path.normcase(path)
    if key in _thumb_cache:
        _thumb_bytes -= pixmap_size(_thumb_cache[key])
        _thumb_order.remove(key)
    _thumb_bytes += pixmap_size(pixmap)
    _thumb_cache[key] = pixmap
    _thumb_order.insert(0, key)
    while (
        _thumb_bytes > _THUMB_MAX_BYTES
        or len(_thumb_cache) > _THUMB_MAX_ENTRIES
    ) and _thumb_order:
        oldest = _thumb_order.pop()
        _thumb_bytes -= pixmap_size(_thumb_cache.pop(oldest))


def _get_cached_thumb(path):
    key = os.path.normcase(path)
    pixmap = _thumb_cache.get(key)
    if pixmap is None:
        return None
    _thumb_order.remove(key)
    _thumb_order.insert(0, key)
    return pixmap


def _pixmap_byte_size(pixmap):
    try:
        return pixmap.width() * pixmap.height() * 4
    except Exception:
        return 0


# Keep a module-local alias so the helper above reads naturally.
pixmap_size = _pixmap_byte_size


def _thumbnail_for_path(path):
    """Return a cached small pixmap for ``path``, decoding at most once."""
    cached = _get_cached_thumb(path)
    if cached is not None:
        return cached
    full = QPixmap(path)
    if full.isNull():
        return None
    size = min(_THUMB_MAX_DIMENSION, full.width(), full.height())
    if size <= 0:
        return None
    thumb = full.scaled(
        size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation
    )
    full = None  # release the full-size decode immediately
    _cache_thumb(path, thumb)
    return thumb


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

    def get_image_path(self):
        """Get current image path"""
        return self._image_path

    def has_content(self):
        """Check if widget has image content"""
        return self._image_path is not None and os.path.exists(self._image_path)

    def _refresh_content(self):
        """Refresh the displayed content based on current state"""
        if self._image_path and os.path.exists(self._image_path):
            self._display_image(self._image_path)
        else:
            self._display_fallback()

    def _display_image(self, path):
        """Display cached, pre-scaled thumbnail (never the full-size decode)."""
        thumb = _thumbnail_for_path(path)
        if thumb is None:
            self._display_fallback()
            return
        scaled = thumb.scaled(
            max(1, self.width - 6),
            max(1, self.height - 6),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.content_label.setPixmap(scaled)
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
            "profiles": "👤",
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
