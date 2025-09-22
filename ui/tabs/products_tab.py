"""
Products Tab - Updated to use BaseTab
"""
from ui.tabs.base_tab import BaseTab
from classes.product_class import ProductClass
from ui.dialogs.edit_dialogs.product_dialog import ProductEditDialog


class ProductsTab(BaseTab):
    """Products tab with editable table"""
    
    def __init__(self, database=None, parent=None):
        super().__init__(ProductClass, ProductEditDialog, database, parent)
    
    def get_preview_category(self):
        """Override to specify preview category for products"""
        return "product"