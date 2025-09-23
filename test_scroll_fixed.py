#!/usr/bin/env python3
"""Test the fixed scrollable table functionality"""

import sys
sys.path.append('.')

from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QTableWidget, QScrollArea
from PySide6.QtCore import Qt

class TestScrollableTable(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Test Fixed Scrollable Table")
        self.setGeometry(100, 100, 800, 600)
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        
        # Create the same setup as operations_table.py
        self.table = QTableWidget()
        self.setup_test_table()
        
        # Create scroll area exactly like in operations_table.py
        scroll_area = QScrollArea()
        scroll_area.setWidget(self.table)
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # Set size constraints - this is crucial for scrolling to work
        scroll_area.setMinimumHeight(200)
        scroll_area.setMaximumHeight(350)
        
        # Make sure the table doesn't have conflicting size policies
        from PySide6.QtWidgets import QSizePolicy
        self.table.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        
        layout.addWidget(scroll_area)
        
        # Add many test rows to verify scrolling
        self.add_test_rows()
    
    def setup_test_table(self):
        """Setup table with test columns"""
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(['Product', 'Quantity', 'Price', 'Subtotal', 'Delete'])
        
        # Set row height to exactly 45px like the preview
        self.table.verticalHeader().setDefaultSectionSize(45)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
    
    def add_test_rows(self):
        """Add multiple test rows to verify scrolling works"""
        from PySide6.QtWidgets import QTableWidgetItem
        
        # Add 15 test rows to force scrolling
        for i in range(15):
            row = self.table.rowCount()
            self.table.setRowCount(row + 1)
            
            self.table.setItem(row, 0, QTableWidgetItem(f"Test Product {i+1}"))
            self.table.setItem(row, 1, QTableWidgetItem(str(i+1)))
            self.table.setItem(row, 2, QTableWidgetItem(f"{10.50 + i:.2f}"))
            self.table.setItem(row, 3, QTableWidgetItem(f"{(10.50 + i) * (i+1):.2f}"))
            self.table.setItem(row, 4, QTableWidgetItem("🗑️"))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TestScrollableTable()
    window.show()
    
    print(f"Table rows: {window.table.rowCount()}")
    print(f"Row height: {window.table.verticalHeader().defaultSectionSize()}")
    print(f"Table estimated height: {window.table.rowCount() * 45}px")
    print(f"Scroll area max height: 350px")
    print("Table should be scrollable with 45px row height!")
    
    sys.exit(app.exec())