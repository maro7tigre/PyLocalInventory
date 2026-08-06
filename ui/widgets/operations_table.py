"""
Operations Table Widget - Clean architecture with proper separation of concerns
"""
from PySide6.QtWidgets import (QWidget, QTableWidget, QTableWidgetItem, QAbstractItemView,
                             QVBoxLayout, QHBoxLayout, QHeaderView, QSizePolicy, QLineEdit,
                             QStyledItemDelegate, QComboBox, QInputDialog)
from PySide6.QtGui import QColor, QBrush, QRegularExpressionValidator
from PySide6.QtCore import Qt, Signal, QRegularExpression, QTimer
from ui.widgets.preview_widget import PreviewWidget
from classes.product_class import ProductClass
from ui.widgets.parameters_widgets import ButtonWidget
from decimal import Decimal, InvalidOperation


class TableDataManager:
    """Handles data operations and validation"""
    
    def __init__(self, item_class, database):
        self.item_class = item_class
        self.database = database
        
        # Get column definitions from item class
        temp_item = item_class(0, database)
        self.table_columns = temp_item.get_visible_parameters("table") if hasattr(temp_item, 'get_visible_parameters') else []
        self.parameter_definitions = temp_item.parameters if hasattr(temp_item, 'parameters') else {}
    
    def get_column_headers(self):
        """Get display headers for table columns"""
        headers = []
        for param_key in self.table_columns:
            if param_key == 'product_preview':
                headers.append('Preview')
            elif param_key == 'product_name':
                headers.append('Name')
            elif param_key == 'item_type':
                headers.append('Type')
            elif param_key == 'delete_action':
                headers.append('Delete')
            else:
                temp_obj = self.item_class(0, self.database)
                if hasattr(temp_obj, 'get_display_name'):
                    headers.append(temp_obj.get_display_name(param_key))
                else:
                    headers.append(param_key.replace('_', ' ').title())
        return headers
    
    def load_items_from_operation(self, parent_operation):
        """Load existing items from parent operation"""
        if not parent_operation or not hasattr(parent_operation, 'id') or not parent_operation.id:
            return []
            
        try:
            if hasattr(parent_operation, 'get_sales_items'):
                return parent_operation.get_sales_items()
            elif hasattr(parent_operation, 'get_import_items'):
                return parent_operation.get_import_items()
        except Exception as e:
            print(f"Error loading items from operation: {e}")
        return []
    
    def extract_row_data(self, table, row):
        """Extract data from a table row"""
        row_data = {}
        
        for col, param_key in enumerate(self.table_columns):
            # Skip non-data / calculated columns
            if param_key in ['delete_action', 'product_preview', 'subtotal']:
                continue
                
            value = self._get_cell_value(table, row, col)
            
            # Skip placeholder text
            if param_key == 'product_name' and value and value.lower() == 'product name':
                continue
                
            if value != "":
                row_data[param_key] = self._convert_value_type(param_key, value)

        try:
            name_col = self.table_columns.index('product_name')
            name_widget = table.cellWidget(row, name_col)
            if name_widget:
                for key in ('item_id', 'product_id', 'service_id', 'item_type'):
                    value = name_widget.property(key)
                    if value not in (None, '', 0, '0'):
                        row_data['id' if key == 'item_id' else key] = value
        except (ValueError, AttributeError):
            pass

        # If we have product_name but no quantity yet, set default 1 (so later logic can proceed)
        if 'product_name' in row_data and 'quantity' not in row_data:
            try:
                default_qty = self.parameter_definitions.get('quantity', {}).get('default', 1)
                row_data['quantity'] = default_qty
            except Exception:
                row_data['quantity'] = 1
        # If unit_price absent, default to 0 (it may be filled later)
        if 'product_name' in row_data and 'unit_price' not in row_data:
            row_data['unit_price'] = 0.0
        if 'product_name' in row_data:
            from core.calculations import calculate_line_subtotal
            row_data['subtotal'] = calculate_line_subtotal(
                row_data.get('quantity', 0),
                row_data.get('unit_price', 0),
            )
        
        return row_data
    
    def _get_cell_value(self, table, row, col):
        """Get value from table cell (widget or item)"""
        widget = table.cellWidget(row, col)
        if widget and hasattr(widget, 'text'):
            return widget.text().strip()
        if widget and hasattr(widget, 'currentData'):
            return str(widget.currentData() or "").strip()
        if widget and hasattr(widget, 'currentText'):
            return widget.currentText().strip()
        
        cell_item = table.item(row, col)
        if cell_item:
            return cell_item.text().strip()
        
        return ""
    
    def _convert_value_type(self, param_key, value):
        """Convert value to proper type based on parameter definition"""
        param_info = self.parameter_definitions.get(param_key, {})
        param_type = param_info.get('type', 'string')
        
        if param_type == 'int':
            try:
                return int(value) if value else 0
            except ValueError:
                return 0
        elif param_type in ('float', 'decimal'):
            try:
                normalized = str(value).replace(" ", "").replace(",", ".")
                return Decimal(normalized) if normalized else Decimal("0")
            except (InvalidOperation, ValueError):
                return Decimal("0")
        
        return value


