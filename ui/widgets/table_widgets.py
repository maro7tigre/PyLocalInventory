import sys
from PySide6.QtWidgets import (QApplication, QTableWidget, 
                               QTableWidgetItem, QHeaderView, QVBoxLayout, 
                               QWidget, QLabel, QPushButton, QHBoxLayout,
                               QDialog, QComboBox, QMessageBox)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt
from core.database import Database
from ui.widgets.themed_widgets import RedButton, BlueButton




class InventoryApp(QWidget):
    def __init__(self, parent=None, section="Inventory", columns=None):
        super().__init__(parent)
        
        # Initialize database
        self.db = Database()
        self.section : str = section
        self.columns : list[str] = columns if columns else ["ID", "Company", "Role", "Product", "Price HT", "Price TTC", "Quantity", "Icon"]
        
        # Setup UI
        self.setup_ui()
        self.refresh_table()
        
        #MARK: theme
        self.setStyleSheet("""
            QLabel { color: #E0E0E0; }
            QTableWidget { 
                background-color: #2D2D30; gridline-color: #3E3E42; color: #E0E0E0;
                border: 1px solid #3E3E42; alternate-background-color: #252526;
            }
            QTableWidget::item:selected { background-color: #3E3E42; }
            QHeaderView::section { background-color: #252526; color: #CCCCCC; padding: 5px; border: none; }
        """)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Header
        header = QHBoxLayout()
        title = QLabel(f"{self.section} Overview :")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        
        # Buttons
        buttons = QHBoxLayout()
        
        Add_button = BlueButton("Add")
        Add_button.clicked.connect(self.add_item)
        buttons.addWidget(Add_button)
        Edit_button = BlueButton("Edit")
        Edit_button.clicked.connect(self.edit_item)
        buttons.addWidget(Edit_button)
        Delete_button = RedButton("Delete")
        Delete_button.clicked.connect(self.delete_item)
        buttons.addWidget(Delete_button)
        
        layout.addLayout(buttons)
        
        self.setup_table()
        layout.addWidget(self.table)

    #MARK: table (overwrite)
    def setup_table(self):
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setColumnHidden(0, True)
        self.table.verticalHeader().setVisible(False)

    def refresh_table(self):
        items = self.db.get_items(self.section)
        self.table.setRowCount(len(items))
        
        for row, item in enumerate(items):
            for column, data in enumerate(self.columns):
                self.table.setItem(row, column, QTableWidgetItem(str(item[data])))

    def get_selected_id(self):
        row = self.table.currentRow()
        return int(self.table.item(row, 0).text()) if row != -1 else None
            
    def add_item(self):
        """overwrite the method in subclass"""
        if (item_id := self.get_selected_id()) is None:
            QMessageBox.warning(self, "Error", "Please select a item to delete")
            return
        pass #TODO: open the add dialog
    
        self.refresh_table()
    
    def edit_item(self):
        """overwrite the method in subclass"""
        if (item_id := self.get_selected_id()) is None:
            QMessageBox.warning(self, "Error", "Please select a item to delete")
            return
        #items = self.db.get_items(self.section)
        pass #TODO: open the edit dialog with item data
    
        self.refresh_table()
    
    def delete_item(self):
        if (item_id := self.get_selected_id()) is None:
            QMessageBox.warning(self, "Error", "Please select a item to delete")
            return
            
        if QMessageBox.question(self, "Confirm", "Delete this item?") == QMessageBox.Yes:
            self.db.delete_item(item_id, self.section)
            self.refresh_table()