
"""
Selectable Widgets

Reusable "lego pieces" for selection interfaces with proper click handling.
Supports both individual items and grids with + buttons.
"""

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, 
                               QScrollArea, QGridLayout, QSizePolicy)
from PySide6.QtCore import Signal, Qt, QEvent
from PySide6.QtGui import QPixmap, QFont
from .simple_widgets import PlaceholderPixmap


class SelectableItem(QFrame):
    """Base class for selectable items with proper click handling"""
    
    clicked = Signal(str)  # item_id
    context_menu_requested = Signal(str, object)  # item_id, global_pos
    
    def __init__(self, item_id, display_name="", is_add_button=False, parent=None):
        super().__init__(parent)
        self.item_id = item_id
        self.display_name = display_name or item_id
        self.is_add_button = is_add_button
        self.is_selected = False
        self.is_hovered = False
        
        # Prevent child widgets from stealing mouse events
        self.setAttribute(Qt.WA_NoMousePropagation, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        
        self.setup_ui()
        self.update_style()
    
    def setup_ui(self):
        """Override in subclasses"""
        pass
    
    def set_selected(self, selected):
        """Update selection state"""
        self.is_selected = selected
        self.update_style()
    
    def update_style(self):
        """Update styling based on current state"""
        if self.is_add_button:
            # Add button styling
            self.setStyleSheet("""
                SelectableItem {
                    background-color: #3c3c3c;
                    border: 2px dashed #6f779a;
                    border-radius: 6px;
                }
                SelectableItem:hover {
                    background-color: #44475c;
                    border: 2px dashed #BB86FC;
                }
            """)
        elif self.is_selected:
            # Selected state - green theme
            self.setStyleSheet("""
                SelectableItem {
                    background-color: #1f2d20;
                    border: 3px solid #4CAF50;
                    border-radius: 6px;
                }
            """)
        elif self.is_hovered:
            # Hover state
            self.setStyleSheet("""
                SelectableItem {
                    background-color: #44475c;
                    border: 2px solid #BB86FC;
                    border-radius: 6px;
                }
            """)
        else:
            # Default state
            self.setStyleSheet("""
                SelectableItem {
                    background-color: #3c3c3c;
                    border: 2px solid #6f779a;
                    border-radius: 6px;
                }
            """)
        self.update()
    
    def enterEvent(self, event):
        """Handle mouse enter"""
        if not self.is_selected:
            self.is_hovered = True
            self.update_style()
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """Handle mouse leave"""
        self.is_hovered = False
        self.update_style()
        super().leaveEvent(event)
    
    def mousePressEvent(self, event):
        """Handle mouse clicks - prevent event propagation to children"""
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.item_id)
            event.accept()
        elif event.button() == Qt.RightButton and not self.is_add_button:
            self.context_menu_requested.emit(self.item_id, event.globalPos())
            event.accept()
    
    def eventFilter(self, obj, event):
        """Filter events from child widgets to prevent them from handling clicks"""
        if event.type() == QEvent.MouseButtonPress:
            # Forward click to parent instead of letting child handle it
            self.mousePressEvent(event)
            return True
        return super().eventFilter(obj, event)
    
    def add_child_widget(self, widget):
        """Add child widget with event filtering"""
        widget.installEventFilter(self)
        widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)


