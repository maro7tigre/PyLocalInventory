"""
Base Tab Class - Enhanced to better support operations
Unified table experience for all entities (Products, Clients, Suppliers, Sales, Imports)
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QTableWidget, QTableWidgetItem, QHeaderView, 
                               QMessageBox, QPushButton, QAbstractItemView,
                               QStyledItemDelegate, QLineEdit, QComboBox, QStyle,
                               QApplication, QStyleOptionViewItem)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt, QSize, QTimer, QObject, QThread, Signal, Slot
from ui.widgets.themed_widgets import RedButton, BlueButton, GreenButton
from ui.widgets.preview_widget import PreviewWidget
from ui.widgets.autocomplete_widgets import AutoCompleteLineEdit, AutoExpandingTextEdit
from ui.widgets.parameters_widgets import ButtonWidget
from core.network.protocol import PermissionDeniedError
from core.database import Database
from datetime import datetime
from decimal import Decimal
import re
import time
import logging

logger = logging.getLogger(__name__)


class _RemoteTableFetchWorker(QObject):
    finished = Signal(object, object, object, float, int)
    failed = Signal(str, float)

    def __init__(self, fetcher):
        super().__init__()
        self.fetcher = fetcher

    @Slot()
    def run(self):
        started = time.perf_counter()
        try:
            result = self.fetcher()
            metrics = {}
            refresh_id = None
            if isinstance(result, tuple):
                if len(result) == 5:
                    items, levels, metrics, refresh_id, memory_info = result
                elif len(result) == 4:
                    items, levels, metrics, refresh_id = result
                elif len(result) == 3:
                    items, levels, metrics = result
                else:
                    items, levels = result
            else:
                items = result
                levels = None
            self.finished.emit(items, levels, metrics, started, refresh_id)
        except Exception as error:
            logger.exception("Remote table fetch failed")
            self.failed.emit(str(error), started)


class BaseTableDelegate(QStyledItemDelegate):
    """Custom delegate for table with autocomplete and read-only cells"""
    
    def __init__(self, base_tab, parent=None):
        super().__init__(parent)
        self.base_tab = base_tab
    
    def createEditor(self, parent, option, index):
        """Create appropriate editor based on column and permissions"""
        col = index.column()
        column_key = self.base_tab.table_columns[col]
        
        # Check if this column is editable
        if not self.base_tab.is_column_editable(column_key):
            return None  # No editor for read-only cells
        
        # Check if the item itself is editable (for widget cells)
        item = self.base_tab.table.item(index.row(), index.column())
        if item and not (item.flags() & Qt.ItemIsEditable):
            return None  # No editor for non-editable items
        
        # Don't create editors for widget cells (like images)
        widget = self.base_tab.table.cellWidget(index.row(), index.column())
        if widget is not None:
            return None  # No editor for widget cells
        
        # Get parameter info for autocomplete
        param_info = self.base_tab.get_column_param_info(column_key)
        options = param_info.get('options', [])
        
        if param_info.get('type', 'string') == 'string':
            editor = AutoExpandingTextEdit(
                parent,
                options=options,
                multi_value=param_info.get('multi_value', False),
                allow_free_text=param_info.get('allow_free_text', True),
            )
        elif options:
            editor = AutoCompleteLineEdit(parent, options)
        else:
            editor = QLineEdit(parent)
        
        return editor

    def sizeHint(self, option, index):
        """Grow rows for wrapped text, including long strings without spaces."""
        text = str(index.data(Qt.DisplayRole) or "")
        if not text:
            return super().sizeHint(option, index)

        column_width = self.base_tab.table.columnWidth(index.column())
        available_width = max(40, column_width - 16)
        bounds = option.fontMetrics.boundingRect(
            0,
            0,
            available_width,
            10000,
            Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap | Qt.TextWrapAnywhere,
            text,
        )
        return QSize(column_width, max(70, bounds.height() + 16))

    def paint(self, painter, option, index):
        """Paint overflowing cell text with wrapping instead of ellipsis."""
        text = str(index.data(Qt.DisplayRole) or "")
        available_width = max(40, option.rect.width() - 16)
        needs_wrap = "\n" in text or option.fontMetrics.horizontalAdvance(text) > available_width
        if not needs_wrap:
            super().paint(painter, option, index)
            return

        styled_option = QStyleOptionViewItem(option)
        self.initStyleOption(styled_option, index)
        painter.save()
        style = styled_option.widget.style() if styled_option.widget else QApplication.style()
        style.drawPrimitive(QStyle.PE_PanelItemViewItem, styled_option, painter, styled_option.widget)
        selected = bool(styled_option.state & QStyle.State_Selected)
        painter.setPen(
            styled_option.palette.highlightedText().color()
            if selected else styled_option.palette.text().color()
        )
        painter.drawText(
            styled_option.rect.adjusted(8, 5, -8, -5),
            Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap | Qt.TextWrapAnywhere,
            text,
        )
        painter.restore()
    
    def setEditorData(self, editor, index):
        """Set current cell value in editor"""
        value = index.model().data(index, Qt.EditRole)
        if isinstance(editor, (QLineEdit, AutoCompleteLineEdit, AutoExpandingTextEdit)):
            editor.setText(str(value) if value else "")
    
    def setModelData(self, editor, model, index):
        """Set editor value back to model and update database"""
        if isinstance(editor, (QLineEdit, AutoCompleteLineEdit, AutoExpandingTextEdit)):
            new_value = editor.text()
            old_value = model.data(index, Qt.EditRole)
            
            if new_value != old_value:
                # Update the model
                model.setData(index, new_value, Qt.EditRole)
                
                # Update the database
                self.base_tab.update_cell_in_database(index.row(), index.column(), new_value)


class BaseTab(QWidget):
    """Base tab with editable table - unified for all entities including operations"""
    
    def __init__(self, object_class, dialog_class, database=None, parent=None):
        super().__init__(parent)
        self.object_class = object_class
        self.dialog_class = dialog_class
        self.database = database
        self.parent_widget = parent
        
        # Get class info
        temp_object = object_class(0, database)
        self.table_columns = temp_object.get_visible_parameters("table")
        self.table_permissions = temp_object.available_parameters["table"]
        self.parameter_definitions = temp_object.parameters
        self.section = temp_object.section

        # Role-based write/delete access (local host database is always fully
        # permitted; a network client is gated by its logged-in user's role).
        # Read access is handled one level up - MainWindow never builds this
        # tab at all when the user lacks read permission for the section.
        self.can_write = self.database.has_permission(self.section, 'write') if self.database else True
        self.can_delete = self.database.has_permission(self.section, 'delete') if self.database else True

        # Store current page of items for filtering/rendering
        self.all_items = []
        self.filtered_items = []
        self._refreshing = False
        self._dialog_open = False
        self._loaded_once = False
        self._needs_refresh = True
        self._last_refresh_at = 0.0
        self._refresh_id = 0
        self._refresh_thread = None
        self._refresh_worker = None

        self.page_size = 100
        self.current_page = 0
        self._has_more_rows = False

        self.setup_ui()
        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self._wait_for_refresh_thread)
    
    def setup_ui(self):
        """Setup tab interface"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Title label (larger)
        title = QLabel(f"{self.section} Management")
        title.setStyleSheet("font-size: 28px; font-weight: bold;")
        layout.addWidget(title)
        
        # Search and controls layout
        controls_layout = QHBoxLayout()
        
        # Search bar
        self.search_bar = AutoCompleteLineEdit(self, self.get_search_options())
        self.search_bar.setPlaceholderText(f"Search {self.section.lower()}...")
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self.filter_table)
        self.search_bar.textChanged.connect(lambda _text: self._search_timer.start())
        controls_layout.addWidget(self.search_bar)
        
        # Order dropdown
        self.order_combo = QComboBox()
        self.setup_order_options()
        self.order_combo.currentTextChanged.connect(self.filter_table)
        controls_layout.addWidget(self.order_combo)
        
        controls_layout.addStretch()
        
        # Action buttons
        entity_name = self.section[:-1] if self.section.endswith('s') else self.section
        
        self.add_btn = BlueButton(f"Add {entity_name}")
        # Increase size only for toolbar buttons next to search bar
        self.add_btn.setStyleSheet(self.add_btn.styleSheet() + "\nQPushButton { font-size: 14px; padding: 5px 10px; }")
        self.add_btn.setMinimumHeight(20)
        self.add_btn.clicked.connect(self.add_item)
        controls_layout.addWidget(self.add_btn)

        self.edit_btn = BlueButton(f"Edit {entity_name}")
        self.edit_btn.setStyleSheet(self.edit_btn.styleSheet() + "\nQPushButton { font-size: 14px; padding: 5px 10px; }")
        self.edit_btn.setMinimumHeight(20)
        self.edit_btn.clicked.connect(self.edit_item)
        controls_layout.addWidget(self.edit_btn)

        self.delete_btn = RedButton(f"Delete {entity_name}")
        self.delete_btn.setStyleSheet(self.delete_btn.styleSheet() + "\nQPushButton { font-size: 14px; padding: 5px 10px; }")
        self.delete_btn.setMinimumHeight(20)
        self.delete_btn.clicked.connect(self.delete_item)
        controls_layout.addWidget(self.delete_btn)

        # Grey out actions the user's role isn't allowed to perform, so they
        # find out before investing time in a form rather than after trying
        # to save it.
        if not self.can_write:
            self.add_btn.setEnabled(False)
            self.add_btn.setToolTip(f"You don't have permission to add {entity_name.lower()}")
            self.edit_btn.setEnabled(False)
            self.edit_btn.setToolTip(f"You don't have permission to edit {entity_name.lower()}")
        if not self.can_delete:
            self.delete_btn.setEnabled(False)
            self.delete_btn.setToolTip(f"You don't have permission to delete {entity_name.lower()}")
        
        self.refresh_btn = GreenButton("Refresh")
        self.refresh_btn.setStyleSheet(self.refresh_btn.styleSheet() + "\nQPushButton { font-size: 14px; padding: 5px 10px; }")
        self.refresh_btn.setMinimumHeight(20)
        self.refresh_btn.clicked.connect(self.refresh_table)
        controls_layout.addWidget(self.refresh_btn)

        self.prev_page_btn = BlueButton("< Prev")
        self.prev_page_btn.setMinimumHeight(20)
        self.prev_page_btn.clicked.connect(self.go_to_previous_page)
        controls_layout.addWidget(self.prev_page_btn)

        self.page_label = QLabel("Page 1")
        self.page_label.setStyleSheet("font-size: 14px; padding: 0 8px;")
        self.page_label.setMinimumWidth(80)
        controls_layout.addWidget(self.page_label)

        self.next_page_btn = BlueButton("Next >")
        self.next_page_btn.setMinimumHeight(20)
        self.next_page_btn.clicked.connect(self.go_to_next_page)
        controls_layout.addWidget(self.next_page_btn)

        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["25", "50", "100", "200"])
        self.page_size_combo.setCurrentText(str(self.page_size))
        self.page_size_combo.currentTextChanged.connect(self.on_page_size_changed)
        self.page_size_combo.setMinimumWidth(80)
        controls_layout.addWidget(self.page_size_combo)

        self.add_additional_toolbar_buttons(controls_layout)
        
        layout.addLayout(controls_layout)
        
        # Table setup
        self.table = QTableWidget()
        self.setup_table()
        layout.addWidget(self.table)
        
        # Apply theme
        self.apply_theme()
    
    def setup_table(self):
        """Setup table columns and properties"""
        # Set column count and headers
        self.table.setColumnCount(len(self.table_columns))
        
        # Create display headers
        headers = []
        for column_key in self.table_columns:
            if column_key in self.parameter_definitions:
                temp_obj = self.object_class(0, self.database)
                display_name = temp_obj.get_display_name(column_key)
                headers.append(display_name)
            else:
                headers.append(column_key)
        
        self.table.setHorizontalHeaderLabels(headers)

        # Table properties
        header = self.table.horizontalHeader()
        header.sectionResized.connect(
            lambda *_: QTimer.singleShot(0, self.table.resizeRowsToContents)
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)

        # Set row height to accommodate images
        self.table.verticalHeader().setDefaultSectionSize(70)

        # Set custom delegate for editing
        self.delegate = BaseTableDelegate(self)
        self.table.setItemDelegate(self.delegate)

        # Set specific column widths (ID fixed at 100px, image/preview 80px, others stretch)
        for i, column_key in enumerate(self.table_columns):
            if column_key == 'id':
                header.setSectionResizeMode(i, QHeaderView.Fixed)
                self.table.setColumnWidth(i, 80)
            elif 'image' in column_key or 'preview' in column_key:
                header.setSectionResizeMode(i, QHeaderView.Fixed)
                self.table.setColumnWidth(i, 80)
            else:
                header.setSectionResizeMode(i, QHeaderView.Stretch)
    
    def is_column_editable(self, column_key):
        """Check if column is editable: the column itself must allow writes
        ('w' permission) and the logged-in user's role must have write access
        to this section at all."""
        if not self.can_write:
            return False
        permission = self.table_permissions.get(column_key, '')
        return 'w' in permission.lower()
    
    def get_column_param_info(self, column_key):
        """Get parameter info for column"""
        return self.parameter_definitions.get(column_key, {})
    
    def refresh_table(self):
        """Refresh table data from database."""
        if self._refreshing:
            return
        if not self.database:
            QMessageBox.warning(self, "Error", "No database connection")
            return

        self._refresh_id += 1
        refresh_id = self._refresh_id
        self.table.setRowCount(0)

        if self.database.__class__.__name__ == "RemoteDatabase":
            self._start_remote_refresh(refresh_id)
            return

        self._start_local_refresh(refresh_id)
        return

    def _create_worker_database(self):
        """Create an independent database connection for background refreshes."""
        if self.database is None:
            return None
        if self.database.__class__.__name__ == 'RemoteDatabase':
            return self.database

        worker_db = Database(self.database.profile_manager)
        worker_db.language = getattr(self.database, 'language', 'en')
        worker_db.registered_classes = self.database.registered_classes
        if getattr(self.database, 'profile_manager', None):
            if not worker_db.connect():
                raise RuntimeError("Failed to connect worker database")
        return worker_db

    def _start_remote_refresh(self, refresh_id):
        """Fetch data on a worker thread; all Qt updates remain on the main thread."""
        self._refreshing = True
        self.refresh_btn.setEnabled(False)
        fetcher = self.background_fetcher(refresh_id)
        self._start_refresh(fetcher, refresh_id, mode='client')

    def _start_local_refresh(self, refresh_id):
        """Fetch data on a worker thread using a dedicated local database connection."""
        self._refreshing = True
        self.refresh_btn.setEnabled(False)
        try:
            worker_db = self._create_worker_database()
        except Exception as error:
            self._refreshing = False
            self.refresh_btn.setEnabled(True)
            logger.exception("Failed to create worker database for section=%s", self.section)
            QMessageBox.critical(
                self, "Error", f"Cannot start local background refresh: {error}"
            )
            return
        fetcher = self.background_fetcher(refresh_id, database=worker_db)
        self._start_refresh(fetcher, refresh_id, worker_db=worker_db, mode='local')

    def _start_refresh(self, fetcher, refresh_id, worker_db=None, mode='local'):
        thread = QThread(self)
        worker = _RemoteTableFetchWorker(fetcher)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._remote_refresh_finished)
        worker.failed.connect(self._remote_refresh_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: setattr(self, "_refresh_thread", None))
        if worker_db is not None:
            thread.finished.connect(lambda: worker_db.close())
        self._refresh_thread = thread
        self._refresh_worker = worker
        self._refresh_mode = mode
        thread.start()

    def _apply_refresh_results(self, items_data, levels, metrics, started, refresh_id):
        if refresh_id != self._refresh_id:
            logger.info(
                "Discarding stale refresh result section=%s refresh_id=%s current_id=%s",
                self.section, refresh_id, self._refresh_id,
            )
            return

        self.all_items = []
        if levels is not None:
            self.database._product_stock_levels = {
                int(key): value for key, value in levels.items()
            }

        if len(items_data) > self.page_size:
            self._has_more_rows = True
            items_data = items_data[:self.page_size]
        else:
            self._has_more_rows = False

        object_prep_start = time.perf_counter()
        for item_data in items_data:
            try:
                obj = self.object_class(item_data.get('ID', 0), self.database)
                for key, value in item_data.items():
                    if key in obj.parameters:
                        param_key = 'id' if key == 'ID' else key
                        try:
                            obj.set_raw_value(param_key, value)
                        except (KeyError, ValueError):
                            logger.warning(
                                "Invalid refresh value section=%s field=%s id=%s",
                                self.section, param_key, item_data.get("ID"),
                            )
                self.all_items.append(obj)
            except Exception:
                logger.exception(
                    "Failed processing section=%s id=%s",
                    self.section, item_data.get("ID"),
                )
        object_prep_duration = (time.perf_counter() - object_prep_start) * 1000
        metrics = metrics or {}
        metrics['object_prep_ms'] = object_prep_duration

        self.search_bar.update_options(self.get_search_options())
        self.filtered_items = list(self.all_items)
        render_start = time.perf_counter()
        self.populate_table_with_items(self.filtered_items)
        render_duration = (time.perf_counter() - render_start) * 1000
        metrics['render_ms'] = render_duration

        self._loaded_once = True
        self._needs_refresh = False
        self._last_refresh_at = time.monotonic()
        self._update_paging_controls()

        metrics['rows'] = len(self.all_items)
        logger.info(
            "refresh_metrics section=%s refresh_id=%s rows=%d metrics=%s",
            self.section, refresh_id, len(self.all_items), metrics,
        )

    @Slot(object, object, object, float, int)
    def _remote_refresh_finished(self, items_data, levels, metrics, started, refresh_id):
        try:
            self._apply_refresh_results(items_data, levels, metrics, started, refresh_id)
        except Exception as error:
            logger.exception("Failed applying section=%s", self.section)
            QMessageBox.critical(
                self, "Error", f"Failed to refresh {self.section}: {error}"
            )
        finally:
            self._finish_refresh(started, mode=getattr(self, '_refresh_mode', 'client'))

    @Slot(str, float)
    def _remote_refresh_failed(self, error, started):
        logger.error("Remote refresh failed section=%s error=%s", self.section, error)
        QMessageBox.critical(
            self, "Connection Error",
            f"Failed to load {self.section} from the host:\n{error}",
        )
        self._finish_refresh(started, mode=getattr(self, '_refresh_mode', 'client'))

    def _finish_refresh(self, started, mode='client'):
        self._refreshing = False
        self.refresh_btn.setEnabled(True)
        elapsed = time.perf_counter() - started
        rows = len(self.all_items)
        logger.log(
            logging.WARNING if elapsed >= 0.5 else logging.INFO,
            "load_%s completed in %.3f seconds rows=%d mode=%s",
            self.section.lower(), elapsed, rows, mode,
        )
        print(
            f"[PERFORMANCE] load_{self.section.lower()} page={self.current_page + 1} "
            f"completed in {elapsed:.3f} seconds mode={mode} rows={rows}"
        )

    def _wait_for_refresh_thread(self):
        """Do not destroy a QThread while an in-flight HTTP call is unwinding."""
        thread = getattr(self, "_refresh_thread", None)
        if thread and thread.isRunning():
            thread.requestInterruption()
            thread.quit()
            if not thread.wait(11000):
                logger.error(
                    "Remote refresh thread did not stop section=%s", self.section
                )

    def background_fetcher(self, refresh_id=None, database=None):
        """Capture filter and paging state before the worker thread starts."""
        database = database or self.database
        section = self.section
        search_text = self.search_bar.text().strip()
        order_option = self.order_combo.currentText()
        limit = self.page_size + 1
        offset = self.current_page * self.page_size

        def fetch():
            if hasattr(database, 'get_operation_summary_items') and section in ('Sales', 'Imports'):
                items = database.get_operation_summary_items(
                    section,
                    search_text=search_text,
                    search_columns=self.get_searchable_fields(),
                    order_by=self._order_by_field(order_option),
                    order_dir=self._order_direction(order_option),
                    limit=limit,
                    offset=offset,
                )
            else:
                items = database.get_items(
                    section,
                    search_text=search_text,
                    search_columns=self.get_searchable_fields(),
                    order_by=self._order_by_field(order_option),
                    order_dir=self._order_direction(order_option),
                    limit=limit,
                    offset=offset,
                )

            levels = None
            if section == 'Products':
                product_ids = [int(item.get('ID')) for item in items if item.get('ID') is not None]
                if hasattr(database, 'get_product_stock_levels_for_product_ids'):
                    try:
                        levels = database.get_product_stock_levels_for_product_ids(product_ids)
                    except Exception:
                        levels = database.get_product_stock_levels()
                else:
                    levels = database.get_product_stock_levels()

            return items, levels, {}, refresh_id

        return fetch

    def fetch_items(self, search_text=None, order_option=None, limit=None, offset=None):
        """Fetch rows for the tab; ownership-aware tabs may override."""
        if hasattr(self.database, 'get_operation_summary_items') and self.section in ('Sales', 'Imports'):
            try:
                return self.database.get_operation_summary_items(
                    self.section,
                    search_text=search_text,
                    search_columns=self.get_searchable_fields(),
                    order_by=self._order_by_field(order_option),
                    order_dir=self._order_direction(order_option),
                    limit=limit,
                    offset=offset,
                )
            except TypeError:
                pass
        if hasattr(self.database, 'get_items'):
            try:
                return self.database.get_items(
                    self.section,
                    search_text=search_text,
                    search_columns=self.get_searchable_fields(),
                    order_by=self._order_by_field(order_option),
                    order_dir=self._order_direction(order_option),
                    limit=limit,
                    offset=offset,
                )
            except TypeError:
                return self.database.get_items(self.section)
        return []
    
    def refresh_on_tab_switch(self):
        """Load lazily and avoid repeating blocking network refreshes."""
        try:
            if self.database and hasattr(self.database, 'conn') and self.database.conn:
                stale = time.monotonic() - self._last_refresh_at >= 30.0
                if not self._loaded_once or self._needs_refresh or stale:
                    self.refresh_table()
                    print(f"✓ Refreshed {self.section} tab data")
        except Exception as e:
            print(f"Error refreshing {self.section} tab on switch: {e}")

    def mark_dirty(self):
        """Request one refresh the next time this tab becomes visible."""
        self._needs_refresh = True

    def on_page_size_changed(self, value):
        try:
            self.page_size = int(value)
        except (ValueError, TypeError):
            self.page_size = 100
        self.current_page = 0
        self.refresh_table()

    def go_to_previous_page(self):
        if self.current_page <= 0:
            return
        self.current_page -= 1
        self.refresh_table()

    def go_to_next_page(self):
        if not self._has_more_rows:
            return
        self.current_page += 1
        self.refresh_table()

    def _update_paging_controls(self):
        self.page_label.setText(f"Page {self.current_page + 1}")
        self.prev_page_btn.setEnabled(self.current_page > 0)
        self.next_page_btn.setEnabled(self._has_more_rows)

    def _order_by_field(self, order_option):
        if not order_option or order_option == "Default":
            return None
        if " ↑" in order_option:
            return order_option.replace(" ↑", "").lower().replace(" ", "_")
        if " ↓" in order_option:
            return order_option.replace(" ↓", "").lower().replace(" ", "_")
        return order_option.lower().replace(" ", "_")

    def _order_direction(self, order_option):
        if not order_option or order_option == "Default":
            return 'asc'
        return 'desc' if " ↓" in order_option else 'asc'

    def filter_table(self):
        """Refresh the current page when the user changes search or order."""
        self.current_page = 0
        self.refresh_table()
    
    def set_table_cell(self, row, col, column_key, obj):
        """Set table cell value based on parameter type"""
        try:
            value = obj.get_value(column_key)
            param_info = obj.parameters.get(column_key, {})
            param_type = param_info.get('type', 'string')
            
            if param_type == 'image' or 'image' in column_key or 'preview' in column_key:
                # Create preview widget for image with fixed size
                category = self.get_preview_category()
                preview_widget = PreviewWidget(60, category)
                if value:
                    preview_widget.set_image_path(value)
                
                # Create a container widget to center the preview
                container = QWidget()
                container_layout = QHBoxLayout(container)
                container_layout.setContentsMargins(0, 0, 0, 0)
                container_layout.addStretch()
                container_layout.addWidget(preview_widget)
                container_layout.addStretch()
                
                self.table.setCellWidget(row, col, container)
            
            elif param_type == 'date':
                # Format date as day-month-year
                formatted_value = self.format_date_for_display(value)
                
                item = QTableWidgetItem(formatted_value)
                item.setData(Qt.UserRole, value)  # Store raw value
                item.setData(Qt.UserRole + 1, obj.id)  # Store object ID
                
                # Make read-only cells non-editable
                if not self.is_column_editable(column_key):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                
                self.table.setItem(row, col, item)
            
            elif param_type == 'float':
                # Format float values with unit if available
                unit = param_info.get('unit', '')
                if value is not None:
                    number = f"{float(value):,.2f}".replace(",", " ")
                    formatted_value = f"{number} {unit}".strip()
                else:
                    formatted_value = f"0.00 {unit}".strip()
                
                item = QTableWidgetItem(formatted_value)
                item.setData(Qt.UserRole, value)  # Store raw value
                item.setData(Qt.UserRole + 1, obj.id)  # Store object ID
                
                # Make read-only cells non-editable
                if not self.is_column_editable(column_key):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                
                self.table.setItem(row, col, item)
            
            elif param_type == 'decimal':
                decimal_value = Decimal(str(value or 0))
                formatted_value = format(decimal_value, "f")
                if "." in formatted_value:
                    formatted_value = formatted_value.rstrip("0").rstrip(".")
                item = QTableWidgetItem(formatted_value)
                item.setData(Qt.UserRole, value)
                item.setData(Qt.UserRole + 1, obj.id)
                if not self.is_column_editable(column_key):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, col, item)

            elif param_type == 'int':
                # Format integer values
                formatted_value = str(int(value)) if value is not None else "0"
                item = QTableWidgetItem(formatted_value)
                item.setData(Qt.UserRole, value)  # Store raw value
                item.setData(Qt.UserRole + 1, obj.id)  # Store object ID
                
                # Make read-only cells non-editable
                if not self.is_column_editable(column_key):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                
                self.table.setItem(row, col, item)
            
            elif param_type == 'button':
                param_info = obj.parameters.get(column_key, {})
                btn_widget = ButtonWidget(param_info)
                obj_id = obj.id
                btn_widget.clicked.connect(lambda oid=obj_id: self.details_callback(oid))

                container = QWidget()
                container_layout = QHBoxLayout(container)
                container_layout.setContentsMargins(0, 0, 0, 0)
                container_layout.addStretch()
                container_layout.addWidget(btn_widget)
                container_layout.addStretch()

                self.table.setCellWidget(row, col, container)

            else:
                # String and other types - handle date formatting
                if column_key == 'date' and value:
                    # Format date as dd-mm-yyyy
                    formatted_value = self.format_date_display(value)
                else:
                    formatted_value = str(value) if value is not None else ""
                
                item = QTableWidgetItem(formatted_value)
                item.setData(Qt.UserRole, value)  # Store raw value
                item.setData(Qt.UserRole + 1, obj.id)  # Store object ID
                
                # Make read-only cells non-editable
                if not self.is_column_editable(column_key):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                
                self.table.setItem(row, col, item)
        
        except Exception as e:
            print(f"Error setting cell ({row}, {col}): {e}")
            item = QTableWidgetItem("Error")
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, col, item)
    
    def format_date_for_display(self, date_value):
        """Format date value for display as day-month-year"""
        if not date_value:
            return ""
        
        try:
            # Handle different input formats
            if isinstance(date_value, str):
                # Try parsing different date formats
                date_formats = ['%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d']
                for fmt in date_formats:
                    try:
                        date_obj = datetime.strptime(date_value, fmt)
                        return date_obj.strftime('%d-%m-%Y')
                    except ValueError:
                        continue
                # If no format matches, return as is
                return str(date_value)
            elif hasattr(date_value, 'strftime'):
                # Already a date/datetime object
                return date_value.strftime('%d-%m-%Y')
            else:
                return str(date_value)
        except Exception as e:
            print(f"Error formatting date {date_value}: {e}")
            return str(date_value)
    
    def get_search_options(self):
        """Get autocomplete options for search - override in subclasses"""
        return []
    
    def setup_order_options(self):
        """Setup order dropdown options - override in subclasses"""
        # Default ordering options
        self.order_combo.addItem("Default")
    
    def get_searchable_fields(self):
        """Get fields that can be searched - override in subclasses"""
        return ['name', 'username']

    def add_additional_toolbar_buttons(self, layout):
        """Hook for subclasses to add extra toolbar buttons."""
        pass

    def details_callback(self, obj_id):
        """Called when a details button is clicked — override in subclasses."""
        pass

    def _create_details_button_cell(self, table, row, col):
        """Create details button cell"""
        button_param = {'text': '🔍', 'size': 30}
        details_btn = ButtonWidget(button_param)
        details_btn.setProperty('row', row)  # Store row for callback
        details_btn.clicked.connect(lambda: self.details_callback(row))
            
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()
        layout.addWidget(details_btn)
        layout.addStretch()
            
        table.setCellWidget(row, col, container)
    
    def parse_date_search(self, search_text):
        """Parse date search queries like 'dd-mm-yyyy' or 'dd-mm-yyyy/dd-mm-yyyy'"""
        date_patterns = [
            r'(\d{1,2}-\d{1,2}-\d{4})/(\d{1,2}-\d{1,2}-\d{4})',  # Range: dd-mm-yyyy/dd-mm-yyyy
            r'(\d{1,2}-\d{1,2}-\d{4})'  # Single: dd-mm-yyyy
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, search_text)
            if match:
                if len(match.groups()) == 2:  # Date range
                    try:
                        start_date = datetime.strptime(match.group(1), '%d-%m-%Y').date()
                        end_date = datetime.strptime(match.group(2), '%d-%m-%Y').date()
                        return ('range', start_date, end_date)
                    except ValueError:
                        pass
                else:  # Single date
                    try:
                        date_obj = datetime.strptime(match.group(1), '%d-%m-%Y').date()
                        return ('single', date_obj)
                    except ValueError:
                        pass
        
        return None
    
    def matches_search(self, obj, search_text):
        """Check if object matches search criteria - override in subclasses for specific logic"""
        if not search_text:
            return True
        
        search_lower = search_text.lower()
        searchable_fields = self.get_searchable_fields()
        
        # Check each searchable field
        for field in searchable_fields:
            try:
                value = obj.get_value(field)
                if value and search_lower in str(value).lower():
                    return True
            except:
                pass
        
        return False
    
    def sort_items(self, items, order_option):
        """Sort items based on order option - override in subclasses for specific logic"""
        if not order_option or order_option == "Default":
            return items
        
        # Parse sort option (format: "Field ↑" or "Field ↓")
        if " ↑" in order_option:
            field = order_option.replace(" ↑", "").lower().replace(" ", "_")
            reverse = False
        elif " ↓" in order_option:
            field = order_option.replace(" ↓", "").lower().replace(" ", "_")
            reverse = True
        else:
            return items
        
        try:
            # Sort based on field type
            if field in ['price', 'unit_price', 'sale_price', 'quantity', 'total', 'subtotal']:
                items.sort(key=lambda x: float(x.get_value(field) or 0), reverse=reverse)
            elif field == 'date':
                items.sort(key=lambda x: self.parse_date_for_sorting(x.get_value(field)), reverse=reverse)
            else:
                items.sort(key=lambda x: str(x.get_value(field) or "").lower(), reverse=reverse)
        except Exception as e:
            print(f"Error sorting by {field}: {e}")
        
        return items
    
    def format_date_display(self, date_value):
        """Format date for display as dd-mm-yyyy"""
        if not date_value:
            return ""
        
        try:
            # Try different input formats and convert to dd-mm-yyyy
            input_formats = ['%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d']
            
            for fmt in input_formats:
                try:
                    date_obj = datetime.strptime(str(date_value), fmt)
                    return date_obj.strftime('%d-%m-%Y')
                except ValueError:
                    continue
            
            # If no format matches, return as-is
            return str(date_value)
        except:
            return str(date_value)
    
    def parse_date_for_sorting(self, date_value):
        """Parse date value for sorting"""
        if not date_value:
            return datetime.min
        
        try:
            # Try different date formats
            formats = ['%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y']
            for fmt in formats:
                try:
                    return datetime.strptime(str(date_value), fmt)
                except ValueError:
                    continue
            return datetime.min
        except:
            return datetime.min
    
    def filter_table(self):
        """Filter and sort table based on search and order criteria"""
        if not self.all_items:
            self.filtered_items = []
            self.populate_table_with_items([])
            return
        
        search_text = self.search_bar.text().strip()
        order_option = self.order_combo.currentText()
        
        # Filter items
        filtered = [item for item in self.all_items if self.matches_search(item, search_text)]
        
        # Sort items
        filtered = self.sort_items(filtered, order_option)

        # Show newest matches first when search is active
        if search_text:
            filtered = list(reversed(filtered))
        self.filtered_items = filtered
        self.populate_table_with_items(filtered)
    
    def populate_table_with_items(self, items):
        """Populate table with given items"""
        sorting_enabled = self.table.isSortingEnabled()
        signals_blocked = self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        try:
            self.table.setRowCount(len(items))
            for row, obj in enumerate(items):
                try:
                    for col, column_key in enumerate(self.table_columns):
                        self.set_table_cell(row, col, column_key, obj)
                except Exception:
                    logger.exception(
                        "Failed rendering section=%s row=%d", self.section, row
                    )
                    for col, column_key in enumerate(self.table_columns):
                        try:
                            value = obj.get_value(column_key) if hasattr(obj, 'get_value') else ""
                            item = QTableWidgetItem(str(value))
                            item.setData(Qt.UserRole, value)
                            item.setData(Qt.UserRole + 1, obj.id if hasattr(obj, 'id') else 0)
                            self.table.setItem(row, col, item)
                        except Exception:
                            logger.exception(
                                "Failed fallback cell section=%s row=%d column=%s",
                                self.section, row, column_key,
                            )
                            self.table.setItem(row, col, QTableWidgetItem("Error"))
            # Content measurement is disproportionately expensive on very
            # large tables; those use the configured 70px default row height.
            if len(items) <= 300:
                self.table.resizeRowsToContents()
        finally:
            self.table.setSortingEnabled(sorting_enabled)
            self.table.blockSignals(signals_blocked)
            self.table.setUpdatesEnabled(True)
            self.table.viewport().update()
    
    def get_preview_category(self):
        """Override in subclasses to specify preview category"""
        return "individual"  # Default category
    
    def update_cell_in_database(self, row, col, new_value):
        """Update database when cell is edited"""
        try:
            # Get object ID - enhanced for better reliability
            obj_id = self.get_object_id_from_row(row)
            if not obj_id:
                return
            
            column_key = self.table_columns[col]
            
            # Update database
            data = {column_key: new_value}
            if self.database.update_item(obj_id, data, self.section):
                print(f"Updated {column_key} to '{new_value}' for {self.section} {obj_id}")
                # Refresh only the specific row to show calculated field updates
                self.refresh_table()
            else:
                QMessageBox.warning(self, "Error", f"Failed to update {column_key}")
                # Revert the change
                self.refresh_table()
        
        except PermissionDeniedError:
            QMessageBox.information(
                self, "Read-Only Access",
                f"You don't have permission to edit {self.section.lower()}."
            )
            self.refresh_table()
        except Exception as e:
            print(f"Error updating cell in database: {e}")
            QMessageBox.critical(self, "Error", f"Database update failed: {e}")
            self.refresh_table()
    
    def get_object_id_from_row(self, row):
        """Get object ID from any cell in the row - enhanced method"""
        # Try to get ID from stored UserRole data
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item:
                obj_id = item.data(Qt.UserRole + 1)
                if obj_id and obj_id > 0:
                    return int(obj_id)
        
        # Fallback: try to find ID column
        if 'id' in self.table_columns:
            id_col = self.table_columns.index('id')
            item = self.table.item(row, id_col)
            if item:
                try:
                    return int(item.text())
                except ValueError:
                    pass
        
        # Last resort: try first column if it looks like an ID
        first_item = self.table.item(row, 0)
        if first_item and first_item.text().isdigit():
            return int(first_item.text())
        
        return None
    
    def get_selected_id(self):
        """Get ID of selected item"""
        row = self.table.currentRow()
        if row == -1:
            return None
        
        return self.get_object_id_from_row(row)
    
    def add_item(self):
        """Add new item"""
        if self._dialog_open:
            return
        if not self.can_write:
            QMessageBox.information(
                self, "Read-Only Access",
                f"You don't have permission to add {self.section.lower()}."
            )
            return

        self._dialog_open = True
        self.add_btn.setEnabled(False)
        try:
            dialog = self.dialog_class(None, self.database, self.parent_widget)
            if dialog.exec():
                self.refresh_table()
        
        except ImportError as e:
            QMessageBox.warning(self, "Error", f"Could not import dialog: {e}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to add {self.section[:-1].lower()}: {e}")
        finally:
            self._dialog_open = False
            self.add_btn.setEnabled(self.can_write)
    
    def edit_item(self):
        """Edit selected item"""
        if self._dialog_open:
            return
        if not self.can_write:
            QMessageBox.information(
                self, "Read-Only Access",
                f"You don't have permission to edit {self.section.lower()}."
            )
            return

        obj_id = self.get_selected_id()
        if obj_id is None:
            QMessageBox.warning(self, "Error", f"Please select a {self.section[:-1].lower()} to edit")
            return
        
        self._dialog_open = True
        self.edit_btn.setEnabled(False)
        try:
            dialog = self.dialog_class(obj_id, self.database, self.parent_widget)
            if dialog.exec():
                self.refresh_table()
        
        except ImportError as e:
            QMessageBox.warning(self, "Error", f"Could not import dialog: {e}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to edit {self.section[:-1].lower()}: {e}")
        finally:
            self._dialog_open = False
            self.edit_btn.setEnabled(self.can_write)
    
    def delete_item(self):
        """Delete selected item"""
        if not self.can_delete:
            QMessageBox.information(
                self, "Read-Only Access",
                f"You don't have permission to delete {self.section.lower()}."
            )
            return

        obj_id = self.get_selected_id()
        if obj_id is None:
            QMessageBox.warning(self, "Error", f"Please select a {self.section[:-1].lower()} to delete")
            return
        
        # Get item name for confirmation
        row = self.table.currentRow()
        name_col = None
        
        # Find name column
        for i, column_key in enumerate(self.table_columns):
            if column_key == 'name':
                name_col = i
                break
        
        item_name = f"ID {obj_id}"
        if name_col is not None:
            name_item = self.table.item(row, name_col)
            if name_item:
                item_name = name_item.text() or f"ID {obj_id}"
        
        reply = QMessageBox.question(
            self, "Confirm Deletion", 
            f"Are you sure you want to delete '{item_name}'?\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                if self.database.delete_item(obj_id, self.section):
                    # Force refresh table to show updated data
                    self.refresh_table()
                    print(f"✓ Deleted {self.section[:-1].lower()} '{item_name}' and refreshed table")
                else:
                    QMessageBox.critical(self, "Error", f"Failed to delete '{item_name}'")  
            except Exception as e:
                print(f"Error deleting {self.section[:-1].lower()}: {e}")
                QMessageBox.critical(self, "Error", f"Error deleting {self.section[:-1].lower()}: {e}")
    
    def apply_theme(self):
        """Apply dark theme styling with blue selection border"""
        self.setStyleSheet("""
            QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLabel {
                color: #E0E0E0;
            }
            QComboBox {
                background-color: #2D2D30;
                color: #E0E0E0;
                border: 1px solid #3E3E42;
                padding: 5px;
                border-radius: 3px;
                font-size: 16px; /* larger order selector font */
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                border: none;
                width: 10px;
                height: 10px;
            }
            QComboBox QAbstractItemView {
                background-color: #2D2D30;
                color: #E0E0E0;
                selection-background-color: #2196F3;
                font-size: 16px; /* larger dropdown items */
            }
            QLineEdit {
                background-color: #2D2D30;
                color: #E0E0E0;
                border: 1px solid #3E3E42;
                padding: 5px;
                border-radius: 3px;
                font-size: 16px; /* larger search bar font */
            }
            QLineEdit:focus {
                border: 2px solid #2196F3;
            }
            QTableWidget {
                background-color: #2D2D30;
                gridline-color: #3E3E42;
                color: #E0E0E0;
                border: 1px solid #3E3E42;
                alternate-background-color: #252526;
                selection-background-color: transparent;
                font-size: 16px; /* larger cell font */
            }
            QTableWidget::item:selected {
                background-color: #2D2D30;
                border: 2px solid #2196F3;
            }
            QTableWidget::item:focus {
                border: 2px solid #2196F3;
                background-color: #2D2D30;
            }
            QHeaderView::section {
                background-color: #252526;
                color: #CCCCCC;
                padding: 5px;
                border: none;
                font-size: 16px; /* larger header font */
            }
        """)
