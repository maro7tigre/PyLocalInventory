"""
Services Tab - Uses BaseTab plus extra service-specific actions
"""
from ui.tabs.base_tab import BaseTab
from classes.service_class import ServiceClass
from ui.dialogs.edit_dialogs.service_dialog import ServiceEditDialog
from ui.widgets.themed_widgets import BlueButton, GreenButton
from PySide6.QtWidgets import QMessageBox, QHeaderView
# haitam


class ServicesTab(BaseTab):
    """Services tab with additional toolbar actions."""

    def __init__(self, database=None, parent=None):
        super().__init__(ServiceClass, ServiceEditDialog, database, parent)

    def get_preview_category(self):
        return "service"

    def get_search_options(self):
        if not self.all_items:
            return []

        options = []
        seen = set()
        for obj in reversed(self.all_items):
            try:
                code = obj.get_value('service_code') or ""
                name = obj.get_value('name') or ""
                for value in (code, name):
                    if value:
                        value_str = str(value)
                        if value_str not in seen:
                            seen.add(value_str)
                            options.append(value_str)
            except Exception:
                pass

        return options

    def setup_order_options(self):
        self.order_combo.clear()
        self.order_combo.addItems([
            "Default",
            "ID ↑",
            "ID ↓",
            "Code ↑",
            "Code ↓",
            "Service Name ↑",
            "Service Name ↓"
        ])

    def get_searchable_fields(self):
        return ['service_code', 'name']

    def matches_search(self, obj, search_text):
        if not search_text:
            return True

        search_lower = search_text.lower()
        try:
            code = obj.get_value('service_code') or ""
            name = obj.get_value('name') or ""
            if search_lower in str(code).lower() or search_lower in str(name).lower():
                return True
        except Exception:
            pass

        return False

    def sort_items(self, items, order_option):
        if not order_option or order_option == "Default":
            return items

        try:
            if order_option == "ID ↑":
                items.sort(key=lambda x: x.id or 0)
            elif order_option == "ID ↓":
                items.sort(key=lambda x: x.id or 0, reverse=True)
            elif order_option == "Code ↑":
                items.sort(key=lambda x: str(x.get_value('service_code') or "").lower())
            elif order_option == "Code ↓":
                items.sort(key=lambda x: str(x.get_value('service_code') or "").lower(), reverse=True)
            elif order_option == "Service Name ↑":
                items.sort(key=lambda x: str(x.get_value('name') or "").lower())
            elif order_option == "Service Name ↓":
                items.sort(key=lambda x: str(x.get_value('name') or "").lower(), reverse=True)
        except Exception as e:
            print(f"Error sorting services: {e}")

        return items

    def add_additional_toolbar_buttons(self, layout):
        self.export_btn = GreenButton("Export Services")
        self.export_btn.setStyleSheet(self.export_btn.styleSheet() + "\nQPushButton { font-size: 14px; padding: 5px 10px; }")
        self.export_btn.clicked.connect(self.export_services)
        layout.addWidget(self.export_btn)

        self.summary_btn = BlueButton("Service Summary")
        self.summary_btn.setStyleSheet(self.summary_btn.styleSheet() + "\nQPushButton { font-size: 14px; padding: 5px 10px; }")
        self.summary_btn.clicked.connect(self.show_service_summary)
        layout.addWidget(self.summary_btn)

    def export_services(self):
        QMessageBox.information(self, "Export Services", "Service export is not implemented yet. This placeholder button is ready for custom export logic.")

    def setup_table(self):
        super().setup_table()
        try:
            info_index = self.table_columns.index('information')
            header = self.table.horizontalHeader()
            header.setSectionResizeMode(info_index, QHeaderView.Interactive)
            self.table.setColumnWidth(info_index, 320)
            self.table.setMinimumWidth(max(self.table.minimumWidth(), 320))
        except ValueError:
            pass

    def show_service_summary(self):
        total_services = len(self.all_items)
        QMessageBox.information(
            self,
            "Service Summary",
            f"Total services: {total_services}"
        )
