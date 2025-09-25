"""
Edit Dialogs package initialization

Entity edit dialogs for PyLocalInventory including:
- Base dialog functionality
- Entity-specific edit dialogs
- Operation dialogs for sales and imports
"""

from .base_dialog import BaseEditDialog, DialogManager
from .base_operation_dialog import BaseOperationDialog
from .product_dialog import ProductEditDialog
from .client_dialog import ClientEditDialog
from .supplier_dialog import SupplierEditDialog
from .sale_dialog import SaleEditDialog
from .import_dialog import ImportEditDialog

__all__ = [
    # Base functionality
    'BaseEditDialog',
    'BaseOperationDialog',
    'DialogManager',
    
    # Entity edit dialogs
    'ProductEditDialog',
    'ClientEditDialog', 
    'SupplierEditDialog',
    'SaleEditDialog',
    'ImportEditDialog'
]