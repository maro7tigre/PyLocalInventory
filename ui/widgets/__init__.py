"""
Widgets Package

Reusable widget components for PyLocalInventory.
"""

# Import all themed widgets
from .themed_widgets import *

# Import simple utility widgets - currently empty, consider removing if unused
# from .simple_widgets import *

# Import selectable widgets (our new "lego pieces")
from .card_widgets import *

# Import specialized widgets
from .welcome_widget import WelcomeWidget
from .password_widget import PasswordWidget

__all__ = [
    # Themed widgets (buttons, inputs, etc.)
    'ThemedMainWindow', 'ThemedDialog', 'GreenButton', 'RedButton', 'OrangeButton', 'BlueButton',
    'ColoredLineEdit', 'ThemedLabel', 'ThemedLineEdit', 'ThemedTextEdit', 
    'ThemedSpinBox', 'ThemedGroupBox', 'ThemedScrollArea', 'ThemedSplitter',
    'ThemedCheckBox', 'ThemedRadioButton', 'ThemedListWidget',
    
    # Simple widgets - empty for now
    
    # Selectable widgets
    'ClickableCard', 'SquareCard',
    
    # Specialized widgets
    'WelcomeWidget', 'PasswordWidget',
]