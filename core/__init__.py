"""
Core package initialization

Core functionality for PyLocalInventory including:
- Database management
- Profile management  
- Password management
"""

from .database import Database
from .profiles import ProfileManager, ProfileClass
from .password import PasswordManager

__all__ = [
    'Database',
    'ProfileManager', 
    'ProfileClass',
    'PasswordManager'
]