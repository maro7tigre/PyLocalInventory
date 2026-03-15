"""
Application entry point - initializes and starts the PySide6 application
"""
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QIcon
from ui.main_window import MainWindow


def main():
    """Application entry point"""
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("logo.png"))
    QGuiApplication.styleHints().setColorScheme(Qt.ColorScheme.Dark)

    # Create and show main window
    window = MainWindow()
    window.show()
    
    # Start event loop
    sys.exit(app.exec())

if __name__ == "__main__":
    main()