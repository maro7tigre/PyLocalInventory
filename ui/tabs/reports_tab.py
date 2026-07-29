"""
Reports Tab - Manage department reports
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QTextEdit, QFrame, QComboBox, QDateEdit, QCheckBox)
from PySide6.QtCore import QDate
from ui.tabs.base_tab import BaseTab
from classes.reports_class import ReportsClass
from ui.dialogs.edit_dialogs.reports_edit_dialog import ReportsEditDialog


class ReportsTab(BaseTab):
    """Tab for managing department reports"""

    def __init__(self, database=None, parent=None):
        super().__init__(ReportsClass, ReportsEditDialog, database, parent)

    def add_additional_toolbar_buttons(self, layout):
        self.user_filter = None
        if getattr(self.database, "is_superadmin", True):
            layout.insertWidget(layout.count() - 1, QLabel("User:"))
            self.user_filter = QComboBox()
            self.user_filter.addItem("All users", None)
            try:
                for user in self.database.list_report_users():
                    self.user_filter.addItem(user["username"], user["id"])
            except Exception as error:
                print(f"Could not load report users: {error}")
            self.user_filter.currentIndexChanged.connect(
                lambda _index: self.refresh_table()
            )
            layout.insertWidget(layout.count() - 1, self.user_filter)

        layout.insertWidget(layout.count() - 1, QLabel("Type:"))
        self.type_filter = QComboBox()
        self.type_filter.addItems([
            "All types", "General", "Sales", "Products", "Services", "Clients",
            "Revenue", "Profit", "Activity",
        ])
        self.type_filter.currentIndexChanged.connect(
            lambda _index: self.refresh_table()
        )
        layout.insertWidget(layout.count() - 1, self.type_filter)

        self.date_filter_enabled = QCheckBox("Date range")
        self.date_from = QDateEdit(QDate.currentDate().addYears(-1))
        self.date_to = QDateEdit(QDate.currentDate())
        for editor in (self.date_from, self.date_to):
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("dd-MM-yyyy")
            editor.setEnabled(False)
            editor.dateChanged.connect(lambda _date: self.refresh_table())
        self.date_filter_enabled.toggled.connect(self._toggle_date_filter)
        layout.insertWidget(layout.count() - 1, self.date_filter_enabled)
        layout.insertWidget(layout.count() - 1, self.date_from)
        layout.insertWidget(layout.count() - 1, self.date_to)

    def _toggle_date_filter(self, enabled):
        self.date_from.setEnabled(enabled)
        self.date_to.setEnabled(enabled)
        self.refresh_table()

    def fetch_items(self):
        owner_id = self.user_filter.currentData() if self.user_filter else None
        use_dates = self.date_filter_enabled.isChecked()
        date_from = self.date_from.date().toString("yyyy-MM-dd") if use_dates else None
        date_to = self.date_to.date().toString("yyyy-MM-dd") if use_dates else None
        report_type = self.type_filter.currentText()
        if report_type == "All types":
            report_type = None
        return self.database.get_reports(owner_id, date_from, date_to, report_type)

    def background_fetcher(self):
        """Capture filter widgets on the GUI thread before network loading."""
        owner_id = self.user_filter.currentData() if self.user_filter else None
        use_dates = self.date_filter_enabled.isChecked()
        date_from = self.date_from.date().toString("yyyy-MM-dd") if use_dates else None
        date_to = self.date_to.date().toString("yyyy-MM-dd") if use_dates else None
        report_type = self.type_filter.currentText()
        if report_type == "All types":
            report_type = None
        database = self.database
        return lambda: database.get_reports(
            owner_id, date_from, date_to, report_type
        )

    def details_callback(self, obj_id):
        """Show full report text in a read-only popup"""
        try:
            report_obj = next((o for o in self.all_items if o.id == obj_id), None)
            if not report_obj:
                return

            department = (
                report_obj.get_value('created_by_username')
                or report_obj.get_value('department')
                or 'Legacy / Unassigned'
            )
            date_val = report_obj.get_value('date') or ''
            report_type = report_obj.get_value("report_type") or "General"
            report_text = report_obj.get_value('report') or ''

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
            type_label = QLabel(f"Type:  {report_type}")
            type_label.setStyleSheet("font-size: 13px; color: #aaaaaa;")
            layout.addWidget(type_label)

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
                dept = obj.get_value('department')
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
        return ['department', 'date', 'report_type']

    def matches_search(self, obj, search_text):
        if not search_text:
            return True
        search_lower = search_text.lower()
        try:
            dept = obj.get_value('department') or ""
            date_val = obj.get_value('date') or ""
            report_type = obj.get_value("report_type") or "General"
            if (
                search_lower in dept.lower()
                or search_lower in date_val.lower()
                or search_lower in report_type.lower()
            ):
                return True
        except Exception:
            pass
        return False

    def sort_items(self, items, order_option):
        if not order_option or order_option == "Default":
            return items
        try:
            if order_option == "Department ↑":
                items.sort(key=lambda x: str(x.get_value('department') or "").lower())
            elif order_option == "Department ↓":
                items.sort(key=lambda x: str(x.get_value('department') or "").lower(), reverse=True)
            elif order_option == "Date ↑":
                items.sort(key=lambda x: self.parse_date_for_sorting(x.get_value('date')))
            elif order_option == "Date ↓":
                items.sort(key=lambda x: self.parse_date_for_sorting(x.get_value('date')), reverse=True)
        except Exception as e:
            print(f"Error sorting reports: {e}")
        return items