class TableRowFactory:
    """Creates and manages table row widgets"""
    
    def __init__(self, data_manager, delete_callback):
        self.data_manager = data_manager
        self.delete_callback = delete_callback
    
    def create_data_row(self, table, row, item):
        """Create a row with existing item data"""
        for col, param_key in enumerate(self.data_manager.table_columns):
            self._create_cell(table, row, col, param_key, item)
    
    def create_empty_row(self, table, row):
        """Create an empty row for new data entry"""
        for col, param_key in enumerate(self.data_manager.table_columns):
            self._create_cell(table, row, col, param_key, None)
    
    def _create_cell(self, table, row, col, param_key, item=None):
        """Create individual cell based on parameter type"""
        if param_key == 'delete_action':
            self._create_delete_button_cell(table, row, col)
        elif param_key == 'product_preview':
            self._create_preview_cell(table, row, col, item)
        elif param_key == 'product_name':
            self._create_autocomplete_cell(table, row, col, param_key, item)
        elif param_key == 'item_type':
            self._create_item_type_cell(table, row, col, item)
        elif self.data_manager.parameter_definitions.get(param_key, {}).get('autocomplete'):
            self._create_autocomplete_cell(table, row, col, param_key, item)
        else:
            self._create_regular_cell(table, row, col, param_key, item)

    def _create_item_type_cell(self, table, row, col, item):
        selector = QComboBox()
        # Build from the class options so the "Keep only in Sale" (manual)
        # choice only appears for Sale item tables.
        labels = {
            "product": "Product",
            "service": "Service",
            "manual": "Keep only in Sale",
        }
        options = self.data_manager.parameter_definitions.get(
            "item_type", {}
        ).get("options", ["product", "service"])
        for option in options:
            selector.addItem(labels.get(option, option.title()), option)
        selected = "product"
        if item and hasattr(item, "get_value"):
            selected = str(item.get_value("item_type") or "")
            if not selected:
                selected = "product" if item.get_value("product_id") else (
                    "service" if item.get_value("service_id") else ""
                )
        index = selector.findData(selected)
        selector.setCurrentIndex(index if index >= 0 else 0)
        selector.setProperty("row", row)
        table.setCellWidget(row, col, selector)
    
    def _create_delete_button_cell(self, table, row, col):
        """Create delete button cell"""
        button_param = {'text': '🗑️', 'color': 'red', 'size': 30}
        delete_btn = ButtonWidget(button_param)
        delete_btn.setProperty('row', row)  # Store row for callback
        delete_btn.clicked.connect(
            lambda _checked=False, btn=delete_btn: self.delete_callback(btn.property('row'))
        )
        
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()
        layout.addWidget(delete_btn)
        layout.addStretch()
        
        table.setCellWidget(row, col, container)
    
    def _create_preview_cell(self, table, row, col, item):
        """Create preview image cell"""
        preview_widget = PreviewWidget(45, "product")
        preview_widget.setFixedSize(45, 45)
        
        # Set preview image if available
        if item:
            preview_path = item.get_product_preview() if hasattr(item, 'get_product_preview') else None
            if preview_path:
                preview_widget.set_image_path(preview_path)
        
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()
        layout.addWidget(preview_widget)
        layout.addStretch()
        
        table.setCellWidget(row, col, container)
    
    def _create_autocomplete_cell(self, table, row, col, param_key, item):
        """Create autocomplete cell for configured string parameters."""
        from ui.widgets.autocomplete_widgets import AutoCompleteLineEdit, AutoExpandingTextEdit
        
        param_info = self.data_manager.parameter_definitions.get(param_key, {})
        temp_item = self.data_manager.item_class(0, self.data_manager.database)
        options = param_info.get('options', [])
        if hasattr(temp_item, 'get_parameter_options'):
            options = lambda key=param_key: temp_item.get_parameter_options(key)
        
        if param_info.get('auto_expand', param_info.get('type') == 'string'):
            autocomplete = AutoExpandingTextEdit(
                options=options,
                multi_value=param_info.get('multi_value', False),
                allow_free_text=param_info.get('allow_free_text', True),
            )
        else:
            autocomplete = AutoCompleteLineEdit(
                options=options,
                allow_free_text=param_info.get('allow_free_text', False),
                multi_value=param_info.get('multi_value', False),
            )
        autocomplete.setPlaceholderText(param_info.get('display_name', {}).get('en', param_key.replace('_', ' ')))
        autocomplete.setProperty('row', row)  # Store row for callbacks
        if hasattr(autocomplete, "setTabChangesFocus"):
            autocomplete.setTabChangesFocus(True)
        if hasattr(autocomplete, '_adjust_height'):
            autocomplete._adjust_height()
        
        # Set current value if item provided
        if item:
            if param_key == 'product_name' and hasattr(item, 'get_product_name'):
                value = item.get_product_name()
            else:
                value = item.get_value(param_key) if hasattr(item, 'get_value') else ""
            autocomplete.setText(str(value or ""))
            autocomplete.setProperty('item_id', getattr(item, 'id', None) or item.get_value('id'))
            autocomplete.setProperty('product_id', item.get_value('product_id'))
            autocomplete.setProperty('service_id', item.get_value('service_id') if 'service_id' in getattr(item, 'parameters', {}) else None)
            stored_type = str(item.get_value("item_type") or "").casefold()
            autocomplete.setProperty(
                'item_type',
                stored_type or (
                    'product' if item.get_value('product_id') else (
                        'service' if autocomplete.property('service_id') else 'product'
                    )
                ),
            )
        
        table.setCellWidget(row, col, autocomplete)
    
    def _create_regular_cell(self, table, row, col, param_key, item):
        """Create regular text cell"""
        value = ""
        if item and hasattr(item, 'get_value'):
            raw_value = item.get_value(param_key)
            if param_key == 'subtotal':
                value = f"{float(raw_value or 0):,.2f}".replace(",", " ")
            elif param_key == 'quantity':
                # NUMERIC(15,3) may return Decimal("4.000"). In locales where
                # a dot is a thousands separator that looks like 4000, even
                # though the stored value is four. Display the canonical value.
                decimal_value = Decimal(str(raw_value or 0))
                value = format(decimal_value, "f")
                if "." in value:
                    value = value.rstrip("0").rstrip(".")
            else:
                value = str(raw_value or "")
        elif param_key == 'quantity':
            # Set default quantity for empty rows
            temp_item = self.data_manager.item_class(0, self.data_manager.database)
            default_qty = temp_item.parameters.get('quantity', {}).get('default', 1)
            value = str(default_qty) if not item else value
        
        cell_item = QTableWidgetItem(value)
        
        table.setItem(row, col, cell_item)


