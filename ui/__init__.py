"""
UI package initialization

User interface components for PyLocalInventory including:
- Main window
- Dialog components
- Tab components  
- Widget components
"""

from .main_window import MainWindow

# Subpackages can be imported as needed:
# from . import dialogs
# from . import tabs
# from . import widgets

__all__ = [
    'MainWindow'
]