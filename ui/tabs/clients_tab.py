"""
Clients Tab - Updated to use BaseTab
"""
from ui.tabs.base_tab import BaseTab
from classes.client_class import ClientClass
from ui.dialogs.edit_dialogs.client_dialog import ClientEditDialog


class ClientsTab(BaseTab):
    """Clients tab with editable table"""
    
    def __init__(self, database=None, parent=None):
        super().__init__(ClientClass, ClientEditDialog, database, parent)
    
    def get_preview_category(self):
        """Override to specify preview category for clients"""
        # Check client type to determine preview category
        # For now, default to individual - could be enhanced to check client type
        return "individual"