class EmptyRowManager:
    """Manages the single empty row at the bottom"""
    
    def __init__(self, table, row_factory):
        self.table = table
        self.row_factory = row_factory
    
    def ensure_single_empty_row(self):
        """Ensure exactly one empty row exists at the bottom"""
        signals_were_blocked = self.table.blockSignals(True)
        try:
            self._remove_all_empty_rows()
            self._add_empty_row()
            self.reindex_row_widgets()
        finally:
            self.table.blockSignals(signals_were_blocked)

    def reindex_row_widgets(self):
        """Keep widget callbacks aligned after table rows move or are deleted."""
        for row in range(self.table.rowCount()):
            for col in range(self.table.columnCount()):
                widget = self.table.cellWidget(row, col)
                if widget is None:
                    continue
                widget.setProperty('row', row)
                for child in widget.findChildren(QWidget):
                    child.setProperty('row', row)
    
    def _remove_all_empty_rows(self):
        """Remove all empty rows from table"""
        rows_to_remove = []
        
        for row in range(self.table.rowCount() - 1, -1, -1):
            if self._is_row_empty(row):
                rows_to_remove.append(row)
        
        for row in rows_to_remove:
            self.table.removeRow(row)
    
    def _add_empty_row(self):
        """Add empty row at the end"""
        row = self.table.rowCount()
        self.table.setRowCount(row + 1)
        self.row_factory.create_empty_row(self.table, row)
    
    def _is_row_empty(self, row):
        """Check if row is empty"""
        # Check product name first (most important)
        product_name = self._get_product_name(row)
        if product_name:
            return False
        
        # Check other meaningful fields
        for col in range(self.table.columnCount()):
            if col >= len(self.row_factory.data_manager.table_columns):
                continue
                
            param_key = self.row_factory.data_manager.table_columns[col]
            
            if param_key in ['delete_action', 'product_preview', 'subtotal', 'quantity']:
                continue
            
            widget = self.table.cellWidget(row, col)
            if widget and hasattr(widget, 'text') and widget.text().strip():
                return False
            cell_item = self.table.item(row, col)
            if cell_item and cell_item.text().strip():
                return False
        
        return True
    
    def _get_product_name(self, row):
        """Get product name from row"""
        try:
            col = self.row_factory.data_manager.table_columns.index('product_name')
            widget = self.table.cellWidget(row, col)
            if widget and hasattr(widget, 'text'):
                return widget.text().strip()
        except (ValueError, AttributeError):
            pass
        return ""