class SquareSelectableItem(SelectableItem):
    """Square selectable item with image and name"""
    
    def __init__(self, item_id, display_name="", image_path=None, size=(120, 140), is_add_button=False, parent=None):
        self.image_path = image_path
        self.item_size = size
        super().__init__(item_id, display_name, is_add_button, parent)
    
    def setup_ui(self):
        """Setup square layout"""
        self.setFixedSize(*self.item_size)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        
        # Image area (takes most space)
        image_size = (self.item_size[0] - 20, self.item_size[1] - 40)
        self.image_label = QLabel()
        self.image_label.setFixedSize(*image_size)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setScaledContents(True)
        self.update_image()
        self.add_child_widget(self.image_label)
        layout.addWidget(self.image_label, alignment=Qt.AlignCenter)
        
        # Name label
        self.name_label = QLabel(self.display_name)
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setStyleSheet("QLabel { color: #ffffff; font-weight: bold; }")
        self.add_child_widget(self.name_label)
        layout.addWidget(self.name_label)
    
    def update_image(self):
        """Update displayed image"""
        image_size = (self.item_size[0] - 20, self.item_size[1] - 40)
        
        if self.is_add_button:
            pixmap = PlaceholderPixmap.create_add_button(image_size)
        elif self.image_path:
            loaded_pixmap = QPixmap(self.image_path)
            if not loaded_pixmap.isNull():
                pixmap = loaded_pixmap.scaled(*image_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            else:
                pixmap = PlaceholderPixmap.create_file_icon(image_size)
        else:
            pixmap = PlaceholderPixmap.create_file_icon(image_size)
        
        self.image_label.setPixmap(pixmap)
    
    def set_image(self, image_path):
        """Update image path and refresh display"""
        self.image_path = image_path
        self.update_image()


class HorizontalSelectableItem(SelectableItem):
    """Horizontal selectable item with image on left, name on upper right, and custom content area"""
    
    def __init__(self, item_id, display_name="", image_path=None, size=(300, 80), is_add_button=False, parent=None):
        self.image_path = image_path
        self.item_size = size
        self.custom_layout = None  # Will be available for adding custom content
        super().__init__(item_id, display_name, is_add_button, parent)
    
    def setup_ui(self):
        """Setup horizontal layout"""
        self.setFixedSize(*self.item_size)
        
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(10)
        
        # Left side - Image
        image_size = (self.item_size[1] - 16, self.item_size[1] - 16)  # Square based on height
        self.image_label = QLabel()
        self.image_label.setFixedSize(*image_size)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setScaledContents(True)
        self.update_image()
        self.add_child_widget(self.image_label)
        main_layout.addWidget(self.image_label)
        
        # Right side - Content area
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(2)
        
        # Name label (top)
        self.name_label = QLabel(self.display_name)
        self.name_label.setStyleSheet("QLabel { color: #ffffff; font-weight: bold; font-size: 12px; }")
        self.name_label.setWordWrap(True)
        self.add_child_widget(self.name_label)
        right_layout.addWidget(self.name_label)
        
        # Custom content area (bottom - expandable)
        self.custom_widget = QWidget()
        self.custom_layout = QVBoxLayout(self.custom_widget)
        self.custom_layout.setContentsMargins(0, 0, 0, 0)
        self.custom_layout.setSpacing(2)
        right_layout.addWidget(self.custom_widget, 1)  # Takes remaining space
        
        main_layout.addWidget(right_widget, 1)
    
    def update_image(self):
        """Update displayed image"""
        image_size = (self.item_size[1] - 16, self.item_size[1] - 16)
        
        if self.is_add_button:
            pixmap = PlaceholderPixmap.create_add_button(image_size)
        elif self.image_path:
            loaded_pixmap = QPixmap(self.image_path)
            if not loaded_pixmap.isNull():
                pixmap = loaded_pixmap.scaled(*image_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            else:
                pixmap = PlaceholderPixmap.create_file_icon(image_size)
        else:
            pixmap = PlaceholderPixmap.create_file_icon(image_size)
        
        self.image_label.setPixmap(pixmap)
    
    def add_custom_content(self, widget):
        """Add widget to custom content area"""
        self.custom_layout.addWidget(widget)
        self.add_child_widget(widget)
    
    def clear_custom_content(self):
        """Clear all custom content"""
        while self.custom_layout.count():
            item = self.custom_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
    
    def set_image(self, image_path):
        """Update image path and refresh display"""
        self.image_path = image_path
        self.update_image()


class SelectableGrid(QScrollArea):
    """Grid container for selectable items with single selection"""
    
    item_selected = Signal(str)  # item_id
    item_context_menu = Signal(str, object)  # item_id, global_pos
    add_button_clicked = Signal()
    
    def __init__(self, item_class=SquareSelectableItem, columns=4, show_add_button=True, parent=None):
        super().__init__(parent)
        self.item_class = item_class
        self.max_columns = columns
        self.show_add_button = show_add_button
        self.items = {}  # item_id -> widget
        self.selected_item_id = None
        
        self.setup_ui()
        
        if self.show_add_button:
            self.add_plus_button()
    
    def setup_ui(self):
        """Setup grid UI"""
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # Styled scroll area
        self.setStyleSheet("""
            SelectableGrid {
                background-color: #2b2b2b;
                border: 1px solid #6f779a;
                border-radius: 4px;
            }
        """)
        
        # Container widget
        container = QWidget()
        container.setStyleSheet("QWidget { background-color: #2b2b2b; }")
        self.setWidget(container)
        
        # Grid layout
        self.grid_layout = QGridLayout(container)
        self.grid_layout.setSpacing(8)
        self.grid_layout.setContentsMargins(8, 8, 8, 8)
    
    def add_plus_button(self):
        """Add the '+' button for creating new items"""
        add_item = self.item_class("__add__", "Add New", is_add_button=True)
        add_item.clicked.connect(lambda: self.add_button_clicked.emit())
        self.grid_layout.addWidget(add_item, 0, 0)
    
    def add_item(self, item_id, display_name="", image_path=None, **kwargs):
        """Add a selectable item to the grid"""
        # Remove existing item if it exists
        if item_id in self.items:
            self.remove_item(item_id)
        
        # Create new item
        item = self.item_class(item_id, display_name, image_path, **kwargs)
        item.clicked.connect(self._on_item_clicked)
        item.context_menu_requested.connect(lambda id, pos: self.item_context_menu.emit(id, pos))
        
        self.items[item_id] = item
        self._arrange_items()
        return item
    
    def remove_item(self, item_id):
        """Remove an item from the grid"""
        if item_id in self.items:
            item = self.items[item_id]
            self.grid_layout.removeWidget(item)
            item.deleteLater()
            del self.items[item_id]
            
            # Clear selection if removed item was selected
            if self.selected_item_id == item_id:
                self.selected_item_id = None
            
            self._arrange_items()
    
    def clear_items(self):
        """Remove all items (except add button)"""
        for item_id in list(self.items.keys()):
            self.remove_item(item_id)
    
    def set_selection(self, item_id):
        """Set which item is selected"""
        # Clear previous selection
        if self.selected_item_id and self.selected_item_id in self.items:
            self.items[self.selected_item_id].set_selected(False)
        
        # Set new selection
        self.selected_item_id = item_id
        if item_id and item_id in self.items:
            self.items[item_id].set_selected(True)
    
    def get_selection(self):
        """Get currently selected item ID"""
        return self.selected_item_id
    
    def get_item(self, item_id):
        """Get item widget by ID"""
        return self.items.get(item_id)
    
    def _on_item_clicked(self, item_id):
        """Handle item selection"""
        self.set_selection(item_id)
        self.item_selected.emit(item_id)
    
    def _arrange_items(self):
        """Arrange items in grid layout"""
        # Remove all widgets
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item and item.widget():
                self.grid_layout.removeWidget(item.widget())
        
        # Add back in order: add button first (if enabled), then items
        row, col = 0, 0
        
        if self.show_add_button:
            add_item = None
            for widget in [self.grid_layout.itemAt(i).widget() for i in range(self.grid_layout.count())]:
                if hasattr(widget, 'is_add_button') and widget.is_add_button:
                    add_item = widget
                    break
            
            if add_item:
                self.grid_layout.addWidget(add_item, row, col)
                col += 1
                if col >= self.max_columns:
                    col = 0
                    row += 1
        
        # Add regular items
        for item_id in sorted(self.items.keys()):
            item = self.items[item_id]
            self.grid_layout.addWidget(item, row, col)
            col += 1
            if col >= self.max_columns:
                col = 0
                row += 1


class SelectableList(QScrollArea):
    """Vertical list container for horizontal selectable items"""
    
    item_selected = Signal(str)  # item_id
    item_context_menu = Signal(str, object)  # item_id, global_pos
    add_button_clicked = Signal()
    
    def __init__(self, item_class=HorizontalSelectableItem, show_add_button=True, parent=None):
        super().__init__(parent)
        self.item_class = item_class
        self.show_add_button = show_add_button
        self.items = {}  # item_id -> widget
        self.selected_item_id = None
        
        self.setup_ui()
        
        if self.show_add_button:
            self.add_plus_button()
    
    def setup_ui(self):
        """Setup list UI"""
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # Styled scroll area
        self.setStyleSheet("""
            SelectableList {
                background-color: #2b2b2b;
                border: 1px solid #6f779a;
                border-radius: 4px;
            }
        """)
        
        # Container widget
        container = QWidget()
        container.setStyleSheet("QWidget { background-color: #2b2b2b; }")
        self.setWidget(container)
        
        # Vertical layout
        self.list_layout = QVBoxLayout(container)
        self.list_layout.setSpacing(4)
        self.list_layout.setContentsMargins(8, 8, 8, 8)
    
    def add_plus_button(self):
        """Add the '+' button for creating new items"""
        add_item = self.item_class("__add__", "Add New", is_add_button=True)
        add_item.clicked.connect(lambda: self.add_button_clicked.emit())
        self.list_layout.addWidget(add_item)
    
    def add_item(self, item_id, display_name="", image_path=None, **kwargs):
        """Add a selectable item to the list"""
        # Remove existing item if it exists
        if item_id in self.items:
            self.remove_item(item_id)
        
        # Create new item
        item = self.item_class(item_id, display_name, image_path, **kwargs)
        item.clicked.connect(self._on_item_clicked)
        item.context_menu_requested.connect(lambda id, pos: self.item_context_menu.emit(id, pos))
        
        self.items[item_id] = item
        
        # Insert before the stretch (and add button if present)
        insert_index = self.list_layout.count() - 1  # Before stretch
        if self.show_add_button:
            insert_index -= 1  # Before add button too
        
        self.list_layout.insertWidget(max(0, insert_index), item)
        return item
    
    def remove_item(self, item_id):
        """Remove an item from the list"""
        if item_id in self.items:
            item = self.items[item_id]
            self.list_layout.removeWidget(item)
            item.deleteLater()
            del self.items[item_id]
            
            # Clear selection if removed item was selected
            if self.selected_item_id == item_id:
                self.selected_item_id = None
    
    def clear_items(self):
        """Remove all items (except add button)"""
        for item_id in list(self.items.keys()):
            self.remove_item(item_id)
    
    def set_selection(self, item_id):
        """Set which item is selected"""
        # Clear previous selection
        if self.selected_item_id and self.selected_item_id in self.items:
            self.items[self.selected_item_id].set_selected(False)
        
        # Set new selection
        self.selected_item_id = item_id
        if item_id and item_id in self.items:
            self.items[item_id].set_selected(True)
    
    def get_selection(self):
        """Get currently selected item ID"""
        return self.selected_item_id
    
    def get_item(self, item_id):
        """Get item widget by ID"""
        return self.items.get(item_id)
    
    def _on_item_clicked(self, item_id):
        """Handle item selection"""
        self.set_selection(item_id)
        self.item_selected.emit(item_id)