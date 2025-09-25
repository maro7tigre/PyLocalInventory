from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QScrollArea, QApplication, QMainWindow
from PySide6.QtCore import Qt, QTimer
from .card_widgets import SquareCard
import uuid
import sys


class BaseCardsList(QWidget):
    """Base class for managing collections of cards with different layouts"""
    
    def __init__(self, category=None, card_type=SquareCard, add_available=True, parent=None):
        super().__init__(parent)
        self.card_type = card_type
        self.add_available = add_available
        self.category = category
        self.parent_dialog = parent  # Store reference to parent dialog
        self.cards = {}  # Dictionary to store cards by ID
        self.selected_card = None  # Currently selected card ID
        self.add_card = None  # Reference to add card if enabled

        
        self.setup_ui()
        self.load_cards()
    
    def setup_ui(self):
        """Setup the base UI - override in subclasses for specific layouts"""
        pass
    
    def load_cards(self):
        """Load available cards - load from parent's profile manager or backup manager"""
        # Clear existing cards
        for card in list(self.cards.values()):
            self.remove_card_from_layout(card)
            card.deleteLater()
        self.cards.clear()
        
        if self.add_card:
            self.remove_card_from_layout(self.add_card)
            self.add_card.deleteLater()
            self.add_card = None
        
        # Create add card if enabled
        if self.add_available:
            self.create_add_card()
        
        # Load data based on category
        if hasattr(self.parent_dialog, 'profile_manager') and self.category == "profiles":
            # Load profile data
            for profile_name, profile in self.parent_dialog.profile_manager.available_profiles.items():
                self.create_card(
                    label_text=profile_name,
                    card_id=profile_name,
                    preview_path=profile.preview_path if hasattr(profile, 'preview_path') else None
                )
        elif hasattr(self.parent_dialog, 'get_available_backups') and self.category == "backups":
            # Load backup data
            backups = self.parent_dialog.get_available_backups()
            for backup_name, backup_info in backups.items():
                self.create_card(
                    label_text=backup_name,
                    card_id=backup_name,
                    preview_path=None  # Backups don't have preview images
                )
        else:
            # Fallback to example data for other categories
            for i in range(5):
                self.create_card(f"Item {i+1}")
    
    def create_add_card(self):
        """Create the special 'add' card"""
        self.add_card = self.card_type("Add New", category="add", parent=self)
        self.add_card.on_pressed = self.on_add_card_pressed
        self.add_card_to_layout(self.add_card, is_add_card=True)
    
    def create_card(self, label_text, card_id=None, preview_path=None):
        """Create a new card with unique ID"""
        if card_id is None:
            card_id = str(uuid.uuid4())
        
        card = self.card_type(label_text, parent=self, category=self.category)
        card.id = card_id
        if preview_path:
            card.set_preview_path(preview_path)
        
        self.cards[card_id] = card
        self.add_card_to_layout(card)
        return card_id
    
    def add_card_to_layout(self, card, is_add_card=False):
        """Add card to the layout - implement in subclasses"""
        pass
    
    def remove_card(self, card_id):
        """Remove a card from the list"""
        if card_id in self.cards:
            card = self.cards[card_id]
            self.remove_card_from_layout(card)
            card.deleteLater()
            del self.cards[card_id]
            
            if self.selected_card == card_id:
                self.selected_card = None
    
    def remove_card_from_layout(self, card):
        """Remove card from layout - implement in subclasses"""
        pass
    
    def select_card(self, card_id):
        """Select a card and update visual states"""
        # Deselect previous card
        if self.selected_card and self.selected_card in self.cards:
            self.cards[self.selected_card].set_selected(False)
        
        # Select new card (can be None to deselect all)
        self.selected_card = card_id
        if card_id and card_id in self.cards:
            self.cards[card_id].set_selected(True)
    
    # Events to delegate to parent dialog
    def on_add_card_pressed(self):
        """Handle add card press - delegate to parent"""
        if hasattr(self.parent_dialog, 'on_add_card_pressed'):
            self.parent_dialog.on_add_card_pressed()
    
    def on_card_pressed(self, card_id):
        """Handle regular card press - delegate to parent"""
        self.select_card(card_id)
        if hasattr(self.parent_dialog, 'on_card_pressed'):
            self.parent_dialog.on_card_pressed(card_id)
    
    def on_card_edit(self, card_id):
        """Handle card edit - delegate to parent"""
        if hasattr(self.parent_dialog, 'on_card_edit'):
            self.parent_dialog.on_card_edit(card_id)
    
    def on_card_duplicate(self, card_id):
        """Handle card duplicate - delegate to parent"""
        if hasattr(self.parent_dialog, 'on_card_duplicate'):
            self.parent_dialog.on_card_duplicate(card_id)
    
    def on_card_delete(self, card_id):
        """Handle card delete - delegate to parent"""
        if hasattr(self.parent_dialog, 'on_card_delete'):
            self.parent_dialog.on_card_delete(card_id)
        else:
            # Fallback behavior
            self.remove_card(card_id)


class _HorizontalCardsList(BaseCardsList):
    """Horizontal layout - cards arranged left to right"""
    
    def setup_ui(self):
        self.layout = QHBoxLayout(self)
        self.layout.setSpacing(10)  # Small space between cards
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.addStretch()  # Push cards to left initially
    
    def add_card_to_layout(self, card, is_add_card=False):
        # Insert before the stretch (last item)
        insert_index = self.layout.count() - 1
        self.layout.insertWidget(insert_index, card)
    
    def remove_card_from_layout(self, card):
        self.layout.removeWidget(card)


