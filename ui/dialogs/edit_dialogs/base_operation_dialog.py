"""
Base Operation Dialog - Unified dialog for operations with items (Sales, Imports)
Replaces the complex manual layout calculations with clean auto-sizing
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QMessageBox, QScrollArea, QWidget,
                               QFormLayout, QSizePolicy)
from PySide6.QtCore import Qt, QThread, QObject, Signal, Slot, QTimer
from PySide6.QtGui import QFont
from ui.widgets.themed_widgets import GreenButton, RedButton
from ui.widgets.operations_table import OperationsTableWidget
from ui.widgets.parameters_widgets import ParameterWidgetFactory
from ui.dialogs.edit_dialogs.unknown_item_review_dialog import UnknownItemReviewDialog
from datetime import datetime
from decimal import Decimal, InvalidOperation
from core.calculations import calculate_line_subtotal, calculate_operation_totals
import os
import uuid
import shiboken6
import time
import threading

_active_background_threads = set()
import logging
from core.runtime_paths import user_data_root

logger = logging.getLogger(__name__)
_save_timeline_logger = logging.getLogger("save_timeline")
# Root logger defaults to WARNING app-wide (no setLevel anywhere in this
# codebase), which would silently drop these diagnostic events - opt this
# specific logger into INFO regardless, so app.log actually captures them.
_save_timeline_logger.setLevel(logging.INFO)


def _log_save_event(event, **fields):
    """TEMPORARY Sale Save freeze diagnostic. Writes to both app.log (via the
    standard logger, for context) and the dedicated
    logs/sale_save_hang_diagnostic.log (via core.sale_save_diagnostics),
    which is the file to read when reproducing a hang. Delete once the
    freeze investigation is closed out."""
    t = threading.current_thread()
    extra = " ".join(f"{k}={v!r}" for k, v in fields.items())
    _save_timeline_logger.info(
        "%s t=%.6f thread=%s(id=%s) %s",
        event, time.perf_counter(), t.name, t.ident, extra,
    )
    from core import sale_save_diagnostics
    sale_save_diagnostics.event(event, **fields)

class SaveWorker(QObject):
    finished = Signal(object)
    error = Signal(str)
    
    def __init__(self, database, is_import, save_kwargs):
        super().__init__()
        self.database = database
        self.is_import = is_import
        self.save_kwargs = save_kwargs
        
    @Slot()
    def process(self):
        worker_db = self.database
        is_local = self.database is not None and self.database.__class__.__name__ != 'RemoteDatabase'
        token = (self.save_kwargs.get('sale_data') or self.save_kwargs.get('import_data') or {}).get('operation_token')
        _log_save_event("SAVE_WORKER_ENTER", token=token, is_local=is_local)
        try:
            if QThread.currentThread().isInterruptionRequested():
                return

            if is_local:
                from core.database import Database
                worker_db = Database(self.database.profile_manager)
                worker_db.language = getattr(self.database, 'language', 'en')
                worker_db.registered_classes = self.database.registered_classes
                if not worker_db.connect():
                    raise RuntimeError(f"Worker could not connect to database: {worker_db.last_error}")

            _log_save_event("RPC_REQUEST_START", token=token, is_import=self.is_import, is_local=is_local)
            if self.is_import:
                res = worker_db.save_import_with_items(**self.save_kwargs)
                if not isinstance(res, dict) or res.get("transaction") != "committed":
                    raise RuntimeError(f"Host returned an invalid import-save result: {res!r}")
                res['expected'] = len(self.save_kwargs.get('items', []))
            else:
                res = worker_db.save_sale_with_items(**self.save_kwargs)
                if not isinstance(res, dict) or res.get('transaction') != 'committed':
                    raise RuntimeError(f"Host returned an invalid sale-save result: {res!r}")
                res['expected'] = len(self.save_kwargs.get('items', []))
            _log_save_event("RPC_REQUEST_END", token=token, result="committed")
            self.finished.emit(res)
            _log_save_event("SAVE_SUCCESS_EMIT", token=token)
        except Exception as e:
            _log_save_event("RPC_REQUEST_END", token=token, result="error", error=str(e))
            self.error.emit(str(e))
            _log_save_event("SAVE_ERROR_EMIT", token=token, error=str(e))
        finally:
            if is_local and worker_db and worker_db != self.database:
                worker_db.close()

class LoadWorker(QObject):
    finished = Signal()
    error = Signal(str)

    def __init__(self, operation_obj, database, fetch_catalog, fetch_devis_preview=False,
                 fetch_bl_preview=False):
        super().__init__()
        self.operation_obj = operation_obj
        self.database = database
        self.fetch_catalog = fetch_catalog
        self.fetch_devis_preview = fetch_devis_preview
        self.fetch_bl_preview = fetch_bl_preview
        self.devis_preview = None
        self.bl_preview = None

    @Slot()
    def process(self):
        worker_db = self.database
        is_local = self.database is not None and self.database.__class__.__name__ != 'RemoteDatabase'
        old_db = getattr(self.operation_obj, 'database', None) if self.operation_obj else None

        try:
            if QThread.currentThread().isInterruptionRequested():
                return

            if is_local:
                from core.database import Database
                worker_db = Database(self.database.profile_manager)
                worker_db.language = getattr(self.database, 'language', 'en')
                worker_db.registered_classes = self.database.registered_classes
                if not worker_db.connect():
                    raise RuntimeError(f"Worker could not connect to database: {worker_db.last_error}")

            if self.operation_obj:
                self.operation_obj.database = worker_db
                self.operation_obj.load_database_data()

            if self.fetch_catalog and getattr(worker_db, 'get_sale_catalog', None):
                self.database.sale_catalog = worker_db.get_sale_catalog(
                    include_clients=worker_db.has_permission('Clients', 'read'),
                    include_suppliers=worker_db.has_permission('Suppliers', 'read'),
                )

            # Advisory Devis preview for a NEW sale. Off-thread so the dialog
            # never blocks on the network; the host re-validates on save.
            if self.fetch_devis_preview and getattr(worker_db, 'get_next_devis_preview', None):
                try:
                    self.devis_preview = worker_db.get_next_devis_preview()
                except Exception:
                    self.devis_preview = None

            # Advisory Bon de Livraison preview for a NEW import. Off-thread so
            # the dialog never blocks on the network; the host re-allocates and
            # validates uniqueness transactionally on save (same pattern as the
            # Devis preview).
            if self.fetch_bl_preview and getattr(worker_db, 'get_next_bl_preview', None):
                try:
                    self.bl_preview = worker_db.get_next_bl_preview()
                except Exception:
                    self.bl_preview = None
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if self.operation_obj:
                self.operation_obj.database = old_db
            if is_local and worker_db and worker_db != self.database:
                worker_db.close()



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
            self.setWindowTitle(f"Edit {self.operation_obj.section[:-1]} - ID {operation_id}")
        else:
            self.operation_obj = operation_class(0, database)
            # Set default date to today for new operations
            if 'date' in self.operation_obj.parameters:
                self.operation_obj.set_value("date", datetime.now().strftime("%Y-%m-%d"))
            self.setWindowTitle(f"New {self.operation_obj.section[:-1]}")
        
        # Setup UI
        self.setup_ui()
        self.apply_theme()
        
        self.setEnabled(False)
        self.setWindowTitle(self.windowTitle() + " (Loading...)")

        self.load_thread = QThread()
        _catalog = getattr(database, "sale_catalog", None)
        self.load_worker = LoadWorker(
            self.operation_obj if operation_id else None,
            database,
            fetch_catalog=not _catalog or "clients" not in _catalog,
            fetch_devis_preview=(not operation_id and 'devis' in self.operation_obj.parameters),
            fetch_bl_preview=(not operation_id and 'bl_number' in self.operation_obj.parameters)
        )
        self.load_worker.moveToThread(self.load_thread)
        self.load_thread.started.connect(self.load_worker.process)
        
        # Safe thread cleanup lifecycle
        self.load_worker.finished.connect(self.load_thread.quit)
        self.load_worker.finished.connect(self.load_worker.deleteLater)
        self.load_thread.finished.connect(self.load_thread.deleteLater)
        self.load_worker.error.connect(self.load_thread.quit)
        self.load_worker.error.connect(self.load_worker.deleteLater)
        
        # Business logic callbacks
        self.load_worker.finished.connect(self._on_load_finished)
        self.load_worker.error.connect(self._on_load_error)
        
        _active_background_threads.add(self.load_thread)
        self.load_thread.finished.connect(self._on_load_thread_finished)
        self.load_thread.start()
        
        # Auto-size dialog
        self.resize(900, 700)

        self.setMinimumSize(600, 500)
    def _on_load_finished(self):
        # NOTE: self.load_thread / self.load_worker are intentionally NOT
        # cleared here - see _on_save_finished. Refs are cleared in
        # _on_load_thread_finished, queued to fire only after load_thread.finished.
        _preview = self.load_worker.devis_preview if self.load_worker else None
        _preview_bl = self.load_worker.bl_preview if self.load_worker else None
        
        try:
            self.setEnabled(True)
            title = self.windowTitle().replace(" (Loading...)", "")
            self.setWindowTitle(title)
            self.load_data()
            if _preview is not None:
                self._apply_devis_preview(_preview)
            if _preview_bl is not None:
                self._apply_bl_preview(_preview_bl)
            
            if hasattr(self, 'items_table') and self.items_table:
                self.items_table.refresh_table()
        except RuntimeError:
            pass

    def _apply_devis_preview(self, preview):
        """Fill the Devis field with the host advisory preview (new Sales only)."""
        if not self.operation_obj or 'devis' not in self.operation_obj.parameters:
            return
        widget = self.parameter_widgets.get('devis')
        if widget is None:
            return
        try:
            ParameterWidgetFactory.set_widget_value(widget, preview)
        except Exception:
            pass

    def _apply_bl_preview(self, preview):
        """Fill the Bon de Livraison field with the host advisory preview
        (new Imports only). Editable, so the user can override it; the host
        re-validates uniqueness and re-allocates on save."""
        if not self.operation_obj or 'bl_number' not in self.operation_obj.parameters:
            return
        widget = self.parameter_widgets.get('bl_number')
        if widget is None:
            return
        try:
            ParameterWidgetFactory.set_widget_value(widget, preview)
        except Exception:
            pass

    def _on_load_error(self, err_msg):
        # Refs are cleared in _on_load_thread_finished (see _on_save_finished).

        try:
            QMessageBox.warning(self, "Load Error", f"Error loading data: {err_msg}")
            self.setEnabled(True)
            title = self.windowTitle().replace(" (Loading...)", "")
            self.setWindowTitle(title)
            self.load_data()
        except RuntimeError:
            pass

    def _on_load_thread_finished(self):
        """Queued (bound-method) handler for load_thread.finished. Fires only
        after the load worker's OS thread has fully stopped, so it is now safe
        to drop the last references to the thread/worker without a QThread
        being destroyed while its native thread is still running."""
        try:
            _active_background_threads.discard(self.load_thread)
        except RuntimeError:
            pass
        self.load_worker = None
        self.load_thread = None

        
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
            
            # Historical-operation flag: one labelled checkbox, no extra form
            # label. Label text is part of the product requirement.
            if param_key == 'is_historical':
                checkbox = getattr(widget, 'checkbox', None)
                if checkbox is not None:
                    section = getattr(self.operation_obj, 'section', 'Sales')
                    if section == 'Imports':
                        checkbox.setText(
                            "Historical Import \u2014 Do not affect current stock"
                        )
                    else:
                        checkbox.setText(
                            "Historical Sale \u2014 Do not affect current stock"
                        )
                form_layout.addRow(widget)
                continue

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
        
        # Remise is an editable input for Sales operations
        if getattr(self.operation_obj, 'section', '') == 'Sales':
            from PySide6.QtWidgets import QDoubleSpinBox
            self.remise_spinbox = QDoubleSpinBox()
            self.remise_spinbox.setRange(0.0, 999999999.0)
            self.remise_spinbox.setDecimals(2)
            self.remise_spinbox.setSuffix(" MAD")
            self.remise_spinbox.setMinimumHeight(30)
            self.remise_spinbox.setStyleSheet("""
                QDoubleSpinBox {
                    background-color: #2D2D2D;
                    color: white;
                    border: 1px solid #555555;
                    padding: 5px;
                }
                QDoubleSpinBox:focus {
                    border: 1px solid #4CAF50;
                }
            """)
            self.remise_spinbox.valueChanged.connect(lambda _: self.update_totals())
        else:
            self.remise_spinbox = None
        
        self.total_ht_widget = self.create_total_widget("Total HT", "MAD")
        self.vat_widget = self.create_total_widget("VAT Amount", "MAD") 
        self.total_ttc_widget = self.create_total_widget("Total TTC", "MAD")
        
        # Add to layout
        totals_layout.addWidget(QLabel("Subtotal:"))
        totals_layout.addWidget(self.subtotal_widget)
        
        if self.remise_spinbox is not None:
            totals_layout.addWidget(QLabel("Remise:"))
            totals_layout.addWidget(self.remise_spinbox)
        
        totals_layout.addWidget(QLabel("Total HT:"))
        totals_layout.addWidget(self.total_ht_widget)
        totals_layout.addWidget(QLabel("TVA:"))
        totals_layout.addWidget(self.vat_widget)
        totals_layout.addWidget(QLabel("Total TTC:"))
        totals_layout.addWidget(self.total_ttc_widget)
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
        
        # Load remise value if the spinbox exists
        if self.remise_spinbox is not None:
            remise_value = self.operation_obj.get_value('remise') or 0.0
            self.remise_spinbox.setValue(float(remise_value))
    
    def update_totals(self):
        """Update total calculation displays"""
        try:
            # Read the visible cells directly. Building model objects here used
            # to resolve every product/service against PostgreSQL whenever a
            # quantity changed, which made rapid editing feel frozen.
            rows = self.items_table.get_current_table_data()
            subtotal = sum(
                (
                    calculate_line_subtotal(
                        row.get("quantity") or 0,
                        row.get("unit_price") or 0,
                    )
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
            
            # Get Remise value
            remise = Decimal("0")
            if self.remise_spinbox is not None:
                try:
                    remise = Decimal(str(self.remise_spinbox.value() or 0))
                except (InvalidOperation, ValueError, TypeError):
                    remise = Decimal("0")
            
            # Centralized Decimal math:
            # Total HT = Subtotal - Remise, TVA = Total HT * rate,
            # Total TTC = Total HT + TVA.
            totals = calculate_operation_totals(subtotal, remise, vat_percent)
            
            # Update displays
            ParameterWidgetFactory.set_widget_value(self.subtotal_widget, totals['original_subtotal'])
            ParameterWidgetFactory.set_widget_value(self.total_ht_widget, totals['total_ht'])
            ParameterWidgetFactory.set_widget_value(self.vat_widget, totals['vat_amount'])
            ParameterWidgetFactory.set_widget_value(self.total_ttc_widget, totals['total_ttc'])
            
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
        raw_rows = []
        try:
            raw_rows = self.items_table.get_current_table_data()
            if not raw_rows:
                errors.append("Please add at least one item")
        except Exception:
            # Fallback to old behavior
            items = self.items_table.get_items_data()
            if not items:
                errors.append("Please add at least one item")

        # Validate Remise for Sales operations
        if (getattr(self.operation_obj, 'section', '') == 'Sales'
                and self.remise_spinbox is not None):
            remise = self.remise_spinbox.value()
            if remise < 0:
                errors.append("Remise cannot be negative")
            raw_subtotal = sum(
                Decimal(str(row.get("quantity") or 0))
                * Decimal(str(row.get("unit_price") or 0))
                for row in raw_rows
            )
            if remise > 0 and raw_subtotal > 0 and Decimal(str(remise)) > raw_subtotal:
                errors.append(
                    f"Remise ({remise:,.2f}) cannot exceed the subtotal ({float(raw_subtotal):,.2f})"
                )

        # Validate the Devis reference for Sales operations
        if (getattr(self.operation_obj, 'section', '') == 'Sales'
                and 'devis' in self.operation_obj.parameters):
            devis_widget = self.parameter_widgets.get('devis')
            raw_devis = ParameterWidgetFactory.get_widget_value(devis_widget) if devis_widget else None
            if raw_devis is not None:
                devis_value = str(raw_devis).strip()
                if devis_value:
                    if len(devis_value) > 40:
                        errors.append("Devis N° must be at most 40 characters")
        
        return errors
    
    def save_changes(self):
        """Prevent double-clicks from starting the same transaction twice."""
        _log_save_event("SAVE_CLICK", token=self.operation_token, operation_id=self.operation_id)
        if self._saving:
            return
        self._saving = True
        self.save_btn.setEnabled(False)
        self.save_btn.setText("Saving...")
        try:
            self._save_changes_impl()
        finally:
            if self.result() == QDialog.Rejected and not (hasattr(self, 'save_thread') and self.save_thread):
                self._saving = False
                if getattr(self, 'save_btn', None):
                    self.save_btn.setEnabled(True)
                    self.save_btn.setText("Save")

    def _save_changes_impl(self):
        """Save operation and items to database (simple, reliable)"""
        # Validate first
        _log_save_event("GUI_VALIDATION_START", token=self.operation_token)
        errors = self.validate_data()
        if errors:
            _log_save_event("GUI_VALIDATION_END", token=self.operation_token, result="errors")
            QMessageBox.warning(self, "Validation Error", "\n".join(errors))
            return

        # Check for missing related entities (client/supplier, products) and offer creation
        proceed, allow_unresolved = self._handle_missing_references()
        _log_save_event(
            "GUI_VALIDATION_END", token=self.operation_token,
            result="ok" if proceed else "cancelled",
        )
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
            
            # Set remise value from spinbox if it exists
            if getattr(self, 'remise_spinbox', None) is not None:
                self.operation_obj.set_value('remise', float(self.remise_spinbox.value()))
            
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
            if self.operation_obj.section in ('Sales', 'Imports'):
                is_import = (self.operation_obj.section == 'Imports')
                
                if not is_import:
                    items_objects = self.items_table.get_items_data()
                    is_historical = bool(self.operation_obj.get_value('is_historical'))
                    sale_state = self.operation_obj.get_value('state') or 'pending'
                    if not is_historical and sale_state != 'on_hold':
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
                    if not self._confirm_sale_summary():
                        return
                        
                # BUILD PAYLOAD ON GUI THREAD
                _log_save_event("PAYLOAD_BUILD_START", token=self.operation_token)
                raw_items = self.items_table.get_current_table_data()
                prepared = []
                if is_import:
                    for raw in raw_items:
                        item = dict(raw)
                        item.pop("row_index", None)
                        prepared.append(item)
                else:
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
                
                save_kwargs = {}
                if is_import:
                    save_kwargs = {
                        'import_data': header,
                        'items': prepared,
                        'import_id': self.operation_id,
                        'visible_row_count': len(raw_items)
                    }
                else:
                    header["is_historical"] = bool(self.operation_obj.get_value("is_historical"))
                    save_kwargs = {
                        'sale_data': header,
                        'items': prepared,
                        'sale_id': self.operation_id,
                        'visible_row_count': len(raw_items),
                        'pending_entities': getattr(self, 'pending_entities', [])
                    }

                action = "updated" if self.operation_id else "created"
                _log_save_event(
                    "PAYLOAD_BUILD_END", token=self.operation_token,
                    item_count=len(prepared),
                )

                self.save_thread = QThread()
                self.save_worker = SaveWorker(self.database, is_import, save_kwargs)
                self.save_worker.moveToThread(self.save_thread)
                self.save_thread.started.connect(self.save_worker.process)
                _log_save_event("SAVE_THREAD_CREATE", token=self.operation_token)

                # Safe thread cleanup lifecycle
                self.save_worker.finished.connect(self.save_thread.quit)
                self.save_worker.finished.connect(self.save_worker.deleteLater)
                self.save_thread.finished.connect(self.save_thread.deleteLater)
                self.save_worker.error.connect(self.save_thread.quit)
                self.save_worker.error.connect(self.save_worker.deleteLater)
                self.save_thread.finished.connect(
                    lambda tok=self.operation_token: _log_save_event("SAVE_THREAD_FINISHED", token=tok)
                )

                # Business logic callbacks.
                #
                # PROVEN ROOT CAUSE (2026-08-07 hang investigation): Qt/PySide6's
                # AutoConnection picks Direct vs Queued by inspecting the
                # *receiver*'s thread affinity - and that inspection only works
                # when the slot is a genuine bound method of a QObject. A lambda
                # has no thread affinity of its own, so PySide6 cannot resolve it
                # and falls back to invoking the lambda directly, synchronously,
                # ON THE EMITTING THREAD - confirmed empirically in this exact
                # PySide6 build (and confirmed live in
                # logs/sale_save_hang_diagnostic.log: SAVE_GUI_CALLBACK and
                # DIALOG_ACCEPT both logged thread=Dummy-1, the SaveWorker
                # thread, not MainThread). Passing an explicit
                # Qt.QueuedConnection to a lambda-wrapped connect() does NOT
                # fix this (also verified empirically) - only connecting
                # directly to a real bound method does. That means
                # self.accept() and _refresh_related_tabs() (QWidget/QDialog
                # calls) were running off the GUI thread, which is illegal in
                # Qt and is what wedges the window into a permanent
                # "Not Responding" state.
                #
                # Fix: connect directly to a real bound method (no lambda) and
                # stash the extra `action` context on self instead of
                # capturing it in a closure.
                self._pending_save_action = action
                self.save_worker.finished.connect(self._on_save_worker_finished)
                self.save_worker.error.connect(self._on_save_error)
                
                _active_background_threads.add(self.save_thread)
                self.save_thread.finished.connect(self._on_save_thread_finished)
                self.save_thread.start()
                _log_save_event("SAVE_THREAD_START", token=self.operation_token)
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

                # Stock validation for sales (skip on_hold — those don't deduct stock)
                if self.operation_obj.section == 'Sales':
                    sale_state = self.operation_obj.get_value('state') or 'pending'
                    is_historical = bool(self.operation_obj.get_value('is_historical'))
                    if not is_historical and sale_state != 'on_hold':
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
            logger.exception(
                "Operation save failed section=%s operation_id=%s",
                getattr(self.operation_obj, "section", "unknown"),
                self.operation_id,
            )
            QMessageBox.critical(self, "Error", f"Failed to save: {str(e)}")

    def _on_save_worker_finished(self, result):
        """Real bound-method slot for SaveWorker.finished (see the comment at
        the connect() call site) - MUST stay a genuine method, never a
        lambda, or Qt loses the ability to dispatch it onto the GUI thread."""
        self._on_save_finished(result, self._pending_save_action)

    def _on_save_finished(self, result, action):
        _log_save_event("SAVE_GUI_CALLBACK", token=self.operation_token, action=action)
        # NOTE: self.save_thread / self.save_worker are intentionally NOT
        # cleared here. The worker's OS thread may still be winding down when
        # this queued callback runs; dropping the last references here lets the
        # QThread be garbage-collected while its native thread is still
        # running, which crashes with a native access violation under load.
        # Refs are cleared in _on_save_thread_finished, queued to fire only
        # after save_thread.finished (i.e. the thread has fully stopped).

        try:
            self._saving = False
            if hasattr(self, 'save_btn') and self.save_btn:
                self.save_btn.setEnabled(True)
                self.save_btn.setText("Save")

            if getattr(self.operation_obj, 'section', '') == 'Sales':
                self.operation_id = result['sale_id']
                self.operation_obj.id = result['sale_id']
                self.operation_obj.set_value('id', result['sale_id'])
                expected = result.get('expected', 0)
                saved = result.get('saved', 0)
                if saved != expected:
                    QMessageBox.critical(self, "Error", 
                        f"Sale was not saved: {expected} visible items were found, "
                        f"but the server confirmed {saved} saved items."
                    )
                    return
                QMessageBox.information(
                    self, "Success",
                    f"Operation {action} successfully. {saved} items saved.\n"
                    f"Inserted: {result.get('inserted', 0)}, updated: {result.get('updated', 0)}, "
                    f"deleted: {result.get('deleted', 0)}."
                )
                _log_save_event("DIALOG_ACCEPT", token=self.operation_token)
                self.accept()
                _log_save_event("POST_SAVE_REFRESH_START", token=self.operation_token)
                self._refresh_related_tabs("Sales", "Products", "Clients")
                _log_save_event("POST_SAVE_REFRESH_END", token=self.operation_token)

            elif getattr(self.operation_obj, 'section', '') == 'Imports':
                self.operation_id = result["import_id"]
                self.operation_obj.id = result["import_id"]
                self.operation_obj.set_value("id", result["import_id"])
                QMessageBox.information(
                    self,
                    "Success",
                    f"Import {action} successfully. {result.get('saved', 0)} items saved.\n"
                    f"Products created: {result.get('created_products', 0)}.",
                )
                _log_save_event("DIALOG_ACCEPT", token=self.operation_token)
                self.accept()
                _log_save_event("POST_SAVE_REFRESH_START", token=self.operation_token)
                self._refresh_related_tabs("Imports", "Products")
                _log_save_event("POST_SAVE_REFRESH_END", token=self.operation_token)
        except RuntimeError:
            pass

    def _on_save_error(self, err_msg):
        _log_save_event("SAVE_GUI_CALLBACK", token=self.operation_token, action="error")
        # Refs are cleared in _on_save_thread_finished (see _on_save_finished).

        try:
            self._saving = False
            if hasattr(self, 'save_btn') and self.save_btn:
                self.save_btn.setEnabled(True)
                self.save_btn.setText("Save")
        
            QMessageBox.critical(self, "Error", f"Failed to save operation: {err_msg}")
        except RuntimeError:
            pass

    def _on_save_thread_finished(self):
        """Queued (bound-method) handler for save_thread.finished. Fires only
        after the save worker's OS thread has fully stopped, so it is now safe
        to drop the last references to the thread/worker without a QThread
        being destroyed while its native thread is still running."""
        try:
            _active_background_threads.discard(self.save_thread)
        except RuntimeError:
            pass
        self.save_worker = None
        self.save_thread = None

    def _confirm_sale_summary(self):
        """Show the required pre-save summary and ask for confirmation."""
        try:
            is_historical = bool(self.operation_obj.get_value('is_historical'))
            new_products = sum(
                1 for e in self.pending_entities
                if str(e.get("type") or "").casefold() == "product"
            )
            new_services = sum(
                1 for e in self.pending_entities
                if str(e.get("type") or "").casefold() == "service"
            )
            kept_only = 0
            try:
                rows = self.items_table.get_current_table_data()
                kept_only = sum(
                    1 for row in rows
                    if str(row.get("item_type") or "").casefold() == "manual"
                )
            except Exception:
                pass
            lines = [
                "Please review this sale before saving:",
                "",
                f"  \u2022 Devis N°: {self.operation_obj.get_value('devis') or '(allocated on save)'}",
                f"  \u2022 Historical Sale: {'Yes' if is_historical else 'No'}",
                (
                    "  \u2022 Stock impact: None (no deduction, no validation)"
                    if is_historical
                    else "  \u2022 Stock impact: Normal (deducts stock once)"
                ),
                f"  \u2022 New Products to create: {new_products}",
                f"  \u2022 New Services to create: {new_services}",
                f"  \u2022 Items kept only in this Sale: {kept_only}",
                "",
                "Save this sale?",
            ]
            return (
                QMessageBox.question(
                    self, "Confirm Sale", "\n".join(lines),
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                == QMessageBox.Yes
            )
        except Exception:
            return True

    def _refresh_related_tabs(self, *sections):
        main_window = self._get_main_window()
        tab_widget = getattr(main_window, "tab_widget", None) if main_window else None
        if not tab_widget:
            return
        wanted = set(sections)
        current_tab = tab_widget.currentWidget()
        for index in range(tab_widget.count()):
            tab = tab_widget.widget(index)
            if getattr(tab, "section", None) not in wanted:
                continue
            if tab is current_tab and hasattr(tab, "refresh_table"):
                tab.refresh_table(force=True)
            elif hasattr(tab, "mark_dirty"):
                tab.mark_dirty()

    @staticmethod
    def _write_sale_save_log(message):
        try:
            log_dir = os.path.join(user_data_root(), 'logs')
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, 'network_sales.log'), 'a', encoding='utf-8') as stream:
                stream.write(f"[{datetime.now().isoformat(timespec='seconds')}] ui {message}\n")
        except OSError:
            logger.exception("Could not write sale diagnostic log")
    
    def closeEvent(self, event):
        # TEMPORARY Sale Save freeze diagnostic marker - see _log_save_event.
        _log_save_event(
            "DIALOG_CLOSE", token=getattr(self, "operation_token", None),
            saving=getattr(self, "_saving", None),
        )
        super().closeEvent(event)

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
            unknown_items = []
            for row_index, item in enumerate(rows):
                name = " ".join(str(item.get("product_name") or "").split())
                if not name:
                    QMessageBox.warning(self, "Missing Item", "Every sale line needs a name.")
                    return False, False
                item_type = str(item.get("item_type") or "").casefold()
                if item_type not in ("product", "service", "manual"):
                    item_type = ""
                # Keep-only lines are snapshots: no catalog link, no creation.
                if item_type == "manual":
                    continue
                if item_type == "product" and self._catalog_entity_exists("product", name):
                    continue
                if item_type == "service" and self._catalog_entity_exists("service", name):
                    continue
                if not item_type and (
                    self._catalog_entity_exists("product", name)
                    or self._catalog_entity_exists("service", name)
                ):
                    continue
                unknown_items.append({
                    "name": name,
                    "item_type": item_type,
                    "quantity": item.get("quantity", 0),
                    "unit_price": item.get("unit_price", 0),
                    "table_row": int(item.get("row_index", row_index + 1)) - 1,
                })

            if unknown_items:
                dialog = UnknownItemReviewDialog(unknown_items, self)
                if dialog.exec() != QDialog.Accepted:
                    return False, False
                decisions = dialog.get_decisions()
                for decision, unknown in zip(decisions, unknown_items):
                    name = decision["name"]
                    action = decision["action"]
                    if action == "cancel":
                        QMessageBox.warning(
                            self, "Editing Required",
                            f"Edit '{name}' before saving the sale, then try again.",
                        )
                        return False, False
                    self._set_row_item_type(unknown["table_row"], action)
                    if action == "manual":
                        continue
                    section = "Products" if action == "product" else "Services"
                    if not self.database.has_permission(section, "write"):
                        QMessageBox.warning(
                            self, "Permission Denied",
                            f"You don't have permission to create {section.lower()}."
                        )
                        return False, False

                    try:
                        price = Decimal(str(unknown.get("unit_price", 0)))
                        quantity = Decimal(str(unknown.get("quantity", 0)))
                    except InvalidOperation:
                        QMessageBox.warning(
                            self, "Invalid Item", f"Invalid quantity or price for {name}."
                        )
                        return False, False
                    if price < 0 or quantity <= 0:
                        QMessageBox.warning(
                            self, "Invalid Item",
                            f"{name}: quantity must be greater than zero and price cannot be negative."
                        )
                        return False, False
                    pending = {
                        "type": action, "name": name, "unit_price": str(price),
                        "sale_price": str(price),
                    }
                    if action == "product":
                        is_historical = bool(self.operation_obj.get_value("is_historical"))
                        from PySide6.QtWidgets import QInputDialog
                        # Historical products start at zero real stock unless the
                        # user enters a real opening quantity.
                        initial, ok = QInputDialog.getDouble(
                            self, "Initial Product Stock",
                            f"Initial stock for '{name}':",
                            0.0 if is_historical else float(quantity),
                            0.0 if is_historical else 0.001,
                            999999999.0, 3,
                        )
                        if not ok:
                            return False, False
                        if not is_historical and Decimal(str(initial)) < quantity:
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
        target = self._normalize_name(name)
        catalog = getattr(self.database, 'sale_catalog', None)
        if catalog:
            entities = catalog.get(item_type + "s", [])
            for e in entities:
                if self._normalize_name(e.get("name", "")) == target:
                    return True
            return False

        # GUI thread must NOT block to query the database over RPC.
        # Catalog wasn't prefetched - assume it exists; the backend
        # re-validates at save time (matches _entity_exists/_validate_stock).
        return True

    def _validate_stock(self, items_objects):
        """Return a list of error strings for any sale item that exceeds available stock."""
        errors = []
        current_sale_id = self.operation_id or 0
        catalog = getattr(self.database, 'sale_catalog', None)
        
        for item in items_objects:
            try:
                product_id = item.get_value('product_id')
                if not product_id:
                    continue
                product_name = item.get_value('product_name') or f"ID {product_id}"
                new_qty = float(item.get_value('quantity') or 0)
                if new_qty <= 0:
                    continue
                
                available = 0
                if catalog:
                    for p in catalog.get("products", []):
                        if p.get("id") == product_id:
                            available = p.get("stock", 0)
                            break
                else:
                    # GUI thread must NOT block to query database over RPC.
                    # Skip early warning; let SaveWorker and backend validate stock.
                    continue
                    
                if new_qty > float(available):
                    errors.append(f"{product_name} (Requested: {new_qty}, Available: {available})")
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
            target = self._normalize_name(username)
            catalog = getattr(self.database, 'sale_catalog', None)
            catalog_key = table.lower()  # "clients" / "suppliers"
            if catalog and catalog_key in catalog:
                return any(
                    target in (self._normalize_name(e.get('username')), self._normalize_name(e.get('name')))
                    for e in catalog.get(catalog_key, [])
                )
            # GUI thread must NOT block to query the database over RPC.
            # The catalog wasn't prefetched (or doesn't cover this table) -
            # assume it exists; the backend re-validates at save time and
            # _handle_missing_references' own pending-entity flow still
            # covers genuinely-new names.
            return True
        except Exception as e:
            print(f"Error checking existence in {table}: {e}")
            return True  # Avoid blocking

    def _product_exists(self, name):
        try:
            target = self._normalize_name(name)
            
            # Use local catalog if available (removes O(N) blocking RPC queries)
            catalog = getattr(self.database, 'sale_catalog', None)
            if catalog:
                if any(self._normalize_name(p['name']) == target for p in catalog.get('products', [])):
                    return True
                for s in catalog.get('services', []):
                    candidates = [s['name'], *self._split_keywords(s.get('keywords') or "")]
                    if any(target == self._normalize_name(c) for c in candidates if c):
                        return True
                return False

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