class TableEventHandler:
    """Handles all table events and interactions"""
    
    def __init__(self, table, data_manager, empty_row_manager, items_changed_callback):
        self.table = table
        self.data_manager = data_manager
        self.empty_row_manager = empty_row_manager
        self.items_changed_callback = items_changed_callback
        self._updating = False
        self._stock_cache = {}
        self._table_events_connected = False
    
    def setup_event_connections(self):
        """Setup event connections"""
        if not self._table_events_connected:
            self.table.itemChanged.connect(self._on_item_changed)
            self.table.cellClicked.connect(self._on_cell_clicked)
            self._table_events_connected = True
        
        # Connect autocomplete widgets
        for row in range(self.table.rowCount()):
            self._connect_row_widgets(row)

    def _on_cell_clicked(self, row, column):
        try:
            if self.data_manager.table_columns[column] == "quantity":
                QTimer.singleShot(0, lambda r=row: self._begin_quantity_edit(r))
        except (IndexError, ValueError):
            pass
    
    def _connect_row_widgets(self, row):
        """Connect widgets in a specific row"""
        try:
            col = self.data_manager.table_columns.index('product_name')
            widget = self.table.cellWidget(row, col)
            if widget and hasattr(widget, 'textChanged'):
                widget.setProperty('row', row)
                if widget.property('operation_events_connected'):
                    return
                if hasattr(widget, 'toPlainText'):
                    widget.textChanged.connect(
                        lambda w=widget: self._on_product_name_changed(
                            int(w.property('row')), w.text()
                        )
                    )
                else:
                    widget.textChanged.connect(
                        lambda text, w=widget: self._on_product_name_changed(
                            int(w.property('row')), text
                        )
                    )
            if widget and hasattr(widget, 'editingFinished'):
                widget.editingFinished.connect(
                    lambda w=widget: self._on_product_selection_finished(
                        int(w.property('row'))
                    )
                )
            if widget:
                widget.setProperty('operation_events_connected', True)
            try:
                type_col = self.data_manager.table_columns.index("item_type")
                selector = self.table.cellWidget(row, type_col)
                if selector and not selector.property("operation_events_connected"):
                    selector.currentIndexChanged.connect(
                        lambda _index, s=selector: self._on_item_type_changed(
                            int(s.property("row"))
                        )
                    )
                    selector.setProperty("operation_events_connected", True)
            except (ValueError, AttributeError):
                pass
        except (ValueError, AttributeError):
            pass

    def _on_item_type_changed(self, row):
        try:
            name_col = self.data_manager.table_columns.index("product_name")
            name_widget = self.table.cellWidget(row, name_col)
            if name_widget:
                name_widget.setProperty("product_id", None)
                name_widget.setProperty("service_id", None)
                name_widget.setProperty("item_type", None)
                if name_widget.text().strip():
                    self._handle_product_selection(row, name_widget.text().strip())
            self.items_changed_callback()
        except (ValueError, AttributeError):
            pass
    
    def _on_item_changed(self, item):
        """Handle item changes"""
        if self._updating:
            return
        
        row = item.row()
        col = item.column()
        
        if col < len(self.data_manager.table_columns):
            param_key = self.data_manager.table_columns[col]
            
            if param_key in ['quantity', 'unit_price']:
                self._updating = True
                try:
                    self._update_row_subtotal(row)
                finally:
                    self._updating = False
                # Trigger immediate validation for quantity changes
                if param_key == 'quantity':
                    self._validate_stock(row)
            elif param_key == 'subtotal':
                self._apply_subtotal_override(row)
        
        # Ensure empty row management
        if not self.empty_row_manager._is_row_empty(row):
            self._updating = True
            try:
                self.empty_row_manager.ensure_single_empty_row()
                self._reconnect_all_widgets()
            finally:
                self._updating = False
        
        self.items_changed_callback()

    @staticmethod
    def _parse_number(value):
        try:
            return float(str(value or "0").replace(" ", "").replace(",", "."))
        except ValueError:
            return 0.0

    def _apply_subtotal_override(self, row):
        """Derive unit price when a user enters the line subtotal directly."""
        try:
            qty_col = self.data_manager.table_columns.index('quantity')
            price_col = self.data_manager.table_columns.index('unit_price')
            subtotal_col = self.data_manager.table_columns.index('subtotal')
            qty_item = self.table.item(row, qty_col)
            price_item = self.table.item(row, price_col)
            subtotal_item = self.table.item(row, subtotal_col)
            if subtotal_item is None:
                return

            quantity = self._parse_number(qty_item.text() if qty_item else "")
            self._updating = True
            if quantity <= 0:
                quantity = 1.0
                if qty_item is None:
                    qty_item = QTableWidgetItem()
                    self.table.setItem(row, qty_col, qty_item)
                qty_item.setText("1")

            subtotal = self._parse_number(subtotal_item.text())
            unit_price = subtotal / quantity
            if price_item is None:
                price_item = QTableWidgetItem()
                self.table.setItem(row, price_col, price_item)

            price_item.setText(f"{unit_price:.6f}".rstrip('0').rstrip('.'))
            was_updating = self._updating
            self._updating = True
            subtotal_item.setText(f"{subtotal:,.2f}".replace(",", " "))
            self._updating = was_updating
            self._updating = False
        except (ValueError, AttributeError, IndexError):
            self._updating = False
    
    def _on_product_name_changed(self, row, text):
        """Handle product name text changes"""
        if self._updating:
            return
        
        # Update corresponding table item
        try:
            col = self.data_manager.table_columns.index('product_name')
            item = self.table.item(row, col)
            if not item:
                item = QTableWidgetItem()
                self.table.setItem(row, col, item)
            
            self._updating = True
            item.setText(text)
            self._updating = False
        except (ValueError, IndexError):
            pass
    
    def _on_product_selection_finished(self, row):
        """Handle when product selection is completed"""
        product_name = self.empty_row_manager._get_product_name(row)
        if product_name:
            self._handle_product_selection(row, product_name)
            self.empty_row_manager.ensure_single_empty_row()
            self._reconnect_all_widgets()
            self.items_changed_callback()
            # Bridge the widget-backed product name to the item-backed
            # quantity delegate. This makes Tab and a single click reliably
            # enter quantity editing instead of merely selecting the row.
            QTimer.singleShot(
                0, lambda r=row: self._begin_quantity_edit(r, select_all=True)
            )

    def _begin_quantity_edit(self, row, select_all=False):
        try:
            quantity_col = self.data_manager.table_columns.index("quantity")
            item = self.table.item(row, quantity_col)
            if item is None or not (item.flags() & Qt.ItemIsEditable):
                return
            self.table.setCurrentCell(row, quantity_col)
            delegate = self.table.itemDelegateForColumn(quantity_col)
            editor = (
                delegate.active_editors.get(row)
                if hasattr(delegate, "active_editors") else None
            )
            if editor is None:
                self.table.editItem(item)
                editor = (
                    delegate.active_editors.get(row)
                    if hasattr(delegate, "active_editors") else None
                )
            if isinstance(editor, QLineEdit):
                editor.setFocus()
            if select_all and isinstance(editor, QLineEdit):
                editor.selectAll()
        except (ValueError, IndexError):
            pass
    
    def _handle_product_selection(self, row, product_name):
        """Handle product selection and auto-fill"""
        if "item_type" in self.data_manager.table_columns:
            selected = self._resolve_sale_catalog_item(row, product_name)
            self._auto_fill_quantity(row)
            if selected is None:
                self._update_row_subtotal(row)
                return
            # The typed catalog resolver already stored the immutable ID and
            # catalog price. Do not run the legacy Product-only price lookup,
            # which would overwrite Service prices with zero.
            self._update_row_subtotal(row)
            return
        temp_item = self.data_manager.item_class(0, self.data_manager.database)
        temp_item.set_value('product_name', product_name)
        
        # Auto-fill quantity if empty
        self._auto_fill_quantity(row)
        
        # Auto-fill unit price
        self._auto_fill_unit_price(row, temp_item)
        
        # Update preview
        self._update_preview(row, temp_item)
        
        # Update subtotal
        self._update_row_subtotal(row)

    @staticmethod
    def _normalized_name(value):
        return " ".join(str(value or "").split()).casefold()

    def _resolve_sale_catalog_item(self, row, entered_name):
        database = self.data_manager.database
        if not database or not getattr(database, "cursor", None):
            return None
        # "Keep only in this Sale" lines stay snapshot-only: never resolve or
        # link them to a catalog record.
        try:
            type_col = self.data_manager.table_columns.index("item_type")
        except ValueError:
            type_col = None
        if type_col is not None:
            selector = self.table.cellWidget(row, type_col)
            if selector and str(selector.currentData() or "") == "manual":
                return None
        target = self._normalized_name(entered_name)
        product = service = None
        remote_catalog = getattr(database, "sale_catalog", None)
        if isinstance(remote_catalog, dict):
            for record in remote_catalog.get("products", []):
                if self._normalized_name(record.get("name")) == target:
                    product = {
                        "type": "product", "id": int(record["id"]),
                        "name": record["name"], "price": record.get("price") or 0,
                    }
                    break
            for record in remote_catalog.get("services", []):
                candidates = [
                    record.get("name"),
                    *str(record.get("keywords") or "").replace(
                        "\n", ","
                    ).replace(";", ",").split(","),
                ]
                if any(self._normalized_name(value) == target for value in candidates):
                    service = {
                        "type": "service", "id": int(record["id"]),
                        "name": record["name"], "price": record.get("price") or 0,
                    }
                    break
        else:
            try:
                database.cursor.execute(
                    "SELECT id, name, sale_price FROM products "
                    "WHERE LOWER(REGEXP_REPLACE(BTRIM(name), '\\s+', ' ', 'g'))=%s "
                    "ORDER BY id LIMIT 2",
                    (target,),
                )
                product_row = database.cursor.fetchone()
                if product_row:
                    product = {
                        "type": "product", "id": int(product_row[0]),
                        "name": product_row[1], "price": product_row[2] or 0,
                    }
                database.cursor.execute(
                    "SELECT id, name, unit_price FROM services "
                    "WHERE LOWER(REGEXP_REPLACE(BTRIM(name), '\\s+', ' ', 'g'))=%s "
                    "ORDER BY id LIMIT 2",
                    (target,),
                )
                service_row = database.cursor.fetchone()
                if service_row:
                    service = {
                        "type": "service", "id": int(service_row[0]),
                        "name": service_row[1], "price": service_row[2] or 0,
                    }
            except Exception:
                return None

        type_col = self.data_manager.table_columns.index("item_type")
        selector = self.table.cellWidget(row, type_col)
        chosen_type = str(selector.currentData() or "") if selector else ""
        if product and service and not chosen_type:
            choice, ok = QInputDialog.getItem(
                self.table,
                "Choose Item Type",
                f"'{entered_name}' exists as both a Product and a Service:",
                ["Product", "Service"],
                editable=False,
            )
            if not ok:
                return None
            chosen_type = choice.casefold()
        elif product and not service:
            chosen_type = "product"
        elif service and not product:
            chosen_type = "service"

        selected = product if chosen_type == "product" else service if chosen_type == "service" else None
        if selector and chosen_type:
            selector.blockSignals(True)
            selector.setCurrentIndex(selector.findData(chosen_type))
            selector.blockSignals(False)
        name_col = self.data_manager.table_columns.index("product_name")
        name_widget = self.table.cellWidget(row, name_col)
        if name_widget:
            name_widget.setProperty("product_id", selected["id"] if selected and chosen_type == "product" else None)
            name_widget.setProperty("service_id", selected["id"] if selected and chosen_type == "service" else None)
            name_widget.setProperty("item_type", chosen_type or None)
            if selected and name_widget.text() != selected["name"]:
                name_widget.setText(selected["name"])
        if selected:
            if chosen_type == "product":
                # Stock changes outside this dialog are irrelevant while the
                # line is being typed. Cache it to avoid synchronous SQL on
                # every quantity keystroke.
                self._stock_cache.pop(int(selected["id"]), None)
            try:
                price_col = self.data_manager.table_columns.index("unit_price")
                price_item = self.table.item(row, price_col) or QTableWidgetItem()
                if not self.table.item(row, price_col):
                    self.table.setItem(row, price_col, price_item)
                if not price_item.text().strip() or self._parse_number(price_item.text()) == 0:
                    price_item.setText(str(selected["price"]))
            except ValueError:
                pass
        return selected
    
    def _auto_fill_quantity(self, row):
        """Auto-fill quantity with default value"""
        try:
            col = self.data_manager.table_columns.index('quantity')
            qty_item = self.table.item(row, col)
            
            current_qty = 0
            if qty_item and qty_item.text().strip():
                try:
                    current_qty = float(qty_item.text())
                except ValueError:
                    current_qty = 0
            
            if current_qty == 0:
                if not qty_item:
                    qty_item = QTableWidgetItem()
                    self.table.setItem(row, col, qty_item)
                qty_item.setText("1")
        except ValueError:
            pass
    
    def _auto_fill_unit_price(self, row, temp_item):
        """Auto-fill unit price from product data"""
        try:
            col = self.data_manager.table_columns.index('unit_price')
            unit_price = temp_item.get_value('unit_price')
            
            if unit_price is not None:
                price_item = self.table.item(row, col)
                if not price_item:
                    price_item = QTableWidgetItem()
                    self.table.setItem(row, col, price_item)
                price_item.setText(str(unit_price))
        except ValueError:
            pass
    
    def _update_preview(self, row, temp_item):
        """Update preview image"""
        try:
            col = self.data_manager.table_columns.index('product_preview')
            if hasattr(temp_item, 'get_product_preview'):
                preview_path = temp_item.get_product_preview()
                container_widget = self.table.cellWidget(row, col)
                if container_widget:
                    for child in container_widget.findChildren(PreviewWidget):
                        if preview_path:
                            child.set_image_path(preview_path)
                        break
        except ValueError:
            pass
    
    def _update_row_subtotal(self, row):
        """Update subtotal for a row"""
        try:
            qty_col = self.data_manager.table_columns.index('quantity')
            price_col = self.data_manager.table_columns.index('unit_price')
            subtotal_col = self.data_manager.table_columns.index('subtotal')
            
            qty_item = self.table.item(row, qty_col)
            price_item = self.table.item(row, price_col)
            
            quantity = Decimal(str(qty_item.text()).replace(" ", "").replace(",", ".")) if qty_item and qty_item.text().strip() else Decimal("0")
            unit_price = Decimal(str(price_item.text()).replace(" ", "").replace(",", ".")) if price_item and price_item.text().strip() else Decimal("0")
            from core.calculations import calculate_line_subtotal
            subtotal = calculate_line_subtotal(quantity, unit_price)
            
            subtotal_item = self.table.item(row, subtotal_col)
            if not subtotal_item:
                subtotal_item = QTableWidgetItem()
                self.table.setItem(row, subtotal_col, subtotal_item)
            
            subtotal_item.setText(f"{subtotal:,.2f}".replace(",", " "))

            # After updating subtotal, validate stock and style quantity cell if exceeded
            self._validate_stock(row)
            
        except (ValueError, AttributeError, IndexError):
            pass
    
    def _reconnect_all_widgets(self):
        """Reconnect all widget events after table changes"""
        for row in range(self.table.rowCount()):
            self._connect_row_widgets(row)

    # --- Stock validation & styling -------------------------------------------------
    def get_row_stock_state(self, row):
        """Return (requested_qty, stock_available, exceeded, product_name) or None if cannot evaluate."""
        db = getattr(self.data_manager, 'database', None)
        if not db or not hasattr(db, 'cursor'):
            return None
        try:
            product_col = self.data_manager.table_columns.index('product_name')
            qty_col = self.data_manager.table_columns.index('quantity')
        except ValueError:
            return None
        product_widget = self.table.cellWidget(row, product_col)
        product_name = product_widget.text().strip() if product_widget and hasattr(product_widget, 'text') else ''
        if not product_name:
            return None
        item_type = str(product_widget.property("item_type") or "").casefold()
        if "item_type" in self.data_manager.table_columns:
            try:
                type_col = self.data_manager.table_columns.index("item_type")
                selector = self.table.cellWidget(row, type_col)
                item_type = str(selector.currentData() or item_type).casefold()
            except (ValueError, AttributeError):
                pass
        if item_type in ("service", "manual"):
            return None
        
        # Get quantity from either active editor or cell item
        requested_qty = 0
        try:
            # Check if there's an active editor for this row
            qty_delegate = self.table.itemDelegateForColumn(qty_col)
            if (hasattr(qty_delegate, 'active_editors') and 
                row in qty_delegate.active_editors):
                # Use editor text for real-time evaluation
                editor = qty_delegate.active_editors[row]
                requested_qty = self._parse_number(editor.text())
            else:
                # Use cell item text
                qty_item = self.table.item(row, qty_col)
                if qty_item:
                    requested_qty = self._parse_number(qty_item.text())
        except (ValueError, AttributeError):
            # Fallback to cell item if editor access fails
            try:
                qty_item = self.table.item(row, qty_col)
                if qty_item:
                    requested_qty = self._parse_number(qty_item.text())
            except ValueError:
                requested_qty = 0

        remote_catalog = getattr(db, "sale_catalog", None)
        if isinstance(remote_catalog, dict):
            product_id = product_widget.property("product_id")
            target_name = self._normalized_name(product_name)
            record = next(
                (
                    candidate
                    for candidate in remote_catalog.get("products", [])
                    if (
                        product_id
                        and int(candidate.get("id") or 0) == int(product_id)
                    ) or self._normalized_name(candidate.get("name")) == target_name
                ),
                None,
            )
            if not record:
                return (requested_qty, None, False, product_name)
            product_widget.setProperty("product_id", int(record["id"]))
            try:
                stock_available = Decimal(str(record.get("stock") or 0))
            except (InvalidOperation, ValueError):
                stock_available = None
            if stock_available is None:
                return (requested_qty, None, False, product_name)
            return (
                requested_qty, stock_available,
                Decimal(str(requested_qty)) > stock_available, product_name,
            )
        
        # Product ID lookup
        product_id = product_widget.property("product_id")
        try:
            if not product_id:
                db.cursor.execute(
                    "SELECT ID FROM Products "
                    "WHERE LOWER(REGEXP_REPLACE(BTRIM(name), '\\s+', ' ', 'g'))=%s "
                    "ORDER BY id LIMIT 1",
                    (self._normalized_name(product_name),),
                )
                res = db.cursor.fetchone()
                if res and res[0]:
                    product_id = res[0]
        except Exception:
            product_id = None
        if not product_id:
            return (requested_qty, None, False, product_name)
        try:
            cache_key = int(product_id)
            if cache_key not in self._stock_cache:
                product_obj = ProductClass(cache_key, db)
                self._stock_cache[cache_key] = product_obj.calculate_quantity()
            stock_available = self._stock_cache[cache_key]
        except Exception:
            stock_available = None
        if stock_available is None:
            return (requested_qty, None, False, product_name)
        exceeded = requested_qty > stock_available
        return (requested_qty, stock_available, exceeded, product_name)
        # Product ID
        product_id = None
        try:
            db.cursor.execute("SELECT ID FROM Products WHERE name = %s LIMIT 1", (product_name,))
            res = db.cursor.fetchone()
            if res and res[0]:
                product_id = res[0]
        except Exception:
            product_id = None
        if not product_id:
            return (requested_qty, None, False, product_name)
        try:
            product_obj = ProductClass(product_id, db)
            stock_available = product_obj.calculate_quantity()
        except Exception:
            stock_available = None
        if stock_available is None:
            return (requested_qty, None, False, product_name)
        exceeded = requested_qty > stock_available
        return (requested_qty, stock_available, exceeded, product_name)

    def _validate_stock(self, row):
        state = self.get_row_stock_state(row)
        if not state:
            return
        requested, available, exceeded, _ = state
        try:
            qty_col = self.data_manager.table_columns.index('quantity')
        except ValueError:
            return
        
        # Check if this cell is currently being edited
        qty_delegate = self.table.itemDelegateForColumn(qty_col)
        is_being_edited = (hasattr(qty_delegate, 'active_editors') and 
                          row in qty_delegate.active_editors)
        
        if is_being_edited:
            # Don't modify the cell item while editing - styling handled by delegate
            return
            
        # Only update cell styling when not actively editing
        qty_item = self.table.item(row, qty_col)
        if not qty_item:
            return
        if available is None:
            self._clear_quantity_style(qty_item)
            return
        if exceeded:
            self._apply_exceeded_style(qty_item, requested, available)
        else:
            self._clear_quantity_style(qty_item)

    def _apply_exceeded_style(self, qty_item: QTableWidgetItem, requested, available):
        """Apply red highlighting indicating quantity exceeds stock."""
        if not qty_item:
            return
        qty_item.setBackground(QBrush(QColor("#6e1d1d")))  # Dark red background
        qty_item.setForeground(QBrush(QColor("#ffffff")))  # White text
        # Store tooltip with info
        qty_item.setToolTip(f"Requested {requested} exceeds available stock {available}")

    def _clear_quantity_style(self, qty_item: QTableWidgetItem):
        """Clear custom styling on quantity cell (restore defaults)."""
        if not qty_item:
            return
        qty_item.setBackground(QBrush())
        qty_item.setForeground(QBrush())
        qty_item.setToolTip("")

    def validate_all_rows(self):
        for row in range(self.table.rowCount()):
            # Skip final empty row
            self._validate_stock(row)


