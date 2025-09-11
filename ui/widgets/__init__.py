"""
Widgets Package

Reusable widget components for PyLocalInventory.
"""

# Import all themed widgets
from .themed_widgets import *

# Import simple utility widgets  
from .simple_widgets import ClickableLabel, PlaceholderPixmap

# Import custom complex widgets
from .custom_widgets import InfoCard, StatusBadge, ActionToolbar, LabeledInput

# Import selectable widgets (our new "lego pieces")
from .selectable_widgets import (
    SelectableItem, SquareSelectableItem, HorizontalSelectableItem,
    SelectableGrid, SelectableList
)

__all__ = [
    # Themed widgets (buttons, inputs, etc.)
    'ThemedMainWindow', 'ThemedDialog', 'GreenButton', 'RedButton', 'OrangeButton', 'BlueButton',
    'ColoredLineEdit', 'ThemedLabel', 'ThemedLineEdit', 'ThemedTextEdit', 
    'ThemedSpinBox', 'ThemedGroupBox', 'ThemedScrollArea', 'ThemedSplitter',
    'ThemedCheckBox', 'ThemedRadioButton', 'ThemedListWidget',
    
    # Simple widgets
    'ClickableLabel', 'PlaceholderPixmap',
    
    # Custom widgets
    'InfoCard', 'StatusBadge', 'ActionToolbar', 'LabeledInput',
    
    # Selectable widgets (the new lego pieces)
    'SelectableItem', 'SquareSelectableItem', 'HorizontalSelectableItem',
    'SelectableGrid', 'SelectableList'
]