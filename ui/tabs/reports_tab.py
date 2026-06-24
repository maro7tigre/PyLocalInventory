"""
Reports Tab - Manage department reports
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QTextEdit, QFrame)
from ui.tabs.base_tab import BaseTab
from classes.reports_class import ReportsClass
from ui.dialogs.edit_dialogs.reports_edit_dialog import ReportsEditDialog


class ReportsTab(BaseTab):
    """Tab for managing department reports"""

    def __init__(self, database=None, parent=None):
        super().__init__(ReportsClass, ReportsEditDialog, database, parent)

    def details_callback(self, obj_id):
        """Show full report text in a read-only popup"""
        try:
            report_obj = next((o for o in self.all_items if o.id == obj_id), None)
            if not report_obj:
                return

            department = report_obj.get_value('Department') or ''
            date_val = report_obj.get_value('Date') or ''
            report_text = report_obj.get_value('Report') or ''

            from ui.widgets.themed_widgets import RedButton

            dialog = QDialog(self)
            dialog.setWindowTitle(f"Report — {department}")
            dialog.setMinimumSize(520, 420)
            dialog.setModal(True)

            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(24, 24, 24, 24)
            layout.setSpacing(10)

            dept_label = QLabel(f"Department:  {department}")
            dept_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #4CAF50;")
            layout.addWidget(dept_label)

            date_label = QLabel(f"Date:  {date_val}")
            date_label.setStyleSheet("font-size: 13px; color: #aaaaaa;")
            layout.addWidget(date_label)

            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet("color: #3E3E42;")
            layout.addWidget(sep)

            text_view = QTextEdit()
            text_view.setReadOnly(True)
            text_view.setPlainText(report_text)
            text_view.setStyleSheet(
                "background-color: #2D2D30; color: #E0E0E0; "
                "border: 1px solid #3E3E42; padding: 10px; font-size: 14px;"
            )
            layout.addWidget(text_view)

            btn_row = QHBoxLayout()
            btn_row.addStretch()
            close_btn = RedButton("Close")
            close_btn.clicked.connect(dialog.reject)
            btn_row.addWidget(close_btn)
            layout.addLayout(btn_row)

            dialog.setStyleSheet(
                "QDialog { background-color: #2b2b2b; color: #ffffff; }"
                "QLabel  { color: #E0E0E0; background-color: transparent; }"
            )
            dialog.exec()

        except Exception as e:
            print(f"Error showing report details: {e}")

    def get_search_options(self):
        options = set()
        for obj in self.all_items:
            try:
                dept = obj.get_value('Department')
                if dept:
                    options.add(str(dept))
            except Exception:
                pass
        return sorted(options)

    def setup_order_options(self):
        self.order_combo.clear()
        self.order_combo.addItems([
            "Default",
            "Department ↑",
            "Department ↓",
            "Date ↑",
            "Date ↓",
        ])

    def get_searchable_fields(self):
        return ['Department', 'Date']

    def matches_search(self, obj, search_text):
        if not search_text:
            return True
        search_lower = search_text.lower()
        try:
            dept = obj.get_value('Department') or ""
            date_val = obj.get_value('Date') or ""
            if search_lower in dept.lower() or search_lower in date_val.lower():
                return True
        except Exception:
            pass
        return False

    def sort_items(self, items, order_option):
        if not order_option or order_option == "Default":
            return items
        try:
            if order_option == "Department ↑":
                items.sort(key=lambda x: str(x.get_value('Department') or "").lower())
            elif order_option == "Department ↓":
                items.sort(key=lambda x: str(x.get_value('Department') or "").lower(), reverse=True)
            elif order_option == "Date ↑":
                items.sort(key=lambda x: self.parse_date_for_sorting(x.get_value('Date')))
            elif order_option == "Date ↓":
                items.sort(key=lambda x: self.parse_date_for_sorting(x.get_value('Date')), reverse=True)
        except Exception as e:
            print(f"Error sorting reports: {e}")
        return items
