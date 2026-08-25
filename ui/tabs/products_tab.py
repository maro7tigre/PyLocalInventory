"""
Products Tab - Updated to use BaseTab
"""
from PySide6.QtWidgets import QMessageBox

from ui.tabs.base_tab import BaseTab
from classes.product_class import ProductClass
from ui.dialogs.edit_dialogs.product_dialog import ProductEditDialog
from ui.widgets.themed_widgets import BlueButton


class ProductsTab(BaseTab):
    """Products tab with editable table"""
    
    def __init__(self, database=None, parent=None):
        super().__init__(ProductClass, ProductEditDialog, database, parent)

    def add_additional_toolbar_buttons(self, layout):
        """Add the Stock History viewer command."""
        self.stock_history_btn = BlueButton("Stock History")
        self.stock_history_btn.setToolTip(
            "Show every stock movement (imports, sales, adjustments) "
            "explaining the selected product's current stock"
        )
        self.stock_history_btn.setMinimumHeight(20)
        self.stock_history_btn.setStyleSheet(
            self.stock_history_btn.styleSheet()
            + "\nQPushButton { font-size: 14px; padding: 5px 10px; }"
        )
        self.stock_history_btn.clicked.connect(self.view_stock_history)
        layout.insertWidget(layout.count() - 1, self.stock_history_btn)

    def view_stock_history(self):
        """Open the stock-movement ledger for the selected product."""
        product_id = self.get_selected_id()
        if product_id is None:
            QMessageBox.information(
                self, "No Selection", "Please select a product first."
            )
            return
        from ui.dialogs.stock_history_dialog import show_stock_history
        product_name = ""
        for obj in getattr(self, "all_items", []) or []:
            try:
                if obj.id == product_id:
                    product_name = str(obj.get_value("name") or "")
                    break
            except Exception:
                continue
        show_stock_history(product_id, product_name, self.database, self)
    
    def get_preview_category(self):
        """Override to specify preview category for products"""
        return "product"
    
    def get_search_options(self):
        """Get autocomplete options for product search"""
        if not self.all_items:
            return []
        
        options = set()
        for obj in self.all_items:
            try:
                # Add usernames and product names
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
        """Setup order dropdown options for products"""
        self.order_combo.clear()
        self.order_combo.addItems([
            "Default",
            "Username ↑",
            "Username ↓", 
            "Product Name ↑",
            "Product Name ↓",
            "Price ↑",
            "Price ↓",
            "Quantity ↑",
            "Quantity ↓"
        ])

    def _order_by_field(self, order_option):
        """Map display labels to allowlisted sort columns."""
        field = super()._order_by_field(order_option)
        if field == 'product_name':
            return 'name'
        if field == 'price':
            return 'sale_price'
        return field
    
    def get_searchable_fields(self):
        """Get fields that can be searched for products"""
        return ['username', 'name']
    
    def matches_search(self, obj, search_text):
        """Check if product matches search criteria"""
        if not search_text:
            return True
        
        search_lower = search_text.lower()
        
        # Check username and product name
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
        """Sort products based on order option"""
        if not order_option or order_option == "Default":
            return items
        
        try:
            if order_option == "Username ↑":
                items.sort(key=lambda x: str(x.get_value('username') or "").lower())
            elif order_option == "Username ↓":
                items.sort(key=lambda x: str(x.get_value('username') or "").lower(), reverse=True)
            elif order_option == "Product Name ↑":
                items.sort(key=lambda x: str(x.get_value('name') or "").lower())
            elif order_option == "Product Name ↓":
                items.sort(key=lambda x: str(x.get_value('name') or "").lower(), reverse=True)
            elif order_option == "Price ↑":
                items.sort(key=lambda x: float(x.get_value('sale_price') or 0))
            elif order_option == "Price ↓":
                items.sort(key=lambda x: float(x.get_value('sale_price') or 0), reverse=True)
            elif order_option == "Quantity ↑":
                items.sort(key=lambda x: float(x.get_value('quantity') or 0))
            elif order_option == "Quantity ↓":
                items.sort(key=lambda x: float(x.get_value('quantity') or 0), reverse=True)
        except Exception as e:
            print(f"Error sorting products: {e}")
        
        return items