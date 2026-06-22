"""
Services Tab - service management using the shared BaseTab experience.
"""
from PySide6.QtWidgets import QMessageBox

from classes.service_class import ServiceClass
from ui.dialogs.edit_dialogs.service_dialog import ServiceEditDialog
from ui.tabs.base_tab import BaseTab
from ui.widgets.themed_widgets import BlueButton, GreenButton


class ServicesTab(BaseTab):
    """Services tab with service-name, description, and keyword search."""

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
                values = [obj.get_value('name') or ""]
                values.extend(self._split_keywords(obj.get_value('keywords') or ""))

                for value in values:
                    if value:
                        value_str = str(value)
                        key = value_str.lower()
                        if key not in seen:
                            seen.add(key)
                            options.append(value_str)
            except Exception:
                pass

        return options

    def setup_order_options(self):
        self.order_combo.clear()
        self.order_combo.addItems([
            "Default",
            "ID Asc",
            "ID Desc",
            "Service Name Asc",
            "Service Name Desc"
        ])

    def get_searchable_fields(self):
        return ['name', 'description', 'keywords']

    def matches_search(self, obj, search_text):
        if not search_text:
            return True

        search_lower = search_text.lower()
        try:
            name = obj.get_value('name') or ""
            description = obj.get_value('description') or ""
            keywords = obj.get_value('keywords') or ""
            return (
                search_lower in str(name).lower() or
                search_lower in str(description).lower() or
                search_lower in str(keywords).lower()
            )
        except Exception:
            return False

    def sort_items(self, items, order_option):
        if not order_option or order_option == "Default":
            return items

        try:
            if order_option == "ID Asc":
                items.sort(key=lambda x: x.id or 0)
            elif order_option == "ID Desc":
                items.sort(key=lambda x: x.id or 0, reverse=True)
            elif order_option == "Service Name Asc":
                items.sort(key=lambda x: str(x.get_value('name') or "").lower())
            elif order_option == "Service Name Desc":
                items.sort(key=lambda x: str(x.get_value('name') or "").lower(), reverse=True)
        except Exception as e:
            print(f"Error sorting services: {e}")

        return items

    def add_additional_toolbar_buttons(self, layout):
        self.export_btn = GreenButton("Export Services")
        self.export_btn.setStyleSheet(
            self.export_btn.styleSheet() + "\nQPushButton { font-size: 14px; padding: 5px 10px; }"
        )
        self.export_btn.clicked.connect(self.export_services)
        layout.addWidget(self.export_btn)

        self.summary_btn = BlueButton("Service Summary")
        self.summary_btn.setStyleSheet(
            self.summary_btn.styleSheet() + "\nQPushButton { font-size: 14px; padding: 5px 10px; }"
        )
        self.summary_btn.clicked.connect(self.show_service_summary)
        layout.addWidget(self.summary_btn)

    def export_services(self):
        QMessageBox.information(
            self,
            "Export Services",
            "Service export is not implemented yet. This placeholder button is ready for custom export logic."
        )

    def show_service_summary(self):
        total_services = len(self.all_items)
        QMessageBox.information(
            self,
            "Service Summary",
            f"Total services: {total_services}"
        )

    @staticmethod
    def _split_keywords(value):
        return [
            part.strip()
            for part in str(value).replace("\n", ",").split(",")
            if part.strip()
        ]