class QuantityDelegate(QStyledItemDelegate):
    """Custom delegate to style quantity editor (QLineEdit) while editing."""
    def __init__(self, event_handler: TableEventHandler, parent=None):
        super().__init__(parent)
        self.event_handler = event_handler
        self.active_editors = {}  # Track active editors by row

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setValidator(QRegularExpressionValidator(
            # Empty text must remain an intermediate valid state so users can
            # select the default "1", delete it, and type a replacement.
            QRegularExpression(r"^(?:|\d+(?:[\.,]\d{0,3})?|[\.,]\d{1,3})$"), editor
        ))
        row = index.row()
        self.active_editors[row] = editor  # Store reference
        self._apply_style(editor, row)
        # Connect textChanged for real-time styling only
        editor.textChanged.connect(lambda _t, r=row, e=editor: self._apply_style(e, r))
        return editor

    def destroyEditor(self, editor, index):
        row = index.row()
        if row in self.active_editors:
            del self.active_editors[row]  # Clean up reference
        super().destroyEditor(editor, index)

    def setEditorData(self, editor, index):
        value = index.model().data(index, Qt.EditRole)
        editor.setText(str(value) if value is not None else "")

    def setModelData(self, editor, model, index):
        value = editor.text().strip()
        if value in ("", ".", ","):
            value = "1"
        model.setData(index, value, Qt.EditRole)
        # After committing, trigger validation so cell styling updates
        row = index.row()
        # Small delay to ensure the editor is fully closed before validation
        from PySide6.QtCore import QTimer
        QTimer.singleShot(50, lambda: self.event_handler._validate_stock(row))

    def _apply_style(self, editor: QLineEdit, row: int):
        state = self.event_handler.get_row_stock_state(row)
        exceeded = False
        if state:
            requested, available, exceeded, _ = state
        if exceeded:
            editor.setStyleSheet("QLineEdit{border:2px solid #f44336; background:#6e1d1d; color:#ffffff; border-radius:4px;}")
            if state and state[1] is not None:
                editor.setToolTip(f"Requested {state[0]} exceeds available stock {state[1]}")
        else:
            # Neutral style (inherit theme but ensure visible border)
            editor.setStyleSheet("QLineEdit{border:1px solid #555555; background:#2e2e2e; color:#ffffff; border-radius:4px;}")
            editor.setToolTip("")


