"""
Report Viewer Widget - displays reports in a table format with print/export capabilities
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, 
                               QTableWidgetItem, QHeaderView, QLabel, QTextEdit)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from ui.widgets.themed_widgets import BlueButton, GreenButton


class ReportViewerWidget(QWidget):
    """Widget for displaying reports with table data and summary information"""
    
    def __init__(self, title="Report", parent=None):
        super().__init__(parent)
        self.title = title
        self.report_data = []
        self.headers = []
        self.summary_text = ""
        
        self.setup_ui()
        self.apply_theme()
    
    def setup_ui(self):
        """Setup the report viewer interface"""
        layout = QVBoxLayout(self)
        
        # Header with title and buttons
        header_layout = QHBoxLayout()
        
        self.title_label = QLabel(self.title)
        self.title_label.setFont(QFont("Arial", 16, QFont.Bold))
        header_layout.addWidget(self.title_label)
        
        header_layout.addStretch()
        
        # Export button
        self.export_btn = BlueButton("Export")
        self.export_btn.clicked.connect(self.export_report)
        header_layout.addWidget(self.export_btn)
        
        # Print button
        self.print_btn = GreenButton("Print")
        self.print_btn.clicked.connect(self.print_report)
        header_layout.addWidget(self.print_btn)
        
        layout.addLayout(header_layout)
        
        # Summary section (optional)
        self.summary_label = QLabel("Summary:")
        self.summary_label.setFont(QFont("Arial", 12, QFont.Bold))
        self.summary_label.hide()
        layout.addWidget(self.summary_label)
        
        self.summary_area = QTextEdit()
        self.summary_area.setMaximumHeight(80)
        self.summary_area.setReadOnly(True)
        self.summary_area.hide()
        layout.addWidget(self.summary_area)
        
        # Table for data
        self.table = QTableWidget()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)
    
    def set_report_data(self, headers, data, summary=None):
        """Set the report data to display"""
        self.headers = headers
        self.report_data = data
        self.summary_text = summary or ""
        
        # Update table
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(data))
        
        # Fill table with data
        for row, item in enumerate(data):
            for col, value in enumerate(item):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))
        
        # Update summary if provided
        if summary:
            self.summary_area.setText(summary)
            self.summary_label.show()
            self.summary_area.show()
        else:
            self.summary_label.hide()
            self.summary_area.hide()
    
    def set_title(self, title):
        """Update report title"""
        self.title = title
        self.title_label.setText(title)
    
    def export_report(self):
        """Export report to file (placeholder)"""
        # TODO: Implement export functionality
        print(f"Exporting report: {self.title}")
    
    def print_report(self):
        """Print report (placeholder)"""
        # TODO: Implement print functionality
        print(f"Printing report: {self.title}")
    
    def apply_theme(self):
        """Apply dark theme styling"""
        self.setStyleSheet("""
            QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
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
            QTextEdit {
                background-color: #3c3c3c;
                color: #ffffff;
                border: 1px solid #555555;
                padding: 5px;
                border-radius: 4px;
            }
        """)