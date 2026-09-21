"""
Application entry point - initializes and starts the PySide6 application
"""
import sys
import logging
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon
from core.runtime_paths import resource_path
from ui.main_window import MainWindow
from ui.theme import apply_dark_theme
from core.logging_config import setup_logging
from core.build_info import APP_BUILD_ID
from core.license import check_license, LicenseStatus, get_license_status_message


def _check_license() -> tuple[LicenseStatus, str]:
    """
    Check license validity.

    Returns:
        Tuple of (LicenseStatus, message)
    """
    status, license_data = check_license()
    message = get_license_status_message(status, license_data)
    return status, message


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

    # Check license before initializing GUI
    license_status, license_message = _check_license()
    logger.info("License check: %s - %s", license_status.value, license_message)

    # Allow grace period to proceed but log warning
    if license_status in (LicenseStatus.EXPIRED, LicenseStatus.INVALID_SIGNATURE,
                          LicenseStatus.MACHINE_ID_MISMATCH, LicenseStatus.NOT_FOUND,
                          LicenseStatus.INVALID_FORMAT):
        # Create minimal QApplication for message box
        app = QApplication(sys.argv)
        app.setApplicationName("PyLocalInventory")
        QMessageBox.critical(
            None,
            "License Error",
            f"{license_message}\n\n"
            "The application cannot start without a valid license.\n"
            "Please contact your administrator or vendor for a valid license file.\n"
            "Your data is safe and has not been modified."
        )
        sys.exit(1)

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
