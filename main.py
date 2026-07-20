"""
Application entry point - initializes and starts the PySide6 application
"""
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from core.runtime_paths import resource_path
from ui.main_window import MainWindow
from ui.theme import apply_dark_theme


def main():
    """Application entry point"""
    app = QApplication(sys.argv)
    app.setApplicationName("PyLocalInventory")
    app.setWindowIcon(QIcon(resource_path("logo.png")))
    apply_dark_theme(app)

    if '--verify-report' in sys.argv:
        from core.report_verification import generate_verification_report
        generate_verification_report()
        return

    # Create and show main window
    window = MainWindow()
    window.show()
    
    # Start event loop
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
