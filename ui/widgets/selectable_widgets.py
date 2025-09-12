from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QMenu
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction


class ClickableWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected = False
        self._hovered = False
        self._change_label_colors = False
        
        # Default colors
        self._bg_normal = "#3B3B3B"
        self._bg_hover = "#171717"
        self._bg_selected = "#3B3B3B"
        self._border_normal = "#a4a4a4"
        self._border_hover = "#ffffff"
        self._border_selected = "#009200"
        
        self.setup_ui()
        self.setup_behavior()
        self._update_style()
    
    def setup_ui(self):
        """Override this method to add your content"""
        layout = QVBoxLayout(self)
        label = QLabel("Your content here")
        layout.addWidget(label)
    
    def setup_behavior(self):
        """Make all children non-interactive and enable hover tracking"""
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_Hover, True)  # Enable hover events
        for child in self.findChildren(QWidget):
            child.setFocusPolicy(Qt.NoFocus)
            child.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    
    def set_colors(self, bg_normal=None, bg_hover=None, bg_selected=None,
                   border_normal=None, border_hover=None, border_selected=None):
        """Set theme colors (only pass the ones you want to change)"""
        if bg_normal is not None:
            self._bg_normal = bg_normal
        if bg_hover is not None:
            self._bg_hover = bg_hover
        if bg_selected is not None:
            self._bg_selected = bg_selected
        if border_normal is not None:
            self._border_normal = border_normal
        if border_hover is not None:
            self._border_hover = border_hover
        if border_selected is not None:
            self._border_selected = border_selected
        self._update_style()
    
    def set_selected(self, selected=True):
        """Set selected state"""
        self._selected = selected
        self._update_style()
    
    def set_label_color_changes(self, enabled=True):
        """Enable/disable automatic label color changes"""
        self._change_label_colors = enabled
        self._update_style()
    
    def enterEvent(self, event):
        """Mouse enters widget"""
        self._hovered = True
        self._update_style()
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """Mouse leaves widget"""
        self._hovered = False
        self._update_style()
        super().leaveEvent(event)
    
    def _update_style(self):
        """Update widget styling based on current state"""
        # Determine current colors
        if self._selected:
            bg_color = self._bg_selected
            border_color = self._border_selected
        elif self._hovered:
            bg_color = self._bg_hover
            border_color = self._border_hover
        else:
            bg_color = self._bg_normal
            border_color = self._border_normal
        
        # Apply widget style
        self.setStyleSheet(f"""
            ClickableWidget {{
                background-color: {bg_color};
                border: 2px solid {border_color};
                border-radius: 4px;
            }}
        """)
        
        # Apply label colors if enabled
        if self._change_label_colors:
            for label in self.findChildren(QLabel):
                label.setStyleSheet(f"color: {border_color};")
    
    def mousePressEvent(self, event):
        """Handle clicks anywhere on the widget"""
        if event.button() == Qt.LeftButton:
            self.on_pressed()
        super().mousePressEvent(event)
    
    def contextMenuEvent(self, event):
        """Handle right-click menu"""
        menu = QMenu(self)
        
        edit_action = QAction("Edit", self)
        duplicate_action = QAction("Duplicate", self)
        delete_action = QAction("Delete", self)
        
        edit_action.triggered.connect(self.on_edit)
        duplicate_action.triggered.connect(self.on_duplicate)
        delete_action.triggered.connect(self.on_delete)
        
        menu.addAction(edit_action)
        menu.addAction(duplicate_action)
        menu.addSeparator()
        menu.addAction(delete_action)
        
        menu.exec(event.globalPos())
    
    # Override these methods in your subclass
    def on_pressed(self):
        pass
    
    def on_edit(self):
        pass
    
    def on_duplicate(self):
        pass
    
    def on_delete(self):
        pass