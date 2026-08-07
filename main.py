"""
Application entry point - initializes and starts the PySide6 application
"""
import sys
import logging
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from core.runtime_paths import resource_path
from ui.main_window import MainWindow
from ui.theme import apply_dark_theme
from core.logging_config import setup_logging
from core.build_info import APP_BUILD_ID


def main():
    """Application entry point"""
    log_file = setup_logging()
    logger = logging.getLogger(__name__)
    from core import diagnostics
    # TEMPORARY - Sale Save freeze investigation. Enables faulthandler and a
    # 5-second all-threads stack dump; see core/sale_save_diagnostics.py.
    from core import sale_save_diagnostics
    hang_log = sale_save_diagnostics.start()
    logger.info("Sale Save hang diagnostic active log=%s", hang_log)
    logger.info("Application startup build_id=%s log=%s", APP_BUILD_ID, log_file)
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
    # Log-only GUI-stall watchdog (created only in the real app, never in
    # tests): reports freezes, never kills or restarts the application.
    app._gui_watchdog = diagnostics.GuiWatchdog(parent=window)
    app.aboutToQuit.connect(lambda: logger.info("Application shutdown"))
    
    # Start event loop
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
