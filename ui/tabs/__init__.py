"""
Tabs package initialization

Tab components for PyLocalInventory including:
- Base tab functionality
- Entity management tabs
- Home and log tabs
"""

from .base_tab import BaseTab, BaseTableDelegate
from .home_tab import HomeTab
from .products_tab import ProductsTab
from .clients_tab import ClientsTab
from .suppliers_tab import SuppliersTab
from .sales_tab import SalesTab, SalesEditDialog
from .imports_tab import ImportsTab, ImportEditDialog
from .log_tab import LogTab

__all__ = [
    # Base functionality
    'BaseTab',
    'BaseTableDelegate',
    
    # Main tabs
    'HomeTab',
    'ProductsTab',
    'ClientsTab', 
    'SuppliersTab',
    'SalesTab',
    'ImportsTab',
    'LogTab',
    
    # Edit dialogs from tabs
    'SalesEditDialog',
    'ImportEditDialog'
]