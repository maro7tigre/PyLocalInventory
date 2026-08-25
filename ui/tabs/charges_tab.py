"""
Charges / Operating Expenses Tab
"""
from datetime import date
from decimal import Decimal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QLineEdit,
    QPushButton, QMessageBox
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor

from ui.tabs.base_tab import BaseTab
from ui.dialogs.edit_dialogs.charge_dialog import ChargeEditDialog
from ui.dialogs.recurring_charges_dialog import RecurringChargesDialog
from ui.dialogs.charge_categories_dialog import ChargeCategoriesDialog
from classes.charge_class import ChargeClass
from ui.widgets.themed_widgets import BlueButton, GreenButton
from ui.widgets.autocomplete_widgets import AutoCompleteLineEdit


class ChargesTab(BaseTab):
    """Charges tab with professional UI and proper category display"""

    # Business-relevant columns for display
    DISPLAY_COLUMNS = [
        'expense_date',
        'category_name',      # Custom: resolved category name
        'description',
        'amount',
        'payment_method',
        'reference',
        'created_by_username',
    ]

    def __init__(self, database=None, parent=None, language: str = 'en'):
        # Don't call super().__init__ yet - we need to customize first
        self.database = database
        self.parent_widget = parent
        self.language = (language or 'en').lower()

        # Category cache: id -> name
        self._category_cache = {}
        self._category_cache_loaded = False

        # Recurring template cache: id -> name
        self._template_cache = {}
        self._template_cache_loaded = False

        # Filter state
        self._current_period = "This Month"
        self._current_category_filter = None  # None = All Categories
        self._summary_total = Decimal('0')
        self._summary_count = 0

        # Initialize base tab with our custom configuration
        super().__init__(ChargeClass, ChargeEditDialog, database, parent)

    def setup_ui(self):
        """Setup tab interface - call parent first to satisfy BaseTab contract, then customize"""
        # Call parent setup_ui to create all required BaseTab attributes
        super().setup_ui()
        
        # Now customize the layout for Charges-specific UI
        # The main layout is self.layout()
        main_layout = self.layout()
        
        # Find the controls layout (it's the second item after title)
        # We need to insert period filter and category filter after the search bar
        controls_layout = None
        for i in range(main_layout.count()):
            item = main_layout.itemAt(i)
            if item and item.layout() and i == 1:  # controls layout is at index 1
                controls_layout = item.layout()
                break
        
        if controls_layout:
            # Insert period filter after search_bar (index 0 in controls_layout)
            period_label = QLabel("Period:")
            period_label.setStyleSheet("font-weight: bold;")
            controls_layout.insertWidget(1, period_label)
            
            self.period_combo = QComboBox()
            self.period_combo.addItems([
                "Today",
                "This Week",
                "This Month",
                "This Year",
            ])
            self.period_combo.setCurrentText("This Month")
            self.period_combo.setMinimumWidth(140)
            self.period_combo.currentTextChanged.connect(self._on_period_changed)
            controls_layout.insertWidget(2, self.period_combo)
            
            # Category filter
            cat_label = QLabel("Category:")
            cat_label.setStyleSheet("font-weight: bold;")
            controls_layout.insertWidget(3, cat_label)
            
            self.category_filter_combo = QComboBox()
            self.category_filter_combo.addItem("All Categories", None)
            self.category_filter_combo.setMinimumWidth(180)
            self.category_filter_combo.currentIndexChanged.connect(self._on_category_filter_changed)
            controls_layout.insertWidget(4, self.category_filter_combo)

            sort_index = controls_layout.indexOf(self.order_combo)
            if sort_index >= 0:
                sort_label = QLabel("Sort:")
                sort_label.setStyleSheet("font-weight: bold;")
                controls_layout.insertWidget(sort_index, sort_label)
        
        # Add summary bar after controls layout (before offline banner and table)
        self.summary_widget = QWidget()
        self.summary_widget.setStyleSheet("""
            QWidget {
                background-color: #2d2d2d;
                border-radius: 6px;
                padding: 8px;
            }
            QLabel {
                color: #ffffff;
            }
        """)
        summary_layout = QHBoxLayout(self.summary_widget)
        summary_layout.setContentsMargins(12, 8, 12, 8)

        self.summary_period_label = QLabel("This Month")
        self.summary_period_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #bbbbbb;")
        summary_layout.addWidget(self.summary_period_label)

        summary_layout.addStretch()

        self.summary_total_label = QLabel("Total: 0.00 MAD")
        self.summary_total_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #4fc3f7;")
        summary_layout.addWidget(self.summary_total_label)

        summary_layout.addSpacing(20)

        self.summary_count_label = QLabel("0 charges")
        self.summary_count_label.setStyleSheet("font-size: 13px; color: #bbbbbb;")
        summary_layout.addWidget(self.summary_count_label)

        # Insert summary widget before the offline banner (which is at index 2)
        main_layout.insertWidget(2, self.summary_widget)
        
        # Apply permissions
        self._apply_permissions()

    def _apply_permissions(self):
        """Apply role-based permissions to action buttons"""
        if not self.can_write:
            self.add_btn.setEnabled(False)
            self.add_btn.setToolTip("You don't have permission to add charges")
            self.edit_btn.setEnabled(False)
            self.edit_btn.setToolTip("You don't have permission to edit charges")
        if not self.can_delete:
            self.delete_btn.setEnabled(False)
            self.delete_btn.setToolTip("You don't have permission to delete charges")
        if not self.can_write:
            self.recurring_btn.setEnabled(False)
            self.categories_btn.setEnabled(False)

    def add_additional_toolbar_buttons(self, layout):
        """Add Charges-specific toolbar buttons"""
        layout.addStretch()
        
        # Recurring charges button
        self.recurring_btn = BlueButton("Recurring Charges")
        self.recurring_btn.setToolTip("Manage recurring charge templates")
        self.recurring_btn.setMinimumHeight(28)
        self.recurring_btn.setStyleSheet(self.recurring_btn.styleSheet() + "\nQPushButton { font-size: 13px; padding: 6px 12px; }")
        self.recurring_btn.clicked.connect(self.show_recurring_dialog)
        layout.addWidget(self.recurring_btn)

        self.categories_btn = BlueButton("Categories")
        self.categories_btn.setToolTip("Manage charge categories")
        self.categories_btn.setMinimumHeight(28)
        self.categories_btn.setStyleSheet(self.categories_btn.styleSheet() + "\nQPushButton { font-size: 13px; padding: 6px 12px; }")
        self.categories_btn.clicked.connect(self.show_categories_dialog)
        layout.addWidget(self.categories_btn)

    def setup_table(self):
        """Setup table with business-relevant columns"""
        self.table.setColumnCount(len(self.DISPLAY_COLUMNS))
        
        # Create display headers
        headers = []
        for col_key in self.DISPLAY_COLUMNS:
            if col_key == 'category_name':
                headers.append("Category")
            elif col_key == 'expense_date':
                headers.append("Date")
            elif col_key == 'description':
                headers.append("Description")
            elif col_key == 'amount':
                headers.append("Amount")
            elif col_key == 'payment_method':
                headers.append("Payment Method")
            elif col_key == 'reference':
                headers.append("Reference")
            elif col_key == 'created_by_username':
                headers.append("Created By")
            else:
                headers.append(col_key.replace('_', ' ').title())
        
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

        # Set default row height
        self.table.verticalHeader().setDefaultSectionSize(50)

        # Column sizing: Date=fit, Category=fit, Description=stretch, Amount=fit, Payment Method=fit, Reference=moderate, Created By=fit
        for i, col_key in enumerate(self.DISPLAY_COLUMNS):
            if col_key in ('expense_date', 'category_name', 'payment_method', 'created_by_username'):
                header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
            elif col_key == 'description':
                header.setSectionResizeMode(i, QHeaderView.Stretch)
            elif col_key == 'amount':
                header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
                self.table.setColumnWidth(i, 100)
            elif col_key == 'reference':
                header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
                self.table.setColumnWidth(i, 140)
            else:
                header.setSectionResizeMode(i, QHeaderView.Stretch)

    def _load_category_cache(self):
        """Load category names into cache for display"""
        if self._category_cache_loaded:
            return
        try:
            categories = []
            
            # Update category filter combo
            current_data = self.category_filter_combo.currentData()
            signals_were_blocked = self.category_filter_combo.blockSignals(True)
            try:
                self.category_filter_combo.clear()
                self.category_filter_combo.addItem("All Categories", None)
                for cat in categories:
                    if cat["active"]:
                        self.category_filter_combo.addItem(cat["name"], cat["id"])

                # Restore selection if possible.
                if current_data is not None:
                    idx = self.category_filter_combo.findData(current_data)
                    if idx >= 0:
                        self.category_filter_combo.setCurrentIndex(idx)
            finally:
                self.category_filter_combo.blockSignals(signals_were_blocked)
            
            self._category_cache_loaded = True
        except Exception as e:
            print(f"Failed to load category cache: {e}")

    def _load_template_cache(self):
        """Load recurring template names into cache for display"""
        if self._template_cache_loaded:
            return
        self._template_cache_loaded = True

    def _get_category_name(self, category_id):
        """Get category name from cache, loading if needed"""
        if not category_id:
            return ""
        if not self._category_cache_loaded:
            self._load_category_cache()
        return self._category_cache.get(category_id, "Unknown category")

    def _get_template_name(self, template_id):
        """Get recurring template name from cache"""
        if not template_id:
            return "No recurring template"
        if not self._template_cache_loaded:
            self._load_template_cache()
        return self._template_cache.get(template_id, "Unavailable template")

    def populate_table_with_items(self, items, append=False):
        """Populate table with charge items, resolving category names"""
        if not append:
            self.table.setRowCount(0)
        
        # Ensure caches are loaded
        self._load_category_cache()
        self._load_template_cache()

        start_row = self.table.rowCount()
        for obj in items:
            row = self.table.rowCount()
            self.table.insertRow(row)

            # Date
            expense_date = obj.get_value('expense_date') or ""
            formatted_date = self.format_date_for_display(expense_date)
            date_item = QTableWidgetItem(formatted_date)
            date_item.setData(Qt.UserRole, expense_date)
            date_item.setData(Qt.UserRole + 1, obj.id)
            if not self.is_column_editable('expense_date'):
                date_item.setFlags(date_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, date_item)

            # Category name
            category_id = obj.get_value('category_id')
            cat_name = obj.get_value('category_name') or self._get_category_name(category_id)
            cat_item = QTableWidgetItem(cat_name)
            cat_item.setData(Qt.UserRole, category_id)
            if not self.is_column_editable('category_id'):
                cat_item.setFlags(cat_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 1, cat_item)

            # Description
            description = obj.get_value('description') or ""
            desc_item = QTableWidgetItem(description)
            if not self.is_column_editable('description'):
                desc_item.setFlags(desc_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 2, desc_item)

            # Amount (formatted)
            amount = obj.get_value('amount') or 0
            try:
                amount_str = f"{Decimal(str(amount)):,.2f}"
            except:
                amount_str = "0.00"
            amount_item = QTableWidgetItem(f"{amount_str} MAD")
            amount_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            amount_item.setData(Qt.UserRole, amount)
            if not self.is_column_editable('amount'):
                amount_item.setFlags(amount_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 3, amount_item)

            # Payment Method
            payment_method = obj.get_value('payment_method') or "Cash"
            pm_item = QTableWidgetItem(payment_method)
            if not self.is_column_editable('payment_method'):
                pm_item.setFlags(pm_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 4, pm_item)

            # Reference
            reference = obj.get_value('reference') or ""
            ref_item = QTableWidgetItem(reference)
            if not self.is_column_editable('reference'):
                ref_item.setFlags(ref_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 5, ref_item)

            # Created By
            created_by = obj.get_value('created_by_username') or ""
            cb_item = QTableWidgetItem(created_by)
            cb_item.setFlags(cb_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 6, cb_item)

            # Store full object data for reference
            self.table.item(row, 0).setData(Qt.UserRole + 1, obj.id)

        self.table.resizeRowsToContents()
        self._update_summary()

    def _update_summary(self):
        """Update the summary bar with period total and count"""
        period_label = self._current_period
        if self._current_category_filter:
            cat_name = self._get_category_name(self._current_category_filter)
            period_label += f" - {cat_name}"
        self.summary_period_label.setText(period_label)

        self.summary_total_label.setText(
            f"Total Charges  {self._summary_total:,.2f} MAD"
        )
        self.summary_count_label.setText(
            f"{self._summary_count} charge{'s' if self._summary_count != 1 else ''}"
        )

    def _on_period_changed(self, period_text):
        """Handle period filter change"""
        self._current_period = period_text
        self.current_page = 0
        self.refresh_table(force=True)

    def _on_category_filter_changed(self, index):
        """Handle category filter change"""
        self._current_category_filter = self.category_filter_combo.currentData()
        self.current_page = 0
        self.refresh_table(force=True)

    def _get_date_range_for_period(self, period):
        """Get date range for the selected period"""
        today = date.today()
        if period == "Today":
            return today.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
        elif period == "This Week":
            # Monday of this week
            monday = today - __import__('datetime').timedelta(days=today.weekday())
            return monday.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
        elif period == "This Month":
            first_day = today.replace(day=1)
            return first_day.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
        elif period == "This Year":
            first_day = today.replace(month=1, day=1)
            return first_day.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
        return today.replace(day=1).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")

    def background_fetcher(self, refresh_id=None, database=None):
        """Override to fetch charges with date range and category filter"""
        database = database or self.database
        section = self.section
        search_text = self.search_bar.text().strip()
        order_option = self.order_combo.currentText() if hasattr(self, 'order_combo') else "Default"
        order_by = self._order_by_field(order_option)
        order_dir = self._order_direction(order_option)
        search_columns = self.get_searchable_fields()
        limit = self.page_size + 1
        after_id = self._after_id
        after_sort = self._after_sort

        # Get date range from period filter
        date_from, date_to = self._get_date_range_for_period(self._current_period)
        category_id = self._current_category_filter

        def fetch():
            # Establish connection inside the worker thread if not connected
            if getattr(database, 'profile_manager', None) and not getattr(database, 'conn', None):
                if not database.connect(verify_schema=False):
                    raise RuntimeError("Failed to connect worker database on background thread")

            if hasattr(database, 'get_charges'):
                categories = database.get_charge_categories()
                templates = database.get_recurring_templates()
                result = database.get_charges(
                    date_from=date_from,
                    date_to=date_to,
                    category_id=category_id,
                    search=search_text if search_text else None,
                    limit=limit,
                    offset=len(self.all_items) if self._appending else 0,
                    order_by=order_by,
                    order_dir=order_dir,
                )
                charges = result.get("charges", [])
                
                # Convert to the format expected by _objects_from_records
                items = []
                for ch in charges:
                    item = {'ID': ch['id']}
                    for key, value in ch.items():
                        item[key] = value
                    items.append(item)
                
                metrics = self._keyset_metrics(order_by, items, limit)
                metrics.update({
                    'charge_categories': categories,
                    'recurring_templates': templates,
                    'summary_total': result.get('period_total', '0'),
                    'summary_count': result.get('total_count', 0),
                })
                return items, None, metrics, refresh_id
            
            # Fallback
            return [], None, {}, refresh_id

        return fetch

    def get_searchable_fields(self):
        """Get fields that can be searched for charges"""
        return ['description', 'reference', 'notes']

    def matches_search(self, obj, search_text):
        """Check if charge matches search criteria (used for local filtering)"""
        if not search_text:
            return True
        search_lower = search_text.lower()
        try:
            description = obj.get_value('description') or ""
            reference = obj.get_value('reference') or ""
            notes = obj.get_value('notes') or ""
            if (search_lower in description.lower() or 
                search_lower in reference.lower() or
                search_lower in notes.lower()):
                return True
        except:
            pass
        return False

    def _order_by_field(self, order_option):
        """Map display labels to allowlisted sort columns."""
        field = super()._order_by_field(order_option)
        if field == 'category':
            return 'category_id'
        if field == 'amount':
            return 'amount'
        return field

    def setup_order_options(self):
        """Setup order dropdown options for charges"""
        if hasattr(self, 'order_combo'):
            self.order_combo.clear()
            self.order_combo.addItems([
                "Date ↑",
                "Date ↓", 
                "Category ↑",
                "Category ↓",
                "Amount ↑",
                "Amount ↓",
                "Description ↑",
                "Description ↓"
            ])
            self.order_combo.setCurrentText("Date ↓")

    def _apply_refresh_results(self, items_data, levels, metrics, started, refresh_id):
        metrics = metrics or {}
        categories = metrics.get('charge_categories', [])
        templates = metrics.get('recurring_templates', [])
        self._category_cache = {c['id']: c['name'] for c in categories}
        self._template_cache = {t['id']: t['name'] for t in templates}
        self._category_cache_loaded = True
        self._template_cache_loaded = True
        current_category = self.category_filter_combo.currentData()
        blocked = self.category_filter_combo.blockSignals(True)
        try:
            self.category_filter_combo.clear()
            self.category_filter_combo.addItem("All Categories", None)
            for category in categories:
                suffix = " (Inactive)" if not category.get('active') else ""
                self.category_filter_combo.addItem(
                    category['name'] + suffix, category['id']
                )
            index = self.category_filter_combo.findData(current_category)
            self.category_filter_combo.setCurrentIndex(max(0, index))
        finally:
            self.category_filter_combo.blockSignals(blocked)
        self._summary_total = Decimal(str(metrics.get('summary_total') or 0))
        self._summary_count = int(metrics.get('summary_count') or 0)
        super()._apply_refresh_results(
            items_data, levels, metrics, started, refresh_id
        )
        self._update_summary()

    def _reconcile_in_place(self, previous_objects, new_objects):
        return False

    def get_preview_category(self):
        """Override to specify preview category for charges"""
        return "charge"

    def show_recurring_dialog(self):
        """Open the recurring charges management dialog."""
        dialog = RecurringChargesDialog(self.database, self)
        dialog.exec()
        # Refresh after dialog closes in case templates were confirmed
        self.refresh_table(force=True)

    def show_categories_dialog(self):
        """Open the categories management dialog."""
        dialog = ChargeCategoriesDialog(self.database, self)
        dialog.exec()
        # Invalidate cache and refresh
        self._category_cache_loaded = False
        self.refresh_table(force=True)

    def refresh_table(self, force=False):
        """Override to invalidate caches on forced refresh"""
        if force:
            self._category_cache_loaded = False
            self._template_cache_loaded = False
        super().refresh_table(force)

    def _cache_key(self):
        """Cache key includes period and category filter"""
        return (self.search_bar.text().strip(), 
                self.order_combo.currentText() if hasattr(self, 'order_combo') else "Default",
                self._current_period,
                self._current_category_filter)

    def add_item(self):
        """Add new charge - set default date to today"""
        if not self.can_write:
            return
        dialog = self.dialog_class(None, self.database, self)
        if dialog.exec():
            self.refresh_table(force=True)

    def edit_item(self):
        """Edit selected charge"""
        row = self.table.currentRow()
        if row < 0:
            return
        if not self.can_write:
            return
        obj_id = self.table.item(row, 0).data(Qt.UserRole + 1)
        if obj_id:
            dialog = self.dialog_class(obj_id, self.database, self)
            if dialog.exec():
                self.refresh_table(force=True)

    def delete_item(self):
        row = self.table.currentRow()
        if row < 0 or not self.can_delete:
            return
        charge_id = self.table.item(row, 0).data(Qt.UserRole + 1)
        description = self.table.item(row, 2).text() or f"Charge {charge_id}"
        reply = QMessageBox.question(
            self,
            "Delete Charge",
            f"Delete '{description}'? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            self.database.delete_charge(charge_id)
            self.refresh_table(force=True)
        except Exception as error:
            QMessageBox.critical(self, "Delete Charge", str(error))