class OperationsTableWidget(QWidget):
    """Clean operations table with proper separation of concerns

    Added feature toggle: highlight_stock_exceed
    When True, quantity cells & editors turn red if requested quantity exceeds available stock.
    When False, no stock lookup nor styling occurs (performance friendly for imports).
    """
    
    items_changed = Signal()
    
    def __init__(self, item_class, parent_operation=None, database=None, columns=None, parent=None,
                 highlight_stock_exceed=False):
        super().__init__(parent)
        
        # Feature flags
        self.highlight_stock_exceed = highlight_stock_exceed
        
        # Core components
        self.data_manager = TableDataManager(item_class, database)
        self.parent_operation = parent_operation
        
        # Override columns if provided
        if columns:
            self.data_manager.table_columns = columns
        
        # Setup UI
        self._setup_ui()
        
        # Create managers
        self.row_factory = TableRowFactory(self.data_manager, self._delete_row)
        self.empty_row_manager = EmptyRowManager(self.table, self.row_factory)
        self.event_handler = TableEventHandler(self.table, self.data_manager, 
                                             self.empty_row_manager, self._on_items_changed)
        
        # If highlighting disabled, monkey patch validator methods to no-op for simplicity
        if not self.highlight_stock_exceed:
            # Replace validate calls with stubs
            self.event_handler._validate_stock = lambda *_args, **_kw: None  # type: ignore
            self.event_handler.validate_all_rows = lambda: None  # type: ignore
        
        # Load data
        self.refresh_table()
        # Install delegates after initial setup (only if highlighting enabled)
        if self.highlight_stock_exceed:
            self._install_delegates()
    
    def _setup_ui(self):
        """Setup user interface"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.table = QTableWidget()
        self._configure_table()
        
        layout.addWidget(self.table)
    
    def _configure_table(self):
        """Configure table properties"""
        # Set columns
        headers = self.data_manager.get_column_headers()
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        
        # Table properties
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(45)
        
        # Column widths
        header = self.table.horizontalHeader()
        for i, param_key in enumerate(self.data_manager.table_columns):
            if param_key == 'product_preview':
                self.table.setColumnWidth(i, 70)
                header.setSectionResizeMode(i, QHeaderView.Fixed)
            elif param_key == 'delete_action':
                self.table.setColumnWidth(i, 50)
                header.setSectionResizeMode(i, QHeaderView.Fixed)
            else:
                header.setSectionResizeMode(i, QHeaderView.Stretch)
        
        # Styling
        self._apply_theme()
    
    def refresh_table(self):
        """Refresh table data"""
        self.table.setRowCount(0)
        
        # Load existing items
        items = self.data_manager.load_items_from_operation(self.parent_operation)
        for item in items:
            row = self.table.rowCount()
            self.table.setRowCount(row + 1)
            self.row_factory.create_data_row(self.table, row, item)
        
        # Ensure empty row
        self.empty_row_manager.ensure_single_empty_row()
        
        # Setup events
        self.event_handler.setup_event_connections()
        # Initial validation so existing rows show state immediately (only if enabled)
        if self.highlight_stock_exceed:
            self.event_handler.validate_all_rows()

    def _install_delegates(self):
        """Install custom delegates (quantity styling)."""
        try:
            qty_col = self.data_manager.table_columns.index('quantity')
        except ValueError:
            return
        delegate = QuantityDelegate(self.event_handler, self.table)
        self.table.setItemDelegateForColumn(qty_col, delegate)
    
    def get_current_table_data(self):
        """Get all non-empty rows as data dictionaries"""
        items_data = []
        diagnostics = []
        for row in range(self.table.rowCount()):
            if self.empty_row_manager._is_row_empty(row):
                diagnostics.append({'row': row + 1, 'status': 'skipped', 'reason': 'empty row'})
                continue
            row_data = self.data_manager.extract_row_data(self.table, row)
            row_data['row_index'] = row + 1
            items_data.append(row_data)
            diagnostics.append({
                'row': row + 1,
                'status': 'extracted',
                'designation': row_data.get('product_name', ''),
                'has_id': bool(row_data.get('id')),
            })
        self.last_extraction_diagnostics = {
            'visible_rows': self.table.rowCount(),
            'extracted_rows': len(items_data),
            'rows': diagnostics,
        }
        return items_data

    def get_all_entered_product_names(self):
        """Return every product_name typed by user (even if product does not exist yet).
        Excludes the final empty row."""
        names = []
        try:
            product_col = self.data_manager.table_columns.index('product_name')
        except ValueError:
            return names
        last_row_index = self.table.rowCount() - 1  # usually the empty row
        for row in range(self.table.rowCount()):
            # Skip clearly empty rows
            if row == last_row_index and self.empty_row_manager._is_row_empty(row):
                continue
            widget = self.table.cellWidget(row, product_col)
            if widget and hasattr(widget, 'text'):
                text = widget.text().strip()
                if text and text.lower() != 'product name':
                    names.append(text)
        return names
    
    def get_items_data(self):
        """Get items as object instances (compatibility method)"""
        items = []
        items_data = self.get_current_table_data()
        
        for item_data in items_data:
            item = self.data_manager.item_class(0, self.data_manager.database)
            # Set product_name first to trigger snapshot logic in item class
            if 'product_name' in item_data:
                try:
                    item.set_value('product_name', item_data['product_name'])
                except Exception:
                    pass
            # Set remaining fields except product_name
            for key, value in item_data.items():
                if key == 'product_name':
                    continue
                try:
                    if hasattr(item, 'is_parameter_calculated') and item.is_parameter_calculated(key):
                        continue
                except Exception:
                    pass
                try:
                    item.set_value(key, value)
                except Exception:
                    pass
            try:
                selected_type = str(item_data.get("item_type") or "").casefold()
                if selected_type == "service":
                    item.parameters["product_id"]["value"] = None
                elif selected_type == "product" and "service_id" in item.parameters:
                    item.parameters["service_id"]["value"] = None
            except Exception:
                pass
            # Attempt resolution (non-fatal if fails); include regardless for later handling
            if (hasattr(item, 'get_value') and not item.get_value('product_id')
                    and str(item_data.get("item_type") or "").casefold() != "service"):
                try:
                    if self.data_manager.database and hasattr(self.data_manager.database, 'cursor'):
                        self.data_manager.database.cursor.execute(
                            "SELECT ID FROM Products WHERE name = %s", (item.get_value('product_name'),))
                        res = self.data_manager.database.cursor.fetchone()
                        if res and res[0]:
                            item.set_value('product_id', res[0])
                except Exception:
                    pass
            items.append(item)
        
        return items
    
    def _delete_row(self, row):
        """Delete a specific row"""
        try:
            row = int(row)
        except (TypeError, ValueError):
            return
        if 0 <= row < self.table.rowCount():
            signals_were_blocked = self.table.blockSignals(True)
            try:
                self.table.removeRow(row)
            finally:
                self.table.blockSignals(signals_were_blocked)
            self.empty_row_manager.ensure_single_empty_row()
            self.event_handler._reconnect_all_widgets()
            self._on_items_changed()
    
    def _on_items_changed(self):
        """Handle items changed event"""
        self.items_changed.emit()
    
    def _apply_theme(self):
        """Apply styling"""
        self.table.setStyleSheet("""
            QHeaderView::section {
                background-color: #404040;
                color: #ffffff;
                padding: 8px;
                border: 1px solid #555555;
                font-weight: bold;
            }
            QScrollBar:vertical {
                background-color: #404040;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #666666;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #777777;
            }
        """)
