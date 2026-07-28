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
from decimal import Decimal, InvalidOperation
import os
import uuid
from core.runtime_paths import user_data_root


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
        self.pending_entities = []
        self.operation_token = uuid.uuid4().hex
        self._saving = False
        
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
            # Read the visible cells directly. Building model objects here used
            # to resolve every product/service against PostgreSQL whenever a
            # quantity changed, which made rapid editing feel frozen.
            rows = self.items_table.get_current_table_data()
            subtotal = sum(
                (
                    Decimal(str(row.get("quantity") or 0))
                    * Decimal(str(row.get("unit_price") or 0))
                    for row in rows
                ),
                Decimal("0"),
            )
            
            # Get VAT percentage
            vat_percent = Decimal("0")
            if 'tva' in self.parameter_widgets:
                try:
                    vat_percent = Decimal(str(
                        ParameterWidgetFactory.get_widget_value(self.parameter_widgets['tva']) or 0
                    ))
                except (InvalidOperation, ValueError, TypeError):
                    vat_percent = Decimal("0")
            
            # Calculate totals
            vat_amount = subtotal * (vat_percent / Decimal("100"))
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
        """Prevent double-clicks from starting the same transaction twice."""
        if self._saving:
            return
        self._saving = True
        self.save_btn.setEnabled(False)
        self.save_btn.setText("Saving...")
        try:
            self._save_changes_impl()
        finally:
            if self.result() == QDialog.Rejected:
                self._saving = False
                self.save_btn.setEnabled(True)
                self.save_btn.setText("Save")

    def _save_changes_impl(self):
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
            if self.operation_obj.section == 'Sales':
                items_objects = self.items_table.get_items_data()
                sale_state = self.operation_obj.get_value('state') or 'pending'
                if sale_state != 'on_hold':
                    stock_errors = self._validate_stock(items_objects)
                    mw = self._get_main_window()
                    warn_stock = getattr(mw, 'warn_insufficient_stock', True) if mw else True
                    if stock_errors and warn_stock:
                        reply = QMessageBox.warning(
                            self, "Insufficient Stock",
                            "Not enough stock for:\n\n" +
                            "\n".join(f"  • {e}" for e in stock_errors) +
                            "\n\nSave anyway?",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                            QMessageBox.StandardButton.No
                        )
                        if reply != QMessageBox.StandardButton.Yes:
                            return
                action = "updated" if self.operation_id else "created"
                result = self._save_sale_atomically()
                self.operation_id = result['sale_id']
                self.operation_obj.id = result['sale_id']
                self.operation_obj.set_value('id', result['sale_id'])
                expected = result.get('expected', 0)
                saved = result.get('saved', 0)
                if saved != expected:
                    raise RuntimeError(
                        f"Sale was not saved: {expected} visible items were found, "
                        f"but the server confirmed {saved} saved items."
                    )
                QMessageBox.information(
                    self, "Success",
                    f"Operation {action} successfully. {saved} items saved.\n"
                    f"Inserted: {result.get('inserted', 0)}, updated: {result.get('updated', 0)}, "
                    f"deleted: {result.get('deleted', 0)}."
                )
                self.accept()
                self._refresh_related_tabs("Sales", "Products", "Clients")
                return

            if self.operation_obj.section == 'Imports':
                action = "updated" if self.operation_id else "created"
                result = self._save_import_atomically()
                self.operation_id = result["import_id"]
                self.operation_obj.id = result["import_id"]
                self.operation_obj.set_value("id", result["import_id"])
                QMessageBox.information(
                    self,
                    "Success",
                    f"Import {action} successfully. {result['saved']} items saved.\n"
                    f"Products created: {result.get('created_products', 0)}.",
                )
                self.accept()
                self._refresh_related_tabs("Imports", "Products")
                return

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
                                    self.database.cursor.execute("SELECT ID FROM Products WHERE name = %s", (pname,))
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

                # Stock validation for sales (skip on_hold — those don't deduct stock)
                if self.operation_obj.section == 'Sales':
                    sale_state = self.operation_obj.get_value('state') or 'pending'
                    if sale_state != 'on_hold':
                        stock_errors = self._validate_stock(items_objects)
                        mw = self._get_main_window()
                        warn_stock = getattr(mw, 'warn_insufficient_stock', True) if mw else True
                        if stock_errors and warn_stock:
                            reply = QMessageBox.warning(
                                self, "Insufficient Stock",
                                "Not enough stock for:\n\n" +
                                "\n".join(f"  \u2022 {e}" for e in stock_errors) +
                                "\n\nSave anyway?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No
                            )
                            if reply != QMessageBox.StandardButton.Yes:
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

    def _save_sale_atomically(self):
        """Send the complete visible sale and line set in one database operation."""
        raw_items = self.items_table.get_current_table_data()
        extraction = getattr(self.items_table, 'last_extraction_diagnostics', {})
        prepared = []
        for index, raw in enumerate(raw_items, start=1):
            item = dict(raw)
            item.pop('row_index', None)
            product_id = item.get('product_id')
            service_id = item.get('service_id')
            item['product_id'] = product_id
            item['service_id'] = service_id
            item['item_type'] = str(
                item.get('item_type')
                or ('product' if product_id else ('service' if service_id else ''))
            ).casefold()
            item['is_new'] = not bool(item.get('id'))
            prepared.append(item)

        header = {
            key: self.operation_obj.get_value(key)
            for key in self.operation_obj.get_visible_parameters('database')
            if not self.operation_obj.is_parameter_calculated(key)
        }
        header["operation_token"] = (
            self.operation_obj.get_value("operation_token") or self.operation_token
        )
        self._write_sale_save_log(
            f"mode={self.database.__class__.__name__} host={getattr(self.database, 'host', 'local')} "
            f"port={getattr(self.database, 'port', 'local')} visible_rows={len(raw_items)} "
            f"extracted_rows={len(prepared)} extraction={extraction} sale_id={self.operation_id} "
            f"client_id={header.get('client_id')} client_identifier={header.get('client_username')} date={header.get('date')} vat={header.get('tva')} "
            f"notes_present={bool(header.get('notes'))} items={prepared}"
        )
        result = self.database.save_sale_with_items(
            header, prepared, self.operation_id, len(raw_items), self.pending_entities
        )
        if not isinstance(result, dict) or result.get('transaction') != 'committed':
            raise RuntimeError(f"Host returned an invalid sale-save result: {result!r}")
        result['expected'] = len(prepared)
        self._write_sale_save_log(
            f"server_result validation=ok inserted={result.get('inserted')} "
            f"updated={result.get('updated')} deleted={result.get('deleted')} "
            f"saved={result.get('saved')} transaction={result.get('transaction')}"
        )
        return result

    def _save_import_atomically(self):
        raw_items = self.items_table.get_current_table_data()
        prepared = []
        for raw in raw_items:
            item = dict(raw)
            item.pop("row_index", None)
            prepared.append(item)
        header = {
            key: self.operation_obj.get_value(key)
            for key in self.operation_obj.get_visible_parameters("database")
            if not self.operation_obj.is_parameter_calculated(key)
        }
        header["operation_token"] = (
            self.operation_obj.get_value("operation_token") or self.operation_token
        )
        result = self.database.save_import_with_items(
            header, prepared, self.operation_id, len(raw_items)
        )
        if not isinstance(result, dict) or result.get("transaction") != "committed":
            raise RuntimeError(f"Host returned an invalid import-save result: {result!r}")
        return result

    def _refresh_related_tabs(self, *sections):
        main_window = self._get_main_window()
        tab_widget = getattr(main_window, "tab_widget", None) if main_window else None
        if not tab_widget:
            return
        wanted = set(sections)
        for index in range(tab_widget.count()):
            tab = tab_widget.widget(index)
            if getattr(tab, "section", None) in wanted and hasattr(tab, "refresh_table"):
                tab.refresh_table()

    @staticmethod
    def _write_sale_save_log(message):
        try:
            log_dir = os.path.join(user_data_root(), 'logs')
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, 'network_sales.log'), 'a', encoding='utf-8') as stream:
                stream.write(f"[{datetime.now().isoformat(timespec='seconds')}] ui {message}\n")
        except OSError:
            pass
    
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

    # ────────────────── Warning-settings helpers ──────────────────────────── #

    def _get_main_window(self):
        """Walk up parent chain to find the MainWindow (has warn_* attributes)."""
        p = self.parent()
        while p is not None:
            if hasattr(p, 'warn_missing_client'):
                return p
            p = p.parent() if callable(getattr(p, 'parent', None)) else None
        return None

    # -------------------- Missing References Handling -------------------- #
    def _handle_missing_references(self):
        """Collect confirmed missing entities without writing them yet.

        The backend creates these pending records in the same transaction as
        the sale. Cancelling the dialog therefore leaves no orphan records.
        """
        try:
            if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
                return True, False

            self.pending_entities = []
            op_section = getattr(self.operation_obj, 'section', '')
            if op_section == "Imports":
                supplier = self._safe_widget_value("supplier_username")
                if not supplier or not self._entity_exists("Suppliers", supplier):
                    QMessageBox.warning(
                        self, "Unknown Supplier",
                        f"Supplier '{supplier or ''}' does not exist. Create the supplier first."
                    )
                    return False, False
                return True, False

            if op_section != "Sales":
                return True, False

            client_value = " ".join(str(self._safe_widget_value("client_username") or "").split())
            if not client_value:
                QMessageBox.warning(self, "Missing Client", "A client is required.")
                return False, False
            if not self._entity_exists("Clients", client_value):
                if not self.database.has_permission("Clients", "write"):
                    QMessageBox.warning(
                        self, "Permission Denied",
                        "You don't have permission to create clients."
                    )
                    return False, False
                if QMessageBox.question(
                    self, "Create Client",
                    f"This client does not exist:\n{client_value}\n\nCreate it?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                ) != QMessageBox.Yes:
                    return False, False
                from PySide6.QtWidgets import QInputDialog
                display_name, ok = QInputDialog.getText(
                    self, "Client Details", "Client name:", text=client_value
                )
                display_name = " ".join(display_name.split())
                if not ok or not display_name:
                    return False, False
                self.pending_entities.append({
                    "type": "client", "username": client_value, "name": display_name,
                    "client_type": "individual",
                })

            rows = self.items_table.get_current_table_data()
            for row_index, item in enumerate(rows):
                name = " ".join(str(item.get("product_name") or "").split())
                if not name:
                    QMessageBox.warning(self, "Missing Item", "Every sale line needs a name.")
                    return False, False
                item_type = str(item.get("item_type") or "").casefold()
                if item_type not in ("product", "service"):
                    from PySide6.QtWidgets import QInputDialog
                    choice, ok = QInputDialog.getItem(
                        self, "Choose Item Type",
                        f"Create or use '{name}' as:", ["Product", "Service"],
                        editable=False,
                    )
                    if not ok:
                        return False, False
                    item_type = choice.casefold()
                    self._set_row_item_type(int(item.get("row_index", row_index + 1)) - 1, item_type)

                exists = self._catalog_entity_exists(item_type, name)
                if exists:
                    continue
                section = "Products" if item_type == "product" else "Services"
                if not self.database.has_permission(section, "write"):
                    QMessageBox.warning(
                        self, "Permission Denied",
                        f"You don't have permission to create {section.lower()}."
                    )
                    return False, False
                if QMessageBox.question(
                    self, f"Create {item_type.title()}",
                    f"This {item_type} does not exist:\n{name}\n\nCreate it?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                ) != QMessageBox.Yes:
                    return False, False

                try:
                    price = Decimal(str(item.get("unit_price", 0)))
                    quantity = Decimal(str(item.get("quantity", 0)))
                except InvalidOperation:
                    QMessageBox.warning(self, "Invalid Item", f"Invalid quantity or price for {name}.")
                    return False, False
                if price < 0 or quantity <= 0:
                    QMessageBox.warning(
                        self, "Invalid Item",
                        f"{name}: quantity must be greater than zero and price cannot be negative."
                    )
                    return False, False
                pending = {
                    "type": item_type, "name": name, "unit_price": str(price),
                    "sale_price": str(price),
                }
                if item_type == "product":
                    from PySide6.QtWidgets import QInputDialog
                    initial, ok = QInputDialog.getDouble(
                        self, "Initial Product Stock",
                        f"Initial stock for '{name}':", float(quantity), 0.001,
                        999999999.0, 3,
                    )
                    if not ok or Decimal(str(initial)) < quantity:
                        QMessageBox.warning(
                            self, "Insufficient Initial Stock",
                            "Initial stock must cover the quantity in this sale."
                        )
                        return False, False
                    purchase_price, ok = QInputDialog.getDouble(
                        self, "Product Purchase Price",
                        f"Purchase cost for '{name}':", 0.0, 0.0, 999999999.0, 2,
                    )
                    if not ok:
                        return False, False
                    pending.update({
                        "initial_quantity": str(initial),
                        "purchase_price": str(purchase_price),
                    })
                self.pending_entities.append(pending)
            return True, False
        except Exception as e:
            print(f"Error handling missing references: {e}")
            QMessageBox.critical(self, "Validation Error", str(e))
            return False, False

    def _set_row_item_type(self, row, item_type):
        try:
            column = self.items_table.data_manager.table_columns.index("item_type")
            selector = self.items_table.table.cellWidget(row, column)
            if selector:
                selector.setCurrentIndex(selector.findData(item_type))
        except (ValueError, AttributeError):
            pass

    def _catalog_entity_exists(self, item_type, name):
        table = "Products" if item_type == "product" else "Services"
        target = self._normalize_name(name)
        self.database.cursor.execute(
            f"SELECT name FROM {table} WHERE name IS NOT NULL"
        )
        return any(
            self._normalize_name(row[0]) == target
            for row in self.database.cursor.fetchall()
        )

    def _validate_stock(self, items_objects):
        """Return a list of error strings for any sale item that exceeds available stock.

        Excludes the current sale's own existing items from the deduction so that editing
        a sale and changing quantities is checked correctly (not double-counted).
        """
        errors = []
        current_sale_id = self.operation_id or 0
        cursor = self.database.cursor
        for item in items_objects:
            try:
                product_id = item.get_value('product_id')
                if not product_id:
                    continue
                product_name = item.get_value('product_name') or f"ID {product_id}"
                new_qty = float(item.get_value('quantity') or 0)
                if new_qty <= 0:
                    continue

                cursor.execute(
                    "SELECT COALESCE(SUM(quantity), 0) FROM Import_Items WHERE product_id = %s",
                    (product_id,)
                )
                total_imports = cursor.fetchone()[0] or 0

                # Exclude the current sale so editing doesn't double-count its own items
                cursor.execute("""
                    SELECT COALESCE(SUM(si.quantity), 0)
                    FROM Sales_Items si
                    JOIN Sales s ON si.sales_id = s.ID
                    WHERE si.product_id = %s
                      AND (s.state IS NULL OR s.state != 'on_hold')
                      AND si.sales_id != %s
                """, (product_id, current_sale_id))
                sold_elsewhere = cursor.fetchone()[0] or 0

                available = total_imports - sold_elsewhere
                if new_qty > available:
                    errors.append(
                        f"'{product_name}': need {int(new_qty)}, only {max(0, int(available))} available"
                    )
            except Exception as e:
                print(f"Stock check error: {e}")
        return errors

    def _safe_widget_value(self, key):
        from ui.widgets.parameters_widgets import ParameterWidgetFactory
        try:
            return ParameterWidgetFactory.get_widget_value(self.parameter_widgets.get(key))
        except Exception:
            return None

    def _entity_exists(self, table, username):
        try:
            normalized = self._normalize_name(username)
            self.database.cursor.execute(
                f"SELECT username, name FROM {table} "
                "WHERE username IS NOT NULL OR name IS NOT NULL"
            )
            return any(
                normalized in (self._normalize_name(row[0]), self._normalize_name(row[1]))
                for row in self.database.cursor.fetchall()
            )
        except Exception as e:
            print(f"Error checking existence in {table}: {e}")
            return True  # Avoid blocking

    def _product_exists(self, name):
        try:
            target = self._normalize_name(name)
            self.database.cursor.execute("SELECT name FROM Products WHERE name IS NOT NULL")
            if any(self._normalize_name(row[0]) == target for row in self.database.cursor.fetchall()):
                return True

            self.database.cursor.execute(
                "SELECT name, keywords FROM Services WHERE name IS NOT NULL AND name != ''"
            )
            name_clean = target
            for service_name, keywords in self.database.cursor.fetchall():
                candidates = [service_name, *self._split_keywords(keywords or "")]
                if any(name_clean == self._normalize_name(candidate) for candidate in candidates if candidate):
                    return True

            return False
        except Exception as e:
            print(f"Error checking product existence: {e}")
            return True

    @staticmethod
    def _normalize_name(value):
        return " ".join(str(value or "").split()).casefold()

    @staticmethod
    def _split_keywords(value):
        return [
            part.strip()
            for part in str(value).replace("\n", ",").split(",")
            if part.strip()
        ]

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

    def _create_service(self, name):
        try:
            from classes.service_class import ServiceClass
            service = ServiceClass(0, self.database, name=name)
            code = "SRV-" + "-".join(str(name).upper().split())[:40]
            service.set_value('service_code', code or 'SRV-NEW')
            service.set_value('service_type', 'Custom Service')
            service.save_to_database()
        except Exception as e:
            print(f"Error auto-creating service '{name}': {e}")
