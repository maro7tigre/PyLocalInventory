"""
Sales tab - Updated to use unified BaseTab approach
Now consistent with Products/Clients/Suppliers experience
"""
from ui.tabs.base_tab import BaseTab
from PySide6.QtCore import Qt, QPoint, QDate
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QSpinBox, QLineEdit,
    QWidget, QProgressBar, QSizePolicy, QFrame, QPushButton, QMessageBox)
from PySide6.QtGui import QPixmap, QColor
from classes.sales_class import SalesClass
from classes.sales_item_class import SalesItemClass
from ui.dialogs.edit_dialogs.base_operation_dialog import BaseOperationDialog
from ui.dialogs.receipt_dialog import ReceiptDialog
from ui.dialogs.payment_dialog import PaymentDialog
from ui.dialogs.order_progress_dialog import OrderProgressDialog
from datetime import datetime
import os
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
        return [
            'item_type', 'product_name', 'information',
            'quantity', 'unit_price', 'subtotal', 'delete_action'
        ]
    
    def validate_data(self):
        """Sales-specific validation"""
        # Keep only base validation; existence check handled in auto-create workflow
        return super().validate_data()
    
    def _validate_client_exists(self, username):
        """Check if client username exists in database"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return False
        
        try:
            self.database.cursor.execute("SELECT COUNT(*) FROM Clients WHERE username = %s", (username,))
            result = self.database.cursor.fetchone()
            return result[0] > 0 if result else False
        except Exception as e:
            print(f"Error validating client: {e}")
            return False


class SalesTab(BaseTab):
    """Sales tab with unified table experience - consistent with other entity tabs"""
    
    def __init__(self, database=None, parent=None):
        super().__init__(SalesClass, SalesEditDialog, database, parent)
        self._ensure_new_columns_order()
    
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
            controls_layout.insertWidget(controls_layout.count() - 1, self.reports_btn)

            self.payment_btn = OrangeButton("💳 Payment")
            self.payment_btn.clicked.connect(self.show_payment_dialog)
            self.payment_btn.setStyleSheet(
                "QPushButton { background:#1565C0; color:#fff; border:none; border-radius:6px; font-size:14px; padding:5px 10px; }"
                "QPushButton:hover { background:#1976D2; }"
            )
            self.payment_btn.setMinimumHeight(20)
            controls_layout.insertWidget(controls_layout.count() - 1, self.payment_btn)

            self.attachments_btn = OrangeButton("Attachments")
            self.attachments_btn.setToolTip("Manage files for the selected sale")
            self.attachments_btn.clicked.connect(self.show_attachments)
            self.attachments_btn.setMinimumHeight(20)
            controls_layout.insertWidget(controls_layout.count() - 1, self.attachments_btn)

    def show_attachments(self):
        sale_id = self.get_selected_id()
        if sale_id is None:
            QMessageBox.information(self, "Attachments", "Select a sale first.")
            return
        from ui.widgets.attachments_widget import AttachmentPanel
        dialog = QDialog(self)
        dialog.setWindowTitle("Sale Attachments")
        dialog.resize(950, 620)
        layout = QVBoxLayout(dialog)
        layout.addWidget(AttachmentPanel(self.database, 'sale', sale_id, dialog))
        dialog.exec()

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
                client_username = obj.get_value('client_username')
                client_name = obj.get_value('client_name')
                information = obj.get_value('information')
                date = obj.get_value('date')
                
                if client_username:
                    options.add(str(client_username))
                if client_name:
                    options.add(str(client_name))
                if information:
                    options.add(str(information))
                if date:
                    options.add(str(date))
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

    def _order_by_field(self, order_option):
        """Map display labels to allowlisted sort columns."""
        field = super()._order_by_field(order_option)
        if field == 'recent':
            return 'date'
        if field == 'total':
            return 'total_ttc'
        return field
    
    def get_searchable_fields(self):
        """Get fields that can be searched for sales"""
        return ['client_username', 'client_name', 'information', 'date']
    
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
            information = obj.get_value('information') or ""
            
            return (
                search_lower in client_username.lower() or 
                search_lower in client_name.lower() or
                search_lower in information.lower()
            )
        except:
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
                items.sort(key=lambda x: float(x.get_value('total_ttc') or 0))
            elif order_option == "Total ↓":
                items.sort(key=lambda x: float(x.get_value('total_ttc') or 0), reverse=True)
        except Exception as e:
            print(f"Error sorting sales: {e}")
        
        return items

    # ------------- New columns injection and custom cell rendering -------------
    _VIRTUAL_COLUMN_HEADERS = {'check_progress': '', 'progress': 'Progress'}

    def _ensure_new_columns_order(self):
        """Ensure state appears after ID, check_progress button is second, and progress column exists."""
        try:
            if 'state' not in self.table_columns:
                self.table_columns.insert(1, 'state')
            if 'check_progress' not in self.table_columns:
                # Insert right after id (index 0), before state
                self.table_columns.insert(1, 'check_progress')
            if 'progress' not in self.table_columns:
                self.table_columns.append('progress')

            temp_obj = self.object_class(0, self.database)
            headers = []
            for key in self.table_columns:
                if key in self._VIRTUAL_COLUMN_HEADERS:
                    headers.append(self._VIRTUAL_COLUMN_HEADERS[key])
                elif key in temp_obj.parameters:
                    headers.append(temp_obj.get_display_name(key))
                else:
                    headers.append(key.capitalize())
            self.table.setColumnCount(len(self.table_columns))
            self.table.setHorizontalHeaderLabels(headers)
            # Fix the check_progress column to a narrow width
            if 'check_progress' in self.table_columns:
                cp_col = self.table_columns.index('check_progress')
                self.table.setColumnWidth(cp_col, 50)
                self.table.horizontalHeader().setSectionResizeMode(cp_col, QHeaderView.Fixed)
            if 'is_historical' in self.table_columns:
                hist_col = self.table_columns.index('is_historical')
                self.table.setColumnWidth(hist_col, 100)
                self.table.horizontalHeader().setSectionResizeMode(hist_col, QHeaderView.Fixed)
        except Exception as e:
            print(f"Error ensuring sales columns order: {e}")

    def populate_table_with_items(self, items, append=False):
        """Populate table with custom state/progress rendering."""
        sorting_enabled = self.table.isSortingEnabled()
        signals_blocked = self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        try:
            start_row = self.table.rowCount() if append else 0
            self.table.setRowCount(start_row + len(items))
            for row, obj in enumerate(items):
                row = start_row + row
                try:
                    for col, column_key in enumerate(self.table_columns):
                        if column_key == 'check_progress':
                            self._set_check_progress_cell(row, col, obj)
                        elif column_key == 'state':
                            self._set_state_cell(row, col, obj)
                        elif column_key == 'is_historical':
                            self._set_historical_cell(row, col, obj)
                        elif column_key == 'progress':
                            self._set_progress_cell(row, col, obj)
                        else:
                            self.set_table_cell(row, col, column_key, obj)
                except Exception as e:
                    print(f"Error processing Sales row {row}: {e}")
            if start_row + len(items) <= 300:
                self.table.resizeRowsToContents()
        finally:
            self.table.setSortingEnabled(sorting_enabled)
            self.table.blockSignals(signals_blocked)
            self.table.setUpdatesEnabled(True)
            self.table.viewport().update()

    def _set_check_progress_cell(self, row, col, obj):
        from PySide6.QtWidgets import QPushButton
        btn = QPushButton("📦")
        btn.setToolTip("Check Progress")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton { background:#1565C0; color:#fff; border:none; border-radius:4px; padding:3px 8px; font-size:15px; }"
            "QPushButton:hover { background:#1976D2; }"
        )
        btn.clicked.connect(lambda _=None, o=obj, r=row, c=col: (self.table.setCurrentCell(r, c), self._open_progress_for_sale(o)))

        container = QWidget()
        lay = QHBoxLayout(container)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.addWidget(btn)
        self.table.setCellWidget(row, col, container)

    def _open_progress_for_sale(self, obj):
        try:
            dialog = OrderProgressDialog(obj, self.database, self)
            dialog.exec()
            self.refresh_table(force=True)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Failed to open progress dialog:\n{e}")
            import traceback
            traceback.print_exc()

    def _set_historical_cell(self, row, col, obj):
        from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton
        is_historical = bool(obj.get_value('is_historical'))
        label = "Historical" if is_historical else ""
        btn = QPushButton(label) if label else QPushButton(" ")
        btn.setEnabled(False)
        if label:
            btn.setStyleSheet(
                "QPushButton { background:#6A1B9A; color:#fff; border:none; "
                "border-radius:6px; padding:4px 10px; font-weight:bold; }"
            )
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(
            lambda _=None, r=row, c=col: self.table.setCurrentCell(r, c)
        )

        container = QWidget()
        lay = QHBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(btn)
        self.table.setCellWidget(row, col, container)

    def _set_state_cell(self, row, col, obj):
        from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton
        state = obj.get_value('state') or 'pending'
        colors = {
            'on_hold': ('On Hold', '#757575'),
            'pending': ('Pending', '#FF9800'),
            'confirmed': ('Confirmed', '#4CAF50'),
            'finished': ('Finished', '#1976D2')
        }
        label, color = colors.get(state, ('Pending', '#FF9800'))
        btn = QPushButton(label)
        btn.setStyleSheet(f"QPushButton {{ background:{color}; color:#fff; border:none; border-radius:6px; padding:4px 10px; }}")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _=None, o=obj, b=btn, r=row, c=col: (self.table.setCurrentCell(r, c), self._open_state_popup(o, b)))

        container = QWidget()
        lay = QHBoxLayout(container)
        lay.setContentsMargins(0,0,0,0)
        lay.addWidget(btn)
        self.table.setCellWidget(row, col, container)

    def _set_progress_cell(self, row, col, obj):
        total_target = float(obj.get_value('total_quantity') or 0)
        total_prod = float(obj.get_value('total_production') or 0)
        if total_target <= 0:
            # Fallback for legacy rows or if summary fields were not loaded
            try:
                items = obj.get_sales_items()
                total_target = sum(float(item.get_value('quantity') or 0) for item in items)
                total_prod = sum(float(item.get_value('production') or 0) for item in items)
            except Exception:
                total_target = 0
                total_prod = 0

        pct = min(int(total_prod / total_target * 100), 100) if total_target > 0 else 0

        if pct >= 100:
            chunk_color = '#4CAF50'
        elif pct > 0:
            chunk_color = '#FF9800'
        else:
            chunk_color = '#555'

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(pct)
        bar.setFormat(f"{pct}%")
        bar.setTextVisible(True)
        bar.setStyleSheet(
            f"QProgressBar {{ border:1px solid #444; border-radius:4px; background:#2a2a2a; text-align:center; color:#fff; }}"
            f"QProgressBar::chunk {{ background:{chunk_color}; border-radius:3px; }}"
        )

        container = QWidget()
        lay = QHBoxLayout(container)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.addWidget(bar)
        # Pass mouse events through so clicking the bar selects the table row
        bar.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        container.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.table.setCellWidget(row, col, container)

    def _open_state_popup(self, obj, anchor):
        """Open a small popup dialog with state choices."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QPushButton, QSizePolicy, QLabel, QFrame
        # Close previous
        if hasattr(self, '_state_popup') and self._state_popup:
            try:
                self._state_popup.close()
            except Exception:
                pass
        popup = QDialog(self)
        popup.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        popup.setAttribute(Qt.WA_TranslucentBackground, False)
        popup.setModal(False)
        popup.setObjectName('statePopup')

        layout = QVBoxLayout(popup)
        layout.setContentsMargins(12,12,12,12)
        layout.setSpacing(8)

        styles = {
            'on_hold': ('On Hold', '#757575'),
            'pending': ('Pending', '#FF9800'),
            'confirmed': ('Confirmed', '#4CAF50'),
            'finished': ('Finished', '#1976D2')
        }
        current = obj.get_value('state') or 'pending'
        for key, (text, color) in styles.items():
            btn = QPushButton(text)
            sel_border = '3px solid #FFFFFF' if key == current else '1px solid #1e1e1e'
            btn.setStyleSheet(
                f"QPushButton {{ background:{color}; color:#fff; border:{sel_border}; border-radius:6px; padding:8px 12px; font-weight:bold; }}"
                f"QPushButton:hover {{ filter: brightness(110%); }}"
            )
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=None, k=key: self._select_state_from_popup(popup, obj, k))
            layout.addWidget(btn)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet('color:#555;')
        layout.addWidget(line)

        cancel_btn = QPushButton('Cancel')
        cancel_btn.setStyleSheet("QPushButton { background:#E53935; color:#fff; border:none; border-radius:6px; padding:8px 12px; }"
                                "QPushButton:hover { background:#EF5350; }")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(
            lambda _=None: self._cancel_sale_from_popup(popup, obj)
        )
        cancel_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(cancel_btn)

        popup.setStyleSheet("#statePopup { background:#2f2f2f; border:2px solid #444; border-radius:10px; }")
        self._state_popup = popup
        # Position near anchor
        global_pos = anchor.mapToGlobal(anchor.rect().bottomLeft())
        popup.move(global_pos + QPoint(0, 6))
        popup.show()

    def _cancel_sale_from_popup(self, popup, obj):
        """Permanently remove a sale after explicit confirmation."""
        popup.close()
        reply = QMessageBox.question(
            self,
            "Cancel Sale",
            "Cancel this sale and remove it permanently?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            if not self.database.delete_item(obj.id, 'Sales'):
                QMessageBox.critical(self, "Error", "The sale could not be cancelled.")
                return
            self.refresh_table(force=True)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"The sale could not be cancelled:\n{exc}")

    def _select_state_from_popup(self, popup, obj, new_state):
        try:
            popup.close()
        except Exception:
            pass
        self._change_sale_state(obj, new_state)

    def _change_sale_state(self, obj, new_state):
        if not self.database:
            return
        try:
            obj.set_value('state', new_state)
            payload = {'state': new_state}
            self.database.update_item(obj.id, payload, 'Sales')
            # Refresh to reflect button style
            self.refresh_table(force=True)
        except Exception as e:
            print(f"Error updating sale state: {e}")
    
    def show_order_progress(self):
        """Show order production progress dialog for the selected sale."""
        from PySide6.QtWidgets import QMessageBox
        obj_id = self.get_selected_id()
        if obj_id is None:
            QMessageBox.warning(self, "No Selection", "Please select a sale to check progress.")
            return
        obj = next((s for s in self.filtered_items if s.id == obj_id), None)
        if obj is None:
            obj = next((s for s in self.all_items if s.id == obj_id), None)
        if obj:
            self._open_progress_for_sale(obj)

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

    def show_payment_dialog(self):
        """Open the payment dialog for the selected sale."""
        from PySide6.QtWidgets import QMessageBox
        try:
            current_row = self.table.currentRow()
            if current_row < 0:
                QMessageBox.information(self, "No Selection", "Please select a sale to record a payment.")
                return
            if current_row >= len(self.filtered_items):
                QMessageBox.warning(self, "Payment Error", "The selected sale row is no longer valid. Please refresh and try again.")
                return
            selected_sale = self.filtered_items[current_row]

            config = {}
            owner = self.parent_widget
            profile_manager = getattr(owner, 'profile_manager', None)
            if profile_manager and profile_manager.selected_profile:
                config = profile_manager.selected_profile.get_value() or {}

            dialog = PaymentDialog(selected_sale, self.database, self, config=config)
            if dialog.exec():
                self.refresh_table(force=True)
        except Exception as error:
            QMessageBox.critical(self, "Payment Error", f"Could not open the payment window:\n{error}")
