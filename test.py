
from ui.widgets.table_parameter_widget import TableParameterWidget
from classes.sales_item_class import SalesItemClass

if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget, QLabel
    from PySide6.QtGui import QFont
    
    app = QApplication(sys.argv)
    
    # Create main window
    window = QWidget()
    layout = QVBoxLayout(window)
    
    # Title
    title = QLabel("SalesItemClass Test - Should Show Delete Buttons!")
    title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
    layout.addWidget(title)
    
    # Create table with SalesItemClass (has delete_action button)
    table_widget = TableParameterWidget(SalesItemClass, None, None)
    layout.addWidget(table_widget)
    
    # Apply theme
    window.setStyleSheet("""
        QWidget { background-color: #2b2b2b; color: #ffffff; }
        QLabel { color: #ffffff; }
    """)
    
    window.setWindowTitle("SalesItemClass Table Test")
    window.resize(800, 600)
    window.show()
    sys.exit(app.exec())