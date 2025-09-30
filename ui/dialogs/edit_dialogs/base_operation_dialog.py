"""
Base Operation Dialog - Unified dialog for operations with items (Sales, Imports)
Replaces the complex manual layout calculations with clean auto-sizing
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QMessageBox, QScrollArea, QWidget,
                               QFormLayout, QSizePolicy)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from ui.widgets.themed_widgets import GreenButton, RedButton
from ui.widgets.operations_table import OperationsTableWidget
from ui.widgets.parameters_widgets import ParameterWidgetFactory
from datetime import datetime


class BaseOperationDialog(QDialog):
    """
    Unified dialog for operations (Sales, Imports) with automatic layout
    Handles: operation parameters + items table + totals calculation
    """
    
    def __init__(self, operation_class, item_class, operation_id=None, database=None, parent=None):
        super().__init__(parent)
        
        self.operation_class = operation_class
        self.item_class = item_class
        self.operation_id = operation_id
        self.database = database
        self.parameter_widgets = {}
        
        # Create or load operation object
        if operation_id:
            self.operation_obj = operation_class(operation_id, database)
            self.operation_obj.load_database_data()
            self.setWindowTitle(f"Edit {self.operation_obj.section[:-1]} - ID {operation_id}")
        else:
            self.operation_obj = operation_class(0, database)
            # Set default date to today for new operations
            if 'date' in self.operation_obj.parameters:
                self.operation_obj.set_value("date", datetime.now().strftime("%Y-%m-%d"))
            self.setWindowTitle(f"New {self.operation_obj.section[:-1]}")
        
        # Setup UI
        self.setup_ui()
        self.load_data()
        self.apply_theme()
        
        # Auto-size dialog
        self.resize(900, 700)
        self.setMinimumSize(600, 500)
        
    def setup_ui(self):
        """Setup clean auto-sizing UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        # ID display (if existing)
        if self.operation_id:
            id_layout = QHBoxLayout()
            id_layout.addWidget(QLabel("ID:"))
            id_label = QLabel(str(self.operation_id))
            id_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
            id_layout.addWidget(id_label)
            id_layout.addStretch()
            layout.addLayout(id_layout)
        
        # Operation parameters (auto-sized form)
        self.setup_parameters_section(layout)
        
        # Items section
        self.setup_items_section(layout)
        
        # Totals section
        self.setup_totals_section(layout)
        
        # Buttons
        self.setup_buttons(layout)
    
    def setup_parameters_section(self, parent_layout):
        """Setup operation parameters with auto-sizing form"""
        # Parameters form
        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)
        form_layout.setContentsMargins(5, 5, 5, 5)
        
        # Get visible dialog parameters
        visible_params = self.operation_obj.get_visible_parameters("dialog")
        
        for param_key in visible_params:
            if param_key == 'items':  # Skip items - handled separately
                continue
                
            param_info = self.operation_obj.parameters[param_key]
            
            # Skip calculated parameters
            if self.operation_obj.is_parameter_calculated(param_key):
                continue
            
            # Create widget
            profile_images_dir = self.get_profile_images_dir()
            editable = self.operation_obj.is_parameter_editable(param_key, "dialog")
            
            widget = ParameterWidgetFactory.create_widget(
                param_info, {}, profile_images_dir, editable
            )
            
            self.parameter_widgets[param_key] = widget

            # If this is the TVA field, refresh totals live when it changes
            if param_key == 'tva':
                # Support legacy numeric spinbox AND new checkbox-based bool widget
                spin = getattr(widget, 'spinbox', None)
                if spin is not None:
                    try:
                        spin.valueChanged.connect(lambda _val: self.update_totals())
                    except Exception:
                        pass
                    try:
                        spin.editingFinished.connect(self.update_totals)
                    except Exception:
                        pass
                checkbox = getattr(widget, 'checkbox', None)
                if checkbox is not None:
                    try:
                        checkbox.stateChanged.connect(lambda _state: self.update_totals())
                    except Exception:
                        pass
            
            # Add to form
            display_name = self.operation_obj.get_display_name(param_key)
            if param_info.get('required', False):
                display_name += " *"
            
            form_layout.addRow(QLabel(display_name + ":"), widget)
        
        parent_layout.addWidget(form_widget)
    
    def setup_items_section(self, parent_layout):
        """Setup items table with auto-sizing"""
        # Items label
        items_label = QLabel(f"{self.operation_obj.section[:-1]} Items")
        items_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        items_label.setStyleSheet("color: #ffffff; margin: 5px 0;")
        parent_layout.addWidget(items_label)
        
        # Items table (auto-sizing with proper policies)
        self.items_table = OperationsTableWidget(
            item_class=self.item_class,
            parent_operation=self.operation_obj,
            database=self.database,
            columns=self.get_item_columns(),
            parent=self,
            highlight_stock_exceed=(getattr(self.operation_obj, 'section', '') == 'Sales')
        )
        
        # Set size policies for proper resizing
        self.items_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.items_table.setMinimumHeight(200)
        
        # Connect to update totals
        self.items_table.items_changed.connect(self.update_totals)
        
        parent_layout.addWidget(self.items_table, 1)  # Give it stretch factor
    
    def get_item_columns(self):
        """Get columns for items table - override in subclasses if needed"""
        temp_item = self.item_class(0, self.database)
        return temp_item.get_visible_parameters("table")
    
    def setup_totals_section(self, parent_layout):
        """Setup totals with auto-sizing horizontal layout"""
        totals_widget = QWidget()
        totals_layout = QHBoxLayout(totals_widget)
        totals_layout.setContentsMargins(5, 5, 5, 5)
        
        # Create total widgets
        self.subtotal_widget = self.create_total_widget("Subtotal", "MAD")
        self.vat_widget = self.create_total_widget("VAT Amount", "MAD") 
        self.total_widget = self.create_total_widget("Total Price", "MAD")
        
        # Add to layout
        totals_layout.addWidget(QLabel("Subtotal:"))
        totals_layout.addWidget(self.subtotal_widget)
        totals_layout.addWidget(QLabel("VAT:"))
        totals_layout.addWidget(self.vat_widget)
        totals_layout.addWidget(QLabel("Total:"))
        totals_layout.addWidget(self.total_widget)
        totals_layout.addStretch()
        
        parent_layout.addWidget(totals_widget)
        
        # Initial calculation
        self.update_totals()
    
    def create_total_widget(self, label, unit):
        """Create a read-only total display widget"""
        widget = ParameterWidgetFactory.create_widget(
            {'type': 'float', 'unit': unit}, {}, None, editable=False
        )
        ParameterWidgetFactory.set_widget_value(widget, 0.0)
        return widget
    
    def setup_buttons(self, parent_layout):
        """Setup save/cancel buttons"""
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.save_btn = GreenButton("Save")
        self.save_btn.clicked.connect(self.save_changes)
        button_layout.addWidget(self.save_btn)
        
        self.cancel_btn = RedButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        
        parent_layout.addLayout(button_layout)
    
    def get_profile_images_dir(self):
        """Get profile images directory"""
        try:
            if (hasattr(self.parent(), 'profile_manager') and 
                self.parent().profile_manager and
                self.parent().profile_manager.selected_profile):
                
                import os
                profile_dir = os.path.dirname(
                    self.parent().profile_manager.selected_profile.config_path
                )
                return os.path.join(profile_dir, "images")
        except:
            pass
        return None
    
    def load_data(self):
        """Load current data into widgets"""
        for param_key, widget in self.parameter_widgets.items():
            current_value = self.operation_obj.get_value(param_key)
            ParameterWidgetFactory.set_widget_value(widget, current_value)
    
    def update_totals(self):
        """Update total calculation displays"""
        try:
            # Get current items
            items = self.items_table.get_items_data()
            
            # Calculate subtotal
            subtotal = sum(item.get_value('subtotal') or 0 for item in items)
            
            # Get VAT percentage
            vat_percent = 0
            if 'tva' in self.parameter_widgets:
                try:
                    vat_percent = float(
                        ParameterWidgetFactory.get_widget_value(self.parameter_widgets['tva']) or 0
                    )
                except Exception:
                    vat_percent = 0
            
            # Calculate totals
            vat_amount = subtotal * (vat_percent / 100)
            total = subtotal + vat_amount
            
            # Update displays
            ParameterWidgetFactory.set_widget_value(self.subtotal_widget, subtotal)
            ParameterWidgetFactory.set_widget_value(self.vat_widget, vat_amount)
            ParameterWidgetFactory.set_widget_value(self.total_widget, total)
            
        except Exception as e:
            print(f"Error updating totals: {e}")
    
    def validate_data(self):
        """Validate operation data"""
        errors = []
        
        # Validate required parameters
        for param_key, widget in self.parameter_widgets.items():
            param_info = self.operation_obj.parameters.get(param_key, {})
            
            if param_info.get('required', False):
                value = ParameterWidgetFactory.get_widget_value(widget)
                if not value or (isinstance(value, str) and not value.strip()):
                    display_name = self.operation_obj.get_display_name(param_key)
                    errors.append(f"{display_name} is required")
        
        # Check if we have at least one entered row (even if product not yet created)
        try:
            raw_rows = self.items_table.get_current_table_data()
            if not raw_rows:
                errors.append("Please add at least one item")
        except Exception:
            # Fallback to old behavior
            items = self.items_table.get_items_data()
            if not items:
                errors.append("Please add at least one item")
        
        return errors
    
    def save_changes(self):
        """Save operation and items to database (simple, reliable)"""
        # Validate first
        errors = self.validate_data()
        if errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(errors))
            return

        # Check for missing related entities (client/supplier, products) and offer creation
        proceed, allow_unresolved = self._handle_missing_references()
        if not proceed:
            return  # User cancelled

        # Force a totals recalculation now that rows are finalized / products possibly created
        try:
            self.update_totals()
        except Exception:
            pass
        
        try:
            # Update operation object (ensure snapshot name fields captured from widgets if present)
            for param_key, widget in self.parameter_widgets.items():
                value = ParameterWidgetFactory.get_widget_value(widget)
                self.operation_obj.set_value(param_key, value)
            # For snapshots: if client_name/supplier_name empty set from username
            try:
                if getattr(self.operation_obj, 'section', '') == 'Sales':
                    if not self.operation_obj.get_value('client_name') and self.operation_obj.get_value('client_username'):
                        self.operation_obj.set_value('client_name', self.operation_obj.get_value('client_username'))
                elif getattr(self.operation_obj, 'section', '') == 'Imports':
                    if not self.operation_obj.get_value('supplier_name') and self.operation_obj.get_value('supplier_username'):
                        self.operation_obj.set_value('supplier_name', self.operation_obj.get_value('supplier_username'))
            except Exception:
                pass
            
            # Save operation to database first (ensures ID exists)
            success = self.operation_obj.save_to_database()
            action = "updated" if self.operation_id else "created"
            self.operation_id = self.operation_obj.id
            
            if success:
                # Simple and robust: clear existing items, then insert current ones using item classes
                operation_id = self.operation_obj.id
                
                # Delete all existing items for this operation
                if self.operation_obj.section == "Sales" and hasattr(self.operation_obj, 'get_sales_items'):
                    existing_items = self.operation_obj.get_sales_items()
                    for item in existing_items:
                        if getattr(item, 'id', 0):
                            self.database.delete_item(item.id, "Sales_Items")
                elif self.operation_obj.section == "Imports" and hasattr(self.operation_obj, 'get_import_items'):
                    existing_items = self.operation_obj.get_import_items()
                    for item in existing_items:
                        if getattr(item, 'id', 0):
                            self.database.delete_item(item.id, "Import_Items")
                
                # Recreate items from the table using item classes (ensures product_name -> product_id mapping)
                # First collect items (may still lack product_id if something failed)
                items_objects = self.items_table.get_items_data()

                # Recalculate subtotal widgets before saving items (ensures UI shows accurate totals)
                try:
                    self.update_totals()
                except Exception:
                    pass

                # Attempt final resolution for any missing product_ids
                unresolved_names = []
                for itm in items_objects:
                    try:
                        if hasattr(itm, 'get_value') and not itm.get_value('product_id'):
                            pname = itm.get_value('product_name') or "(unknown)"
                            # Try resolve again from DB (in case created just now)
                            if self.database and hasattr(self.database, 'cursor') and self.database.cursor:
                                try:
                                    self.database.cursor.execute("SELECT ID FROM Products WHERE name = ?", (pname,))
                                    res = self.database.cursor.fetchone()
                                    if res and res[0]:
                                        itm.set_value('product_id', res[0])
                                except Exception:
                                    pass
                            if not itm.get_value('product_id'):
                                unresolved_names.append(pname)
                    except Exception:
                        pass

                if unresolved_names and not allow_unresolved:
                    QMessageBox.critical(self, "Error", "Could not resolve product IDs for: " + ", ".join(unresolved_names) + "\nAborting save.")
                    return

                items_saved = 0
                for item in items_objects:
                    if self.operation_obj.section == "Sales":
                        item.set_value('sales_id', operation_id)
                    elif self.operation_obj.section == "Imports":
                        item.set_value('import_id', operation_id)
                    if item.save_to_database():
                        items_saved += 1
                
                QMessageBox.information(self, "Success", f"Operation {action} successfully!\n{items_saved} items saved.")
                self.accept()  # Close dialog successfully
            else:
                QMessageBox.critical(self, "Error", "Failed to save operation")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save: {str(e)}")
    
    def apply_theme(self):
        """Apply dark theme"""
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
            }
            QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
            }
        """)

    # -------------------- Missing References Handling -------------------- #
    def _handle_missing_references(self):
        """Detect missing client/supplier or products and prompt user to create them.

        Returns True if it's OK to proceed with saving (after creating if user agreed),
        False if the user cancelled.
        """
        try:
            if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
                return True, True  # Can't verify without DB

            missing_clients = []
            missing_suppliers = []
            missing_products = []

            # Determine operation type
            op_section = getattr(self.operation_obj, 'section', '')

            # Check main entity username
            if op_section == 'Sales' and 'client_username' in self.parameter_widgets:
                client_username = self._safe_widget_value('client_username')
                if client_username and not self._entity_exists('Clients', client_username):
                    missing_clients.append(client_username)
            elif op_section == 'Imports' and 'supplier_username' in self.parameter_widgets:
                supplier_username = self._safe_widget_value('supplier_username')
                if supplier_username and not self._entity_exists('Suppliers', supplier_username):
                    missing_suppliers.append(supplier_username)

            # Check products from items table (only those not already present)
            try:
                raw_names = self.items_table.get_all_entered_product_names()
                for product_name in raw_names:
                    if product_name and not self._product_exists(product_name):
                        if product_name not in missing_products:
                            missing_products.append(product_name)
            except Exception as e:
                print(f"Error collecting raw product names: {e}")

            if not (missing_clients or missing_suppliers or missing_products):
                return True, True  # Nothing missing

            # Build message
            msg_lines = ["Some referenced entries do not exist:"]
            if missing_clients:
                msg_lines.append(f" - Clients: {', '.join(missing_clients)}")
            if missing_suppliers:
                msg_lines.append(f" - Suppliers: {', '.join(missing_suppliers)}")
            if missing_products:
                msg_lines.append(f" - Products: {', '.join(missing_products)}")
            msg_lines.append("")
            msg_lines.append("Choose an action:")
            msg_lines.append(" - Create & Continue: auto-create missing entries")
            msg_lines.append(" - Ignore: continue without creating (snapshots stored)")
            msg_lines.append(" - Cancel: go back and edit")

            from PySide6.QtWidgets import QMessageBox
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Missing References")
            box.setText("\n".join(msg_lines))
            create_btn = box.addButton("Create & Continue", QMessageBox.AcceptRole)
            ignore_btn = box.addButton("Ignore", QMessageBox.DestructiveRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()

            clicked = box.clickedButton()
            if clicked == create_btn:
                # Create missing ones
                for username in missing_clients:
                    self._create_client(username)
                for username in missing_suppliers:
                    self._create_supplier(username)
                for product_name in missing_products:
                    self._create_product(product_name)
            elif clicked == ignore_btn:
                # Ensure snapshots for client/supplier name reflect entered username (even if entity absent)
                try:
                    if op_section == 'Sales' and 'client_username' in self.parameter_widgets:
                        uname = self._safe_widget_value('client_username')
                        # set client_name parameter value directly on operation object
                        self.operation_obj.set_value('client_name', uname)
                    elif op_section == 'Imports' and 'supplier_username' in self.parameter_widgets:
                        uname = self._safe_widget_value('supplier_username')
                        self.operation_obj.set_value('supplier_name', uname)
                except Exception as e:
                    print(f"Error setting snapshot names on ignore: {e}")
                # For products, product_name already captured in item rows; nothing extra needed
                # Allow unresolved product IDs (they stay NULL) -> second flag True
                return True, True
            else:
                return False, False  # Cancel

            # After creation path: unresolved not allowed (we created them)
            return True, True
        except Exception as e:
            print(f"Error handling missing references: {e}")
            return True, True  # Fail-open so user can still save

    def _safe_widget_value(self, key):
        from ui.widgets.parameters_widgets import ParameterWidgetFactory
        try:
            return ParameterWidgetFactory.get_widget_value(self.parameter_widgets.get(key))
        except Exception:
            return None

    def _entity_exists(self, table, username):
        try:
            self.database.cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE username = ?", (username,))
            res = self.database.cursor.fetchone()
            return res and res[0] > 0
        except Exception as e:
            print(f"Error checking existence in {table}: {e}")
            return True  # Avoid blocking

    def _product_exists(self, name):
        try:
            self.database.cursor.execute("SELECT COUNT(*) FROM Products WHERE name = ?", (name,))
            res = self.database.cursor.fetchone()
            return res and res[0] > 0
        except Exception as e:
            print(f"Error checking product existence: {e}")
            return True

    def _create_client(self, username):
        try:
            from classes.client_class import ClientClass
            client = ClientClass(0, self.database)
            client.set_value('username', username)
            client.set_value('name', username)
            # client_type now optional; keep default
            client.save_to_database()
        except Exception as e:
            print(f"Error auto-creating client '{username}': {e}")

    def _create_supplier(self, username):
        try:
            from classes.supplier_class import SupplierClass
            supplier = SupplierClass(0, self.database)
            supplier.set_value('username', username)
            supplier.set_value('name', username)
            supplier.save_to_database()
        except Exception as e:
            print(f"Error auto-creating supplier '{username}': {e}")

    def _create_product(self, name):
        try:
            from classes.product_class import ProductClass
            product = ProductClass(0, self.database)
            product.set_value('name', name)
            product.set_value('username', name)
            product.save_to_database()
        except Exception as e:
            print(f"Error auto-creating product '{name}': {e}")