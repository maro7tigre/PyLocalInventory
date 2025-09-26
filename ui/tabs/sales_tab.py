"""
Sales tab - Updated to use unified BaseTab approach
Now consistent with Products/Clients/Suppliers experience
"""
from ui.tabs.base_tab import BaseTab
from classes.sales_class import SalesClass
from classes.sales_item_class import SalesItemClass
from ui.dialogs.edit_dialogs.base_operation_dialog import BaseOperationDialog
from datetime import datetime
import re


class SalesEditDialog(BaseOperationDialog):
    """Sales-specific dialog using unified base operation dialog"""
    
    def __init__(self, sales_id=None, database=None, parent=None):
        super().__init__(
            operation_class=SalesClass,
            item_class=SalesItemClass, 
            operation_id=sales_id,
            database=database,
            parent=parent
        )
    
    def get_item_columns(self):
        """Override to specify sales item columns"""
        return ['product_preview', 'product_name', 'quantity', 'unit_price', 'subtotal', 'delete_action']
    
    def validate_data(self):
        """Sales-specific validation"""
        # Keep only base validation; existence check handled in auto-create workflow
        return super().validate_data()
    
    def _validate_client_exists(self, username):
        """Check if client username exists in database"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return False
        
        try:
            self.database.cursor.execute("SELECT COUNT(*) FROM Clients WHERE username = ?", (username,))
            result = self.database.cursor.fetchone()
            return result[0] > 0 if result else False
        except Exception as e:
            print(f"Error validating client: {e}")
            return False


class SalesTab(BaseTab):
    """Sales tab with unified table experience - consistent with other entity tabs"""
    
    def __init__(self, database=None, parent=None):
        super().__init__(SalesClass, SalesEditDialog, database, parent)
    
    def setup_ui(self):
        """Override setup_ui to add reports button"""
        # Call parent setup first
        super().setup_ui()
        
        # Find the controls layout and add reports button
        controls_layout = None
        for i in range(self.layout().count()):
            item = self.layout().itemAt(i)
            if item and hasattr(item, 'layout') and item.layout():
                # Check if this is the controls layout by looking for buttons
                for j in range(item.layout().count()):
                    widget = item.layout().itemAt(j).widget() if item.layout().itemAt(j) else None
                    if widget and hasattr(widget, 'text') and 'Add' in widget.text():
                        controls_layout = item.layout()
                        break
                if controls_layout:
                    break
        
        if controls_layout:
            from ui.widgets.themed_widgets import OrangeButton
            self.reports_btn = OrangeButton("📊 Reports")
            self.reports_btn.clicked.connect(self.show_reports)
            self.reports_btn.setStyleSheet(self.reports_btn.styleSheet() + "\nQPushButton { font-size: 14px; padding: 5px 10px; }")
            self.reports_btn.setMinimumHeight(20)
            
            # Insert before the last item (which should be the refresh button)
            controls_layout.insertWidget(controls_layout.count() - 1, self.reports_btn)
    
    def get_preview_category(self):
        """Override to specify preview category for sales operations"""
        return "individual"  # Since sales are typically associated with clients
    
    def get_search_options(self):
        """Get autocomplete options for sales search"""
        if not self.all_items:
            return []
        
        options = set()
        for obj in self.all_items:
            try:
                # Add client usernames, client names, and products
                client_username = obj.get_value('client_username')
                client_name = obj.get_value('client_name')
                date = obj.get_value('date')
                
                if client_username:
                    options.add(str(client_username))
                if client_name:
                    options.add(str(client_name))
                if date:
                    # Add formatted date
                    options.add(str(date))
                
                # Add products from sales items if available
                if hasattr(obj, 'items') and obj.items:
                    for item in obj.items:
                        try:
                            product_name = item.get_value('product_name')
                            if product_name:
                                options.add(str(product_name))
                        except:
                            pass
            except:
                pass
        
        return sorted(list(options))
    
    def setup_order_options(self):
        """Setup order dropdown options for sales"""
        self.order_combo.clear()
        self.order_combo.addItems([
            "Default",
            "Client Username ↑",
            "Client Username ↓", 
            "Client Name ↑",
            "Client Name ↓",
            "Recent ↑",
            "Recent ↓",
            "Total ↑",
            "Total ↓"
        ])
    
    def get_searchable_fields(self):
        """Get fields that can be searched for sales"""
        return ['client_username', 'client_name', 'date']
    
    def matches_search(self, obj, search_text):
        """Check if sales matches search criteria"""
        if not search_text:
            return True
        
        search_lower = search_text.lower()
        
        # Check for date search patterns first
        date_search = self.parse_date_search(search_text)
        if date_search:
            return self._matches_date_search(obj, date_search)
        
        # Check client username, client name, and products
        try:
            client_username = obj.get_value('client_username') or ""
            client_name = obj.get_value('client_name') or ""
            
            if (search_lower in client_username.lower() or 
                search_lower in client_name.lower()):
                return True
            
            # Check products in sales items
            if hasattr(obj, 'items') and obj.items:
                for item in obj.items:
                    try:
                        product_name = item.get_value('product_name') or ""
                        if search_lower in product_name.lower():
                            return True
                    except:
                        pass
        except:
            pass
        
        return False
    
    def _matches_date_search(self, obj, date_search):
        """Check if sales matches date search criteria"""
        try:
            sales_date_str = obj.get_value('date')
            if not sales_date_str:
                return False
            
            # Parse sales date (try multiple formats)
            sales_date = None
            date_formats = ['%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y']
            for fmt in date_formats:
                try:
                    sales_date = datetime.strptime(str(sales_date_str), fmt).date()
                    break
                except ValueError:
                    continue
            
            if not sales_date:
                return False
            
            if date_search[0] == 'single':
                return sales_date == date_search[1]
            elif date_search[0] == 'range':
                return date_search[1] <= sales_date <= date_search[2]
        except:
            pass
        
        return False
    
    def sort_items(self, items, order_option):
        """Sort sales based on order option"""
        if not order_option or order_option == "Default":
            return items
        
        try:
            if order_option == "Client Username ↑":
                items.sort(key=lambda x: str(x.get_value('client_username') or "").lower())
            elif order_option == "Client Username ↓":
                items.sort(key=lambda x: str(x.get_value('client_username') or "").lower(), reverse=True)
            elif order_option == "Client Name ↑":
                items.sort(key=lambda x: str(x.get_value('client_name') or "").lower())
            elif order_option == "Client Name ↓":
                items.sort(key=lambda x: str(x.get_value('client_name') or "").lower(), reverse=True)
            elif order_option == "Recent ↑":
                items.sort(key=lambda x: self.parse_date_for_sorting(x.get_value('date')))
            elif order_option == "Recent ↓":
                items.sort(key=lambda x: self.parse_date_for_sorting(x.get_value('date')), reverse=True)
            elif order_option == "Total ↑":
                items.sort(key=lambda x: float(x.get_value('total_price') or 0))
            elif order_option == "Total ↓":
                items.sort(key=lambda x: float(x.get_value('total_price') or 0), reverse=True)
        except Exception as e:
            print(f"Error sorting sales: {e}")
        
        return items
    
    def show_reports(self):
        """Show reports dialog for selected sales record"""
        try:
            # Get selected row
            current_row = self.table.currentRow()
            
            if current_row < 0:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(self, "No Selection", "Please select a sales record to generate a report.")
                return
            
            # Get the sales object from the current row
            if current_row >= len(self.filtered_items):
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Error", f"Selected row is invalid. Row: {current_row}, Filtered items: {len(self.filtered_items)}")
                return
            
            selected_sales = self.filtered_items[current_row]
            
            # Get profile manager from parent (main window)
            profile_manager = None
            if hasattr(self.parent_widget, 'profile_manager'):
                profile_manager = self.parent_widget.profile_manager
            elif hasattr(self.parent_widget, 'parent') and hasattr(self.parent_widget.parent, 'profile_manager'):
                profile_manager = self.parent_widget.parent.profile_manager
            
            if not profile_manager:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Error", "Could not access profile manager.")
                return
            
            # Show reports dialog
            from ui.dialogs.reports_dialog import ReportsDialog
            dialog = ReportsDialog(selected_sales, profile_manager, self)
            dialog.exec()
            
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Failed to show reports dialog:\n{str(e)}")
            print(f"Error in show_reports: {e}")
            import traceback
            traceback.print_exc()