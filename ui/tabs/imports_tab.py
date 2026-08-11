"""
Imports tab - Updated to use unified BaseTab approach
Now consistent with Products/Clients/Suppliers experience
"""
from ui.tabs.base_tab import BaseTab
from classes.import_class import ImportClass
from classes.import_item_class import ImportItemClass
from classes.supplier_class import SupplierClass
from ui.dialogs.edit_dialogs.base_operation_dialog import BaseOperationDialog
from ui.dialogs.supplier_details_dialog import SupplierDetailsDialog
from ui.widgets.themed_widgets import BlueButton
from datetime import datetime
import re


class ImportEditDialog(BaseOperationDialog):
    """Import-specific dialog using unified base operation dialog"""
    
    def __init__(self, import_id=None, database=None, parent=None):
        super().__init__(
            operation_class=ImportClass,
            item_class=ImportItemClass,
            operation_id=import_id,
            database=database,
            parent=parent
        )
    
    def get_item_columns(self):
        """Override to specify import item columns"""
        return ['product_preview', 'product_name', 'quantity', 'unit_price', 'subtotal', 'delete_action']
    
    def validate_data(self):
        """Import-specific validation"""
        # Only base validation; existence handled in auto-create workflow
        return super().validate_data()
    
    def _validate_supplier_exists(self, username):
        """Check if supplier username exists in database"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return False
        
        try:
            self.database.cursor.execute("SELECT COUNT(*) FROM Suppliers WHERE username = %s", (username,))
            result = self.database.cursor.fetchone()
            return result[0] > 0 if result else False
        except Exception as e:
            print(f"Error validating supplier: {e}")
            return False


class ImportsTab(BaseTab):
    """Imports tab with unified table experience - consistent with other entity tabs"""
    
    def __init__(self, database=None, parent=None):
        super().__init__(ImportClass, ImportEditDialog, database, parent)
    
    def get_preview_category(self):
        """Override to specify preview category for import operations"""
        return "company"  # Since imports are typically associated with suppliers

    def add_additional_toolbar_buttons(self, layout):
        """Add the Bon de Livraison button beside the other import actions."""
        from ui.widgets.themed_widgets import OrangeButton

        self.bdl_btn = OrangeButton("📦 Bon de livraison")
        self.bdl_btn.setStyleSheet(
            self.bdl_btn.styleSheet()
            + "\nQPushButton { font-size: 14px; padding: 5px 10px; }"
        )
        self.bdl_btn.setMinimumHeight(20)
        self.bdl_btn.clicked.connect(self.show_bon_de_livraison)
        layout.addWidget(self.bdl_btn)

        self.view_supplier_btn = BlueButton("View Supplier")
        self.view_supplier_btn.setToolTip(
            "View the supplier of the selected import (imports, payments, balance)"
        )
        self.view_supplier_btn.setStyleSheet(
            self.view_supplier_btn.styleSheet()
            + "\nQPushButton { font-size: 14px; padding: 5px 10px; }"
        )
        self.view_supplier_btn.setMinimumHeight(20)
        self.view_supplier_btn.clicked.connect(self.view_supplier)
        layout.addWidget(self.view_supplier_btn)

    def view_supplier(self):
        """Open the account view of the selected import's supplier."""
        from PySide6.QtWidgets import QMessageBox
        try:
            current_row = self.table.currentRow()
            if current_row < 0:
                QMessageBox.information(
                    self, "No Selection",
                    "Please select an import to view its supplier.",
                )
                return
            if current_row >= len(self.filtered_items):
                QMessageBox.warning(
                    self, "Error",
                    "The selected row is no longer valid. Please refresh and try again.",
                )
                return

            import_obj = self.filtered_items[current_row]
            supplier_id = import_obj.get_value('supplier_id') or None
            username = import_obj.get_value('supplier_username')
            if not supplier_id and username:
                if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
                    QMessageBox.warning(self, "Supplier Error", "No database connection.")
                    return
                self.database.cursor.execute(
                    "SELECT ID FROM Suppliers WHERE username = %s", (username,)
                )
                res = self.database.cursor.fetchone()
                if res:
                    supplier_id = res[0]
            if not supplier_id:
                QMessageBox.warning(
                    self, "Supplier Error", "This import has no associated supplier."
                )
                return

            supplier = SupplierClass(int(supplier_id), self.database)
            if not supplier.load_database_data():
                QMessageBox.warning(self, "Supplier Error", "Could not load the supplier.")
                return

            dialog = SupplierDetailsDialog(supplier, self.database, self)
            dialog.showMaximized()
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Failed to open the supplier:\n{str(e)}"
            )
            print(f"Error in view_supplier: {e}")
            import traceback
            traceback.print_exc()

    def show_bon_de_livraison(self):
        """Generate a Bon de Livraison PDF for the selected import."""
        from PySide6.QtWidgets import QMessageBox
        try:
            current_row = self.table.currentRow()
            if current_row < 0:
                QMessageBox.information(
                    self, "No Selection",
                    "Please select an import to generate a Bon de Livraison.",
                )
                return
            if current_row >= len(self.filtered_items):
                QMessageBox.warning(
                    self, "Error",
                    "The selected row is no longer valid. Please refresh and try again.",
                )
                return

            import_obj = self.filtered_items[current_row]

            profile_manager = None
            if hasattr(self.parent_widget, 'profile_manager'):
                profile_manager = self.parent_widget.profile_manager
            elif hasattr(self.parent_widget, 'parent') and hasattr(
                self.parent_widget.parent, 'profile_manager'
            ):
                profile_manager = self.parent_widget.parent.profile_manager

            if not profile_manager:
                QMessageBox.warning(
                    self, "Error", "Could not access profile manager."
                )
                return

            from ui.dialogs.import_bdl_dialog import ImportBdlDialog
            dialog = ImportBdlDialog(import_obj, profile_manager, self)
            dialog.exec()

        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Failed to generate Bon de Livraison:\n{str(e)}"
            )
            print(f"Error in show_bon_de_livraison: {e}")
            import traceback
            traceback.print_exc()
    
    def get_search_options(self):
        """Get autocomplete options for imports search"""
        if not self.all_items:
            return []
        
        options = set()
        for obj in self.all_items:
            try:
                supplier_username = obj.get_value('supplier_username')
                supplier_name = obj.get_value('supplier_name')
                date = obj.get_value('date')
                bl_number = obj.get_value('bl_number')
                
                if supplier_username:
                    options.add(str(supplier_username))
                if supplier_name:
                    options.add(str(supplier_name))
                if date:
                    options.add(str(date))
                if bl_number:
                    options.add(str(bl_number))
            except:
                pass
        
        return sorted(list(options))
    
    def setup_order_options(self):
        """Setup order dropdown options for imports"""
        self.order_combo.clear()
        self.order_combo.addItems([
            "Default",
            "Supplier Username ↑",
            "Supplier Username ↓", 
            "Supplier Name ↑",
            "Supplier Name ↓",
            "Recent ↑",
            "Recent ↓",
            "Total ↑",
            "Total ↓"
        ])

    def _order_by_field(self, order_option):
        """Map display labels to allowlisted sort columns."""
        field = super()._order_by_field(order_option)
        if field == 'recent':
            return 'date'
        if field == 'total':
            return 'total_price'
        return field
    
    def get_searchable_fields(self):
        """Get fields that can be searched for imports"""
        return ['supplier_username', 'supplier_name', 'date', 'bl_number']
    
    def matches_search(self, obj, search_text):
        """Check if import matches search criteria"""
        if not search_text:
            return True
        
        search_lower = search_text.lower()
        
        date_search = self.parse_date_search(search_text)
        if date_search:
            return self._matches_date_search(obj, date_search)
        
        try:
            supplier_username = obj.get_value('supplier_username') or ""
            supplier_name = obj.get_value('supplier_name') or ""
            bl_number = obj.get_value('bl_number') or ""
            return (
                search_lower in supplier_username.lower() or 
                search_lower in supplier_name.lower() or
                search_lower in str(bl_number).lower()
            )
        except:
            return False
    
    def _matches_date_search(self, obj, date_search):
        """Check if import matches date search criteria"""
        try:
            import_date_str = obj.get_value('date')
            if not import_date_str:
                return False
            
            # Parse import date (try multiple formats)
            import_date = None
            date_formats = ['%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y']
            for fmt in date_formats:
                try:
                    import_date = datetime.strptime(str(import_date_str), fmt).date()
                    break
                except ValueError:
                    continue
            
            if not import_date:
                return False
            
            if date_search[0] == 'single':
                return import_date == date_search[1]
            elif date_search[0] == 'range':
                return date_search[1] <= import_date <= date_search[2]
        except:
            pass
        
        return False
    
    def details_callback(self, obj_id):
        """Open the edit dialog for the selected import to view its details."""
        try:
            dialog = self.dialog_class(obj_id, self.database, self.parent_widget)
            if dialog.exec():
                self.refresh_table(force=True)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Failed to open import details: {e}")

    def sort_items(self, items, order_option):
        """Sort imports based on order option"""
        if not order_option or order_option == "Default":
            return items
        
        try:
            if order_option == "Supplier Username ↑":
                items.sort(key=lambda x: str(x.get_value('supplier_username') or "").lower())
            elif order_option == "Supplier Username ↓":
                items.sort(key=lambda x: str(x.get_value('supplier_username') or "").lower(), reverse=True)
            elif order_option == "Supplier Name ↑":
                items.sort(key=lambda x: str(x.get_value('supplier_name') or "").lower())
            elif order_option == "Supplier Name ↓":
                items.sort(key=lambda x: str(x.get_value('supplier_name') or "").lower(), reverse=True)
            elif order_option == "Recent ↑":
                items.sort(key=lambda x: self.parse_date_for_sorting(x.get_value('date')))
            elif order_option == "Recent ↓":
                items.sort(key=lambda x: self.parse_date_for_sorting(x.get_value('date')), reverse=True)
            elif order_option == "Total ↑":
                items.sort(key=lambda x: float(x.get_value('total_price') or 0))
            elif order_option == "Total ↓":
                items.sort(key=lambda x: float(x.get_value('total_price') or 0), reverse=True)
        except Exception as e:
            print(f"Error sorting imports: {e}")
        
        return items