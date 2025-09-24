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
    
    def get_search_options(self):
        """Get autocomplete options for client search"""
        if not self.all_items:
            return []
        
        options = set()
        for obj in self.all_items:
            try:
                # Add usernames and client names
                username = obj.get_value('username')
                name = obj.get_value('name')
                if username:
                    options.add(str(username))
                if name:
                    options.add(str(name))
            except:
                pass
        
        return sorted(list(options))
    
    def setup_order_options(self):
        """Setup order dropdown options for clients"""
        self.order_combo.clear()
        self.order_combo.addItems([
            "Default",
            "Username ↑",
            "Username ↓", 
            "Client Name ↑",
            "Client Name ↓"
        ])
    
    def get_searchable_fields(self):
        """Get fields that can be searched for clients"""
        return ['username', 'name']
    
    def matches_search(self, obj, search_text):
        """Check if client matches search criteria"""
        if not search_text:
            return True
        
        search_lower = search_text.lower()
        
        # Check username and client name
        try:
            username = obj.get_value('username') or ""
            name = obj.get_value('name') or ""
            
            if (search_lower in username.lower() or 
                search_lower in name.lower()):
                return True
        except:
            pass
        
        return False
    
    def sort_items(self, items, order_option):
        """Sort clients based on order option"""
        if not order_option or order_option == "Default":
            return items
        
        try:
            if order_option == "Username ↑":
                items.sort(key=lambda x: str(x.get_value('username') or "").lower())
            elif order_option == "Username ↓":
                items.sort(key=lambda x: str(x.get_value('username') or "").lower(), reverse=True)
            elif order_option == "Client Name ↑":
                items.sort(key=lambda x: str(x.get_value('name') or "").lower())
            elif order_option == "Client Name ↓":
                items.sort(key=lambda x: str(x.get_value('name') or "").lower(), reverse=True)
        except Exception as e:
            print(f"Error sorting clients: {e}")
        
        return items