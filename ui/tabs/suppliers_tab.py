"""
Suppliers Tab - Updated to use BaseTab
"""
from ui.tabs.base_tab import BaseTab
from classes.supplier_class import SupplierClass
from ui.dialogs.edit_dialogs.supplier_dialog import SupplierEditDialog


class SuppliersTab(BaseTab):
    """Suppliers tab with editable table"""
    
    def __init__(self, database=None, parent=None):
        super().__init__(SupplierClass, SupplierEditDialog, database, parent)
    
    def get_preview_category(self):
        """Override to specify preview category for suppliers"""
        return "company"