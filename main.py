"""
Application entry point - initializes and starts the PySide6 application
"""
import sys
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow

def main():
    """Application entry point"""
    app = QApplication(sys.argv)
    
    # Create and show main window
    window = MainWindow()
    window.show()
    
    # Start event loop
    sys.exit(app.exec())

if __name__ == "__main__":
    main()