"""
Table Widget with Add/Edit/Delete/Report functionality
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QTableWidget, QTableWidgetItem, QHeaderView, 
                               QMessageBox, QDialog)
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtCore import Qt
from ui.widgets.themed_widgets import RedButton, BlueButton, GreenButton
from ui.widgets.report_viewer import ReportViewerWidget
from ui.widgets.preview_widget import PreviewWidget
from core.reports_generator import ReportsGenerator


class TableWidget(QWidget):
    """ table with CRUD operations and reporting"""
    
    def __init__(self, section="Items", database=None, columns=None, parent=None):
        super().__init__(parent)
        self.section = section
        self.database = database
        self.columns = columns or ["ID", "Name"]
        self.reports_generator = ReportsGenerator(database) if database else None
        
        self.setup_ui()
        self.apply_theme()
        self.refresh_table()
    
    def setup_ui(self):
        """Setup table interface"""
        layout = QVBoxLayout(self)
        
        # Header with title and buttons
        header_layout = QHBoxLayout()
        
        title = QLabel(f"{self.section} Overview")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        header_layout.addWidget(title)
        header_layout.addStretch()
        
        # Action buttons
        self.add_btn = BlueButton("Add")
        self.add_btn.clicked.connect(self.add_item)
        header_layout.addWidget(self.add_btn)
        
        self.edit_btn = BlueButton("Edit")
        self.edit_btn.clicked.connect(self.edit_item)
        header_layout.addWidget(self.edit_btn)
        
        self.delete_btn = RedButton("Delete")
        self.delete_btn.clicked.connect(self.delete_item)
        header_layout.addWidget(self.delete_btn)
        
        self.report_btn = GreenButton("Report")
        self.report_btn.clicked.connect(self.show_report)
        header_layout.addWidget(self.report_btn)
        
        layout.addLayout(header_layout)
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setColumnHidden(0, True)  # Hide ID column
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        
        layout.addWidget(self.table)
    
    def refresh_table(self):
        """Refresh table data from database"""
        if not self.database:
            return
        
        items = self.database.get_items(self.section)
        self.table.setRowCount(len(items))
        
        for row, item in enumerate(items):
            for col, column_name in enumerate(self.columns):
                if column_name == "preview image" and column_name in item:
                    # Handle preview image column specially
                    preview_widget = PreviewWidget(50, "individual")
                    if item[column_name]:
                        preview_widget.set_image_path(item[column_name])
                    self.table.setCellWidget(row, col, preview_widget)
                else:
                    value = item.get(column_name, "")
                    self.table.setItem(row, col, QTableWidgetItem(str(value)))
    
    def get_selected_id(self):
        """Get ID of selected item"""
        row = self.table.currentRow()
        if row == -1:
            return None
        return int(self.table.item(row, 0).text()) if self.table.item(row, 0) else None
    
    def add_item(self):
        """Add new item - override in subclasses"""
        QMessageBox.information(self, "Info", f"Add {self.section[:-1]} dialog would open here")
    
    def edit_item(self):
        """Edit selected item - override in subclasses"""
        item_id = self.get_selected_id()
        if item_id is None:
            QMessageBox.warning(self, "Error", f"Please select a {self.section[:-1].lower()} to edit")
            return
        QMessageBox.information(self, "Info", f"Edit {self.section[:-1]} {item_id} dialog would open here")
    
    def delete_item(self):
        """Delete selected item"""
        item_id = self.get_selected_id()
        if item_id is None:
            QMessageBox.warning(self, "Error", f"Please select a {self.section[:-1].lower()} to delete")
            return
        
        reply = QMessageBox.question(
            self, "Confirm Deletion", 
            f"Are you sure you want to delete this {self.section[:-1].lower()}?\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            if self.database.delete_item(item_id, self.section):
                QMessageBox.information(self, "Success", f"{self.section[:-1]} deleted successfully")
                self.refresh_table()
            else:
                QMessageBox.critical(self, "Error", f"Failed to delete {self.section[:-1].lower()}")
    
    def show_report(self):
        """Show report for selected item"""
        item_id = self.get_selected_id()
        if item_id is None:
            QMessageBox.warning(self, "Error", f"Please select a {self.section[:-1].lower()} to generate report")
            return
        
        if not self.reports_generator:
            QMessageBox.warning(self, "Error", "Reports generator not available")
            return
        
        # Generate report based on section
        if self.section == "Clients":
            headers, data, summary = self.reports_generator.generate_client_report(item_id)
            title = f"Client Report - ID {item_id}"
        elif self.section == "Products":
            headers, data, summary = self.reports_generator.generate_product_report(item_id)
            title = f"Product Report - ID {item_id}"
        elif self.section == "Suppliers":
            headers, data, summary = self.reports_generator.generate_supplier_report(item_id)
            title = f"Supplier Report - ID {item_id}"
        else:
            QMessageBox.information(self, "Info", f"Reports not available for {self.section}")
            return
        
        # Show report dialog
        self.show_report_dialog(title, headers, data, summary)
    
    def show_report_dialog(self, title, headers, data, summary):
        """Show report in a dialog"""
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setModal(True)
        dialog.resize(800, 600)
        
        layout = QVBoxLayout(dialog)
        
        report_viewer = ReportViewerWidget(title)
        report_viewer.set_report_data(headers, data, summary)
        layout.addWidget(report_viewer)
        
        # Apply dark theme to dialog
        dialog.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
        """)
        
        dialog.exec()
    
    def apply_theme(self):
        """Apply dark theme styling"""
        self.setStyleSheet("""
            QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLabel {
                color: #E0E0E0;
            }
            QTableWidget {
                background-color: #2D2D30;
                gridline-color: #3E3E42;
                color: #E0E0E0;
                border: 1px solid #3E3E42;
                alternate-background-color: #252526;
            }
            QTableWidget::item:selected {
                background-color: #3E3E42;
            }
            QHeaderView::section {
                background-color: #252526;
                color: #CCCCCC;
                padding: 5px;
                border: none;
            }
        """)