class _VerticalCardsList(BaseCardsList):
    """Vertical layout - cards arranged top to bottom"""
    
    def setup_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(10)  # Small space between cards
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.addStretch()  # Push cards to top initially
    
    def add_card_to_layout(self, card, is_add_card=False):
        # Insert before the stretch (last item)
        insert_index = self.layout.count() - 1
        self.layout.insertWidget(insert_index, card)
    
    def remove_card_from_layout(self, card):
        self.layout.removeWidget(card)


class _GridCardsList(BaseCardsList):
    """Grid layout - cards arranged in grid with equal spacing like file manager"""
    
    def __init__(self, category=None, card_type=SquareCard, add_available=True, card_size=120, min_spacing=10, parent=None):
        self.card_size = card_size
        self.min_spacing = min_spacing
        self.min_layout_width = card_size + (min_spacing * 2)
        self.cards_order = []  # Track card order for grid positioning
        super().__init__(category, card_type, add_available, parent)
    
    def setup_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)
        
        # Container widget for grid positioning
        self.grid_container = QWidget()
        self.layout.addWidget(self.grid_container)
        self.layout.addStretch()  # Push grid to top
        
        # Timer for delayed layout updates (performance optimization)
        self.layout_timer = QTimer()
        self.layout_timer.timeout.connect(self._update_grid_layout)
        self.layout_timer.setSingleShot(True)
    
    def add_card_to_layout(self, card, is_add_card=False):
        card.setParent(self.grid_container)
        if is_add_card:
            self.cards_order.insert(0, card)  # Add card goes first
        else:
            self.cards_order.append(card)
        
        # Delayed layout update for performance
        self.layout_timer.start(50)
    
    def remove_card_from_layout(self, card):
        if card in self.cards_order:
            self.cards_order.remove(card)
            self.layout_timer.start(50)
    
    def resizeEvent(self, event):
        """Handle resize events to update grid layout"""
        super().resizeEvent(event)
        self.layout_timer.start(50)
    
    def _update_grid_layout(self):
        """Update grid positions with equal spacing"""
        if not self.cards_order:
            return
        
        container_width = self.grid_container.width()
        if container_width < self.min_layout_width:
            return
        
        # Calculate how many cards fit horizontally
        available_width = container_width - (self.min_spacing * 2)  # Account for margins
        cards_per_row = max(1, (available_width + self.min_spacing) // (self.card_size + self.min_spacing))
        
        # Calculate actual spacing for centering
        total_cards_width = cards_per_row * self.card_size
        total_spacing_width = (cards_per_row - 1) * self.min_spacing
        extra_space = available_width - total_cards_width - total_spacing_width
        horizontal_margin = extra_space // 2 + self.min_spacing
        
        # Position cards in grid
        row = 0
        col = 0
        
        for card in self.cards_order:
            x = horizontal_margin + col * (self.card_size + self.min_spacing)
            y = self.min_spacing + row * (self.card_size + self.min_spacing)
            
            card.move(x, y)
            card.show()
            
            col += 1
            if col >= cards_per_row:
                col = 0
                row += 1
        
        # Update container height based on rows needed
        total_rows = (len(self.cards_order) + cards_per_row - 1) // cards_per_row
        container_height = max(100, total_rows * (self.card_size + self.min_spacing) + self.min_spacing)
        self.grid_container.setFixedHeight(container_height)


# Scrollable wrapper classes
class HorizontalCardsList(QScrollArea):
    """Scrollable horizontal cards list"""
    
    def __init__(self, category=None, card_type=SquareCard, add_available=True, parent=None):
        super().__init__(parent)
        self.cards_list = _HorizontalCardsList(category, card_type, add_available, parent)
        
        self.setWidget(self.cards_list)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setWidgetResizable(True)
    
    def __getattr__(self, name):
        """Delegate attribute access to the internal cards list"""
        return getattr(self.cards_list, name)


class VerticalCardsList(QScrollArea):
    """Scrollable vertical cards list"""
    
    def __init__(self, category=None, card_type=SquareCard, add_available=True, parent=None):
        super().__init__(parent)
        self.cards_list = _VerticalCardsList(category, card_type, add_available, parent)
        
        self.setWidget(self.cards_list)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidgetResizable(True)
    
    def __getattr__(self, name):
        """Delegate attribute access to the internal cards list"""
        return getattr(self.cards_list, name)


class GridCardsList(QScrollArea):
    """Scrollable grid cards list"""
    
    def __init__(self, category = None, card_type=SquareCard, add_available=True, card_size=120, min_spacing=10, parent=None):
        super().__init__(parent)
        self.cards_list = _GridCardsList(category, card_type, add_available, card_size, min_spacing, parent)
        
        self.setWidget(self.cards_list)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidgetResizable(True)
    
    def __getattr__(self, name):
        """Delegate attribute access to the internal cards list"""
        return getattr(self.cards_list, name)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Create main window
    window = QMainWindow()
    window.setWindowTitle("Card Lists Demo")
    window.resize(800, 600)
    
    # Choose which layout to test - change this line to switch layouts
    scroll_area = HorizontalCardsList(category="individual")  # or VerticalCardsList() or GridCardsList()
    
    window.setCentralWidget(scroll_area)
    window.show()
    
    sys.exit(app.exec())