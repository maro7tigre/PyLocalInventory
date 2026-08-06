import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEvent

import ui.main_window
from ui.main_window import MainWindow

class TestMainWindowShutdown(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_closeEvent_robust_logging(self):
        """Test that closeEvent safely shuts down even if logger methods raise exceptions."""
        
        # Verify the global logger exists in the module
        self.assertTrue(hasattr(ui.main_window, 'logger'))
        
        # Create a MinimalMainWindow properly inheriting from MainWindow
        # We must call __init__ but we mock out all heavy setup.
        with patch.object(MainWindow, '__init__', lambda self: super(MainWindow, self).__init__()):
            window = MainWindow()
            # Bypass any leftover initializations
            window._shutting_down = False
            window.tab_visibility = {}
            window.network_server = MagicMock()
            window.network_server.is_running = True
            window.database = MagicMock()
            window.tab_widget = MagicMock()
            window.tab_widget.count.return_value = 1
            
            mock_tab = MagicMock()
            window.tab_widget.widget.return_value = mock_tab
            
            # Mock cleanup methods
            window.save_app_config = MagicMock()
            window._stop_sync_coordinator = MagicMock()

            # Create a mock close event
            event = MagicMock()

            # Patch the logger methods to raise NameError (simulating teardown)
            def raise_name_error(*args, **kwargs):
                raise NameError("name 'logger' is not defined")

            with patch.object(ui.main_window.logger, 'info', side_effect=raise_name_error), \
                 patch.object(ui.main_window.logger, 'error', side_effect=raise_name_error):
                 
                # Run closeEvent
                window.closeEvent(event)
                
                # Verify cleanup dependencies were called despite logger exceptions
                window.save_app_config.assert_called_once()
                window._stop_sync_coordinator.assert_called_once()
                mock_tab._wait_for_refresh_thread.assert_called_once()
                mock_tab._wait_for_dashboard_thread.assert_called_once()
                window.network_server.stop.assert_called_once()
                window.database.close.assert_called_once()
                
                # Verify event was accepted
                event.accept.assert_called_once()

if __name__ == "__main__":
    unittest.main()
