"""
Dialogs package initialization

Dialog components for PyLocalInventory including:
- Profile management dialogs
- Backup management dialogs
- Report generation dialogs
- Entity edit dialogs
"""

from .profiles_dialog import ProfilesDialog
from .backups_dialog import BackupsDialog
from .reports_dialog import ReportsDialog

# Edit dialogs are imported from their subdirectory
from .edit_dialogs import (
    BaseEditDialog,
    BaseOperationDialog, 
    DialogManager,
    ProductEditDialog,
    ClientEditDialog,
    SupplierEditDialog,
    SaleEditDialog,
    ImportEditDialog
)

__all__ = [
    # Main dialogs
    'ProfilesDialog',
    'BackupsDialog', 
    'ReportsDialog',
    
    # Edit dialogs
    'BaseEditDialog',
    'BaseOperationDialog',
    'DialogManager',
    'ProductEditDialog',
    'ClientEditDialog',
    'SupplierEditDialog', 
    'SaleEditDialog',
    'ImportEditDialog'
]