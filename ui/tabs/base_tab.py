"""
Base Tab Class - Enhanced to better support operations
Unified table experience for all entities (Products, Clients, Suppliers, Sales, Imports)
"""
import shiboken6
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
from core.memory_utils import process_memory_mb
from core.session_cache import SessionCache, DEFAULT_STALE_SECONDS
from core.cache_policies import ENABLE_SQLITE_CACHE
from core import diagnostics
from datetime import datetime
from decimal import Decimal
import re
import threading
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
        is_success = False
        error_msg = ""
        items = levels = metrics = refresh_id = None
        try:
            if QThread.currentThread().isInterruptionRequested():
                error_msg = "Cancelled before fetch"
                return
                
            with diagnostics.operation("table_fetch", section=getattr(self, '_section', '')):
                result = self.fetcher()
                
                if QThread.currentThread().isInterruptionRequested():
                    error_msg = "Cancelled after fetch"
                    return
                
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
                is_success = True
        except Exception as error:
            logger.exception("Remote table fetch failed")
            error_msg = str(error) or "Unknown error"
        finally:
            if is_success:
                self.finished.emit(items, levels, metrics, started, refresh_id)
            else:
                self.failed.emit(error_msg, started)


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
        self._request_count = 0
        self._refresh_thread = None
        self._refresh_worker = None
        self._refresh_pending = False
        self._in_flight_key = None

        self.page_size = 100
        self.current_page = 0
        self._has_more_rows = False
        self._after_id = None
        self._after_sort = None
        self._appending = False

        # Session RAM cache of raw record dicts keyed by (search, order).
        # Serves tab switches instantly and refreshes stale views in the
        # background, so identical database/network requests are not repeated.
        self._cache = SessionCache()
        self._cache_hits = 0

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
        # A manual Refresh always re-fetches from the source (never serves the
        # session cache), and passes an explicit True instead of letting the
        # button's `checked` argument leak into the force flag.
        self.refresh_btn.clicked.connect(lambda _checked=False: self.refresh_table(force=True))
        controls_layout.addWidget(self.refresh_btn)

        self.load_more_btn = BlueButton("Load more")
        self.load_more_btn.setMinimumHeight(20)
        self.load_more_btn.setToolTip("Scroll to the bottom of the table to load more rows automatically")
        self.load_more_btn.clicked.connect(self.load_more_rows)
        self.load_more_btn.setVisible(False)
        controls_layout.addWidget(self.load_more_btn)

        self.add_additional_toolbar_buttons(controls_layout)
        
        layout.addLayout(controls_layout)

        # Offline/stale banner: shown (non-blocking) when the host cannot be
        # reached so the user knows the rows on screen are cached display data.
        self._offline_banner = QLabel(
            "Offline - showing cached data. The host could not be reached; "
            "changes made elsewhere may not be visible yet."
        )
        self._offline_banner.setStyleSheet(
            "QLabel { background-color: #b22222; color: white; "
            "padding: 6px; border-radius: 4px; font-weight: bold; }"
        )
        self._offline_banner.setWordWrap(True)
        self._offline_banner.setVisible(False)
        layout.addWidget(self._offline_banner)
        
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

        # Infinite scroll: when the user reaches the bottom, append the next
        # keyset batch instead of showing a "Next" button.
        self.table.verticalScrollBar().valueChanged.connect(
            self._maybe_load_more_on_scroll
        )

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
    
    def _cache_key(self):
        """Key identifying the current search+sort view; subclasses (e.g.
        ReportsTab with extra filter widgets) may override to widen it."""
        return (self.search_bar.text().strip(), self.order_combo.currentText())

    def _log_tab_request(self, source, key, rows=0, **extra):
        """Emit one structured line per data request a tab makes, for the
        regression investigation. Records which source served the request
        (ram / disk / network / offline / coalesced), the generation id,
        whether a fetch was already in flight, the thread it ran on, how many
        refreshes preceded it, and the current process RAM footprint."""
        self._request_count += 1
        logger.info(
            "tab_request section=%s request_id=%d source=%s key=%s rows=%d "
            "thread=%s gen=%d in_flight=%s refresh_calls=%d memory_mb=%.1f extra=%s",
            self.section, self._request_count, source, key, rows,
            threading.current_thread().name,
            self._refresh_id,
            bool(self._refreshing),
            self._request_count,
            process_memory_mb(),
            extra,
        )

    def refresh_table(self, force=False):
        """Load the first batch of rows (full reset of filters, sort, cursor).

        Rendering order, cheapest first, without ever blocking the UI:
        1. the in-memory session cache (instant), then
        2. the on-disk SQLite cache (remote clients render their last-fetched
           rows immediately on launch instead of waiting on the network), then
        3. a background fetch from the source (host PG or local PG).

        When the exact current view is already cached and ``force`` is False,
        the table renders from it and a background refresh is only started
        when the cached view is stale - identical requests are never repeated.
        Mutation sites pass ``force=True`` so the source of truth is always
        re-fetched.
        """
        if not self.database:
            QMessageBox.warning(self, "Error", "No database connection")
            return

        key = self._cache_key()
        if self._refreshing:
            # At most one request is ever in flight per tab. When an identical
            # non-forced view is already being fetched, the in-flight request
            # covers this activation - drop the duplicate so one activation
            # produces exactly one request.
            if self._appending:
                return
            if key == self._in_flight_key and not force:
                self._log_tab_request('coalesced', key, rows=0, reason='duplicate_view_in_flight')
                return
            # A newer/different view supersedes the in-flight fetch: bump the
            # generation id so its result is rejected as stale when it returns,
            # and re-issue the newest view once the current request unwinds.
            self._refresh_id += 1
            self._refresh_pending = True
            self._in_flight_key = key
            self._log_tab_request('coalesced', key, rows=0, reason='superseded_in_flight')
            return

        use_cache = not (force or self._needs_refresh)
        offline = bool(getattr(self.database, 'offline', False))
        entry = self._cache.get(key) if use_cache else None
        if entry is not None and entry.records:
            self._log_tab_request('ram', key, rows=len(entry.records))
            self._render_from_cache(entry, key)
            if entry.is_stale() and not offline:
                self._log_tab_request('ram_refresh', key, rows=len(entry.records))
                self._start_full_refresh(preserve_table=True)
            return

        if use_cache and self._try_render_from_disk(key):
            return

        if offline:
            self._log_tab_request('offline', key)
            # Host is known unreachable: never fire a refresh that will hang on
            # the network - keep whatever the cache holds and flag the rows as
            # possibly stale instead.
            self._set_offline_banner(True)
            return

        self._log_tab_request('network', key, rows=0)
        self._start_full_refresh()

    def _start_full_refresh(self, preserve_table=False):
        """Reset paging state and fetch the first batch in the background.

        The currently rendered rows are always kept on screen until the fresh
        batch arrives: a failed fetch must never blank the table, and the new
        rows either patch the existing ones in place (same record ids) or
        fully replace them via re-render. The old code cleared the table
        here, which (a) emptied it whenever the fetch failed and (b) left
        ``_apply_refresh_results`` reconciling in place against rows that no
        longer existed, so a manual force-refresh on a populated tab blanked
        it. ``preserve_table`` is kept as a no-op for call-site compatibility.
        """
        self._refresh_id += 1
        refresh_id = self._refresh_id
        self._in_flight_key = self._cache_key()
        self.current_page = 0
        self._after_id = None
        self._after_sort = None
        self._has_more_rows = False
        self._appending = False

        if self.database.__class__.__name__ == "RemoteDatabase":
            self._start_remote_refresh(refresh_id)
            return

        self._start_local_refresh(refresh_id)
        return

    def _render_from_cache(self, entry, key):
        """Synchronously render a cached view without any database request."""
        cache_render_start = time.perf_counter()
        self._cache_hits += 1
        self._refresh_id += 1
        self.current_page = 0
        self._appending = False
        self._has_more_rows = entry.has_more
        self._after_id = entry.after_id
        self._after_sort = entry.after_sort

        if entry.levels is not None:
            self.database._product_stock_levels = entry.levels

        self.all_items = self._objects_from_records(entry.records)
        self.filtered_items = list(self.all_items)
        self.search_bar.update_options(self.get_search_options())
        self.table.setRowCount(0)
        render_start = time.perf_counter()
        self.populate_table_with_items(self.all_items)
        render_duration = (time.perf_counter() - render_start) * 1000

        self._loaded_once = True
        self._needs_refresh = False
        self._last_refresh_at = time.monotonic()
        self._update_paging_controls()

        logger.info(
            "session_cache_hit section=%s key=%s rows=%d render_ms=%.2f",
            self.section, key, len(self.all_items), render_duration,
        )
        print(
            f"[PERFORMANCE] {self.section} served from session cache: "
            f"{len(self.all_items)} rows in "
            f"{(time.perf_counter() - cache_render_start) * 1000:.2f} ms"
        )

    def _disk_cache(self):
        """Return this tab's on-disk SQLite cache, or None when the disk cache
        is disabled, when not a network client, or when the cache failed to
        open."""
        if not ENABLE_SQLITE_CACHE:
            return None
        database = self.database
        if database is None or database.__class__.__name__ != 'RemoteDatabase':
            return None
        cache = getattr(database, 'cache', None)
        if cache is None or not getattr(cache, 'opened', False):
            return None
        return cache

    def _invalidate_disk_views(self):
        """Drop this section's cached on-disk views after a local mutation so a
        stale snapshot is never rendered; the next refresh repopulates the
        cache from the host's authoritative data."""
        disk = self._disk_cache()
        if disk is None:
            return
        try:
            disk.invalidate_views(self.section)
        except Exception:
            logger.exception("Disk cache invalidation failed section=%s", self.section)


    def _disk_view_key(self):
        """Serialize the whole cache key (2-element BaseTab key or the wider
        subclass keys like ReportsTab's) into a single string for the disk
        views table. repr() is deterministic and unique per key tuple."""
        return repr(self._cache_key())

    def _try_render_from_disk(self, key):
        """Render the current view from the on-disk SQLite cache.

        Used on the first visit to a view (RAM cache miss) so a network client
        shows its last-fetched rows immediately instead of waiting on a full
        HTTP fetch. When the cached view is older than the staleness window a
        background refresh is started (preserving the rendered table) so the
        host's authoritative rows replace it in place. Returns True when a
        disk view was rendered, False when there was nothing to show.
        """
        disk = self._disk_cache()
        if disk is None:
            return False
        try:
            view = disk.get_view(self.section, self._disk_view_key(), '')
        except Exception:
            logger.exception("Disk cache view lookup failed section=%s", self.section)
            return False
        if view is None:
            return False
        record_ids, has_more, after_id, after_sort, stored_at = view
        if not record_ids:
            return False
        try:
            records_by_id = disk.get_records(self.section, record_ids)
        except Exception:
            logger.exception("Disk cache records read failed section=%s", self.section)
            return False
        records = [
            records_by_id.get(row_id)
            for row_id in record_ids
            if records_by_id.get(row_id) is not None
        ]
        if not records:
            return False

        self._log_tab_request('disk', key, rows=len(records))
        self._render_from_disk(key, records, has_more, after_id, after_sort, disk)
        offline = bool(getattr(self.database, 'offline', False))
        age = time.time() - stored_at
        if offline:
            # Keep showing the cached snapshot (even if stale) and tell the
            # user it may be out of date - no point hanging on the host.
            self._set_offline_banner(True)
        elif age >= DEFAULT_STALE_SECONDS:
            self._start_full_refresh(preserve_table=True)
        return True

    def _render_from_disk(self, key, records, has_more, after_id, after_sort, disk):
        """Synchronously render a disk-cached view without any network request,
        rehydrating the RAM session cache so repeated switches stay RAM-fast."""
        cache_render_start = time.perf_counter()
        self._cache_hits += 1
        self._refresh_id += 1
        self.current_page = 0
        self._appending = False
        self._has_more_rows = has_more
        self._after_id = after_id
        self._after_sort = after_sort

        if self.section == 'Products':
            levels = disk.get_stock()
            if levels:
                self.database._product_stock_levels = {
                    int(k): value for k, value in levels.items()
                }
        else:
            levels = None

        self.all_items = self._objects_from_records(records)
        self.filtered_items = list(self.all_items)
        self.search_bar.update_options(self.get_search_options())
        self.table.setRowCount(0)
        render_start = time.perf_counter()
        self.populate_table_with_items(self.all_items)
        render_duration = (time.perf_counter() - render_start) * 1000

        # Rehydrate the RAM layer so the view stays instant after this first
        # disk read; the background refresh will refresh both layers in step.
        self._cache.set_first_batch(
            key, list(records), levels, has_more, after_id, after_sort,
        )

        self._loaded_once = True
        self._needs_refresh = False
        self._last_refresh_at = time.monotonic()
        self._update_paging_controls()

        logger.info(
            "session_cache_disk_hit section=%s key=%s rows=%d render_ms=%.2f",
            self.section, key, len(self.all_items), render_duration,
        )
        print(
            f"[PERFORMANCE] {self.section} served from disk cache: "
            f"{len(self.all_items)} rows in "
            f"{(time.perf_counter() - cache_render_start) * 1000:.2f} ms"
        )

    def _maybe_load_more_on_scroll(self, value):
        """Trigger a keyset append when the scrollbar nears the bottom."""
        scrollbar = self.table.verticalScrollBar()
        if self._appending or self._refreshing or not self._has_more_rows:
            return
        if value >= scrollbar.maximum() - 150:
            self.load_more_rows()

    def load_more_rows(self):
        """Append the next keyset batch to the already-loaded rows."""
        if self._refreshing or self._appending:
            return
        if not self._has_more_rows or self._after_id is None:
            return
        if not self.database:
            return

        self._refresh_id += 1
        refresh_id = self._refresh_id
        self._appending = True

        if self.database.__class__.__name__ == "RemoteDatabase":
            self._start_remote_refresh(refresh_id, appending=True)
            return

        self._start_local_refresh(refresh_id, appending=True)

    def _create_worker_database(self):
        """Create an independent database connection for background refreshes."""
        if self.database is None:
            return None
        if self.database.__class__.__name__ == 'RemoteDatabase':
            return self.database

        from core.database import Database
        worker_db = Database(self.database.profile_manager)
        worker_db.language = getattr(self.database, 'language', 'en')
        worker_db.registered_classes = self.database.registered_classes
        # DO NOT connect synchronously on the GUI thread.
        # Connection will be established inside the worker's fetch() closure.
        # Skip schema verification for worker connections to avoid repeated DDL.
        return worker_db

    def _start_remote_refresh(self, refresh_id, appending=False):
        """Fetch data on a worker thread; all Qt updates remain on the main thread."""
        self._refreshing = True
        self.refresh_btn.setEnabled(False)
        fetcher = self.background_fetcher(refresh_id)
        self._start_refresh(fetcher, refresh_id, mode='client')

    def _start_local_refresh(self, refresh_id, appending=False):
        """Fetch data on a worker thread using a dedicated local database connection."""
        self._refreshing = True
        self.refresh_btn.setEnabled(False)
        try:
            worker_db = self._create_worker_database()
        except Exception as error:
            self._refreshing = False
            self._appending = False
            self.refresh_btn.setEnabled(True)
            logger.exception("Failed to create worker database for section=%s", self.section)
            QMessageBox.critical(
                self, "Error", f"Cannot start local background refresh: {error}"
            )
            return
        fetcher = self.background_fetcher(refresh_id, database=worker_db)
        self._start_refresh(fetcher, refresh_id, worker_db=worker_db, mode='local')

    def _start_refresh(self, fetcher, refresh_id, worker_db=None, mode='local'):
        existing_thread = getattr(self, "_refresh_thread", None)
        is_running = False
        if existing_thread is not None:
            try:
                if shiboken6.isValid(existing_thread) and existing_thread.isRunning():
                    is_running = True
            except RuntimeError:
                pass
                
        if is_running:
            logger.warning("Duplicate refresh requested while thread is active. Ignoring.")
            if worker_db is not None:
                worker_db.close()
            return
            
        thread = QThread(QApplication.instance())
        thread.setObjectName(f"{self.section}-table-refresh")
        worker = _RemoteTableFetchWorker(fetcher)
        worker._section = self.section
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._remote_refresh_finished)
        worker.failed.connect(self._remote_refresh_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_refresh_thread_finished)
        thread.finished.connect(
            lambda: diagnostics.worker_cleanup("table_fetch", self.section, refresh_id)
        )
        if worker_db is not None:
            thread.finished.connect(lambda: worker_db.close())
        self._refresh_thread = thread
        self._refresh_worker = worker
        self._refresh_mode = mode
        diagnostics.worker_started("table_fetch", self.section, refresh_id)
        thread.start()

    def _objects_from_records(self, items_data):
        """Build object-class instances from raw record dicts (shared by the
        background fetch path and the session-cache render path)."""
        new_objects = []
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
                new_objects.append(obj)
            except Exception:
                logger.exception(
                    "Failed processing section=%s id=%s",
                    self.section, item_data.get("ID"),
                )
        return new_objects

    def _apply_refresh_results(self, items_data, levels, metrics, started, refresh_id):
        if refresh_id != self._refresh_id:
            logger.info(
                "tab_result section=%s gen=%s accepted=no reason=stale_refresh_id "
                "current_gen=%s rows=%d",
                self.section, refresh_id, self._refresh_id, len(items_data or []),
            )
            return

        network_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "tab_result section=%s gen=%s accepted=yes reason=fresh "
            "network_ms=%.1f rows=%d in_flight_before=%s",
            self.section, refresh_id, network_ms, len(items_data or []),
            bool(self._refreshing),
        )

        appending = self._appending
        metrics = metrics or {}
        has_more = len(items_data) > self.page_size
        items_data = items_data if not has_more else items_data[:self.page_size]

        if levels is not None:
            self.database._product_stock_levels = {
                int(key): value for key, value in levels.items()
            }

        object_prep_start = time.perf_counter()
        new_objects = self._objects_from_records(items_data)
        object_prep_duration = (time.perf_counter() - object_prep_start) * 1000

        # Reconcile by record ID: when the freshly fetched set has the same
        # rows in the same order as what is already on screen (the common
        # background refresh case), update the changed cells in place so the
        # table is never cleared and selection/scroll survive untouched.
        # Otherwise fall back to a full re-render with selection and scroll
        # position restored afterwards.
        previous_selection = self.get_selected_id()
        previous_scroll = self.table.verticalScrollBar().value()

        render_duration = 0.0
        if appending:
            self.all_items.extend(new_objects)
            self.current_page += 1
        else:
            previous_all = self.all_items
            self.all_items = new_objects
            self.current_page = 0
            render_start = time.perf_counter()
            if previous_all and self._reconcile_in_place(previous_all, new_objects):
                pass
            else:
                self.populate_table_with_items(self.all_items)
                self._restore_selection_and_scroll(previous_selection, previous_scroll)
            render_duration = (time.perf_counter() - render_start) * 1000

        # Advance the keyset cursor to the last row that was actually shown.
        cursor = metrics.get('after_id')
        if cursor is not None:
            self._after_id = cursor
            self._after_sort = metrics.get('after_sort')
        self._has_more_rows = has_more and len(new_objects) == self.page_size

        # Keep the session cache in step with what the user has loaded.
        cache_key = self._cache_key()
        if appending:
            self._cache.append_batch(
                cache_key, list(items_data), levels, self._has_more_rows,
                self._after_id, self._after_sort,
            )
        else:
            self._cache.set_first_batch(
                cache_key, list(items_data), levels, self._has_more_rows,
                self._after_id, self._after_sort,
            )

        # Mirror the successful fetch into the on-disk SQLite cache so the
        # next launch (or tab open after the RAM entry is evicted) renders
        # from disk instead of the network.
        self._store_batch_to_disk(items_data, levels)

        metrics['object_prep_ms'] = object_prep_duration

        self.search_bar.update_options(self.get_search_options())
        self.filtered_items = list(self.all_items)
        if appending and len(new_objects):
            render_start = time.perf_counter()
            self.populate_table_with_items(new_objects, append=True)
            render_duration = (time.perf_counter() - render_start) * 1000
        metrics['render_ms'] = render_duration

        self._loaded_once = True
        self._needs_refresh = False
        self._last_refresh_at = time.monotonic()
        self._update_paging_controls()
        self._set_offline_banner(False)

        metrics['rows'] = len(self.all_items)
        metrics['memory_mb'] = process_memory_mb()
        logger.info(
            "refresh_metrics section=%s refresh_id=%s rows=%d metrics=%s",
            self.section, refresh_id, len(self.all_items), metrics,
        )
        logger.info(
            "tab_batch section=%s refresh_id=%s batch=%d appending=%s "
            "more=%s memory_mb=%s",
            self.section, refresh_id, self.current_page + 1, appending,
            self._has_more_rows, metrics['memory_mb'],
        )

    def _store_batch_to_disk(self, items_data, levels):
        """Mirror the just-fetched batch into the on-disk SQLite cache: the raw
        wire records (payloads exactly as the host returned them, including
        Decimal-to-string totals), the view's ordered id list with its keyset
        cursor, and product stock levels. Runs on the UI thread but only
        touches a handful of local rows, so it stays non-blocking."""
        disk = self._disk_cache()
        if disk is None:
            return
        try:
            disk.store_records(self.section, items_data)
        except Exception:
            logger.exception("Disk cache records write failed section=%s", self.section)
        try:
            record_ids = []
            for obj in self.all_items:
                obj_id = getattr(obj, 'id', None)
                if obj_id:
                    record_ids.append(int(obj_id))
            if record_ids:
                disk.store_view(
                    self.section, self._disk_view_key(), '', record_ids,
                    has_more=self._has_more_rows,
                    after_id=self._after_id,
                    after_sort=self._after_sort,
                )
        except Exception:
            logger.exception("Disk cache view write failed section=%s", self.section)
        if levels is not None:
            try:
                disk.store_stock(levels)
            except Exception:
                logger.exception("Disk cache stock write failed section=%s", self.section)

    def _reconcile_in_place(self, previous_objects, new_objects):
        """Rewrite the on-screen rows in place when the freshly fetched set
        matches the previously displayed set in the same order (a refresh
        where no record was inserted or deleted). Returns True when rows were
        patched in place, False when the caller must do a full re-render."""
        if not new_objects:
            return False
        if self.table.rowCount() == 0:
            # Nothing is rendered (e.g. the table was cleared elsewhere): rows
            # cannot be patched in place, the caller must do a full re-render.
            return False
        current_ids = [getattr(obj, 'id', None) for obj in previous_objects]
        new_ids = [getattr(obj, 'id', None) for obj in new_objects]
        if current_ids != new_ids:
            return False
        self.all_items = list(new_objects)
        for row, obj in enumerate(new_objects):
            self._rewrite_row(row, obj)
        return True

    def _rewrite_row(self, row, obj):
        """Replace every cell of ``row`` from ``obj`` without touching the row
        count, so the row index, selection and scroll position survive."""
        for col in range(self.table.columnCount()):
            self.table.setCellWidget(row, col, None)
        for col, column_key in enumerate(self.table_columns):
            try:
                self.set_table_cell(row, col, column_key, obj)
            except Exception:
                logger.exception(
                    "Failed in-place cell section=%s row=%d column=%s",
                    self.section, row, column_key,
                )
                self.table.setItem(row, col, QTableWidgetItem("Error"))
        self.table.resizeRowToContents(row)

    def _restore_selection_and_scroll(self, selected_id, scroll_value):
        """Re-apply the scroll offset and re-select the row whose record id
        matches the previously selected one after a full re-render."""
        if scroll_value is not None:
            scrollbar = self.table.verticalScrollBar()
            scrollbar.setValue(min(int(scroll_value), scrollbar.maximum()))
        if selected_id:
            for row in range(self.table.rowCount()):
                if self.get_object_id_from_row(row) == selected_id:
                    self.table.selectRow(row)
                    self.table.setCurrentCell(row, 0)
                    break

    def _set_offline_banner(self, visible):
        """Show/hide the non-blocking "offline - showing cached data" banner."""
        if hasattr(self, '_offline_banner'):
            self._offline_banner.setVisible(visible)

    @Slot(object, object, object, float, int)
    def _remote_refresh_finished(self, items_data, levels, metrics, started, refresh_id):
        success = False
        try:
            self._apply_refresh_results(items_data, levels, metrics, started, refresh_id)
            success = True
        except Exception as error:
            logger.exception("Failed applying section=%s", self.section)
            QMessageBox.critical(
                self, "Error", f"Failed to refresh {self.section}: {error}"
            )
        finally:
            diagnostics.worker_finished("table_fetch", self.section, refresh_id)
            self._finish_refresh(
                started,
                mode=getattr(self, '_refresh_mode', 'client'),
                success=success,
            )

    @Slot(str, float)
    def _remote_refresh_failed(self, error, started):
        logger.error("Remote refresh failed section=%s error=%s", self.section, error)
        # Keep whatever is already rendered (session/disk cache or the last
        # successful fetch) visible and mark the tab as showing stale data;
        # a modal box here would block the user for every failing tab.
        self._set_offline_banner(True)
        diagnostics.worker_failed("table_fetch", self.section, self._refresh_id)
        self._finish_refresh(started, mode=getattr(self, '_refresh_mode', 'client'), success=False)

    def _finish_refresh(self, started, mode='client', success=True):
        self._refreshing = False
        self._appending = False
        self._in_flight_key = None
        self.refresh_btn.setEnabled(True)
        self._update_paging_controls()
        elapsed = time.perf_counter() - started
        rows = len(self.all_items)
        if success:
            logger.log(
                logging.WARNING if elapsed >= 0.5 else logging.INFO,
                "load_%s completed in %.3f seconds rows=%d mode=%s",
                self.section.lower(), elapsed, rows, mode,
            )
            print(
                f"[PERFORMANCE] load_{self.section.lower()} batch={self.current_page + 1} "
                f"completed in {elapsed:.3f} seconds mode={mode} rows={rows}"
            )
        else:
            logger.warning(
                "load_%s failed after %.3f seconds rows=%d mode=%s",
                self.section.lower(), elapsed, rows, mode,
            )
            print(
                f"[PERFORMANCE] load_{self.section.lower()} batch={self.current_page + 1} "
                f"FAILED after {elapsed:.3f} seconds mode={mode} rows={rows}"
            )
        if self._refresh_pending:
            # A newer view was requested while this fetch was in flight; its
            # result was invalidated, so re-issue it now that no request is
            # running (single in-flight at any moment, nothing dropped).
            self._refresh_pending = False
            QTimer.singleShot(0, lambda: self.refresh_table(force=True))

    @Slot()
    def _on_refresh_thread_finished(self):
        thread = self.sender()
        if self._refresh_thread is thread:
            self._refresh_thread = None
            self._refresh_worker = None

    def _wait_for_refresh_thread(self, timeout_ms=5000):
        """Do not destroy a QThread while an in-flight HTTP call is unwinding."""
        self._cache.clear()
        thread = getattr(self, "_refresh_thread", None)
        
        if thread is None:
            return True
            
        try:
            if not shiboken6.isValid(thread) or not thread.isRunning():
                self._refresh_thread = None
                self._refresh_worker = None
                return True
                
            if thread == QThread.currentThread():
                return False
                
            thread.requestInterruption()
            thread.quit()
            
            if not thread.wait(timeout_ms):
                logger.error(
                    "Remote refresh thread did not stop section=%s timeout=%sms", 
                    self.section, timeout_ms
                )
                return False
                
            self._refresh_thread = None
            self._refresh_worker = None
            return True
            
        except RuntimeError:
            # If it's deleted during the checks, it's already finished.
            self._refresh_thread = None
            self._refresh_worker = None
            return True

    def background_fetcher(self, refresh_id=None, database=None):
        """Capture filter and keyset cursor state before the worker thread starts."""
        database = database or self.database
        section = self.section
        search_text = self.search_bar.text().strip()
        order_option = self.order_combo.currentText()
        order_by = self._order_by_field(order_option)
        order_dir = self._order_direction(order_option)
        search_columns = self.get_searchable_fields()
        limit = self.page_size + 1
        after_id = self._after_id
        after_sort = self._after_sort

        def fetch():
            # Establish connection inside the worker thread if not connected
            if getattr(database, 'profile_manager', None) and not getattr(database, 'conn', None):
                if not database.connect(verify_schema=False):
                    raise RuntimeError("Failed to connect worker database on background thread")
            
            if hasattr(database, 'get_operation_summary_items') and section in ('Sales', 'Imports'):
                items = database.get_operation_summary_items(
                    section,
                    search_text=search_text,
                    search_columns=search_columns,
                    order_by=order_by,
                    order_dir=order_dir,
                    limit=limit,
                    after_id=after_id,
                    after_sort=after_sort,
                )
                # If the optimized summary path unexpectedly returns no rows,
                # fall back to the generic get_items call so the UI still shows
                # records while we debug the root cause.
                if not items:
                    try:
                        logger.warning("Summary query returned no rows, falling back to get_items for section=%s", section)
                        items = database.get_items(
                            section,
                            search_text=search_text,
                            search_columns=search_columns,
                            order_by=order_by,
                            order_dir=order_dir,
                            limit=limit,
                            after_id=after_id,
                            after_sort=after_sort,
                        )
                    except Exception:
                        # Keep original empty result if fallback fails
                        logger.exception(
                            "get_items fallback also failed for section=%s", section
                        )
            else:
                items = database.get_items(
                    section,
                    search_text=search_text,
                    search_columns=search_columns,
                    order_by=order_by,
                    order_dir=order_dir,
                    limit=limit,
                    after_id=after_id,
                    after_sort=after_sort,
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

            metrics = self._keyset_metrics(order_by, items, limit)
            return items, levels, metrics, refresh_id

        return fetch

    def _keyset_metrics(self, order_by, items, limit):
        """Return the keyset cursor pointing after the rows that will be shown.

        The fetch pulls ``limit = page_size + 1`` rows so the UI can tell that
        more data exists; the cursor must reference the last *displayed* row
        (``page_size`` rows), not the extra probe row.
        """
        if not items:
            return {}
        page_size = limit - 1
        shown = items if len(items) <= page_size else items[:page_size]
        last = shown[-1]
        last_id = last.get('ID')
        if last_id is None:
            return {}
        sort_value = last.get(order_by) if order_by else None
        if sort_value is not None:
            sort_value = Database._keyset_sort_value(order_by, sort_value)
        return {'after_id': last_id, 'after_sort': sort_value}

    def fetch_items(self, search_text=None, order_option=None, limit=None, offset=None,
                    after_id=None, after_sort=None):
        """Fetch rows for the tab; ownership-aware tabs may override."""
        order_by = self._order_by_field(order_option)
        order_dir = self._order_direction(order_option)
        if hasattr(self.database, 'get_operation_summary_items') and self.section in ('Sales', 'Imports'):
            try:
                items = self.database.get_operation_summary_items(
                    self.section,
                    search_text=search_text,
                    search_columns=self.get_searchable_fields(),
                    order_by=order_by,
                    order_dir=order_dir,
                    limit=limit,
                    offset=offset,
                    after_id=after_id,
                    after_sort=after_sort,
                )
                if not items:
                    try:
                        logger.warning("Summary fetch empty, falling back to get_items for section=%s", self.section)
                        return self.database.get_items(
                            self.section,
                            search_text=search_text,
                            search_columns=self.get_searchable_fields(),
                            order_by=order_by,
                            order_dir=order_dir,
                            limit=limit,
                            offset=offset,
                            after_id=after_id,
                            after_sort=after_sort,
                        )
                    except Exception:
                        return items
            except TypeError:
                pass
        if hasattr(self.database, 'get_items'):
            try:
                return self.database.get_items(
                    self.section,
                    search_text=search_text,
                    search_columns=self.get_searchable_fields(),
                    order_by=order_by,
                    order_dir=order_dir,
                    limit=limit,
                    offset=offset,
                    after_id=after_id,
                    after_sort=after_sort,
                )
            except TypeError:
                return self.database.get_items(self.section)
        return []
    
    def refresh_on_tab_switch(self):
        """Load lazily and avoid repeating blocking network refreshes.

        Refreshes are non-blocking (worker thread), so this runs for local
        host connections and for network clients alike. The previous
        ``hasattr(self.database, 'conn')`` gate was only true on the host,
        which left remote Client tabs without data until a manual Refresh.

        One request per tab activation: a switch never fires a second request
        while a fetch is already in flight, and never duplicates a fetch that
        just completed (2s grace window). Any other activation forces a fresh
        load so the visible rows reflect the latest source data.
        """
        try:
            if self.database:
                if self._refreshing:
                    return
                if time.monotonic() - self._last_refresh_at < 2.0:
                    return
                if not self._loaded_once or self._needs_refresh:
                    self.refresh_table(force=True)
                    print(f"[OK] Refreshed {self.section} tab data")
        except Exception as e:
            print(f"Error refreshing {self.section} tab on switch: {e}")

    def mark_dirty(self):
        """Request one refresh the next time this tab becomes visible."""
        self._needs_refresh = True
        self._cache.clear()

    def go_to_previous_page(self):
        """Backwards-compatible no-op: pagination is now append-only via keyset."""

    def go_to_next_page(self):
        """Backwards-compatible alias for load_more_rows()."""
        self.load_more_rows()

    def _update_paging_controls(self):
        loaded = len(self.all_items)
        self.load_more_btn.setVisible(self._has_more_rows and loaded > 0)
        self.load_more_btn.setEnabled(not self._appending)

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
    
    def populate_table_with_items(self, items, append=False):
        """Populate table with given items; append renders new rows after the
        existing ones (infinite scroll) instead of replacing the table."""
        sorting_enabled = self.table.isSortingEnabled()
        signals_blocked = self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        try:
            start_row = self.table.rowCount() if append else 0
            self.table.setRowCount(start_row + len(items))
            for offset, obj in enumerate(items):
                row = start_row + offset
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
            if start_row + len(items) <= 300:
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
                self._cache.clear()
                self._invalidate_disk_views()
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
                self._cache.clear()
                self._invalidate_disk_views()
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
                self._cache.clear()
                self._invalidate_disk_views()
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
                    self._cache.clear()
                    self._invalidate_disk_views()
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
